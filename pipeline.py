#!/usr/bin/env python3
"""Deterministic multi-vendor IMS EMS transformation CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from adapters import kind_of, parse_file, vendor_of
from pipeline_core.errors import PipelineError, RecordError
from pipeline_core.io import (
    Candidate,
    atomic_write_jsonl,
    deduplicate,
    make_rejection,
    rejected_sort_key,
)
from pipeline_core.rules import load_rules
from pipeline_core.transform import transform_raw
from pipeline_core.validate import initialize_validator, validate_record


def _input_files(input_root: Path, excluded_paths: set[Path]) -> list[Path]:
    return sorted(
        (
            path
            for path in input_root.rglob("*")
            if path.is_file()
            and path.resolve() not in excluded_paths
            and vendor_of(path.name) is not None
            and kind_of(path.name) is not None
        ),
        key=lambda path: path.relative_to(input_root).as_posix(),
    )


def _relative_source(path: Path, input_root: Path) -> str:
    return path.relative_to(input_root).as_posix()


def run_transform(
    *,
    input_dir: str,
    rules_dir: str,
    out_path: str,
    rejected_path: str | None,
) -> dict[str, int]:
    input_root = Path(input_dir)
    if not input_root.exists():
        raise PipelineError(f"입력 경로가 없습니다: {input_root}")
    if not input_root.is_dir():
        raise PipelineError(f"입력 경로가 디렉터리가 아닙니다: {input_root}")

    output = Path(out_path)
    rejected_output = Path(rejected_path) if rejected_path else None
    if rejected_output and output.resolve() == rejected_output.resolve():
        raise PipelineError("--out과 --rejected는 서로 다른 경로여야 합니다.")

    repository = load_rules(rules_dir)
    initialize_validator()
    excluded_paths = {output.resolve()}
    if rejected_output:
        excluded_paths.add(rejected_output.resolve())
    files = _input_files(input_root, excluded_paths)

    candidates: list[Candidate] = []
    rejected: list[dict[str, Any]] = []
    parsed_count = 0
    for path in files:
        source_file = _relative_source(path, input_root)
        vendor = vendor_of(path.name)
        record_type = kind_of(path.name)
        yielded = False
        file_error_recorded = False
        adapter_started = False
        try:
            parsed = parse_file(str(path))
            adapter_started = True
            for source_index, (raw, error) in enumerate(parsed, start=1):
                yielded = True
                parsed_count += 1
                if error is not None:
                    code = "UNKNOWN_INPUT_TYPE" if vendor is None or record_type is None else "PARSE_ERROR"
                    rejected.append(
                        make_rejection(
                            source_file=source_file,
                            source_index=source_index,
                            error_code=code,
                            error_message=error,
                            vendor=vendor,
                            record_type=record_type,
                        )
                    )
                    continue
                if raw is None:
                    rejected.append(
                        make_rejection(
                            source_file=source_file,
                            source_index=source_index,
                            error_code="ADAPTER_ERROR",
                            error_message="Adapter가 raw와 error를 모두 비워 반환했습니다.",
                            vendor=vendor,
                            record_type=record_type,
                        )
                    )
                    continue
                if vendor is None or record_type is None:
                    rejected.append(
                        make_rejection(
                            source_file=source_file,
                            source_index=source_index,
                            error_code="UNKNOWN_INPUT_TYPE",
                            error_message="파일명에서 vendor/record_type을 식별할 수 없습니다.",
                            vendor=vendor,
                            record_type=record_type,
                            raw_record=raw,
                        )
                    )
                    continue

                try:
                    rule = repository.select(vendor, record_type, raw)
                    record = transform_raw(raw, rule)
                    if record["vendor"] != vendor or record["record_type"] != record_type:
                        raise RecordError(
                            "IDENTITY_MISMATCH",
                            "파일 식별 결과와 규칙이 생성한 vendor/record_type이 다릅니다.",
                            partial_record=record,
                        )
                    try:
                        validate_record(record)
                    except RecordError as exc:
                        raise RecordError(
                            exc.code,
                            exc.message,
                            partial_record=record,
                        ) from exc
                    candidates.append(
                        Candidate(
                            record=record,
                            source_file=source_file,
                            source_record_index=source_index,
                            raw_record=raw,
                        )
                    )
                except RecordError as exc:
                    rejected.append(
                        make_rejection(
                            source_file=source_file,
                            source_index=source_index,
                            error_code=exc.code,
                            error_message=exc.message,
                            vendor=vendor,
                            record_type=record_type,
                            raw_record=raw,
                            partial_record=exc.partial_record,
                        )
                    )
                except (KeyError, TypeError, ValueError, OverflowError) as exc:
                    rejected.append(
                        make_rejection(
                            source_file=source_file,
                            source_index=source_index,
                            error_code="UNEXPECTED_RECORD_ERROR",
                            error_message=(
                                "예상하지 못한 레코드 변환 오류: "
                                f"{type(exc).__name__}: {exc}"
                            ),
                            vendor=vendor,
                            record_type=record_type,
                            raw_record=raw,
                        )
                    )
        except (OSError, UnicodeError) as exc:
            file_error_recorded = True
            rejected.append(
                make_rejection(
                    source_file=source_file,
                    source_index=0,
                    error_code="ADAPTER_FILE_ERROR",
                    error_message=f"파일 처리 실패: {type(exc).__name__}: {exc}",
                    vendor=vendor,
                    record_type=record_type,
                )
            )
        except (RuntimeError, IndexError, TypeError, ValueError) as exc:
            file_error_recorded = True
            error_code = "PARSE_ERROR" if adapter_started else "ADAPTER_UNEXPECTED_ERROR"
            error_prefix = "Adapter 파싱 오류" if adapter_started else "Adapter 예상 외 오류"
            rejected.append(
                make_rejection(
                    source_file=source_file,
                    source_index=0,
                    error_code=error_code,
                    error_message=f"{error_prefix}: {type(exc).__name__}: {exc}",
                    vendor=vendor,
                    record_type=record_type,
                )
            )
        except Exception as exc:
            file_error_recorded = True
            rejected.append(
                make_rejection(
                    source_file=source_file,
                    source_index=0,
                    error_code="ADAPTER_UNEXPECTED_ERROR",
                    error_message=(
                        "Adapter 예상 외 오류: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    vendor=vendor,
                    record_type=record_type,
                )
            )
        if not yielded and not file_error_recorded:
            rejected.append(
                make_rejection(
                    source_file=source_file,
                    source_index=0,
                    error_code="EMPTY_INPUT_FILE",
                    error_message="Adapter가 레코드를 한 건도 반환하지 않았습니다.",
                    vendor=vendor,
                    record_type=record_type,
                )
            )

    accepted, duplicate_rejections = deduplicate(candidates)
    rejected.extend(duplicate_rejections)
    rejected.sort(key=rejected_sort_key)

    try:
        if rejected_output is not None:
            atomic_write_jsonl(rejected_output, rejected)
        atomic_write_jsonl(output, accepted)
    except (OSError, TypeError, ValueError) as exc:
        raise PipelineError(f"출력 저장 실패: {exc}") from exc

    return {
        "files": len(files),
        "parsed": parsed_count,
        "accepted": len(accepted),
        "rejected": len(rejected),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline.py")
    subparsers = parser.add_subparsers(dest="command", required=True)
    transform = subparsers.add_parser("transform")
    transform.add_argument("--input", required=True)
    transform.add_argument("--rules", required=True)
    transform.add_argument("--out", required=True)
    transform.add_argument("--rejected")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "transform":
            summary = run_transform(
                input_dir=args.input,
                rules_dir=args.rules,
                out_path=args.out,
                rejected_path=args.rejected,
            )
        else:  # argparse prevents this branch.
            raise PipelineError(f"지원하지 않는 명령: {args.command}")
    except PipelineError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    print(
        "[SUMMARY] files={files} parsed={parsed} accepted={accepted} rejected={rejected}".format(
            **summary
        ),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
