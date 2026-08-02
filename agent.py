#!/usr/bin/env python3
"""Claude-backed declarative rule generation and validation CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable

from adapters import kind_of, parse_file, vendor_of
from pipeline_core.errors import PipelineError, RecordError, RuleValidationError
from pipeline_core.rules import (
    CM_PARAMETERS,
    CM_TARGET_TYPES,
    PM_COUNTERS,
    PM_TARGET_TYPES,
    PROBABLE_CAUSES,
    RECORD_TARGET_TYPES,
    RECORD_TARGETS,
    SEVERITIES,
    TRANSIENT_TARGETS,
    Rule,
    RuleRepository,
    load_rules,
    validate_rule,
)
from pipeline_core.transform import transform_raw
from pipeline_core.validate import initialize_validator, validate_record

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None

PROJECT_ROOT = Path(__file__).resolve().parent
RULE_SCHEMA_VERSION = "1.0"
DEFAULT_MODEL = "claude-sonnet-5"
RECORD_TYPES = ("CM", "PM", "FM")
RECORD_TYPE_ORDER = {name: index for index, name in enumerate(RECORD_TYPES)}
MAX_REJECTION_RATIO = 0.10  # 원본 데이터 오염 5% + 표본 분산 마진 5%
LEGACY_AGENT_KEYS = {
    "icd_version",
    "metadata_mapping",
    "time_mapping",
    "value_multiplier",
    "parameter_mapping",
    "counter_mapping",
    "alarm_mapping",
    "enum_mapping",
    "mapping_reason",
    "unmapped_fields",
}
CANONICAL_RULE_KEYS = {
    "rule_schema_version",
    "rule_version",
    "source_document_version",
    "compatible_source_document_versions",
    "vendor",
    "record_type",
    "match",
    "required_source_fields",
    "time",
    "mappings",
    "unmapped",
}


class AgentError(Exception):
    """Expected Agent failure that must produce a non-zero CLI exit code."""


def _load_environment() -> None:
    if load_dotenv is not None:
        load_dotenv(PROJECT_ROOT / ".env")


def call_llm_api(messages: list[dict[str, str]], system: str) -> str:
    _load_environment()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise AgentError(
            "ANTHROPIC_API_KEY가 설정되지 않았습니다. 환경변수 또는 프로젝트의 .env에 설정하십시오."
        )

    try:
        import anthropic
    except ModuleNotFoundError as exc:
        raise AgentError(
            "anthropic 패키지가 필요합니다. "
            "`python -m pip install -r requirements.txt`로 설치하십시오."
        ) from exc

    model = os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=12000,
            system=system,
            messages=messages,
        )
    except Exception as exc:
        raise AgentError(f"Claude API 호출 실패: {type(exc).__name__}: {exc}") from exc

    text_blocks = [
        block.text
        for block in response.content
        if getattr(block, "type", "") == "text" and getattr(block, "text", "")
    ]
    if not text_blocks:
        raise AgentError("Claude API 응답에 JSON 텍스트가 없습니다.")
    return "\n".join(text_blocks)


def clean_json_output(text: str) -> str:
    cleaned = re.sub(r"^\s*```json\s*", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    start_index = cleaned.find("{")
    end_index = cleaned.rfind("}")
    if start_index == -1 or end_index < start_index:
        return cleaned.strip()
    return cleaned[start_index: end_index + 1]


def _canonical_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_text(path: Path, label: str) -> str:
    if not path.is_file():
        raise AgentError(f"{label} 파일이 없습니다: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AgentError(f"{label} 파일 읽기 실패: {path}: {exc}") from exc


def _rule_sort_key(data: dict[str, Any]) -> tuple[str, int, str, str]:
    return (
        str(data.get("vendor", "")),
        RECORD_TYPE_ORDER.get(str(data.get("record_type", "")), 99),
        str(data.get("source_document_version", "")),
        str(data.get("rule_version", "")),
    )


def _rule_slot(data: dict[str, Any]) -> tuple[str, str, str]:
    return (
        data["vendor"],
        data["record_type"],
        data["source_document_version"],
    )


def _rules_root_and_staging(out_dir: str | Path) -> tuple[Path, Path]:
    output = Path(out_dir)
    if output.name in {"staging", "active", "artifacts", "archive"}:
        rules_root = output.parent
    else:
        rules_root = output
    return rules_root, rules_root / "staging"


def _load_rule_items(path: Path) -> list[dict[str, Any]]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AgentError(f"규칙 JSON 읽기 실패: {path}: {exc}") from exc
    items = loaded if isinstance(loaded, list) else [loaded]
    if not items or any(not isinstance(item, dict) for item in items):
        raise AgentError(f"규칙 파일은 비어 있지 않은 JSON 객체 또는 객체 배열이어야 합니다: {path}")
    return items


def _existing_rule_context(
        rules_dir: str | Path,
        vendor: str,
        record_type: str,
) -> tuple[str, list[dict[str, Any]]]:
    root = Path(rules_dir)
    if not root.exists():
        return "[]", []
    try:
        repository = load_rules(root)
    except RuleValidationError:
        return "[]", []
    existing = [
        rule.data
        for rule in repository.candidates(vendor, record_type)
    ]
    return json.dumps(existing, ensure_ascii=False, indent=2), existing


def _sample_records(
        sample_dir: str | Path | None,
        vendor: str,
        record_type: str,
        *,
        maximum: int = 10,
) -> list[dict[str, Any]]:
    if sample_dir is None:
        return []
    root = Path(sample_dir)
    if not root.is_dir():
        raise AgentError(f"--sample 경로가 디렉터리가 아닙니다: {root}")

    records: list[dict[str, Any]] = []
    seen_signatures: set[frozenset[str]] = set()

    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and vendor_of(path.name) == vendor
        and kind_of(path.name) == record_type
    )
    for path in files:
        try:
            parsed = parse_file(str(path))
            for raw, error in parsed:
                if error is None and isinstance(raw, dict):
                    sig = frozenset(raw.keys())
                    if sig not in seen_signatures:
                        seen_signatures.add(sig)
                        records.append(raw)
                        if len(records) >= maximum:
                            return records
        except (OSError, UnicodeError, RuntimeError, TypeError, ValueError):
            continue
    return records


def _time_template(record_type: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "source": "<actual_source_time_field>",
        "target": "timestamp",
        "format": "<one of: %Y%m%d%H%M%S | iso8601_utc | epoch_ms>",
        "role": "<one of: interval_start | interval_end | instant>",
    }
    if record_type == "PM":
        base.update(
            {
                "interval_source": "<actual_interval_field>",
                "interval_unit": "<one of: minute | second | iso_duration>",
            }
        )
    if record_type == "FM":
        base["event_time_source"] = "<actual_event_time_field>"
    return base


def get_json_template(record_type: str, vendor: str) -> dict[str, Any]:
    if record_type == "PM":
        destination = "counters"
        target = "sip.register.attempt"
        source_type = "integer"
        target_type = "integer"
    elif record_type == "CM":
        destination = "parameters"
        target = "sip.timer.t1_ms"
        source_type = "integer"
        target_type = "integer"
    else:
        destination = "record"
        target = "alarm_id"
        source_type = "string"
        target_type = "string"

    return {
        "rule_schema_version": RULE_SCHEMA_VERSION,
        "rule_version": "1.0.0",
        "source_document_version": "<version_from_document>",
        "compatible_source_document_versions": [],
        "vendor": vendor,
        "record_type": record_type,
        "match": {
            "required_fields": ["<stable_signature_field>"],
            "forbidden_fields": [],
            "any_of": [],
        },
        "required_source_fields": ["<every_mandatory_source_field>"],
        "time": _time_template(record_type),
        "mappings": [
            {
                "sources": [{"field": "<actual_source_field>", "priority": 1}],
                "destination": destination,
                "target": target,
                "source_type": source_type,
                "target_type": target_type,
                "operations": [],
                "conflict_policy": "reject_if_different",
            }
        ],
        "unmapped": [],
    }


def _contract_reference(record_type: str) -> dict[str, Any]:
    if record_type == "PM":
        payload_targets = {
            name: PM_TARGET_TYPES[name]
            for name in sorted(PM_COUNTERS)
        }
    elif record_type == "CM":
        payload_targets = {
            name: CM_TARGET_TYPES[name]
            for name in sorted(CM_PARAMETERS)
        }
    else:
        payload_targets = {}
    record_targets = {
        name: RECORD_TARGET_TYPES[name]
        for name in sorted(RECORD_TARGETS[record_type])
    }
    return {
        "record_targets_and_types": record_targets,
        "payload_targets_and_types": payload_targets,
        "fm_transient_targets": sorted(TRANSIENT_TARGETS) if record_type == "FM" else [],
        "allowed_severity_outputs": sorted(SEVERITIES) if record_type == "FM" else [],
        "allowed_probable_cause_outputs": (
            sorted(PROBABLE_CAUSES) if record_type == "FM" else []
        ),
        "allowed_operations": {
            "trim": {"shape": {"op": "trim"}, "source_type": "string"},
            "scale": {
                "shape": {"op": "scale", "factor": "<positive_number>"},
                "source_type": "integer or number",
            },
            "enum": {
                "shape": {"op": "enum", "values": {"<source_value>": "<standard_value>"}},
                "note": "severity and probable_cause require exactly one enum operation",
            },
        },
        "allowed_destinations": {
            "record": "top-level Unified record fields",
            "counters": "PM only",
            "parameters": "CM only",
            "transient": "FM is_cleared only; removed before final output",
        },
    }


def _build_prompt(
        *,
        doc_filename: str,
        doc_content: str,
        dictionary_content: str,
        unified_schema_content: str,
        vendor: str,
        record_type: str,
        existing_rules_str: str,
        samples: list[dict[str, Any]],
        added_fields: list[str],
        removed_fields: list[str],
) -> str:
    template = json.dumps(get_json_template(record_type, vendor), ensure_ascii=False, indent=2)
    contract = json.dumps(_contract_reference(record_type), ensure_ascii=False, indent=2)
    sample_text = json.dumps(samples, ensure_ascii=False, indent=2)

    return f"""
[Authoritative Pipeline Rule Contract]
The output is NOT a Unified data record. It is one declarative rule object consumed directly by pipeline_core.rules.validate_rule. Use exactly the canonical keys shown in the template.

Canonical contract reference:
{contract}

[Required Canonical JSON Shape]
{template}

[Important Rule Semantics & Version Update Directives]
1. Replace every <placeholder>; no placeholder may remain.
2. match.required_fields must be a minimal but unique source-field signature.
3. Every match.required_fields item and every time source must also appear in required_source_fields.
4. Each mappings item is source-to-standard and has sources in priority order.
5. Use operations:[{{"op":"scale","factor":N}}] for unit conversion. If the ICD changed a format (e.g., % to ratio), UPDATE the scale factor.
6. For FM clear indicators, map a documented boolean/code to destination="transient", target="is_cleared".
7. Return exactly ONE JSON object for {vendor}/{record_type}.

[Deterministic Schema Diff (Physical Data Analysis)]
The following lists were generated by diffing the keys in the NEW raw samples against the fields expected by the OLD existing rules.
- Added Fields (exist in new data, but not in old rules): {added_fields}
- Removed Fields (existed in old rules, but absent from new data): {removed_fields}

CRITICAL DIRECTIVES BASED ON DIFF:
- YOU MUST include the 'Added Fields' inside `match.required_fields` to definitively route new data to this new rule.
- YOU MUST include the 'Removed Fields' inside `match.forbidden_fields` to prevent this new rule from misfiring on older data.
- YOU MUST ALWAYS output `compatible_source_document_versions: []`. Do not guess backward compatibility. Physical dry-run validations will handle appending older versions automatically later.

[Counter Dictionary]
{dictionary_content}

[Unified Output Schema]
{unified_schema_content}

[Vendor ICD]
file: {doc_filename}
{doc_content}

[Parsed Raw Samples (Unique Schemas)]
{sample_text}

[Existing Valid Rules For The Same Vendor And Record Type]
Use these as regression context to understand the PREVIOUS version's signature.
{existing_rules_str}
""".strip()


def _contains_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return re.search(r"<[^>]+>", value) is not None
    if isinstance(value, list):
        return any(_contains_placeholder(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_placeholder(item) for item in value.values())
    return False


def _validate_generated_rule(
        data: Any,
        *,
        vendor: str,
        record_type: str,
        path: Path,
) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise AgentError(f"{vendor}/{record_type}: Claude 출력 최상위가 JSON 객체가 아닙니다.")
    legacy = sorted(set(data).intersection(LEGACY_AGENT_KEYS))
    if legacy:
        raise AgentError(f"{vendor}/{record_type}: 폐기된 Agent 키가 포함되었습니다: {', '.join(legacy)}")
    missing = sorted(CANONICAL_RULE_KEYS - set(data))
    extra = sorted(set(data) - CANONICAL_RULE_KEYS)
    if missing:
        raise AgentError(f"{vendor}/{record_type}: Pipeline 규칙 필수 키 누락: {', '.join(missing)}")
    if extra:
        raise AgentError(f"{vendor}/{record_type}: 지원하지 않는 최상위 키: {', '.join(extra)}")
    if data.get("vendor") != vendor or data.get("record_type") != record_type:
        raise AgentError(f"{vendor}/{record_type}: Claude 출력의 vendor/record_type이 요청과 다릅니다.")
    if _contains_placeholder(data):
        raise AgentError(f"{vendor}/{record_type}: 규칙에 치환되지 않은 placeholder가 있습니다.")

    try:
        return validate_rule(data, path)
    except RuleValidationError as exc:
        raise AgentError(f"{vendor}/{record_type}: Pipeline 규칙 검증 실패: {exc}") from exc


def _generate_rule_with_repair(
        *,
        prompt: str,
        vendor: str,
        record_type: str,
        maximum_attempts: int = 3,
) -> dict[str, Any]:
    system_prompt = (
        "You generate deterministic declarative data-mapping rules. "
        "Return exactly one valid JSON object and no markdown or commentary. "
        "Never invent a source field, unit, enum value, or conversion without "
        "evidence from the supplied ICD or parsed sample."
    )

    messages = [{"role": "user", "content": prompt}]
    last_error = ""

    for attempt in range(1, maximum_attempts + 1):
        response_text = call_llm_api(messages, system=system_prompt)
        cleaned = clean_json_output(response_text)

        try:
            parsed = json.loads(cleaned)
            parsed["compatible_source_document_versions"] = []

            return _validate_generated_rule(
                parsed,
                vendor=vendor,
                record_type=record_type,
                path=Path(f"<claude:{vendor}:{record_type}>"),
            )
        except (json.JSONDecodeError, AgentError) as exc:
            last_error = str(exc)
            if attempt == maximum_attempts:
                break

            messages.append({"role": "assistant", "content": response_text})
            messages.append({
                "role": "user",
                "content": f"[Validation Error]\n{last_error}\n\nProvide the completely corrected JSON object only."
            })

    raise AgentError(
        f"{vendor}/{record_type}: {maximum_attempts}회 생성 후에도 유효한 규칙을 만들지 못했습니다. "
        f"마지막 오류: {last_error}"
    )


def _merge_candidate_bundle(
        existing: Iterable[dict[str, Any]],
        generated: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = {_rule_slot(item): item for item in existing}
    for item in generated:
        merged[_rule_slot(item)] = item
    return sorted(merged.values(), key=_rule_sort_key)


def propose(
        doc_file: str,
        vendor: str,
        rules_dir: str,
        out_dir: str,
        sample_dir: str | None = None,
) -> int:
    if vendor not in {"VENDOR_A", "VENDOR_B", "VENDOR_C"}:
        raise AgentError(f"지원하지 않는 vendor입니다: {vendor}")

    doc_path = Path(doc_file)
    doc_content = _read_text(doc_path, "ICD")
    dictionary_content = _read_text(
        PROJECT_ROOT / "schema" / "counter_dictionary.md",
        "Counter Dictionary",
    )
    unified_schema_content = _read_text(
        PROJECT_ROOT / "schema" / "unified_v1.schema.json",
        "Unified Schema",
    )

    generated: list[dict[str, Any]] = []
    prompt_snapshots: dict[str, str] = {}
    print(f"[{vendor}] ICD 문서 분석 시작: {doc_path}")

    for record_type in RECORD_TYPES:
        samples = _sample_records(sample_dir, vendor, record_type)

        existing_rules_str, existing_rule_dicts = _existing_rule_context(rules_dir, vendor, record_type)

        old_fields = set()
        for rule_data in existing_rule_dicts:
            old_fields.update(rule_data.get("required_source_fields", []))
            for mapping in rule_data.get("mappings", []):
                for source in mapping.get("sources", []):
                    old_fields.add(source.get("field", ""))
        old_fields.discard("")
        old_fields.discard(None)

        new_fields = set()
        for rec in samples:
            new_fields.update(rec.keys())

        added_fields = sorted(new_fields - old_fields) if old_fields else []
        removed_fields = sorted(old_fields - new_fields) if old_fields else []

        prompt = _build_prompt(
            doc_filename=doc_path.name,
            doc_content=doc_content,
            dictionary_content=dictionary_content,
            unified_schema_content=unified_schema_content,
            vendor=vendor,
            record_type=record_type,
            existing_rules_str=existing_rules_str,
            samples=samples,
            added_fields=added_fields,
            removed_fields=removed_fields,
        )

        prompt_snapshots[record_type] = prompt
        print(
            f"[{vendor}/{record_type}] 규칙 생성 중"
            + (f" - 고유 스키마 샘플 {len(samples)}건 대조 완료" if samples else " - 문서 기준")
        )
        generated.append(
            _generate_rule_with_repair(
                prompt=prompt,
                vendor=vendor,
                record_type=record_type,
            )
        )

    rules_root, staging_dir = _rules_root_and_staging(out_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    document_version = generated[0].get("source_document_version", "unknown")
    version_str = document_version.replace(".", "_")

    candidate_path = staging_dir / f"{vendor.lower()}_{version_str}_candidates.json"

    existing_candidates: list[dict[str, Any]] = []
    if candidate_path.is_file():
        for index, item in enumerate(_load_rule_items(candidate_path)):
            existing_candidates.append(
                validate_rule(item, Path(f"{candidate_path}#{index}"))
            )

    bundle = _merge_candidate_bundle(existing_candidates, generated)
    _atomic_write_json(candidate_path, bundle)

    snapshot_name = f"{vendor.lower()}_{version_str}_prompt_snapshot.json"
    snapshot = {
        "vendor": vendor,
        "source_document": doc_path.name,
        "source_document_version": document_version,
        "record_types": list(RECORD_TYPES),
        "prompts": prompt_snapshots,
    }
    _atomic_write_json(rules_root / "artifacts" / snapshot_name, snapshot)

    print(
        f"[PROPOSED] {len(generated)}개 규칙을 개별 파일로 저장했습니다: "
        f"{candidate_path}"
    )
    print(
        f"[NEXT] python agent.py validate --rules {rules_root} "
        f"--input {sample_dir or '<raw_dir>'}"
    )
    return 0


def _rules_from_repository(repository: RuleRepository) -> list[Rule]:
    return list(repository.rules)


def _repository_from_rules(rules: Iterable[Rule]) -> RuleRepository:
    ordered = sorted(
        rules,
        key=lambda rule: (
            rule.vendor,
            RECORD_TYPE_ORDER.get(rule.record_type, 99),
            rule.data["source_document_version"],
            rule.data["rule_version"],
            rule.path.as_posix(),
        ),
    )
    identities: dict[tuple[str, str, str, str], Path] = {}
    signatures: dict[tuple[str, str, str], Path] = {}
    for rule in ordered:
        identity = (
            rule.vendor,
            rule.record_type,
            rule.data["source_document_version"],
            rule.data["rule_version"],
        )
        if identity in identities:
            raise AgentError(
                f"중복 규칙 identity: {identity} ({identities[identity]}, {rule.path})"
            )
        identities[identity] = rule.path
        signature = (
            rule.vendor,
            rule.record_type,
            _canonical_json(rule.data["match"]),
        )
        if signature in signatures:
            raise AgentError(
                f"중복 규칙 signature: {rule.vendor}/{rule.record_type} "
                f"({signatures[signature]}, {rule.path})"
            )
        signatures[signature] = rule.path
    return RuleRepository(ordered)


def _merge_active_and_candidates(
        active: Iterable[Rule],
        candidates: Iterable[Rule],
) -> RuleRepository:
    candidate_rules = list(candidates)
    replacement_slots = {_rule_slot(rule.data) for rule in candidate_rules}
    combined = [
        rule for rule in active
        if _rule_slot(rule.data) not in replacement_slots
    ]
    combined.extend(candidate_rules)
    return _repository_from_rules(combined)


def _json_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.json") if path.is_file())


def _resolve_validation_rules(
        rules_dir: str | Path,
) -> tuple[Path, RuleRepository, list[Rule], bool]:
    requested = Path(rules_dir)
    if not requested.is_dir():
        raise AgentError(f"규칙 디렉터리가 없습니다: {requested}")

    if requested.name == "staging":
        rules_root = requested.parent
        staging = requested
    else:
        rules_root = requested
        staging = rules_root / "staging"

    staged_files = _json_files(staging) if staging.is_dir() else []
    if staged_files:
        staged_repository = load_rules(staging)
        staged_rules = _rules_from_repository(staged_repository)
        active_dir = rules_root / "active"
        active_rules: list[Rule] = []
        if active_dir.is_dir() and _json_files(active_dir):
            active_rules = _rules_from_repository(load_rules(active_dir))
        effective = _merge_active_and_candidates(active_rules, staged_rules)
        return rules_root, effective, staged_rules, True

    repository = load_rules(requested)
    return rules_root, repository, _rules_from_repository(repository), False


def _input_files(input_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in input_dir.rglob("*")
        if path.is_file()
        and vendor_of(path.name) is not None
        and kind_of(path.name) is not None
    )


def _validate_with_raw_input(
        *,
        repository: RuleRepository,
        required_rules: list[Rule],
        input_dir: Path,
        require_every_rule: bool,
) -> None:
    files = _input_files(input_dir)
    if not files:
        raise AgentError(f"검증 가능한 원본 파일이 없습니다: {input_dir}")

    initialize_validator()
    stats: dict[int, dict[str, int]] = {
        id(rule): {"selected": 0, "accepted": 0, "rejected": 0}
        for rule in required_rules
    }
    required_by_id = {id(rule): rule for rule in required_rules}
    selection_failures = 0
    parse_failures = 0

    for path in files:
        vendor = vendor_of(path.name)
        record_type = kind_of(path.name)
        try:
            parsed = parse_file(str(path))
            for raw, error in parsed:
                if error is not None or not isinstance(raw, dict):
                    parse_failures += 1
                    continue
                try:
                    selected = repository.select(vendor, record_type, raw)
                except RecordError:
                    selection_failures += 1
                    continue
                selected_stats = stats.get(id(selected))
                if selected_stats is None:
                    continue
                selected_stats["selected"] += 1
                try:
                    record = transform_raw(raw, selected)
                    validate_record(record)
                except RecordError:
                    selected_stats["rejected"] += 1
                else:
                    selected_stats["accepted"] += 1
        except (OSError, UnicodeError, RuntimeError, TypeError, ValueError):
            parse_failures += 1

    failed_labels: list[str] = []
    total_accepted = 0

    for rule_id, rule in sorted(
            required_by_id.items(),
            key=lambda item: _rule_sort_key(item[1].data),
    ):
        rule_stats = stats[rule_id]
        selected = rule_stats["selected"]
        accepted = rule_stats["accepted"]
        rejected = rule_stats["rejected"]
        total_accepted += accepted

        if selected == 0:
            if not require_every_rule:
                status = "SKIP"
                print(f"[{status}] {rule.label}: selected=0")
            else:
                status = "FAIL"
                failed_labels.append(rule.label)
                print(f"[{status}] {rule.label}: selected=0 (필수 데이터 매칭 실패)")
        else:
            rejection_ratio = rejected / selected
            # 허용 임계치(10%) 이하의 거절률이면서 최소 1건 이상 성공해야 승격 통과
            if rejection_ratio <= MAX_REJECTION_RATIO and accepted > 0:
                status = "PASS"
            else:
                status = "FAIL"
                failed_labels.append(rule.label)

            print(
                f"[{status}] {rule.label}: selected={selected} "
                f"accepted={accepted} rejected={rejected} "
                f"(거절률: {rejection_ratio:.1%})"
            )

    print(
        f"[RAW SUMMARY] files={len(files)} parse_failures={parse_failures} "
        f"selection_failures={selection_failures}"
    )
    if failed_labels:
        raise AgentError(
            "실제 원본 변환 거절률이 임계치를 초과했거나 매칭 데이터가 없는 규칙: "
            + ", ".join(failed_labels)
        )
    if total_accepted == 0:
        raise AgentError("어떤 규칙도 실제 원본을 정상 Unified 레코드로 변환하지 못했습니다.")


def _unique_directory(parent: Path, stem: str) -> Path:
    candidate = parent / stem
    suffix = 2
    while candidate.exists():
        candidate = parent / f"{stem}_{suffix}"
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def _promote(
        *,
        rules_root: Path,
        repository: RuleRepository,
        staged_rules: list[Rule],
) -> Path:
    active_dir = rules_root / "active"
    staging_dir = rules_root / "staging"
    archive_root = rules_root / "archive"
    artifacts_dir = rules_root / "artifacts"
    active_dir.mkdir(parents=True, exist_ok=True)
    archive_root.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    bundle = sorted(
        (rule.data for rule in repository.rules),
        key=_rule_sort_key,
    )
    digest = hashlib.sha256(_canonical_json(bundle).encode("utf-8")).hexdigest()[:12]

    existing_active = _json_files(active_dir)
    if existing_active:
        old_digest = hashlib.sha256(
            "\n".join(
                f"{path.relative_to(active_dir).as_posix()}:{hashlib.sha256(path.read_bytes()).hexdigest()}"
                for path in existing_active
            ).encode("utf-8")
        ).hexdigest()[:12]
        archive_dir = _unique_directory(archive_root, f"active_{old_digest}")
        for path in existing_active:
            relative = path.relative_to(active_dir)
            destination = archive_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(destination))

    grouped_rules = {}
    for rule in repository.rules:
        key = (rule.vendor, rule.data.get("source_document_version", "unknown"))
        grouped_rules.setdefault(key, []).append(rule.data)

    for (v_name, v_doc), rule_list in grouped_rules.items():
        safe_ver = v_doc.replace(".", "_")
        file_path = active_dir / f"{v_name.lower()}_{safe_ver}_rules.json"
        _atomic_write_json(file_path, sorted(rule_list, key=_rule_sort_key))

    staged_bundle = sorted((rule.data for rule in staged_rules), key=_rule_sort_key)
    _atomic_write_json(
        artifacts_dir / f"validated_candidates_{digest}.json",
        staged_bundle,
    )
    if staging_dir.is_dir():
        validated_dir = _unique_directory(
            artifacts_dir,
            f"staging_validated_{digest}",
        )
        for path in _json_files(staging_dir):
            relative = path.relative_to(staging_dir)
            destination = validated_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(destination))

    return active_dir


def validate(rules_dir: str, input_dir: str) -> int:
    input_path = Path(input_dir)
    if not input_path.is_dir():
        raise AgentError(f"입력 데이터 디렉터리가 없습니다: {input_path}")

    rules_root, repository, checked_rules, staged = _resolve_validation_rules(rules_dir)
    mode = "staging 후보 + active 회귀" if staged else "active 규칙"
    print(
        f"[SCHEMA PASS] {len(repository.rules)}개 Pipeline 규칙 로드 완료 "
        f"({mode})"
    )
    _validate_with_raw_input(
        repository=repository,
        required_rules=checked_rules,
        input_dir=input_path,
        require_every_rule=staged,
    )

    if staged:
        active_path = _promote(
            rules_root=rules_root,
            repository=repository,
            staged_rules=checked_rules,
        )
        print(f"[PROMOTED] 검증을 통과한 후보를 활성 규칙 파일로 분리 승격했습니다: {active_path}")
    else:
        print("[VALIDATION PASS] 활성 규칙과 실제 원본의 적용 검증을 통과했습니다.")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Claude Agent for Pipeline-Compatible Declarative Rule Generation"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose_parser = subparsers.add_parser("propose")
    propose_parser.add_argument("--doc", required=True)
    propose_parser.add_argument("--vendor", required=True)
    propose_parser.add_argument("--rules", required=True)
    propose_parser.add_argument("--out", required=True)
    propose_parser.add_argument("--sample", required=False)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--rules", required=True)
    validate_parser.add_argument("--input", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "propose":
            return propose(
                args.doc,
                args.vendor,
                args.rules,
                args.out,
                args.sample,
            )
        if args.command == "validate":
            return validate(args.rules, args.input)
        raise AgentError(f"지원하지 않는 명령입니다: {args.command}")
    except (AgentError, PipelineError, RuleValidationError, OSError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())