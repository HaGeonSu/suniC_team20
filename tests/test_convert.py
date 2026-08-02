from __future__ import annotations

import math
import unittest

from pipeline_core.convert import (
    apply_scale,
    epoch_ms_to_kst,
    granularity_to_seconds,
    iso_duration_to_seconds,
    map_enum,
    set_nested_metric,
    strip_text,
    subtract_interval,
    to_boolean,
    to_integer,
    to_number,
    utc_iso_to_kst,
    vendor_a_time_to_kst,
)
from pipeline_core.errors import RecordError
from pipeline_core.io import canonical_json, json_safe


class ScalarConversionTests(unittest.TestCase):
    def test_safe_integer(self) -> None:
        self.assertEqual(to_integer(" 42 "), 42)
        self.assertEqual(to_integer("42.0"), 42)
        for bad in (True, "42.1", "", "NaN", float("inf")):
            with self.subTest(bad=bad), self.assertRaises(RecordError):
                to_integer(bad)

    def test_safe_number_rejects_non_finite(self) -> None:
        self.assertEqual(to_number(" 42.5 "), 42.5)
        for bad in (False, "NaN", "Infinity", math.inf, math.nan):
            with self.subTest(bad=bad), self.assertRaises(RecordError):
                to_number(bad)

    def test_safe_boolean(self) -> None:
        for source, expected in (
            (True, True),
            (False, False),
            (1, True),
            (0, False),
            (" true ", True),
            ("FALSE", False),
        ):
            with self.subTest(source=source):
                self.assertIs(to_boolean(source), expected)
        with self.assertRaises(RecordError):
            to_boolean("yes")

    def test_trim(self) -> None:
        self.assertEqual(strip_text("  P_CSCF \t"), "P_CSCF")
        with self.assertRaises(RecordError):
            strip_text(123)

    def test_scale_and_enum(self) -> None:
        self.assertAlmostEqual(apply_scale("0.3391", 100), 33.91)
        self.assertEqual(map_enum("Critical", {"Critical": "CRITICAL"}), "CRITICAL")
        self.assertIs(map_enum(False, {"false": False, "true": True}), False)
        with self.assertRaises(RecordError):
            map_enum("Unknown", {"Critical": "CRITICAL"})


class TimeConversionTests(unittest.TestCase):
    def test_vendor_a_kst(self) -> None:
        self.assertEqual(
            vendor_a_time_to_kst("20260601000000"),
            "2026-06-01T00:00:00+09:00",
        )

    def test_utc_z_to_kst(self) -> None:
        self.assertEqual(
            utc_iso_to_kst("2026-05-31T15:15:00Z"),
            "2026-06-01T00:15:00+09:00",
        )

    def test_epoch_milliseconds_to_kst(self) -> None:
        self.assertEqual(epoch_ms_to_kst(0), "1970-01-01T09:00:00+09:00")
        with self.assertRaises(RecordError):
            epoch_ms_to_kst(1)

    def test_iso_duration_and_units(self) -> None:
        self.assertEqual(iso_duration_to_seconds("PT15M"), 900)
        self.assertEqual(iso_duration_to_seconds("P1DT2H3M4S"), 93784)
        self.assertEqual(granularity_to_seconds("5", "minute"), 300)
        self.assertEqual(granularity_to_seconds(300, "second"), 300)
        self.assertEqual(granularity_to_seconds("PT15M", "iso_duration"), 900)
        for bad in ("PT", "P1M", "PT0S", "PT0.5S"):
            with self.subTest(bad=bad), self.assertRaises(RecordError):
                iso_duration_to_seconds(bad)

    def test_vendor_b_interval_end_becomes_start(self) -> None:
        end_kst = utc_iso_to_kst("2026-05-31T15:15:00Z")
        self.assertEqual(
            subtract_interval(end_kst, iso_duration_to_seconds("PT15M")),
            "2026-06-01T00:00:00+09:00",
        )


class NestedStorageTests(unittest.TestCase):
    def test_stores_metric_name_as_map_key(self) -> None:
        record: dict[str, object] = {}
        set_nested_metric(record, "counters", "resource.cpu.usage", 33.91)
        set_nested_metric(record, "parameters", "sip.timer.t1_ms", 500)
        self.assertEqual(record["counters"], {"resource.cpu.usage": 33.91})
        self.assertEqual(record["parameters"], {"sip.timer.t1_ms": 500})

    def test_non_finite_raw_diagnostic_is_valid_json(self) -> None:
        safe = json_safe({"value": float("nan"), "nested": [float("inf")]})
        serialized = canonical_json(safe)
        self.assertEqual(
            serialized,
            '{"nested":[{"__non_finite_number__":"Infinity"}],'
            '"value":{"__non_finite_number__":"NaN"}}',
        )


if __name__ == "__main__":
    unittest.main()
