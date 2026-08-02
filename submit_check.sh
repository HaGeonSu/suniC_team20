#!/usr/bin/env bash
# 제출 전 자가 점검 스크립트.
#
# 채점기는 여러분의 CLI를 "그대로" 실행합니다. 이 스크립트는 채점기가 하는 것과
# 같은 방식으로 다음을 확인합니다:
#   1) 제출물 필수 구성 (pipeline.py / agent.py / rules/ / adapters/)
#   2) transform CLI 규약 준수
#   3) 결정론 — 같은 입력을 두 번 변환해서 결과가 1바이트도 다르지 않은지
#   4) 실행 시간 (채점 제한: 10분)
#
# 사용법 (팀 저장소 루트에서):
#   bash submit_check.sh [팀코드루트=.] [raw디렉터리=data/public/raw]
set -u

ROOT="${1:-.}"
RAW="${2:-data/public/raw}"
FAIL=0

echo "== 1. 제출물 구성 확인 =="
for f in pipeline.py agent.py rules adapters; do
  if [ -e "$ROOT/$f" ]; then
    echo "  ok  $f"
  else
    echo "  ✗   $f 가 없습니다 (제출물 최상위에 있어야 합니다)"
    FAIL=1
  fi
done

if [ ! -d "$RAW" ]; then
  echo "✗ raw 디렉터리를 찾을 수 없습니다: $RAW"
  exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo
echo "== 2. transform 1회차 (CLI 규약 + 시간 측정) =="
START=$SECONDS
( cd "$ROOT" && python3 pipeline.py transform \
    --input "$RAW" --rules rules \
    --out "$WORK/run1.jsonl" --rejected "$WORK/rej1.jsonl" )
RC=$?
ELAPSED=$((SECONDS - START))
if [ $RC -ne 0 ]; then
  echo "✗ transform 이 비정상 종료했습니다 (exit $RC)"
  exit 1
fi
echo "  ok  ${ELAPSED}초 소요"
if [ $ELAPSED -gt 600 ]; then
  echo "  ✗   10분(600초)을 초과했습니다. 채점 시 0점 처리됩니다."
  FAIL=1
fi

echo
echo "== 3. transform 2회차 → 결정론 검사 =="
( cd "$ROOT" && python3 pipeline.py transform \
    --input "$RAW" --rules rules \
    --out "$WORK/run2.jsonl" --rejected "$WORK/rej2.jsonl" ) || { echo "✗ 2회차 실패"; exit 1; }

if diff -q "$WORK/run1.jsonl" "$WORK/run2.jsonl" >/dev/null 2>&1; then
  echo "  ok  두 번 실행한 결과가 완전히 동일합니다"
else
  echo "  ✗   같은 입력·같은 규칙인데 결과가 다릅니다."
  echo "      변환 엔진 안에 비결정적 요소(LLM 호출, 시각 의존, 정렬 안 된 순회 등)가 있습니다."
  echo "      채점 환경은 네트워크가 차단된 상태로 transform 을 실행합니다."
  FAIL=1
fi

echo
if [ $FAIL -eq 0 ]; then
  echo "== 통과. eval/validate.py 로 정확도까지 확인하세요 =="
else
  echo "== 실패 항목이 있습니다. 위 ✗ 를 해결하고 다시 실행하세요 =="
fi
exit $FAIL
