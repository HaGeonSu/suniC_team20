from __future__ import annotations

import unittest
from pathlib import Path

from adapters import parse_file
from pipeline_core.errors import RecordError
from pipeline_core.rules import load_rules
from pipeline_core.transform import transform_raw
from pipeline_core.validate import validate_record


ROOT = Path(__file__).resolve().parents[1]
A_CM = ROOT / "data/public/raw/A_IMS-CSCF-A01_CM_20260601_0000.cfg"
A_FM = ROOT / "data/public/raw/A_IMS-CSCF-A01_FM_20260601_0000.log"


class VendorACmFmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository = load_rules(ROOT / "rules")

    def test_cm_has_snapshot_and_all_required_parameters(self) -> None:
        raw, error = next(parse_file(str(A_CM)))
        self.assertIsNone(error)
        rule = self.repository.select("VENDOR_A", "CM", raw)
        record = transform_raw(raw, rule)
        validate_record(record)

        self.assertEqual(record["timestamp"], "2026-06-01T03:00:00+09:00")
        self.assertEqual(record["snapshot_id"], "IMS-CSCF-A01-20260601-01")
        self.assertEqual(len(record["parameters"]), 10)
        self.assertEqual(record["parameters"]["sip.timer.t1_ms"], 500)
        self.assertEqual(record["parameters"]["registration.expire_sec"], 3600)

    def test_fm_v10_uses_single_time_for_timestamp_and_event_time(self) -> None:
        raw, error = next(parse_file(str(A_FM)))
        self.assertIsNone(error)
        rule = self.repository.select("VENDOR_A", "FM", raw)
        record = transform_raw(raw, rule)
        validate_record(record)

        self.assertEqual(rule.data["source_document_version"], "1.0")
        self.assertEqual(record["timestamp"], "2026-06-01T04:14:45+09:00")
        self.assertEqual(record["event_time"], record["timestamp"])
        self.assertEqual(record["severity"], "WARNING")
        self.assertNotIn("is_cleared", record)

    def test_fm_v10_clear_overrides_original_severity(self) -> None:
        raw = {
            "NEName": "GENERIC-A",
            "NETYPE": "S_CSCF",
            "ALM_ID": "ALM1002",
            "SEV": "1",
            "CLR": "1",
            "PC": "CPU_OVERLOAD",
            "MO": "ManagedElement=GENERIC-A,Subsystem=SIP",
            "ETIME": "20260602111500",
        }
        rule = self.repository.select("VENDOR_A", "FM", raw)
        record = transform_raw(raw, rule)
        validate_record(record)

        self.assertEqual(record["severity"], "CLEARED")
        self.assertNotIn("additional_text", record)
        self.assertNotIn("is_cleared", record)

    def test_fm_v11_selects_by_absent_clr_and_maps_severity_five(self) -> None:
        raw = {
            "NEName": "GENERIC-A",
            "NETYPE": "I_CSCF",
            "ALM_ID": "ALM1008",
            "SEV": "5",
            "PC": "CONFIG_MISMATCH",
            "MO": "ManagedElement=GENERIC-A,Subsystem=SIP",
            "ETIME": "20260608103000",
        }
        rule = self.repository.select("VENDOR_A", "FM", raw)
        record = transform_raw(raw, rule)
        validate_record(record)

        self.assertEqual(rule.data["source_document_version"], "1.1")
        self.assertEqual(record["severity"], "CLEARED")
        self.assertNotIn("is_cleared", record)

    def test_unknown_fm_enums_are_not_guessed(self) -> None:
        raw = {
            "NEName": "GENERIC-A",
            "NETYPE": "P_CSCF",
            "ALM_ID": "ALM1002",
            "SEV": "99",
            "CLR": "0",
            "PC": "UNDOCUMENTED_CAUSE",
            "MO": "ManagedElement=GENERIC-A,Subsystem=SIP",
            "ETIME": "20260601000000",
        }
        rule = self.repository.select("VENDOR_A", "FM", raw)
        with self.assertRaises(RecordError) as context:
            transform_raw(raw, rule)
        self.assertEqual(context.exception.code, "INVALID_ENUM")


if __name__ == "__main__":
    unittest.main()
