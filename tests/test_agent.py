import json
import shutil
from pathlib import Path

import pytest

import agent


ROOT = Path(__file__).resolve().parents[1]


def test_template_uses_only_pipeline_rule_contract():
    template = agent.get_json_template("PM", "VENDOR_A")

    assert set(template) == agent.CANONICAL_RULE_KEYS
    assert not set(template).intersection(agent.LEGACY_AGENT_KEYS)
    assert template["rule_schema_version"] == "1.0"
    assert template["record_type"] == "PM"
    assert template["mappings"][0]["destination"] == "counters"


def test_legacy_agent_shape_is_rejected():
    legacy = {
        "vendor": "VENDOR_A",
        "record_type": "PM",
        "icd_version": "1.0",
        "counter_mapping": {"RegAtt": "sip.register.attempt"},
    }

    with pytest.raises(agent.AgentError, match="폐기된 Agent 키"):
        agent._validate_generated_rule(
            legacy,
            vendor="VENDOR_A",
            record_type="PM",
            path=Path("<test>"),
        )


def test_propose_writes_one_pipeline_compatible_array(tmp_path, monkeypatch):
    source_rules = {
        record_type: json.loads(
            (
                ROOT
                / "rules"
                / "active"
                / f"vendor_c_{record_type.lower()}_v1_0.json"
            ).read_text(encoding="utf-8")
        )
        for record_type in agent.RECORD_TYPES
    }

    def fake_call(prompt):
        for record_type in agent.RECORD_TYPES:
            if f"one JSON object for VENDOR_C/{record_type}" in prompt:
                return json.dumps(source_rules[record_type])
        raise AssertionError("record type marker missing from prompt")

    monkeypatch.setattr(agent, "call_llm_api", fake_call)
    out_root = tmp_path / "rules"

    result = agent.propose(
        str(ROOT / "docs" / "VendorC_API_Guide_v1.0.md"),
        "VENDOR_C",
        str(ROOT / "rules"),
        str(out_root),
    )

    assert result == 0
    candidate_path = out_root / "staging" / "candidate_rules.json"
    candidate_rules = json.loads(candidate_path.read_text(encoding="utf-8"))
    assert isinstance(candidate_rules, list)
    assert len(candidate_rules) == 3
    for index, rule in enumerate(candidate_rules):
        agent.validate_rule(rule, Path(f"{candidate_path}#{index}"))


def test_validate_promotes_staging_and_consolidates_active(tmp_path):
    rules_root = tmp_path / "rules"
    shutil.copytree(ROOT / "rules", rules_root)
    staging = rules_root / "staging"
    staging.mkdir(exist_ok=True)
    candidate = json.loads(
        (ROOT / "rules" / "active" / "vendor_c_cm_v1_0.json").read_text(
            encoding="utf-8"
        )
    )
    (staging / "candidate_rules.json").write_text(
        json.dumps([candidate], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = agent.validate(str(rules_root), str(ROOT / "data" / "public" / "raw"))

    assert result == 0
    active_bundle = json.loads(
        (rules_root / "active" / "rules.json").read_text(encoding="utf-8")
    )
    assert isinstance(active_bundle, list)
    assert len(active_bundle) == 12
    assert not list((rules_root / "staging").glob("*.json"))
