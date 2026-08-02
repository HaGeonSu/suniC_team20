"""Rule repository loading, validation, and signature-based selection."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .errors import RecordError, RuleValidationError

RULE_SCHEMA_VERSION = "1.0"
VENDORS = {"VENDOR_A", "VENDOR_B", "VENDOR_C"}
RECORD_TYPES = {"PM", "CM", "FM"}
VALUE_TYPES = {"string", "integer", "number", "boolean"}
DESTINATIONS = {"record", "counters", "parameters", "transient"}
CONFLICT_POLICIES = {"reject_if_different", "prefer_first"}
TIME_FORMATS = {"%Y%m%d%H%M%S", "iso8601_utc", "epoch_ms"}
TIME_ROLES = {"interval_start", "interval_end", "instant"}
INTERVAL_UNITS = {"minute", "second", "iso_duration"}
OPERATIONS = {"trim", "scale", "enum"}
ACTIVE_RULES_DIRNAME = "active"
NON_ACTIVE_RULE_DIRS = {"staging", "artifacts", "archive"}

PM_COUNTERS = {
    "sip.register.attempt",
    "sip.register.success",
    "sip.register.fail",
    "sip.invite.attempt",
    "sip.invite.success",
    "sip.invite.fail",
    "sip.response.4xx",
    "sip.response.5xx",
    "sip.response.6xx",
    "session.active.count",
    "session.setup.time_ms",
    "resource.cpu.usage",
    "resource.memory.usage",
    "traffic.msg.rx",
    "traffic.msg.tx",
    "sip.register.success_rate",
    "sip.invite.fail_5xx",
}
CM_PARAMETERS = {
    "sip.timer.t1_ms",
    "sip.timer.t2_ms",
    "sip.timer.invite_timeout_ms",
    "registration.expire_sec",
    "session.max_count",
    "session.expire_sec",
    "overload.cpu_threshold",
    "transport.sip.port",
    "ha.heartbeat_interval_ms",
    "qos.dscp.value",
}
RECORD_TARGETS = {
    "PM": {"ne_id", "ne_type"},
    "CM": {"ne_id", "ne_type", "snapshot_id"},
    "FM": {
        "ne_id",
        "ne_type",
        "alarm_id",
        "severity",
        "probable_cause",
        "managed_object",
        "additional_text",
    },
}
TRANSIENT_TARGETS = {"is_cleared"}
SEVERITIES = {"CRITICAL", "MAJOR", "MINOR", "WARNING", "CLEARED"}
PROBABLE_CAUSES = {
    "LINK_FAILURE",
    "CPU_OVERLOAD",
    "MEMORY_EXHAUSTION",
    "LICENSE_EXPIRY",
    "REGISTRATION_STORM",
    "SIP_TIMEOUT",
    "DATABASE_UNAVAILABLE",
    "CONFIG_MISMATCH",
}
PM_TARGET_TYPES = {
    "sip.register.attempt": "integer",
    "sip.register.success": "integer",
    "sip.register.fail": "integer",
    "sip.invite.attempt": "integer",
    "sip.invite.success": "integer",
    "sip.invite.fail": "integer",
    "sip.response.4xx": "integer",
    "sip.response.5xx": "integer",
    "sip.response.6xx": "integer",
    "session.active.count": "integer",
    "session.setup.time_ms": "number",
    "resource.cpu.usage": "number",
    "resource.memory.usage": "number",
    "traffic.msg.rx": "integer",
    "traffic.msg.tx": "integer",
    "sip.register.success_rate": "number",
    "sip.invite.fail_5xx": "integer",
}
CM_TARGET_TYPES = {
    "sip.timer.t1_ms": "integer",
    "sip.timer.t2_ms": "integer",
    "sip.timer.invite_timeout_ms": "integer",
    "registration.expire_sec": "integer",
    "session.max_count": "integer",
    "session.expire_sec": "integer",
    "overload.cpu_threshold": "number",
    "transport.sip.port": "integer",
    "ha.heartbeat_interval_ms": "integer",
    "qos.dscp.value": "integer",
}
RECORD_TARGET_TYPES = {
    "ne_id": "string",
    "ne_type": "string",
    "snapshot_id": "string",
    "alarm_id": "string",
    "severity": "string",
    "probable_cause": "string",
    "managed_object": "string",
    "additional_text": "string",
}


@dataclass(frozen=True)
class Rule:
    path: Path
    data: dict[str, Any]

    @property
    def vendor(self) -> str:
        return self.data["vendor"]

    @property
    def record_type(self) -> str:
        return self.data["record_type"]

    @property
    def label(self) -> str:
        return (
            f"{self.vendor}/{self.record_type}/"
            f"{self.data['source_document_version']}@{self.data['rule_version']}"
        )

    def matches(self, raw: dict[str, Any]) -> bool:
        match = self.data["match"]
        keys = set(raw)
        return (
            set(match["required_fields"]).issubset(keys)
            and not set(match["forbidden_fields"]).intersection(keys)
            and all(set(group).intersection(keys) for group in match["any_of"])
        )


class RuleRepository:
    def __init__(self, rules: Iterable[Rule]) -> None:
        ordered = sorted(
            rules,
            key=lambda r: (
                r.vendor,
                r.record_type,
                r.data["source_document_version"],
                r.data["rule_version"],
                r.path.as_posix(),
            ),
        )
        self.rules = tuple(ordered)
        self._by_identity: dict[tuple[str, str], tuple[Rule, ...]] = {}
        for vendor in sorted(VENDORS):
            for record_type in sorted(RECORD_TYPES):
                selected = tuple(
                    r for r in self.rules if r.vendor == vendor and r.record_type == record_type
                )
                if selected:
                    self._by_identity[(vendor, record_type)] = selected

    def candidates(self, vendor: str, record_type: str) -> tuple[Rule, ...]:
        return self._by_identity.get((vendor, record_type), ())

    def select(self, vendor: str, record_type: str, raw: dict[str, Any]) -> Rule:
        candidates = self.candidates(vendor, record_type)
        matches = [rule for rule in candidates if rule.matches(raw)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            labels = ", ".join(rule.label for rule in matches)
            raise RecordError("RULE_AMBIGUOUS", f"둘 이상의 규칙 시그니처가 일치합니다: {labels}")

        other_kinds = sorted(
            {
                rule.record_type
                for rule in self.rules
                if rule.vendor == vendor and rule.record_type != record_type and rule.matches(raw)
            }
        )
        if other_kinds:
            raise RecordError(
                "INPUT_TYPE_MISMATCH",
                f"파일명 유형은 {record_type}이지만 본문 시그니처는 {','.join(other_kinds)}입니다.",
            )
        if not candidates:
            raise RecordError(
                "RULE_NOT_FOUND",
                f"{vendor}/{record_type}에 적용할 규칙이 없습니다.",
            )
        raise RecordError(
            "RULE_NOT_FOUND",
            f"{vendor}/{record_type} 규칙의 필드 시그니처와 일치하지 않습니다.",
        )


def _fail(path: Path, message: str) -> None:
    raise RuleValidationError(f"{path}: {message}")


def _require_string(data: dict[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        _fail(path, f"{key}는 비어 있지 않은 문자열이어야 합니다.")
    return value


def _string_list(value: Any, name: str, path: Path, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        _fail(path, f"{name}는 문자열 배열이어야 합니다.")
    if any(not isinstance(item, str) or not item for item in value):
        _fail(path, f"{name}에는 비어 있지 않은 문자열만 허용됩니다.")
    if len(value) != len(set(value)):
        _fail(path, f"{name}에 중복 값이 있습니다.")
    return value


def _validate_match(data: dict[str, Any], path: Path) -> None:
    match = data.get("match")
    if not isinstance(match, dict):
        _fail(path, "match 객체가 필요합니다.")
    required = _string_list(match.get("required_fields"), "match.required_fields", path, allow_empty=False)
    forbidden = _string_list(match.get("forbidden_fields", []), "match.forbidden_fields", path)
    any_of = match.get("any_of", [])
    if not isinstance(any_of, list):
        _fail(path, "match.any_of는 문자열 배열의 배열이어야 합니다.")
    for index, group in enumerate(any_of):
        _string_list(group, f"match.any_of[{index}]", path, allow_empty=False)
    if set(required).intersection(forbidden):
        _fail(path, "match.required_fields와 forbidden_fields가 겹칩니다.")


def _validate_time(data: dict[str, Any], path: Path) -> None:
    time_rule = data.get("time")
    if not isinstance(time_rule, dict):
        _fail(path, "time 객체가 필요합니다.")
    _require_string(time_rule, "source", path)
    if time_rule.get("target") != "timestamp":
        _fail(path, "time.target은 timestamp여야 합니다.")
    raw_format = time_rule.get("format")
    if raw_format not in TIME_FORMATS:
        _fail(path, f"지원하지 않는 time.format: {raw_format!r}")
    role = time_rule.get("role")
    if role not in TIME_ROLES:
        _fail(path, f"지원하지 않는 time.role: {role!r}")
    if raw_format == "%Y%m%d%H%M%S" and time_rule.get("source_timezone") != "Asia/Seoul":
        _fail(path, "시간대 없는 Vendor A 시각은 source_timezone=Asia/Seoul이어야 합니다.")
    if data["record_type"] == "PM":
        _require_string(time_rule, "interval_source", path)
        if time_rule.get("interval_unit") not in INTERVAL_UNITS:
            _fail(path, f"지원하지 않는 interval_unit: {time_rule.get('interval_unit')!r}")
    elif "interval_source" in time_rule or "interval_unit" in time_rule:
        _fail(path, "PM이 아닌 규칙에는 interval_source/interval_unit을 둘 수 없습니다.")
    if data["record_type"] == "FM":
        _require_string(time_rule, "event_time_source", path)


def _allowed_target(record_type: str, destination: str, target: str) -> bool:
    if destination == "record":
        return target in RECORD_TARGETS[record_type]
    if destination == "counters":
        return record_type == "PM" and target in PM_COUNTERS
    if destination == "parameters":
        return record_type == "CM" and target in CM_PARAMETERS
    if destination == "transient":
        return record_type == "FM" and target in TRANSIENT_TARGETS
    return False


def _required_target_type(destination: str, target: str) -> str:
    if destination == "record":
        return RECORD_TARGET_TYPES[target]
    if destination == "counters":
        return PM_TARGET_TYPES[target]
    if destination == "parameters":
        return CM_TARGET_TYPES[target]
    return "boolean"


def _validate_operation(operation: Any, path: Path, label: str) -> None:
    if not isinstance(operation, dict):
        _fail(path, f"{label}의 operation은 객체여야 합니다.")
    name = operation.get("op")
    if name not in OPERATIONS:
        _fail(path, f"{label}에 지원하지 않는 연산이 있습니다: {name!r}")
    if name == "scale":
        factor = operation.get("factor")
        if (
            isinstance(factor, bool)
            or not isinstance(factor, (int, float))
            or not math.isfinite(float(factor))
            or float(factor) <= 0
        ):
            _fail(path, f"{label}의 scale factor는 유한한 양수여야 합니다.")
    if name == "enum":
        values = operation.get("values")
        if not isinstance(values, dict) or not values:
            _fail(path, f"{label}의 enum values는 비어 있지 않은 객체여야 합니다.")
        if any(not isinstance(key, str) for key in values):
            _fail(path, f"{label}의 enum key는 문자열이어야 합니다.")


def _validate_mappings(data: dict[str, Any], path: Path) -> None:
    mappings = data.get("mappings")
    if not isinstance(mappings, list) or not mappings:
        _fail(path, "mappings는 비어 있지 않은 배열이어야 합니다.")
    seen_targets: set[tuple[str, str]] = set()
    for index, mapping in enumerate(mappings):
        label = f"mappings[{index}]"
        if not isinstance(mapping, dict):
            _fail(path, f"{label}는 객체여야 합니다.")
        sources = mapping.get("sources")
        if not isinstance(sources, list) or not sources:
            _fail(path, f"{label}.sources는 비어 있지 않은 배열이어야 합니다.")
        priorities: list[int] = []
        fields: list[str] = []
        for source in sources:
            if not isinstance(source, dict):
                _fail(path, f"{label}.sources 항목은 객체여야 합니다.")
            field = source.get("field")
            priority = source.get("priority")
            if not isinstance(field, str) or not field:
                _fail(path, f"{label}.sources.field가 누락되었습니다.")
            if not isinstance(priority, int) or isinstance(priority, bool) or priority < 1:
                _fail(path, f"{label}.sources.priority는 1 이상의 정수여야 합니다.")
            fields.append(field)
            priorities.append(priority)
        if len(fields) != len(set(fields)) or len(priorities) != len(set(priorities)):
            _fail(path, f"{label}.sources의 field 또는 priority가 중복됩니다.")
        if priorities != sorted(priorities):
            _fail(path, f"{label}.sources는 priority 오름차순이어야 합니다.")
        destination = mapping.get("destination")
        target = mapping.get("target")
        if destination not in DESTINATIONS:
            _fail(path, f"{label}.destination이 잘못되었습니다: {destination!r}")
        if not isinstance(target, str) or not target:
            _fail(path, f"{label}.target이 누락되었습니다.")
        if not _allowed_target(data["record_type"], destination, target):
            _fail(path, f"{label}의 표준 target이 허용되지 않습니다: {destination}.{target}")
        target_key = (destination, target)
        if target_key in seen_targets:
            _fail(path, f"같은 target으로의 모호한 중복 매핑: {destination}.{target}")
        seen_targets.add(target_key)
        if mapping.get("source_type") not in VALUE_TYPES:
            _fail(path, f"{label}.source_type이 잘못되었습니다.")
        if mapping.get("target_type") not in VALUE_TYPES:
            _fail(path, f"{label}.target_type이 잘못되었습니다.")
        required_target_type = _required_target_type(destination, target)
        if mapping["target_type"] != required_target_type:
            _fail(
                path,
                f"{label}.target_type은 {destination}.{target}의 사전 타입 "
                f"{required_target_type!r}이어야 합니다.",
            )
        if mapping.get("conflict_policy") not in CONFLICT_POLICIES:
            _fail(path, f"{label}.conflict_policy가 잘못되었습니다.")
        operations = mapping.get("operations")
        if not isinstance(operations, list):
            _fail(path, f"{label}.operations는 배열이어야 합니다.")
        for op_index, operation in enumerate(operations):
            _validate_operation(operation, path, f"{label}.operations[{op_index}]")
            if operation["op"] == "trim" and mapping["source_type"] != "string":
                _fail(path, f"{label}의 trim 연산은 string source에만 허용됩니다.")
            if operation["op"] == "scale" and mapping["source_type"] not in {"integer", "number"}:
                _fail(path, f"{label}의 scale 연산은 수치 source에만 허용됩니다.")
        enum_operations = [operation for operation in operations if operation["op"] == "enum"]
        if target in {"severity", "probable_cause"}:
            if len(enum_operations) != 1:
                _fail(path, f"{label}의 {target} 매핑에는 enum 연산이 정확히 하나 필요합니다.")
            allowed = SEVERITIES if target == "severity" else PROBABLE_CAUSES
            outputs = set(enum_operations[0]["values"].values())
            if not outputs.issubset(allowed):
                _fail(path, f"{label}의 {target} enum 출력에 표준에 없는 값이 있습니다.")


def validate_rule(data: Any, path: Path) -> dict[str, Any]:
    if not isinstance(data, dict):
        _fail(path, "규칙 최상위는 객체여야 합니다.")
    if data.get("rule_schema_version") != RULE_SCHEMA_VERSION:
        _fail(path, f"지원하지 않는 rule_schema_version: {data.get('rule_schema_version')!r}")
    _require_string(data, "rule_version", path)
    _require_string(data, "source_document_version", path)
    compatible = data.get("compatible_source_document_versions", [])
    _string_list(compatible, "compatible_source_document_versions", path)
    if data.get("vendor") not in VENDORS:
        _fail(path, f"지원하지 않는 vendor: {data.get('vendor')!r}")
    if data.get("record_type") not in RECORD_TYPES:
        _fail(path, f"지원하지 않는 record_type: {data.get('record_type')!r}")
    _validate_match(data, path)
    required = _string_list(
        data.get("required_source_fields"),
        "required_source_fields",
        path,
        allow_empty=False,
    )
    if not set(data["match"]["required_fields"]).issubset(required):
        _fail(path, "match.required_fields는 required_source_fields의 부분집합이어야 합니다.")
    _validate_time(data, path)
    time_rule = data["time"]
    time_sources = {time_rule["source"]}
    if data["record_type"] == "PM":
        time_sources.add(time_rule["interval_source"])
    if data["record_type"] == "FM":
        time_sources.add(time_rule["event_time_source"])
    missing_time_sources = sorted(time_sources - set(required))
    if missing_time_sources:
        _fail(
            path,
            "시간 원본 필드는 required_source_fields에 포함되어야 합니다: "
            + ", ".join(missing_time_sources),
        )
    _validate_mappings(data, path)
    unmapped = data.get("unmapped")
    if not isinstance(unmapped, list):
        _fail(path, "unmapped는 배열이어야 합니다.")
    for index, item in enumerate(unmapped):
        if not isinstance(item, dict):
            _fail(path, f"unmapped[{index}]는 객체여야 합니다.")
        _require_string(item, "source", path)
        _require_string(item, "reason", path)
        _require_string(item, "evidence", path)
    return data


def _canonical_signature(rule: Rule) -> str:
    return json.dumps(rule.data["match"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _active_rules_root(root: Path) -> Path:
    active = root / ACTIVE_RULES_DIRNAME
    return active if active.is_dir() else root


def _is_active_rule_file(path: Path, search_root: Path) -> bool:
    try:
        relative_parts = path.relative_to(search_root).parts[:-1]
    except ValueError:
        return False
    return not any(part in NON_ACTIVE_RULE_DIRS or part.startswith(".") for part in relative_parts)


def load_rules(rules_dir: str | Path) -> RuleRepository:
    root = Path(rules_dir)
    if not root.exists():
        raise RuleValidationError(f"규칙 디렉터리가 없습니다: {root}")
    if not root.is_dir():
        raise RuleValidationError(f"규칙 경로가 디렉터리가 아닙니다: {root}")

    search_root = _active_rules_root(root)
    files = sorted(
        path
        for path in search_root.rglob("*.json")
        if path.is_file() and _is_active_rule_file(path, search_root)
    )
    if not files:
        if search_root != root:
            raise RuleValidationError(f"활성 규칙 JSON이 없습니다: {search_root}")
        raise RuleValidationError(f"규칙 JSON이 없습니다: {root}")

    rules: list[Rule] = []
    for path in files:
        try:
            with path.open(encoding="utf-8") as handle:
                loaded = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuleValidationError(f"{path}: 규칙 JSON 읽기 실패: {exc}") from exc
        items = loaded if isinstance(loaded, list) else [loaded]
        for index, item in enumerate(items):
            item_path = path if len(items) == 1 else Path(f"{path}#{index}")
            rules.append(Rule(item_path, validate_rule(item, item_path)))

    identities: dict[tuple[str, str, str, str], Path] = {}
    signatures: dict[tuple[str, str, str], Path] = {}
    for rule in rules:
        identity = (
            rule.vendor,
            rule.record_type,
            rule.data["source_document_version"],
            rule.data["rule_version"],
        )
        if identity in identities:
            raise RuleValidationError(
                f"중복 규칙 identity: {identity} ({identities[identity]}, {rule.path})"
            )
        identities[identity] = rule.path
        signature = (rule.vendor, rule.record_type, _canonical_signature(rule))
        if signature in signatures:
            raise RuleValidationError(
                f"중복 규칙 signature: {rule.vendor}/{rule.record_type} "
                f"({signatures[signature]}, {rule.path})"
            )
        signatures[signature] = rule.path
    return RuleRepository(rules)
