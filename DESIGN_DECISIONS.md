# Pipeline 설계 결정 로그

## 범위

- Vendor A/B/C의 PM·CM·FM과 제공 v1.0/v1.1 문서를 처리한다.
- `agent.py`는 Claude API로 새 문서의 Pipeline 호환 후보 규칙을 생성한다.
- Pipeline은 기존 규칙이 맞지 않아도 Agent를 자동 실행하지 않는다.
- 제공 `adapters.parse_file`, `vendor_of`, `kind_of` 이후 단계만 책임진다.

## 근거 우선순위

1. `schema/unified_v1.schema.json`, `schema/counter_dictionary.md`
2. 벤더 인터페이스 문서
3. Adapter가 반환한 공개 원본의 필드 시그니처
4. 기존 임시 매핑 JSON

골든 데이터는 규칙 설계에 사용하지 않고 구현 후 검증에만 사용한다.

## 규칙 표현과 버전 선택

- 규칙 객체의 표준 형식은 Pipeline의 `validate_rule` 계약 하나만 사용한다.
- Agent 후보와 승격된 실행 규칙은 각각 하나의 JSON 객체 배열로 묶는다.
- 실행 규칙은 `rules/active/`에만 둔다.
- Agent 후보는 `rules/staging/`, prompt·분석 자료는 `rules/artifacts/`, 이전 버전은
  `rules/archive/`에 보관한다.
- 동일 signature 갱신은 새 규칙을 기존 active 규칙 옆에 추가하지 않고, 회귀 검증 후
  기존 규칙을 archive로 이동한 뒤 원자적으로 교체한다.
- 모든 매핑은 원본 후보(`sources`)에서 표준 target으로 향한다.
- 각 규칙에 `rule_schema_version`, `rule_version`,
  `source_document_version`, `vendor`, `record_type`을 기록한다.
- 원본 후보는 정수 `priority` 오름차순으로 기록한다.
- 동일 target 후보가 동시에 존재하면 변환 후 값을 비교한다.
  - `reject_if_different`: 값이 다르면 레코드 거부
  - `prefer_first`: 문서 근거가 있는 규칙에서만 우선순위가 높은 값을 사용
- 하나의 target을 여러 mapping 항목으로 나누는 규칙은 로딩 단계에서 거부한다.
- 규칙 선택은 날짜나 장비 ID가 아니라 `match.required_fields`,
  `match.forbidden_fields`, `match.any_of`로 표현한 원본 필드 시그니처를 사용한다.
- 같은 Vendor/유형에서 둘 이상의 규칙이 일치하면 `RULE_AMBIGUOUS`로 거부한다.
- 규칙에 없는 원본 필드는 추측해 출력하지 않는다.
- 표준 필드에 대응하지 않는 원본 필드는 `unmapped` 배열에
  `source`, `reason`, `evidence`로 기록하며 변환에는 사용하지 않는다.

## Agent 생성·검증·승격

- API 키는 `ANTHROPIC_API_KEY` 환경변수에서만 읽으며 소스, 규칙,
  prompt snapshot에 기록하지 않는다.
- Agent는 ICD, Counter Dictionary, Unified Schema, 선택 raw sample,
  같은 Vendor/유형의 기존 규칙을 Claude에 제공한다.
- Claude는 PM·CM·FM 각각 한 개의 Pipeline 규칙 객체를 반환한다.
- 문법 오류, 폐기된 Agent 키, placeholder, Pipeline 규칙 검증 오류가 있으면
  오류를 다시 제공해 최대 3회 교정한다.
- 세 규칙이 모두 유효해야 `rules/staging/candidate_rules.json` 배열을
  원자적으로 갱신한다.
- `agent.py validate`는 staging 규칙과 기존 active 규칙을 병합한 뒤
  identity 및 match signature 충돌을 검사한다.
- 실제 Adapter 출력에서 후보 규칙이 선택되고, 최소 한 건 이상 정상 Unified
  레코드를 생성해야 승격한다.
- 검증 실패는 종료 코드 2로 전달하며 active 규칙을 변경하지 않는다.
- 검증 성공 시 기존 active를 archive에 보존하고 전체 실행 규칙을
  `rules/active/rules.json` 배열로 원자적으로 승격한다.

## 시간과 구간

- Vendor A의 14자리 무오프셋 시각은 문서 §2.2에 따라 `Asia/Seoul`로 해석한다.
- Vendor B의 UTC ISO 8601 또는 `Z` 시각은 KST `+09:00`으로 변환한다.
- Vendor B PM은 문서 §3.4/§4.2에 따라 `endTime - duration`을 표준
  `timestamp`로 쓴다.
- Vendor C의 epoch 값은 문서에 따라 millisecond로 해석하고 KST로 변환한다.
- FM 원본에 시각이 하나뿐이면 동일한 정규화 값을 `timestamp`와 `event_time`에 쓴다.
- Unified Schema가 소수 초를 허용하지 않으므로 1초로 정확히 표현할 수 없는 입력은
  자르거나 반올림하지 않고 거부한다.

## 자료형과 단위

- count는 boolean과 소수값을 허용하지 않는 integer로 변환한다.
- number는 NaN과 양·음의 Infinity를 거부한다.
- rejected의 원본 진단값에 non-finite float가 있으면 JSON 표준을 깨지 않도록
  `{"__non_finite_number__": "NaN|Infinity|-Infinity"}` 표식으로만 보존한다.
- ratio→percent와 second→millisecond 같은 변환은 규칙의 양의 유한
  `scale.factor`로 표현한다.
- minute, second, ISO 8601 duration은 공통 granularity 변환기를 사용한다.
- 문서 근거가 없는 상수, 기본값, 파생값은 생성하지 않는다.

## FM 정책

- severity와 probable cause는 규칙의 명시적 enum만 허용한다.
- 알 수 없는 enum은 `INVALID_ENUM`으로 거부하며 비슷한 표준값으로 보정하지 않는다.
- Vendor별 clear 표시는 규칙에서 transient `is_cleared`로 변환한다.
- clear가 참이면 최종 `severity`를 `CLEARED`로 바꾸고 transient 값은 제거한다.
- Unified Schema에 없는 `is_cleared`는 최종 레코드에 출력하지 않는다.
- `additional_text`는 원본 값이 있을 때만 출력한다.

## 검증 순서

1. 규칙의 필수 원본 필드 검사
2. 필드·시간·단위 변환과 레코드 조립
3. `schema/unified_v1.schema.json`의 `Draft202012Validator` 검사
4. Counter Dictionary 필수 항목·타입·범위 검사
5. PM 불변식 검사

Counter Dictionary의 강제 불변식은 다음을 포함한다.

- REGISTER/INVITE 성공 ≤ 시도
- REGISTER/INVITE 시도 = 성공 + 실패
- 4xx + 5xx + 6xx = REGISTER 실패 + INVITE 실패
- 수신 traffic ≥ REGISTER 시도 + INVITE 시도
- 선택 `invite.fail_5xx` ≤ 전체 INVITE 실패
- 모든 필수 PM 카운터가 동시에 0이면 수집기 리셋으로 판단해 `COUNTER_RESET` 거부

성공률 97~99.5% 설명은 장애 구간에서 예외가 있다고 명시되어 있어 보편적 거부
조건으로 사용하지 않는다.

## 중복과 정렬

- 정규화 키는 `eval/compare_core.py`의 `record_key`와 같은 필드 조합을 사용한다.
- 키와 payload가 같은 중복은 한 건만 정상 출력한다.
- 키가 같고 payload가 다르면 입력 순서로 승자를 고르지 않고 그룹 전체를
  `DUPLICATE_CONFLICT`로 거부한다.
- 입력 파일, 규칙, 정상 레코드, 거부 레코드를 명시적 정렬한다.
- 시간 역전은 입력 순서에 의존하지 않고 최종 정렬로 해결한다.

## rejected

- 변환 중 확보된 `vendor`, `record_type`, `ne_id`, `timestamp`,
  `granularity_sec`, `alarm_id`, `snapshot_id`를 가능한 범위에서 최상위에 복사한다.
- 각 거부에는 `source_file`, `source_index`, 안정적 오류 코드와 원본 진단값을 남긴다.
- Adapter가 깨진 행에 raw를 제공하지 않으면 장비·시각을 추측하지 않는다.
- Adapter의 예상 외 예외는 해당 파일의 `ADAPTER_UNEXPECTED_ERROR`로 격리하고 다른
  파일 처리를 계속한다.
- `--rejected`가 없으면 거부 파일을 만들지 않지만 변환은 계속한다.

## 입력 유형 교차검증과 Adapter 한계

- 파일명은 `vendor_of`, `kind_of`의 공식 식별 결과로 사용한다.
- 재귀 탐색 중 두 함수가 인식하는 파일만 Adapter에 전달한다.
- Adapter 이후 raw가 다른 record type 규칙 시그니처와 일치하면
  `INPUT_TYPE_MISMATCH`로 거부한다.
- Vendor A에서 PM으로 이름 붙은 파일의 본문이 단 한 줄의 FM 텍스트인 경우, 제공 CSV
  Adapter가 헤더로만 소비하고 raw를 내지 않아 본문 유형을 복원할 수 없다. 원본 파서를
  재구현하지 않는 제약을 우선해 `EMPTY_INPUT_FILE`로 기록하며 유형을 추측하지 않는다.

## 원자성과 결정론

- JSON은 UTF-8, `sort_keys=True`, `ensure_ascii=False`, `allow_nan=False`,
  고정 separators로 직렬화한다.
- 출력과 rejected는 대상 디렉터리의 임시 파일을 완성·flush·fsync한 뒤
  `os.replace`한다.
- 정상·거부 출력 경로는 입력 탐색 대상에서 명시적으로 제외한다.
- 현재 시각, UUID, random, 네트워크, LLM을 사용하지 않는다.

## 외부 의존성과 제출 검사

- Pipeline은 Draft 2020-12 Schema 검사용 `jsonschema`를 사용한다.
- Agent는 Claude 호출용 `anthropic`과 로컬 환경변수 로드용
  `python-dotenv`를 사용하며 모두 `requirements.txt`에 버전을 제한했다.
- 현재 실행 환경에는 `/tmp`가 없고 기본 Python에 `jsonschema`가 설치되어 있지 않아
  원본 `submit_check.sh`는 Pipeline 실행 전에도 환경 오류를 낸다.
- 별도 의존성 경로에서 단위·공식 검증을 수행했으며, 동일 transform의 다른 출력 경로
  결과를 바이트 비교해 결정론을 검증한다.
- Agent 포함 제출물 구성, Pipeline CLI, 결정론 검사를 통과했다.
