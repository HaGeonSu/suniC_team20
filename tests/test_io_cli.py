from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from pipeline import run_transform
from pipeline_core.io import make_rejection, record_key


ROOT = Path(__file__).resolve().parents[1]
A_PM = ROOT / "data/public/raw/A_IMS-CSCF-A01_PM_20260601_0000.csv"
C_PM = ROOT / "data/public/raw/C_IMS-CSCF-C01_PM_20260601.json"


class RejectionMetadataTests(unittest.TestCase):
    def test_rejection_preserves_normalized_key_at_top_level(self) -> None:
        partial = {
            "vendor": "VENDOR_C",
            "record_type": "PM",
            "ne_id": "GENERIC-C",
            "timestamp": "2026-06-01T00:00:00+09:00",
            "granularity_sec": 300,
        }
        rejected = make_rejection(
            source_file="nested/C_GENERIC-C_PM_20260601.json",
            source_index=3,
            error_code="MISSING_REQUIRED_FIELD",
            error_message="cpu_pct 누락",
            raw_record={"ne": "GENERIC-C"},
            partial_record=partial,
        )
        self.assertEqual(record_key(rejected), record_key(partial))
        self.assertEqual(rejected["source_index"], 3)
        self.assertNotIn("source_record_index", rejected)

    def test_missing_payload_field_keeps_public_noise_key(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            workspace = Path(temp)
            raw_dir = workspace / "raw"
            raw_dir.mkdir()
            source_rows = json.loads(C_PM.read_text(encoding="utf-8"))
            row = dict(source_rows[0])
            del row["cpu_pct"]
            source = raw_dir / "C_GENERIC-C_PM_20260601.json"
            source.write_text(
                json.dumps([row], ensure_ascii=False),
                encoding="utf-8",
            )
            output = workspace / "unified.jsonl"
            rejected_path = workspace / "rejected.jsonl"
            summary = run_transform(
                input_dir=str(raw_dir),
                rules_dir=str(ROOT / "rules"),
                out_path=str(output),
                rejected_path=str(rejected_path),
            )
            self.assertEqual(summary["accepted"], 0)
            rejected = json.loads(rejected_path.read_text(encoding="utf-8").strip())
            self.assertEqual(rejected["error_code"], "MISSING_REQUIRED_FIELD")
            for key in (
                "vendor",
                "record_type",
                "ne_id",
                "timestamp",
                "granularity_sec",
                "source_file",
                "source_index",
                "raw_record",
            ):
                self.assertIn(key, rejected)


class InputDiscoveryTests(unittest.TestCase):
    def test_only_adapter_recognized_files_are_processed_recursively(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            workspace = Path(temp)
            raw_dir = workspace / "raw"
            nested = raw_dir / "nested"
            nested.mkdir(parents=True)
            shutil.copy2(A_PM, nested / A_PM.name)
            (raw_dir / "old_unified.jsonl").write_text("{not input}\n", encoding="utf-8")
            (raw_dir / "notes.txt").write_text("not input\n", encoding="utf-8")

            output = raw_dir / "new_unified.jsonl"
            rejected = raw_dir / "new_rejected.jsonl"
            first = run_transform(
                input_dir=str(raw_dir),
                rules_dir=str(ROOT / "rules"),
                out_path=str(output),
                rejected_path=str(rejected),
            )
            first_bytes = output.read_bytes()
            first_rejected = rejected.read_bytes()
            second = run_transform(
                input_dir=str(raw_dir),
                rules_dir=str(ROOT / "rules"),
                out_path=str(output),
                rejected_path=str(rejected),
            )

            self.assertEqual(first["files"], 1)
            self.assertEqual(second["files"], 1)
            self.assertEqual(output.read_bytes(), first_bytes)
            self.assertEqual(rejected.read_bytes(), first_rejected)

    def test_one_bad_record_does_not_contaminate_good_record(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            workspace = Path(temp)
            raw_dir = workspace / "raw"
            raw_dir.mkdir()
            rows = json.loads(C_PM.read_text(encoding="utf-8"))
            good = dict(rows[0])
            bad = dict(rows[1])
            del bad["msg_out"]
            source = raw_dir / "C_GENERIC-C_PM_20260601.json"
            source.write_text(
                json.dumps([bad, good], ensure_ascii=False),
                encoding="utf-8",
            )

            output = workspace / "unified.jsonl"
            rejected = workspace / "rejected.jsonl"
            summary = run_transform(
                input_dir=str(raw_dir),
                rules_dir=str(ROOT / "rules"),
                out_path=str(output),
                rejected_path=str(rejected),
            )
            self.assertEqual(summary["accepted"], 1)
            self.assertEqual(summary["rejected"], 1)
            self.assertEqual(len(output.read_text(encoding="utf-8").splitlines()), 1)
            error = json.loads(rejected.read_text(encoding="utf-8"))
            self.assertEqual(error["error_code"], "MISSING_REQUIRED_FIELD")

    def test_malformed_adapter_inputs_are_rejected_without_stopping_run(self) -> None:
        cases = {
            "A_GENERIC_PM_20260601_0000.csv": "",
            "A_GENERIC_FM_20260601_0000.log": (
                "20260601000000 IMSALARM: NETYPE=P_CSCF ALM_ID=A1 "
                "SEV=1 PC=1 MO=core EVENT_TIME=20260601000000\n"
            ),
            "C_GENERIC_PM_20260601.json": "[1]",
        }
        for filename, content in cases.items():
            with self.subTest(filename=filename), tempfile.TemporaryDirectory(dir=ROOT) as temp:
                workspace = Path(temp)
                raw_dir = workspace / "raw"
                raw_dir.mkdir()
                (raw_dir / filename).write_text(content, encoding="utf-8")
                output = workspace / "unified.jsonl"
                rejected_path = workspace / "rejected.jsonl"

                summary = run_transform(
                    input_dir=str(raw_dir),
                    rules_dir=str(ROOT / "rules"),
                    out_path=str(output),
                    rejected_path=str(rejected_path),
                )

                self.assertEqual(summary["accepted"], 0)
                self.assertEqual(summary["rejected"], 1)
                rejected = json.loads(rejected_path.read_text(encoding="utf-8"))
                self.assertEqual(rejected["error_code"], "PARSE_ERROR")

    def test_unexpected_adapter_exception_is_file_scoped(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            workspace = Path(temp)
            raw_dir = workspace / "raw"
            raw_dir.mkdir()
            source = raw_dir / "C_GENERIC_PM_20260601.json"
            source.write_text("[]", encoding="utf-8")
            output = workspace / "unified.jsonl"
            rejected_path = workspace / "rejected.jsonl"

            def broken_adapter(_path: str):
                raise RuntimeError("synthetic adapter failure")

            with patch("pipeline.parse_file", side_effect=broken_adapter):
                summary = run_transform(
                    input_dir=str(raw_dir),
                    rules_dir=str(ROOT / "rules"),
                    out_path=str(output),
                    rejected_path=str(rejected_path),
                )

            self.assertEqual(summary["accepted"], 0)
            self.assertEqual(summary["rejected"], 1)
            rejected = json.loads(rejected_path.read_text(encoding="utf-8"))
            self.assertEqual(rejected["error_code"], "ADAPTER_UNEXPECTED_ERROR")
            self.assertIn("RuntimeError", rejected["error_message"])


if __name__ == "__main__":
    unittest.main()
