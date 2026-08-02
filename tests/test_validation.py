from __future__ import annotations

import copy
import unittest
from pathlib import Path

from adapters import parse_file
from pipeline_core.errors import RecordError
from pipeline_core.rules import load_rules
from pipeline_core.transform import transform_raw
from pipeline_core.validate import (
    PM_REQUIRED,
    initialize_validator,
    validate_dictionary,
    validate_pm_invariants,
    validate_record,
    validate_schema,
)


ROOT = Path(__file__).resolve().parents[1]
A_PM = ROOT / "data/public/raw/A_IMS-CSCF-A01_PM_20260601_0000.csv"
A_CM = ROOT / "data/public/raw/A_IMS-CSCF-A01_CM_20260601_0000.cfg"


class ValidationSequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository = load_rules(ROOT / "rules")
        raw_pm, error = next(parse_file(str(A_PM)))
        if error:
            raise AssertionError(error)
        cls.pm = transform_raw(raw_pm, cls.repository.select("VENDOR_A", "PM", raw_pm))
        raw_cm, error = next(parse_file(str(A_CM)))
        if error:
            raise AssertionError(error)
        cls.cm = transform_raw(raw_cm, cls.repository.select("VENDOR_A", "CM", raw_cm))

    def test_uses_draft_2020_12_validator(self) -> None:
        self.assertEqual(type(initialize_validator()).__name__, "Draft202012Validator")

    def test_schema_rejects_additional_property(self) -> None:
        record = copy.deepcopy(self.pm)
        record["invented"] = "value"
        with self.assertRaises(RecordError) as context:
            validate_schema(record)
        self.assertEqual(context.exception.code, "SCHEMA_VALIDATION_ERROR")

    def test_missing_required_counter_is_dictionary_error(self) -> None:
        record = copy.deepcopy(self.pm)
        del record["counters"]["sip.register.attempt"]
        validate_schema(record)
        with self.assertRaises(RecordError) as context:
            validate_dictionary(record)
        self.assertEqual(context.exception.code, "MISSING_REQUIRED_FIELD")

    def test_integer_counter_rejects_fractional_number(self) -> None:
        record = copy.deepcopy(self.pm)
        record["counters"]["sip.register.attempt"] = 1.5
        validate_schema(record)
        with self.assertRaises(RecordError) as context:
            validate_dictionary(record)
        self.assertEqual(context.exception.code, "TYPE_CONVERSION_ERROR")

    def test_cm_parameter_range(self) -> None:
        record = copy.deepcopy(self.cm)
        record["parameters"]["qos.dscp.value"] = 64
        with self.assertRaises(RecordError) as context:
            validate_record(record)
        self.assertEqual(context.exception.code, "VALUE_OUT_OF_RANGE")

    def test_each_pm_invariant_is_enforced(self) -> None:
        mutations = {
            "register_success": lambda c: c.__setitem__(
                "sip.register.success", c["sip.register.attempt"] + 1
            ),
            "invite_success": lambda c: c.__setitem__(
                "sip.invite.success", c["sip.invite.attempt"] + 1
            ),
            "response_sum": lambda c: c.__setitem__(
                "sip.response.4xx", c["sip.response.4xx"] + 1
            ),
            "register_sum": lambda c: c.__setitem__(
                "sip.register.attempt", c["sip.register.attempt"] + 1
            ),
            "invite_sum": lambda c: c.__setitem__(
                "sip.invite.attempt", c["sip.invite.attempt"] + 1
            ),
            "traffic": lambda c: c.__setitem__(
                "traffic.msg.rx",
                c["sip.register.attempt"] + c["sip.invite.attempt"] - 1,
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                record = copy.deepcopy(self.pm)
                mutate(record["counters"])
                with self.assertRaises(RecordError) as context:
                    validate_pm_invariants(record)
                self.assertEqual(context.exception.code, "INVARIANT_VIOLATION")

    def test_all_zero_required_pm_metrics_are_counter_reset(self) -> None:
        record = copy.deepcopy(self.pm)
        for name in PM_REQUIRED:
            record["counters"][name] = 0
        with self.assertRaises(RecordError) as context:
            validate_pm_invariants(record)
        self.assertEqual(context.exception.code, "COUNTER_RESET")

    def test_success_rate_anomaly_is_not_universal_rejection(self) -> None:
        record = copy.deepcopy(self.pm)
        record["counters"]["sip.register.success_rate"] = 50.0
        validate_record(record)


if __name__ == "__main__":
    unittest.main()
