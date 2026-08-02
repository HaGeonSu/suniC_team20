#!/usr/bin/env python3
"""공통 비교 엔진. validate.py(공개)와 grade.py(비공개)가 이 파일을 함께 쓴다.

비교 규칙이 공개·비공개에서 1비트라도 달라지면 채점 분쟁이 생기므로,
규칙은 전부 여기에만 있고 두 CLI 는 데이터셋만 바꿔 문다.
"""

import glob
import json
import os
from datetime import datetime, timedelta, timezone

from jsonschema import Draft202012Validator

KST = timezone(timedelta(hours=9))
FLOAT_TOL = 1e-6

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_DIR = os.environ.get("IMS_SCHEMA_DIR") or os.path.join(HERE, "..", "schema")
SCHEMA_PATH = os.path.join(SCHEMA_DIR, "unified_v1.schema.json")


# ------------------------------------------------------------------ 로딩

def load_records(path):
    """파일 또는 디렉터리에서 통합 레코드를 읽는다(.jsonl / .json 배열 모두 허용)."""
    files = []
    if os.path.isdir(path):
        for pat in ("*.jsonl", "*.json"):
            files.extend(sorted(glob.glob(os.path.join(path, "**", pat), recursive=True)))
    else:
        files = [path]

    out = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            text = fh.read().strip()
        if not text:
            continue
        if f.endswith(".jsonl"):
            for line in text.splitlines():
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        else:
            data = json.loads(text)
            out.extend(data if isinstance(data, list) else [data])
    return out


def load_exclusions(path):
    if not path or not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as fh:
        return set(json.load(fh).get("excluded_keys", []))


# -------------------------------------------------------------- 정규화·키

def norm_timestamp(value):
    """타임존을 KST 로 정규화해 비교한다. +00:00 로 준 값도 같은 시각이면 일치."""
    if not isinstance(value, str):
        return value
    v = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(v).astimezone(KST).isoformat()
    except ValueError:
        return value


def record_key(rec):
    """매칭 키: (vendor, ne_id, record_type, timestamp[정규화], granularity_sec, 식별자)

    식별자는 FM 은 alarm_id, CM 은 snapshot_id, PM 은 공백이다. PM 만으로는
    한 NE·한 시각에 레코드가 하나뿐이지만, FM 은 같은 시각에 여러 알람이 올 수 있다.
    """
    disc = rec.get("alarm_id") or rec.get("snapshot_id") or ""
    return "|".join([
        str(rec.get("vendor", "")),
        str(rec.get("ne_id", "")),
        str(rec.get("record_type", "")),
        norm_timestamp(rec.get("timestamp", "")),
        str(rec.get("granularity_sec", "")),
        str(disc),
    ])


PAYLOAD_KEY = {"PM": "counters", "CM": "parameters"}
FM_FIELDS = ["severity", "probable_cause", "managed_object", "event_time",
             "additional_text", "ne_type"]


def flatten(rec):
    """레코드를 '필드명 → 값' 평면 맵으로. 필드 순서·공백은 비교에서 무시된다."""
    out = {"ne_type": rec.get("ne_type")}
    rt = rec.get("record_type")
    if rt in PAYLOAD_KEY:
        for k, v in (rec.get(PAYLOAD_KEY[rt]) or {}).items():
            out[k.strip()] = v
    elif rt == "FM":
        for f in FM_FIELDS:
            if f in rec:
                out[f] = rec[f]
    return out


def values_equal(expected, actual):
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected == actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) <= FLOAT_TOL
    if isinstance(expected, str) and isinstance(actual, str):
        e, a = expected.strip(), actual.strip()
        if e == a:
            return True
        # 시각 문자열은 타임존 정규화 후 비교
        ne, na = norm_timestamp(e), norm_timestamp(a)
        return ne == na
    return expected == actual


# ------------------------------------------------------------------ 스키마

_validator = None


def validator():
    global _validator
    if _validator is None:
        with open(SCHEMA_PATH, encoding="utf-8") as fh:
            _validator = Draft202012Validator(json.load(fh))
    return _validator


def schema_errors(rec):
    return [e.message for e in validator().iter_errors(rec)]


# ------------------------------------------------------------------ 비교

def compare(golden, output, excluded=None, rejected_keys=None, max_diffs=10):
    """반환: 지표 + 실패 상세가 담긴 리포트 dict."""
    excluded = excluded or set()
    rejected_keys = rejected_keys or set()

    # 1) 스키마 검증
    invalid = []
    valid_out = []
    for r in output:
        errs = schema_errors(r)
        if errs:
            invalid.append({"key": record_key(r), "error": errs[0]})
        else:
            valid_out.append(r)
    schema_validity_rate = len(valid_out) / len(output) if output else 0.0

    # 2) 중복 제거 실패 탐지 — 같은 키가 두 번 이상 나오면 두 번째부터는 환각으로 센다
    out_index, dup_keys = {}, []
    for r in valid_out:
        k = record_key(r)
        if k in out_index:
            dup_keys.append(k)
        else:
            out_index[k] = r

    gold_index = dict((record_key(g), g) for g in golden)
    expected_keys = set(gold_index) - excluded          # 채점 대상
    produced_keys = set(out_index)

    matched = expected_keys & produced_keys
    missing = expected_keys - produced_keys
    # 노이즈로 제외된 레코드를 출력한 것은 감점하지 않는다(중립).
    hallucinated = produced_keys - set(gold_index)

    coverage = len(matched) / len(expected_keys) if expected_keys else 0.0
    denom = len(matched) + len(hallucinated)
    precision = len(matched) / denom if denom else 0.0
    f1 = (2 * coverage * precision / (coverage + precision)) if (coverage + precision) else 0.0
    hallucination_rate = len(hallucinated) / len(produced_keys) if produced_keys else 0.0

    # 3) 필드 정확도. 골든에 없는 필드를 지어내면(환각) 분모에 더해 감점한다 —
    #    그러지 않으면 카운터를 발명해도 아무 대가가 없다.
    total_fields = correct_fields = extra_fields = 0
    diffs = []
    for k in sorted(matched):
        g_flat = flatten(gold_index[k])
        o_flat = flatten(out_index[k])
        for name, exp in g_flat.items():
            total_fields += 1
            act = o_flat.get(name, "<MISSING>")
            if values_equal(exp, act):
                correct_fields += 1
            elif len(diffs) < max_diffs:
                diffs.append({"key": k, "field": name, "expected": exp, "actual": act})
        for name in o_flat:
            if name not in g_flat:
                extra_fields += 1
                if len(diffs) < max_diffs:
                    diffs.append({"key": k, "field": name, "expected": "<골든에 없음>",
                                  "actual": o_flat[name]})
    denom_fields = total_fields + extra_fields
    field_accuracy = correct_fields / denom_fields if denom_fields else 0.0

    # 4) 노이즈 처리 위생: 제외 대상을 사유와 함께 rejected 로그에 남겼는지
    noise_logged = len(rejected_keys & excluded)
    noise_handling = noise_logged / len(excluded) if excluded else 1.0

    return {
        "metrics": {
            "schema_validity_rate": round(schema_validity_rate, 4),
            "coverage": round(coverage, 4),
            "precision": round(precision, 4),
            "f1": round(f1, 4),
            "hallucination_rate": round(hallucination_rate, 4),
            "field_accuracy": round(field_accuracy, 4),
            "noise_handling": round(noise_handling, 4),
        },
        "counts": {
            "golden_total": len(golden),
            "excluded_by_noise": len(excluded),
            "expected": len(expected_keys),
            "output_total": len(output),
            "output_schema_invalid": len(invalid),
            "output_duplicate_keys": len(dup_keys),
            "matched": len(matched),
            "missing": len(missing),
            "hallucinated": len(hallucinated),
            "fields_compared": total_fields,
            "fields_correct": correct_fields,
            "fields_hallucinated": extra_fields,
        },
        "samples": {
            "schema_invalid": invalid[:max_diffs],
            "missing": sorted(missing)[:max_diffs],
            "hallucinated": sorted(hallucinated)[:max_diffs],
            "field_diffs": diffs,
        },
    }


BASE_WEIGHTS = {"schema_validity_rate": 0.15, "f1": 0.30, "field_accuracy": 0.55}
NOISE_BONUS = 5.0   # 노이즈 처리는 감점이 아니라 가점(최대 +5, 총점은 100 상한)


def score(report, weights=None):
    """단일 시나리오 점수(0~100)."""
    w = weights or BASE_WEIGHTS
    m = report["metrics"]
    base = sum(m[k] * v for k, v in w.items()) * 100
    return round(min(100.0, base + m["noise_handling"] * NOISE_BONUS), 2)


def render_markdown(title, report, sc=None):
    m, c, s = report["metrics"], report["counts"], report["samples"]
    L = ["# %s" % title, ""]
    if sc is not None:
        L += ["**점수: %.2f / 100**" % sc, ""]
    L += ["| 지표 | 값 |", "|---|---|"]
    for k, v in m.items():
        L.append("| %s | %.2f%% |" % (k, v * 100))
    L += ["", "| 항목 | 건수 |", "|---|---|"]
    for k, v in c.items():
        L.append("| %s | %d |" % (k, v))

    if s["schema_invalid"]:
        L += ["", "## 스키마 위반 (상위 %d건)" % len(s["schema_invalid"]), ""]
        for e in s["schema_invalid"]:
            L.append("- `%s` — %s" % (e["key"], e["error"]))
    if s["missing"]:
        L += ["", "## 누락된 레코드 (상위 %d건)" % len(s["missing"]), ""]
        L += ["- `%s`" % k for k in s["missing"]]
    if s["hallucinated"]:
        L += ["", "## 골든에 없는 레코드 (환각, 상위 %d건)" % len(s["hallucinated"]), ""]
        L += ["- `%s`" % k for k in s["hallucinated"]]
    if s["field_diffs"]:
        L += ["", "## 필드 불일치 (상위 %d건)" % len(s["field_diffs"]), "",
              "| 레코드 | 필드 | 기대값 | 실제값 |", "|---|---|---|---|"]
        for d in s["field_diffs"]:
            L.append("| `%s` | `%s` | `%s` | `%s` |"
                     % (d["key"], d["field"], d["expected"], d["actual"]))
    return "\n".join(L) + "\n"
