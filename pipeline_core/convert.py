"""Small deterministic conversion functions with no I/O."""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, MutableMapping
from zoneinfo import ZoneInfo

from .errors import RecordError

KST = timezone(timedelta(hours=9))
SEOUL = ZoneInfo("Asia/Seoul")
VENDOR_A_TIME_FORMAT = "%Y%m%d%H%M%S"
_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


def strip_text(value: Any) -> str:
    if not isinstance(value, str):
        raise RecordError("INVALID_STRING", "문자열 값이 아닙니다.")
    return value.strip()


def to_integer(value: Any) -> int:
    if isinstance(value, bool):
        raise RecordError("INVALID_INTEGER", "boolean은 integer로 변환할 수 없습니다.")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise RecordError("INVALID_INTEGER", "유한한 정수 값이 아닙니다.")
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise RecordError("INVALID_INTEGER", "빈 문자열은 integer로 변환할 수 없습니다.")
        try:
            number = Decimal(text)
        except InvalidOperation as exc:
            raise RecordError("INVALID_INTEGER", f"integer 변환 실패: {text!r}") from exc
        if not number.is_finite() or number != number.to_integral_value():
            raise RecordError("INVALID_INTEGER", f"정수 값이 아닙니다: {text!r}")
        return int(number)
    raise RecordError("INVALID_INTEGER", f"integer 변환을 지원하지 않는 타입: {type(value).__name__}")


def to_number(value: Any) -> float:
    if isinstance(value, bool):
        raise RecordError("INVALID_NUMBER", "boolean은 number로 변환할 수 없습니다.")
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise RecordError("INVALID_NUMBER", "빈 문자열은 number로 변환할 수 없습니다.")
        try:
            number = float(Decimal(text))
        except (InvalidOperation, ValueError, OverflowError) as exc:
            raise RecordError("INVALID_NUMBER", f"number 변환 실패: {text!r}") from exc
    else:
        raise RecordError("INVALID_NUMBER", f"number 변환을 지원하지 않는 타입: {type(value).__name__}")
    if not math.isfinite(number):
        raise RecordError("NON_FINITE_NUMBER", "NaN 또는 Infinity는 출력할 수 없습니다.")
    return number


def to_boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
    raise RecordError("INVALID_BOOLEAN", f"boolean 변환 실패: {value!r}")


def cast_value(value: Any, target_type: str) -> Any:
    if target_type == "string":
        return strip_text(value)
    if target_type == "integer":
        return to_integer(value)
    if target_type == "number":
        return to_number(value)
    if target_type == "boolean":
        return to_boolean(value)
    raise RecordError("UNSUPPORTED_TYPE", f"지원하지 않는 자료형: {target_type}")


def apply_scale(value: Any, factor: float) -> float:
    number = to_number(value)
    result = float(Decimal(str(number)) * Decimal(str(factor)))
    if not math.isfinite(result):
        raise RecordError("NON_FINITE_NUMBER", "배율 적용 결과가 NaN 또는 Infinity입니다.")
    return result


def enum_key(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def map_enum(value: Any, values: Mapping[str, Any]) -> Any:
    key = enum_key(value)
    if key not in values:
        raise RecordError("UNKNOWN_ENUM_VALUE", f"enum에 정의되지 않은 값: {key!r}")
    return values[key]


def _format_kst(dt: datetime) -> str:
    localized = dt.astimezone(KST)
    if localized.microsecond:
        raise RecordError("UNSUPPORTED_SUBSECOND", "Unified Schema는 소수 초 시각을 허용하지 않습니다.")
    return localized.replace(microsecond=0).isoformat(timespec="seconds")


def vendor_a_time_to_kst(value: Any) -> str:
    text = strip_text(value)
    try:
        naive = datetime.strptime(text, VENDOR_A_TIME_FORMAT)
    except ValueError as exc:
        raise RecordError("INVALID_TIMESTAMP", f"Vendor A 시각 형식 오류: {text!r}") from exc
    return _format_kst(naive.replace(tzinfo=SEOUL))


def utc_iso_to_kst(value: Any) -> str:
    text = strip_text(value)
    if not text.endswith("Z"):
        raise RecordError("INVALID_TIMESTAMP", "UTC ISO 8601 시각은 Z로 끝나야 합니다.")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise RecordError("INVALID_TIMESTAMP", f"UTC ISO 8601 시각 형식 오류: {text!r}") from exc
    if parsed.utcoffset() != timedelta(0):
        raise RecordError("INVALID_TIMESTAMP", "UTC ISO 8601 시각의 오프셋이 0이 아닙니다.")
    return _format_kst(parsed)


def epoch_ms_to_kst(value: Any) -> str:
    milliseconds = to_integer(value)
    if milliseconds % 1000:
        raise RecordError("UNSUPPORTED_SUBSECOND", "epoch millisecond 값에 소수 초가 포함되어 있습니다.")
    try:
        parsed = datetime.fromtimestamp(milliseconds // 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise RecordError("INVALID_TIMESTAMP", f"epoch millisecond 범위 오류: {milliseconds}") from exc
    return _format_kst(parsed)


def parse_timestamp(value: Any, raw_format: str) -> str:
    if raw_format == VENDOR_A_TIME_FORMAT:
        return vendor_a_time_to_kst(value)
    if raw_format == "iso8601_utc":
        return utc_iso_to_kst(value)
    if raw_format == "epoch_ms":
        return epoch_ms_to_kst(value)
    raise RecordError("UNSUPPORTED_TIME_FORMAT", f"지원하지 않는 시각 형식: {raw_format}")


def iso_duration_to_seconds(value: Any) -> int:
    text = strip_text(value)
    match = _DURATION_RE.fullmatch(text)
    if not match or not any(match.groupdict().values()):
        raise RecordError("INVALID_DURATION", f"ISO 8601 duration 형식 오류: {text!r}")
    seconds = (
        Decimal(match.group("days") or "0") * Decimal(86400)
        + Decimal(match.group("hours") or "0") * Decimal(3600)
        + Decimal(match.group("minutes") or "0") * Decimal(60)
        + Decimal(match.group("seconds") or "0")
    )
    if not seconds.is_finite() or seconds <= 0 or seconds != seconds.to_integral_value():
        raise RecordError("INVALID_DURATION", "구간 길이는 양의 정수 초여야 합니다.")
    return int(seconds)


def granularity_to_seconds(value: Any, unit: str) -> int:
    if unit == "iso_duration":
        return iso_duration_to_seconds(value)
    amount = to_integer(value)
    if unit == "minute":
        seconds = amount * 60
    elif unit == "second":
        seconds = amount
    else:
        raise RecordError("UNSUPPORTED_INTERVAL_UNIT", f"지원하지 않는 구간 단위: {unit}")
    if seconds <= 0:
        raise RecordError("INVALID_DURATION", "구간 길이는 양수여야 합니다.")
    return seconds


def subtract_interval(interval_end_kst: str, granularity_sec: int) -> str:
    try:
        end = datetime.fromisoformat(interval_end_kst)
    except ValueError as exc:
        raise RecordError("INVALID_TIMESTAMP", f"정규화된 종료 시각 오류: {interval_end_kst!r}") from exc
    if end.utcoffset() != timedelta(hours=9):
        raise RecordError("INVALID_TIMESTAMP", "종료 시각은 KST(+09:00)여야 합니다.")
    return _format_kst(end - timedelta(seconds=granularity_sec))


def set_nested_metric(
    record: MutableMapping[str, Any],
    destination: str,
    target: str,
    value: Any,
) -> None:
    if destination == "record":
        record[target] = value
        return
    if destination not in {"counters", "parameters", "transient"}:
        raise RecordError("UNSUPPORTED_DESTINATION", f"지원하지 않는 저장 위치: {destination}")
    container = record.setdefault(destination, {})
    if not isinstance(container, MutableMapping):
        raise RecordError("INTERNAL_ERROR", f"{destination} 저장소가 맵이 아닙니다.")
    container[target] = value
