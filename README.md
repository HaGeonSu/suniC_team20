# 멀티벤더 IMS EMS 데이터 통합 Pipeline

Vendor A/B/C의 PM·CM·FM 원본을 제공 Adapter로 평면화한 뒤, JSON 규칙에 따라
Unified Schema v1.0 JSONL로 변환하는 결정론적 Pipeline이다.

## 실행 환경

- Python 3.10 이상
- `jsonschema>=4.23,<5`

설치:

```bash
python -m pip install -r requirements.txt
```

`jsonschema`는 `schema/unified_v1.schema.json`을
`Draft202012Validator`로 검사하기 위해 필요하다. 제공 `eval/validate.py`도 같은
패키지를 사용한다.

## 변환

v1.0 공개 데이터:

```bash
python pipeline.py transform \
  --input data/public/raw \
  --rules rules \
  --out unified.jsonl \
  --rejected rejected.jsonl
```

v1.1 공개 데이터:

```bash
python pipeline.py transform \
  --input data/public_v11/raw \
  --rules rules \
  --out unified_v11.jsonl \
  --rejected rejected_v11.jsonl
```

레코드 단위 오류와 Adapter 파일 단위 오류는 `rejected.jsonl`에 격리되며 실행은
계속된다. 입력·활성 규칙·Schema 초기화나 출력 저장 같은 실행 전역 오류는 종료 코드
2를 반환한다. 모든 필수 PM 카운터가 동시에 0인 수집기 리셋 레코드는
`COUNTER_RESET`으로 분리한다.

## 검증

```bash
python -m unittest discover -s tests -v

python eval/validate.py \
  --unified unified.jsonl \
  --golden data/public/golden_sample/ \
  --exclusions data/public/exclusions.json \
  --rejected rejected.jsonl
```

결정론은 동일 transform을 서로 다른 출력 경로로 두 번 실행한 뒤 정상·거부
JSONL을 각각 `cmp` 또는 `diff`로 비교한다.

## 구조

```text
pipeline.py                 CLI와 파일/레코드 격리
pipeline_core/
  convert.py                자료형·시간·duration·배율·enum 순수 함수
  rules.py                  규칙 검증과 필드 시그니처 선택
  transform.py              공통 PM·CM·FM 조립
  validate.py               JSON Schema·Counter Dictionary·PM 불변식
  io.py                     중복·정렬·원자적 JSONL 저장
  errors.py                 실행 전역/레코드 오류
rules/
  active/                     검증 완료 실행 규칙
  staging/                    Agent 후보 규칙
  artifacts/                  Agent 보조 산출물
  archive/                    교체된 이전 규칙
tests/                      단위·통합·회귀 테스트
DESIGN_DECISIONS.md         문서 근거와 정책 기록
```

Vendor 원본 필드명, alias, enum, 배율, 시간 형식, clear 표현은 `rules/`에 있다.
공통 변환 엔진에는 장비 ID·날짜·파일명 전용 매핑 분기가 없다.

## 현재 범위

- Pipeline: Vendor A/B/C PM·CM·FM
- 문서 버전: 제공 v1.0 및 v1.1
- 규칙 생성 Agent: 미구현

`agent.py`를 요구하는 전체 제출 구성 검사는 아직 통과 대상이 아니다. Pipeline이
규칙 불일치 시 Agent나 LLM을 자동 호출하지도 않는다.

## Agent 규칙 반영 계약

Agent는 후보 규칙과 prompt snapshot을 `rules/` 최상위에 섞어 쓰지 않는다. 후보는
`rules/staging/`, 보조 JSON은 `rules/artifacts/`에 저장하고, 검증 및 기존 데이터 회귀
테스트를 통과한 규칙만 `rules/active/`로 승격한다. 자세한 정책은 `rules/README.md`를
참조한다.

Agent와 Pipeline은 같은 규칙 객체 스키마를 사용한다. Agent의 주 산출물은
`rules/staging/candidate_rules.json`의 JSON 객체 배열이며, PM·CM·FM 모두
`match`, `required_source_fields`, `time`, `mappings`, `unmapped` 구조로 표현한다.
`agent.py validate`는 Pipeline 규칙 검증기와 실제 Adapter 출력으로 후보를 점검한다.
후보가 모두 정상 Unified 레코드를 생성하면 기존 active 규칙과 병합하여
`rules/active/rules.json`으로 승격하고, 기존 active 파일은 `rules/archive/`에 보존한다.

```bash
python agent.py propose --doc docs/VendorA_PMS_Interface_Spec_v1.1.md \
  --vendor VENDOR_A --rules rules --out rules --sample data/public_v11/raw

python agent.py validate --rules rules --input data/public_v11/raw
```

Claude API 키는 소스에 넣지 않는다. `ANTHROPIC_API_KEY` 환경변수 또는 프로젝트
최상위 `.env`에 설정한다. 모델을 바꿔야 할 때만 `CLAUDE_MODEL` 환경변수를 사용한다.
