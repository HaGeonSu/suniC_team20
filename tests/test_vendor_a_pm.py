from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from adapters import parse_file
from pipeline_core.io import Candidate, deduplicate
from pipeline_core.rules import load_rules
from pipeline_core.transform import transform_raw
from pipeline_core.validate import validate_record


ROOT = Path(__file__).resolve().parents[1]
V10_SAMPLE = ROOT / "data/public/raw/A_IMS-CSCF-A01_PM_20260601_0000.csv"
V11_SAMPLE = ROOT / "data/public_v11/raw/A_IMS-CSCF-A01_PM_20260608_0000.csv"


class VendorAPMTransformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repository = load_rules(ROOT / "rules")

    def _first_record(self, path: Path) -> tuple[dict[str, object], dict[str, object]]:
        raw, error = next(parse_file(str(path)))
        self.assertIsNone(error)
        rule = self.repository.select("VENDOR_A", "PM", raw)
        record = transform_raw(raw, rule)
        validate_record(record)
        return raw, record

    def test_v10_real_adapter_to_unified_record(self) -> None:
        _, record = self._first_record(V10_SAMPLE)
        self.assertEqual(record["schema_version"], "1.0")
        self.assertEqual(record["timestamp"], "2026-06-01T00:00:00+09:00")
        self.assertEqual(record["granularity_sec"], 300)
        self.assertEqual(len(record["counters"]), 15)
        self.assertEqual(record["counters"]["sip.register.attempt"], 1263)
        self.assertEqual(record["counters"]["resource.cpu.usage"], 32.26)

    def test_v11_real_adapter_uses_signature_and_optional_counters(self) -> None:
        raw, record = self._first_record(V11_SAMPLE)
        selected = self.repository.select("VENDOR_A", "PM", raw)
        self.assertEqual(selected.data["source_document_version"], "1.1")
        self.assertEqual(record["counters"]["sip.invite.fail_5xx"], 3)
        self.assertEqual(record["counters"]["sip.register.success_rate"], 98.95)

    def test_different_cpu_alias_values_reject_instead_of_overwrite(self) -> None:
        raw, error = next(parse_file(str(V10_SAMPLE)))
        self.assertIsNone(error)
        raw["CpuUsage"] = "99.99"
        rule = self.repository.select("VENDOR_A", "PM", raw)
        with self.assertRaisesRegex(Exception, "후보 값이 서로 다릅니다"):
            transform_raw(raw, rule)

    def test_semantic_invariant_rejects_schema_valid_record(self) -> None:
        raw, error = next(parse_file(str(V10_SAMPLE)))
        self.assertIsNone(error)
        raw["RegSucc"] = raw["RegAtt"]
        rule = self.repository.select("VENDOR_A", "PM", raw)
        record = transform_raw(raw, rule)
        with self.assertRaisesRegex(Exception, "REGISTER 시도=성공\\+실패"):
            validate_record(record)


class DuplicatePolicyTests(unittest.TestCase):
    def test_identical_duplicate_keeps_one(self) -> None:
        record = {
            "schema_version": "1.0",
            "record_type": "PM",
            "vendor": "VENDOR_A",
            "ne_type": "P_CSCF",
            "ne_id": "GENERIC-NE",
            "timestamp": "2026-01-01T00:00:00+09:00",
            "granularity_sec": 300,
            "counters": {"sip.register.attempt": 1},
        }
        items = [
            Candidate(record, f"source-{index}.csv", 1, {"row": index})
            for index in range(2)
        ]
        accepted, rejected = deduplicate(items)
        self.assertEqual(len(accepted), 1)
        self.assertEqual([item["error_code"] for item in rejected], ["DUPLICATE_RECORD"])

    def test_conflicting_duplicate_rejects_whole_group(self) -> None:
        base = {
            "schema_version": "1.0",
            "record_type": "PM",
            "vendor": "VENDOR_A",
            "ne_type": "P_CSCF",
            "ne_id": "GENERIC-NE",
            "timestamp": "2026-01-01T00:00:00+09:00",
            "granularity_sec": 300,
        }
        first = dict(base, counters={"metric.value": 1})
        second = dict(base, counters={"metric.value": 2})
        accepted, rejected = deduplicate(
            [
                Candidate(first, "a.csv", 1, {"value": 1}),
                Candidate(second, "b.csv", 1, {"value": 2}),
            ]
        )
        self.assertEqual(accepted, [])
        self.assertEqual(
            [item["error_code"] for item in rejected],
            ["DUPLICATE_CONFLICT", "DUPLICATE_CONFLICT"],
        )


class PipelineCliIntegrationTests(unittest.TestCase):
    def test_cli_is_deterministic_and_rejected_is_optional(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            workspace = Path(temp)
            raw_dir = workspace / "raw"
            raw_dir.mkdir()
            shutil.copy2(V10_SAMPLE, raw_dir / V10_SAMPLE.name)
            run1 = workspace / "run1.jsonl"
            run2 = workspace / "run2.jsonl"
            rejected1 = workspace / "rejected1.jsonl"

            command = [
                sys.executable,
                str(ROOT / "pipeline.py"),
                "transform",
                "--input",
                str(raw_dir),
                "--rules",
                str(ROOT / "rules"),
                "--out",
                str(run1),
                "--rejected",
                str(rejected1),
            ]
            first = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("[SUMMARY]", first.stderr)

            second_command = command.copy()
            second_command[second_command.index(str(run1))] = str(run2)
            second_command = second_command[:-2]
            second = subprocess.run(
                second_command,
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(run1.read_bytes(), run2.read_bytes())
            self.assertFalse((workspace / "rejected2.jsonl").exists())

            records = [
                json.loads(line)
                for line in run1.read_text(encoding="utf-8").splitlines()
                if line
            ]
            self.assertGreater(len(records), 0)
            for record in records:
                validate_record(record)

    def test_missing_input_is_nonzero_global_error(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            workspace = Path(temp)
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "pipeline.py"),
                    "transform",
                    "--input",
                    str(workspace / "missing"),
                    "--rules",
                    str(ROOT / "rules"),
                    "--out",
                    str(workspace / "out.jsonl"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("[ERROR]", result.stderr)

    def test_malformed_rules_are_global_and_preserve_existing_output(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            workspace = Path(temp)
            rules_dir = workspace / "rules"
            rules_dir.mkdir()
            (rules_dir / "broken.json").write_text("{not-json", encoding="utf-8")
            output = workspace / "out.jsonl"
            output.write_bytes(b"previous-output\n")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "pipeline.py"),
                    "transform",
                    "--input",
                    str(ROOT / "data/public/raw"),
                    "--rules",
                    str(rules_dir),
                    "--out",
                    str(output),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_bytes(), b"previous-output\n")


if __name__ == "__main__":
    unittest.main()
