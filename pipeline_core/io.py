"""Deterministic ordering, duplicate handling, and atomic JSONL output."""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


JSON_OPTIONS = {
    "ensure_ascii": False,
    "sort_keys": True,
    "allow_nan": False,
    "separators": (",", ":"),
}


@dataclass(frozen=True)
class Candidate:
    record: dict[str, Any]
    source_file: str
    source_record_index: int
    raw_record: dict[str, Any]


def canonical_json(value: Any) -> str:
    return json.dumps(value, **JSON_OPTIONS)


def json_safe(value: Any) -> Any:
    """Keep rejected diagnostics JSON-serializable without emitting JSON NaN."""
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            label = "NaN"
        elif value > 0:
            label = "Infinity"
        else:
            label = "-Infinity"
        return {"__non_finite_number__": label}
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    return value


def record_key(record: dict[str, Any]) -> tuple[str, str, str, str, int | str, str]:
    discriminator = record.get("alarm_id") or record.get("snapshot_id") or ""
    return (
        str(record.get("vendor", "")),
        str(record.get("ne_id", "")),
        str(record.get("record_type", "")),
        str(record.get("timestamp", "")),
        record.get("granularity_sec", ""),
        str(discriminator),
    )


def rejected_sort_key(rejected: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(rejected.get("source_file", "")),
        int(rejected.get("source_index", 0)),
        str(rejected.get("error_code", "")),
        canonical_json(rejected),
    )


def make_rejection(
    *,
    source_file: str,
    source_index: int,
    error_code: str,
    error_message: str,
    vendor: str | None = None,
    record_type: str | None = None,
    raw_record: dict[str, Any] | None = None,
    partial_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rejected: dict[str, Any] = {
        "source_file": source_file,
        "source_index": source_index,
        "error_code": error_code,
        "error_message": error_message,
    }
    if vendor is not None:
        rejected["vendor"] = vendor
    if record_type is not None:
        rejected["record_type"] = record_type
    for key in (
        "schema_version",
        "record_type",
        "vendor",
        "ne_type",
        "ne_id",
        "timestamp",
        "granularity_sec",
        "alarm_id",
        "snapshot_id",
    ):
        if partial_record and key in partial_record:
            rejected[key] = partial_record[key]
    if raw_record is not None:
        rejected["raw_record"] = json_safe(raw_record)
    return rejected


def deduplicate(
    candidates: Iterable[Candidate],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[tuple[str, str, str, str, int | str, str], list[Candidate]] = {}
    for candidate in candidates:
        groups.setdefault(record_key(candidate.record), []).append(candidate)

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for key in sorted(groups):
        group = sorted(
            groups[key],
            key=lambda item: (
                canonical_json(item.record),
                item.source_file,
                item.source_record_index,
                canonical_json(json_safe(item.raw_record)),
            ),
        )
        serialized = {canonical_json(item.record) for item in group}
        if len(group) == 1:
            accepted.append(group[0].record)
            continue
        if len(serialized) == 1:
            accepted.append(group[0].record)
            for duplicate in group[1:]:
                rejected.append(
                    make_rejection(
                        source_file=duplicate.source_file,
                        source_index=duplicate.source_record_index,
                        error_code="DUPLICATE_RECORD",
                        error_message="동일 키와 동일 값을 가진 중복 레코드입니다.",
                        raw_record=duplicate.raw_record,
                        partial_record=duplicate.record,
                    )
                )
            continue
        for conflict in group:
            rejected.append(
                make_rejection(
                    source_file=conflict.source_file,
                    source_index=conflict.source_record_index,
                    error_code="DUPLICATE_CONFLICT",
                    error_message="동일 키의 레코드 값이 서로 달라 모두 거부했습니다.",
                    raw_record=conflict.raw_record,
                    partial_record=conflict.record,
                )
            )

    accepted.sort(key=lambda record: (record_key(record), canonical_json(record)))
    rejected.sort(key=rejected_sort_key)
    return accepted, rejected


def atomic_write_jsonl(path: str | Path, records: Iterable[dict[str, Any]]) -> None:
    target = Path(path)
    if target.exists() and target.is_dir():
        raise OSError(f"출력 경로가 디렉터리입니다: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(canonical_json(record))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
