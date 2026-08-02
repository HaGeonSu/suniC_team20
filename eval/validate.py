#!/usr/bin/env python3
"""팀 공개용 자가검증기.

usage:
  python validate.py --unified ./unified/ --golden ../data/public/golden_sample/ \
                     [--exclusions ../data/public/exclusions.json] [--rejected ./rejected.jsonl]

공개 골든 샘플에 대해 지표를 출력하고, 실패 레코드 상위 10건은 필드 단위 diff 로
보여준다. 채점기(grade.py)와 완전히 동일한 비교 규칙(compare_core)을 쓴다.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compare_core as cc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unified", required=True, help="통합 변환 결과 (파일 또는 디렉터리)")
    ap.add_argument("--golden", required=True, help="공개 골든 샘플 (파일 또는 디렉터리)")
    ap.add_argument("--exclusions", default=None, help="노이즈 exclusion 목록 JSON")
    ap.add_argument("--rejected", default=None, help="팀이 기록한 rejected.jsonl (선택)")
    ap.add_argument("--report", default=None, help="Markdown 리포트 저장 경로 (선택)")
    args = ap.parse_args()

    golden = cc.load_records(args.golden)
    output = cc.load_records(args.unified)
    excluded = cc.load_exclusions(args.exclusions)

    rejected_keys = set()
    if args.rejected and os.path.exists(args.rejected):
        with open(args.rejected, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rejected_keys.add(cc.record_key(json.loads(line)))

    # 골든 샘플은 전체 골든의 부분집합이다. 샘플에 없는 날짜의 출력까지 환각으로 세면
    # 억울하므로, 샘플이 커버하는 (ne_id, 날짜) 범위로 출력을 먼저 좁힌다.
    scope = set((g["ne_id"], g["timestamp"][:10]) for g in golden)
    scoped = [r for r in output
              if (r.get("ne_id"), str(r.get("timestamp", ""))[:10]) in scope]
    dropped = len(output) - len(scoped)

    report = cc.compare(golden, scoped, excluded=excluded, rejected_keys=rejected_keys)
    sc = cc.score(report)

    md = cc.render_markdown("자가검증 리포트 (공개 골든 샘플)", report, sc)
    print(md)
    if dropped:
        print("(참고: 골든 샘플 범위 밖의 출력 %d건은 채점에서 제외했습니다)" % dropped)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write(md)
        print("리포트 저장 → %s" % args.report)

    m = report["metrics"]
    if m["schema_validity_rate"] < 1.0 or m["field_accuracy"] < 0.99:
        print("\n[!] 스키마 위반이 있거나 필드 정확도가 99% 미만입니다. 위 diff 를 먼저 보세요.")
        return 1
    print("\n[OK] 스키마 100%% 통과 / 필드 정확도 %.2f%%" % (m["field_accuracy"] * 100))
    return 0


if __name__ == "__main__":
    sys.exit(main())
