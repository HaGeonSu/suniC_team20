"""Draft 2020-12 schema validation and Counter Dictionary semantics."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .errors import PipelineError, RecordError
from .rules import CM_PARAMETERS, PM_COUNTERS

try:
    from jsonschema import Draft202012Validator
except ModuleNotFoundError as exc:  # Reported as a run-level error by initialize_validator().
    Draft202012Validator = None  # type: ignore[assignment,misc]
    _JSONSCHEMA_IMPORT_ERROR: ModuleNotFoundError | None = exc
else:
    _JSONSCHEMA_IMPORT_ERROR = None


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "unified_v1.schema.json"
_validator: Any | None = None

PM_REQUIRED = {
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
}
PM_TYPES_RANGES: dict[str, tuple[str, float, float]] = {
    "sip.register.attempt": ("integer", 0, 10_000_000),
    "sip.register.success": ("integer", 0, 10_000_000),
    "sip.register.fail": ("integer", 0, 10_000_000),
    "sip.invite.attempt": ("integer", 0, 10_000_000),
    "sip.invite.success": ("integer", 0, 10_000_000),
    "sip.invite.fail": ("integer", 0, 10_000_000),
    "sip.response.4xx": ("integer", 0, 10_000_000),
    "sip.response.5xx": ("integer", 0, 10_000_000),
    "sip.response.6xx": ("integer", 0, 10_000_000),
    "session.active.count": ("integer", 0, 2_000_000),
    "session.setup.time_ms": ("number", 0, 60_000),
    "resource.cpu.usage": ("number", 0, 100),
    "resource.memory.usage": ("number", 0, 100),
    "traffic.msg.rx": ("integer", 0, 100_000_000),
    "traffic.msg.tx": ("integer", 0, 100_000_000),
    "sip.register.success_rate": ("number", 0, 100),
    "sip.invite.fail_5xx": ("integer", 0, 10_000_000),
}
CM_TYPES_RANGES: dict[str, tuple[str, float, float]] = {
    "sip.timer.t1_ms": ("integer", 100, 2_000),
    "sip.timer.t2_ms": ("integer", 1_000, 8_000),
    "sip.timer.invite_timeout_ms": ("integer", 4_000, 64_000),
    "registration.expire_sec": ("integer", 60, 86_400),
    "session.max_count": ("integer", 1_000, 5_000_000),
    "session.expire_sec": ("integer", 90, 7_200),
    "overload.cpu_threshold": ("number", 50, 100),
    "transport.sip.port": ("integer", 1, 65_535),
    "ha.heartbeat_interval_ms": ("integer", 100, 10_000),
    "qos.dscp.value": ("integer", 0, 63),
}


def initialize_validator(schema_path: str | Path = SCHEMA_PATH) -> Any:
    """Load and check the supplied schema once; failures stop the whole run."""
    global _validator
    if _validator is not None:
        return _validator
    if Draft202012Validator is None:
        raise PipelineError(
            "jsonschema 패키지가 필요합니다. "
            "`python -m pip install -r requirements.txt`로 설치하십시오."
        ) from _JSONSCHEMA_IMPORT_ERROR
    path = Path(schema_path)
    try:
        with path.open(encoding="utf-8") as handle:
            schema = json.load(handle)
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise PipelineError(f"Unified JSON Schema 초기화 실패: {path}: {exc}") from exc
    _validator = Draft202012Validator(schema)
    return _validator


def _schema_error_path(error: Any) -> str:
    parts = [str(part) for part in error.absolute_path]
    return ".".join(parts) if parts else "<record>"


def validate_schema(record: dict[str, Any]) -> None:
    validator = initialize_validator()
    errors = sorted(
        validator.iter_errors(record),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            tuple(str(part) for part in error.absolute_schema_path),
            error.message,
        ),
    )
    if errors:
        error = errors[0]
        raise RecordError(
            "SCHEMA_VALIDATION_ERROR",
            f"{_schema_error_path(error)}: {error.message}",
        )


def _value_is_type(value: Any, expected_type: str) -> bool:
    if isinstance(value, bool):
        return False
    if expected_type == "integer":
        return isinstance(value, int)
    if expected_type == "number":
        return isinstance(value, (int, float)) and math.isfinite(float(value))
    return False


def _validate_dictionary_values(
    values: dict[str, Any],
    definitions: dict[str, tuple[str, float, float]],
) -> None:
    for name in sorted(values):
        expected_type, minimum, maximum = definitions[name]
        value = values[name]
        if not _value_is_type(value, expected_type):
            raise RecordError(
                "TYPE_CONVERSION_ERROR",
                f"{name}은(는) Counter Dictionary의 {expected_type} 타입이어야 합니다.",
            )
        if value < minimum or value > maximum:
            raise RecordError(
                "VALUE_OUT_OF_RANGE",
                f"{name}={value!r}, 허용 범위는 {minimum:g}~{maximum:g}입니다.",
            )


def validate_dictionary(record: dict[str, Any]) -> None:
    if record["record_type"] == "PM":
        values = record["counters"]
        allowed = PM_COUNTERS
        required = PM_REQUIRED
        definitions = PM_TYPES_RANGES
        label = "PM 카운터"
    elif record["record_type"] == "CM":
        values = record["parameters"]
        allowed = CM_PARAMETERS
        required = CM_PARAMETERS
        definitions = CM_TYPES_RANGES
        label = "CM 파라미터"
    else:
        return

    unknown = sorted(set(values) - allowed)
    if unknown:
        raise RecordError(
            "SCHEMA_VALIDATION_ERROR",
            f"Counter Dictionary에 없는 {label}: " + ", ".join(unknown),
        )
    missing = sorted(required - set(values))
    if missing:
        raise RecordError(
            "MISSING_REQUIRED_FIELD",
            f"Counter Dictionary 필수 {label} 누락: " + ", ".join(missing),
        )
    _validate_dictionary_values(values, definitions)


def validate_pm_invariants(record: dict[str, Any]) -> None:
    if record["record_type"] != "PM":
        return
    counters = record["counters"]

    # A simultaneous zero across every required PM metric is treated as a
    # collection/reset artifact rather than a valid no-traffic interval.
    if all(counters[name] == 0 for name in PM_REQUIRED):
        raise RecordError(
            "COUNTER_RESET",
            "모든 필수 PM 카운터가 0인 수집기 리셋 레코드입니다.",
        )

    checks = (
        (
            counters["sip.register.success"] <= counters["sip.register.attempt"],
            "REGISTER 성공 건수가 시도 건수보다 큽니다.",
        ),
        (
            counters["sip.invite.success"] <= counters["sip.invite.attempt"],
            "INVITE 성공 건수가 시도 건수보다 큽니다.",
        ),
        (
            counters["sip.response.4xx"]
            + counters["sip.response.5xx"]
            + counters["sip.response.6xx"]
            == counters["sip.register.fail"] + counters["sip.invite.fail"],
            "4xx+5xx+6xx와 REGISTER/INVITE 실패 합계가 다릅니다.",
        ),
        (
            counters["sip.register.attempt"]
            == counters["sip.register.success"] + counters["sip.register.fail"],
            "REGISTER 시도=성공+실패 불변식을 위반했습니다.",
        ),
        (
            counters["sip.invite.attempt"]
            == counters["sip.invite.success"] + counters["sip.invite.fail"],
            "INVITE 시도=성공+실패 불변식을 위반했습니다.",
        ),
        (
            counters["traffic.msg.rx"]
            >= counters["sip.register.attempt"] + counters["sip.invite.attempt"],
            "수신 메시지가 REGISTER+INVITE 시도 합보다 작습니다.",
        ),
    )
    for valid, message in checks:
        if not valid:
            raise RecordError("INVARIANT_VIOLATION", message)

    if (
        "sip.invite.fail_5xx" in counters
        and counters["sip.invite.fail_5xx"] > counters["sip.invite.fail"]
    ):
        raise RecordError(
            "INVARIANT_VIOLATION",
            "5xx INVITE 실패가 전체 INVITE 실패보다 큽니다.",
        )
    if "sip.register.success_rate" in counters and counters["sip.register.attempt"] == 0:
        raise RecordError(
            "INVARIANT_VIOLATION",
            "REGISTER 시도가 0이면 성공률 필드를 출력할 수 없습니다.",
        )


def validate_record(record: dict[str, Any]) -> None:
    """Required source validation occurs in transform_raw before this sequence."""
    validate_schema(record)
    validate_dictionary(record)
    validate_pm_invariants(record)
