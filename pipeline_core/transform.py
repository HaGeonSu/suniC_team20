"""Apply validated source-to-standard rules to flat adapter records."""

from __future__ import annotations

from typing import Any

from .convert import (
    apply_scale,
    cast_value,
    granularity_to_seconds,
    map_enum,
    parse_timestamp,
    set_nested_metric,
    strip_text,
    subtract_interval,
)
from .errors import RecordError
from .rules import Rule


_CONVERSION_ERROR_CODES = {
    "INVALID_STRING",
    "INVALID_INTEGER",
    "INVALID_NUMBER",
    "INVALID_BOOLEAN",
    "NON_FINITE_NUMBER",
    "UNSUPPORTED_TYPE",
    "INVALID_TIMESTAMP",
    "UNSUPPORTED_SUBSECOND",
    "UNSUPPORTED_TIME_FORMAT",
    "INVALID_DURATION",
    "UNSUPPORTED_INTERVAL_UNIT",
}


def _stable_error_code(code: str) -> str:
    if code == "UNKNOWN_ENUM_VALUE":
        return "INVALID_ENUM"
    if code in _CONVERSION_ERROR_CODES:
        return "TYPE_CONVERSION_ERROR"
    return code


def _present(raw: dict[str, Any], field: str) -> bool:
    if field not in raw or raw[field] is None:
        return False
    return not (isinstance(raw[field], str) and not raw[field].strip())


def _apply_operations(value: Any, mapping: dict[str, Any]) -> Any:
    converted = cast_value(value, mapping["source_type"])
    for operation in mapping["operations"]:
        name = operation["op"]
        if name == "trim":
            converted = strip_text(converted)
        elif name == "scale":
            converted = apply_scale(converted, float(operation["factor"]))
        elif name == "enum":
            converted = map_enum(converted, operation["values"])
        else:  # The loader prevents this branch.
            raise RecordError("UNSUPPORTED_OPERATION", f"지원하지 않는 연산: {name}")
    return cast_value(converted, mapping["target_type"])


def _resolve_mapping(raw: dict[str, Any], mapping: dict[str, Any]) -> Any | None:
    candidates: list[tuple[str, Any]] = []
    for source in mapping["sources"]:
        field = source["field"]
        if _present(raw, field):
            try:
                converted = _apply_operations(raw[field], mapping)
            except RecordError as exc:
                raise RecordError(
                    _stable_error_code(exc.code),
                    f"{field} → {mapping['target']} 변환 실패: {exc.message}",
                ) from exc
            candidates.append((field, converted))
    if not candidates:
        return None

    first_field, first_value = candidates[0]
    different = [(field, value) for field, value in candidates[1:] if value != first_value]
    if different and mapping["conflict_policy"] == "reject_if_different":
        values = ", ".join(f"{field}={value!r}" for field, value in candidates)
        raise RecordError(
            "TARGET_CONFLICT",
            f"{mapping['target']} 후보 값이 서로 다릅니다: {values}",
        )
    if different and mapping["conflict_policy"] != "prefer_first":
        raise RecordError(
            "UNSUPPORTED_CONFLICT_POLICY",
            f"지원하지 않는 충돌 정책: {mapping['conflict_policy']}",
        )
    _ = first_field
    return first_value


def _apply_time(raw: dict[str, Any], rule: Rule, record: dict[str, Any]) -> None:
    time_rule = rule.data["time"]
    granularity_sec: int | None = None
    if rule.record_type == "PM":
        granularity_sec = granularity_to_seconds(
            raw[time_rule["interval_source"]],
            time_rule["interval_unit"],
        )
        record["granularity_sec"] = granularity_sec

    timestamp = parse_timestamp(raw[time_rule["source"]], time_rule["format"])
    if time_rule["role"] == "interval_end":
        if granularity_sec is None:
            raise RecordError("INVALID_TIME_RULE", "interval_end에는 구간 길이가 필요합니다.")
        timestamp = subtract_interval(timestamp, granularity_sec)
    record["timestamp"] = timestamp

    if rule.record_type == "FM":
        record["event_time"] = parse_timestamp(
            raw[time_rule["event_time_source"]],
            time_rule["format"],
        )


def transform_raw(raw: dict[str, Any], rule: Rule) -> dict[str, Any]:
    """Transform one flat adapter record or raise a recoverable RecordError."""
    record: dict[str, Any] = {
        "schema_version": "1.0",
        "record_type": rule.record_type,
        "vendor": rule.vendor,
    }
    try:
        missing = sorted(
            field for field in rule.data["required_source_fields"] if not _present(raw, field)
        )
        record_mappings = [
            mapping for mapping in rule.data["mappings"] if mapping["destination"] == "record"
        ]
        payload_mappings = [
            mapping for mapping in rule.data["mappings"] if mapping["destination"] != "record"
        ]
        identity_targets = {"ne_id", "ne_type", "alarm_id", "snapshot_id"}
        identity_mappings = [
            mapping for mapping in record_mappings if mapping["target"] in identity_targets
        ]
        remaining_record_mappings = [
            mapping for mapping in record_mappings if mapping["target"] not in identity_targets
        ]
        for mapping in identity_mappings:
            value = _resolve_mapping(raw, mapping)
            if value is not None:
                set_nested_metric(record, mapping["destination"], mapping["target"], value)

        time_rule = rule.data["time"]
        time_fields = {time_rule["source"]}
        if rule.record_type == "PM":
            time_fields.add(time_rule["interval_source"])
        if rule.record_type == "FM":
            time_fields.add(time_rule["event_time_source"])
        missing_time = sorted(time_fields.intersection(missing))
        if missing_time:
            raise RecordError(
                "MISSING_REQUIRED_FIELD",
                "필수 시간 원본 필드가 없습니다: " + ", ".join(missing_time),
                partial_record=record,
            )

        try:
            _apply_time(raw, rule, record)
        except RecordError as exc:
            raise RecordError(
                _stable_error_code(exc.code),
                f"시각/구간 변환 실패: {exc.message}",
                partial_record=record,
            ) from exc
        if missing:
            raise RecordError(
                "MISSING_REQUIRED_FIELD",
                "필수 원본 필드가 없습니다: " + ", ".join(missing),
                partial_record=record,
            )
        for mapping in remaining_record_mappings:
            value = _resolve_mapping(raw, mapping)
            if value is not None:
                set_nested_metric(record, mapping["destination"], mapping["target"], value)
        for mapping in payload_mappings:
            value = _resolve_mapping(raw, mapping)
            if value is not None:
                set_nested_metric(
                    record,
                    mapping["destination"],
                    mapping["target"],
                    value,
                )

        transient = record.pop("transient", {})
        if rule.record_type == "FM" and transient.get("is_cleared") is True:
            record["severity"] = "CLEARED"
        return record
    except RecordError as exc:
        partial = dict(record)
        partial.pop("transient", None)
        partial.update(exc.partial_record)
        raise RecordError(exc.code, exc.message, partial_record=partial) from exc
