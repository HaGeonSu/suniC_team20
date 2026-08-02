from __future__ import annotations

import unittest
from pathlib import Path

from adapters import kind_of, parse_file, vendor_of
from pipeline_core.errors import RecordError
from pipeline_core.rules import load_rules
from pipeline_core.transform import transform_raw
from pipeline_core.validate import validate_record


ROOT = Path(__file__).resolve().parents[1]


class MultiVendorRuleTransformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository = load_rules(ROOT / "rules")

    def transform_first(self, relative_path: str) -> tuple[dict[str, object], dict[str, object]]:
        path = ROOT / relative_path
        raw, error = next(parse_file(str(path)))
        self.assertIsNone(error)
        rule = self.repository.select(vendor_of(path.name), kind_of(path.name), raw)
        record = transform_raw(raw, rule)
        validate_record(record)
        return rule.data, record

    def test_vendor_b_pm_v10_utc_end_time_ratio_and_duration(self) -> None:
        rule, record = self.transform_first(
            "data/public/raw/B_IMS-CSCF-B01_PM_20260601.xml"
        )
        self.assertEqual(rule["source_document_version"], "1.0")
        self.assertEqual(record["timestamp"], "2026-06-01T00:00:00+09:00")
        self.assertEqual(record["granularity_sec"], 900)
        self.assertAlmostEqual(record["counters"]["resource.cpu.usage"], 40.76)
        self.assertAlmostEqual(record["counters"]["resource.memory.usage"], 46.42)

    def test_vendor_b_pm_v11_alias_signature_and_optional_metrics(self) -> None:
        rule, record = self.transform_first(
            "data/public_v11/raw/B_IMS-CSCF-B01_PM_20260608.xml"
        )
        self.assertEqual(rule["source_document_version"], "1.1")
        self.assertAlmostEqual(record["counters"]["resource.cpu.usage"], 39.67)
        self.assertEqual(record["counters"]["sip.invite.fail_5xx"], 9)
        self.assertAlmostEqual(record["counters"]["sip.register.success_rate"], 98.51)

    def test_vendor_b_cm_adapter_flattened_fields_and_ratio(self) -> None:
        _, record = self.transform_first(
            "data/public/raw/B_IMS-CSCF-B01_CM_20260601.xml"
        )
        self.assertEqual(record["timestamp"], "2026-06-01T03:00:00+09:00")
        self.assertEqual(len(record["parameters"]), 10)
        self.assertEqual(record["parameters"]["overload.cpu_threshold"], 80.0)
        self.assertEqual(record["parameters"]["registration.expire_sec"], 3600)

    def test_vendor_b_fm_uses_event_time_for_both_times(self) -> None:
        _, record = self.transform_first(
            "data/public/raw/B_IMS-CSCF-B01_FM_20260601.xml"
        )
        self.assertEqual(record["event_time"], record["timestamp"])
        self.assertEqual(record["severity"], "WARNING")
        self.assertEqual(record["probable_cause"], "MEMORY_EXHAUSTION")

    def test_vendor_c_pm_epoch_milliseconds(self) -> None:
        _, record = self.transform_first(
            "data/public/raw/C_IMS-CSCF-C01_PM_20260601.json"
        )
        self.assertEqual(record["timestamp"], "2026-06-01T00:00:00+09:00")
        self.assertEqual(record["granularity_sec"], 300)
        self.assertEqual(record["counters"]["resource.cpu.usage"], 34.26)

    def test_vendor_c_cm_uses_adapter_flattened_cfg(self) -> None:
        _, record = self.transform_first(
            "data/public/raw/C_IMS-CSCF-C01_CM_20260601.json"
        )
        self.assertEqual(record["snapshot_id"], "IMS-CSCF-C01-20260601-01")
        self.assertEqual(len(record["parameters"]), 10)
        self.assertEqual(record["parameters"]["sip.timer.t1_ms"], 600)

    def test_vendor_c_fm_clear_overrides_severity_without_is_cleared(self) -> None:
        raw = {
            "ne": "GENERIC-C",
            "kind": "S_CSCF",
            "alm": "ALM1001",
            "sev": "CR",
            "clr": True,
            "cause": "LINK_FAILURE",
            "obj": "ManagedElement=GENERIC-C,Link=1",
            "evt_ts": 1780258472000,
            "ts": 1780258532000,
        }
        rule = self.repository.select("VENDOR_C", "FM", raw)
        record = transform_raw(raw, rule)
        validate_record(record)

        self.assertEqual(record["severity"], "CLEARED")
        self.assertNotEqual(record["event_time"], record["timestamp"])
        self.assertNotIn("additional_text", record)
        self.assertNotIn("is_cleared", record)

    def test_vendor_b_unknown_enum_is_rejected_not_coerced(self) -> None:
        raw = {
            "managedElement": "GENERIC-B",
            "localDn": "GENERIC-B",
            "neType": "P_CSCF",
            "alarmId": "ALM1002",
            "perceivedSeverity": "Catastrophic",
            "probableCause": "CPU_OVERLOAD",
            "objectInstance": "ManagedElement=GENERIC-B,CPU=1",
            "eventTime": "2026-06-01T00:00:00Z",
        }
        rule = self.repository.select("VENDOR_B", "FM", raw)
        with self.assertRaises(RecordError) as context:
            transform_raw(raw, rule)
        self.assertEqual(context.exception.code, "INVALID_ENUM")


if __name__ == "__main__":
    unittest.main()
