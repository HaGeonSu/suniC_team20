from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from pipeline_core.errors import RecordError, RuleValidationError
from pipeline_core.rules import load_rules


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_RULES = ROOT / "rules" / "active"


class RuleLoaderTests(unittest.TestCase):
    def test_loads_vendor_a_pm_versions(self) -> None:
        repository = load_rules(ROOT / "rules")
        candidates = repository.candidates("VENDOR_A", "PM")
        self.assertEqual([r.data["source_document_version"] for r in candidates], ["1.0", "1.1"])

    def test_selects_by_fields_not_filename_date_or_device(self) -> None:
        repository = load_rules(ROOT / "rules")
        v10 = repository.select(
            "VENDOR_A",
            "PM",
            {
                "NEName": "ANY-NE",
                "NeType": "P_CSCF",
                "CollectTime": "20301231235500",
                "Interval": "5",
                "CpuLoad": "10",
            },
        )
        v11 = repository.select(
            "VENDOR_A",
            "PM",
            {
                "NEName": "ANOTHER-NE",
                "NeType": "S_CSCF",
                "CollectTime": "20200101000000",
                "Interval": "5",
                "CpuUsage": "10",
                "InvFail5xx": "0",
                "RegSuccRate": "99",
            },
        )
        self.assertEqual(v10.data["source_document_version"], "1.0")
        self.assertEqual(v11.data["source_document_version"], "1.1")

    def test_invalid_scale_is_global_rule_error(self) -> None:
        source = json.loads((ACTIVE_RULES / "vendor_a_pm_v1_0.json").read_text(encoding="utf-8"))
        broken = copy.deepcopy(source)
        broken["mappings"][2]["operations"] = [{"op": "scale", "factor": 0}]
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "broken.json").write_text(
                json.dumps(broken, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaises(RuleValidationError):
                load_rules(temp_dir)

    def test_unknown_target_is_global_rule_error(self) -> None:
        source = json.loads((ACTIVE_RULES / "vendor_a_pm_v1_0.json").read_text(encoding="utf-8"))
        broken = copy.deepcopy(source)
        broken["mappings"][2]["target"] = "invented.counter"
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "broken.json").write_text(
                json.dumps(broken, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaises(RuleValidationError):
                load_rules(temp_dir)

    def test_signature_mismatch_is_record_error(self) -> None:
        repository = load_rules(ROOT / "rules")
        with self.assertRaises(RecordError) as context:
            repository.select("VENDOR_A", "PM", {"NEName": "ANY"})
        self.assertEqual(context.exception.code, "RULE_NOT_FOUND")

    def test_dictionary_target_type_mismatch_is_global_rule_error(self) -> None:
        source = json.loads((ACTIVE_RULES / "vendor_a_pm_v1_0.json").read_text(encoding="utf-8"))
        broken = copy.deepcopy(source)
        broken["mappings"][2]["target_type"] = "number"
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "broken.json").write_text(
                json.dumps(broken, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaises(RuleValidationError):
                load_rules(temp_dir)

    def test_overlapping_runtime_signatures_are_rule_ambiguous(self) -> None:
        source = json.loads((ACTIVE_RULES / "vendor_a_pm_v1_0.json").read_text(encoding="utf-8"))
        broader = copy.deepcopy(source)
        broader["rule_version"] = "1.0.1"
        broader["match"]["required_fields"] = ["NEName", "CollectTime", "CpuLoad"]
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "exact.json").write_text(
                json.dumps(source, ensure_ascii=False),
                encoding="utf-8",
            )
            Path(temp_dir, "broad.json").write_text(
                json.dumps(broader, ensure_ascii=False),
                encoding="utf-8",
            )
            repository = load_rules(temp_dir)
            with self.assertRaises(RecordError) as context:
                repository.select(
                    "VENDOR_A",
                    "PM",
                    {
                        "NEName": "GENERIC-A",
                        "NeType": "P_CSCF",
                        "CollectTime": "20260601000000",
                        "Interval": "5",
                        "CpuLoad": "30",
                    },
                )
            self.assertEqual(context.exception.code, "RULE_AMBIGUOUS")

    def test_time_sources_must_be_required_source_fields(self) -> None:
        source = json.loads((ACTIVE_RULES / "vendor_a_pm_v1_0.json").read_text(encoding="utf-8"))
        broken = copy.deepcopy(source)
        time_source = broken["time"]["source"]
        broken["required_source_fields"].remove(time_source)
        broken["match"]["required_fields"].remove(time_source)
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "broken.json").write_text(
                json.dumps(broken, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaises(RuleValidationError) as context:
                load_rules(temp_dir)
            self.assertIn("시간 원본 필드", str(context.exception))

    def test_active_directory_ignores_staging_and_artifacts(self) -> None:
        source = json.loads((ACTIVE_RULES / "vendor_a_pm_v1_0.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active = root / "active"
            active.mkdir()
            (active / "vendor_a_pm.json").write_text(
                json.dumps(source, ensure_ascii=False),
                encoding="utf-8",
            )
            artifacts = root / "artifacts"
            artifacts.mkdir()
            (artifacts / "prompt_snapshot.json").write_text(
                json.dumps({"prompt": "not a rule"}, ensure_ascii=False),
                encoding="utf-8",
            )
            staging = root / "staging"
            staging.mkdir()
            duplicate = copy.deepcopy(source)
            duplicate["rule_version"] = "9.9.9"
            (staging / "candidate.json").write_text(
                json.dumps(duplicate, ensure_ascii=False),
                encoding="utf-8",
            )

            repository = load_rules(root)
            self.assertEqual(len(repository.rules), 1)
            self.assertEqual(repository.rules[0].data["rule_version"], source["rule_version"])


if __name__ == "__main__":
    unittest.main()
