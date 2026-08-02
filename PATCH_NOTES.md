# Pipeline 필수 수정 패치

## 반영 내용

1. **Adapter 예외 격리 — 제공 Adapter 원본 유지**
   - 제공받은 `adapters/__init__.py`는 한 글자도 수정하지 않았다.
   - 빈 Vendor A PM CSV, 잘못된 FM prefix, Vendor C의 비객체 JSON 원소에서 발생하는 예외를 `pipeline.py`의 Adapter 호출 경계에서 `PARSE_ERROR`로 격리한다.
   - Adapter 자체가 호출 단계에서 예상하지 못한 예외를 던지면 해당 파일만 `ADAPTER_UNEXPECTED_ERROR`로 rejected 처리한다.
   - Adapter 오류 뒤 `EMPTY_INPUT_FILE`이 중복 기록되지 않게 했다.

2. **시간 규칙 정합성 검증**
   - `time.source`, PM의 `interval_source`, FM의 `event_time_source`가 모두
     `required_source_fields`에 포함되는지 규칙 로딩 단계에서 검사한다.
   - 잘못된 Agent 규칙이 런타임 `KeyError`를 일으키기 전에 전역 규칙 오류로 차단한다.

3. **PM 카운터 리셋 탐지**
   - 모든 필수 PM 카운터가 동시에 0이면 `COUNTER_RESET`으로 rejected 처리한다.

4. **Agent 규칙 수명주기 분리**
   - 실행 규칙: `rules/active/`
   - 후보 규칙: `rules/staging/`
   - 보조 JSON: `rules/artifacts/`
   - 이전 규칙: `rules/archive/`
   - `rules/active/`가 있으면 Pipeline은 그 디렉터리의 JSON만 읽는다.
   - 동일 signature 갱신은 기존 active 규칙을 archive로 이동한 뒤 교체하는 정책으로 고정했다.

5. **테스트 및 제출물 정리**
   - 경계 테스트를 추가해 총 61개 테스트를 구성했다.
   - 불완전한 `.deps/`와 Python cache 파일을 제거했다.

6. **Agent와 Pipeline 규칙 계약 통일**
   - Agent의 기존 `metadata_mapping`, `time_mapping`,
     `counter_mapping/parameter_mapping/alarm_mapping` 형식을 제거했다.
   - Agent가 Pipeline의 `match`, `required_source_fields`, `time`,
     `mappings`, `unmapped` 형식을 직접 생성하도록 변경했다.
   - PM·CM·FM 후보를 `rules/staging/candidate_rules.json`의 단일 JSON
     객체 배열로 병합한다.
   - Claude 출력은 Pipeline 규칙 검증기로 즉시 검사하고, 실패 시 검증 오류를
     포함해 최대 3회 교정한다.
   - API 키는 코드나 prompt snapshot에 저장하지 않고
     `ANTHROPIC_API_KEY`로만 읽는다.

7. **Agent validate 실동작 및 승격**
   - `rules/active` 하위까지 탐색하지 못해 0개 검사하던 문제를 제거했다.
   - Agent 자체 매핑 스키마가 아니라 Pipeline의 `validate_rule`을 사용한다.
   - Adapter가 만든 실제 raw에 대해 규칙 선택, 변환, Unified Schema 검증까지
     수행한다.
   - 실패가 하나라도 있으면 종료 코드 2를 반환하고 active를 수정하지 않는다.
   - staging 후보가 모두 통과하면 기존 active와 병합한 단일
     `rules/active/rules.json` 배열로 승격한다. 이전 active는 archive에 보존한다.

## 검증 결과

- 단위·통합 테스트: **61/61 + 추가 서브테스트 29개 통과**
- 공개 v1.0: **100/100**
  - accepted 6,965 / rejected 262
  - noise_handling **80.85%**
- 공개 v1.1: **100/100**
  - accepted 803 / rejected 30
  - noise_handling **73.91%**
- v1.0·v1.1 정상 및 rejected JSONL 두 번 실행 바이트 비교: **동일**
- `agent.py validate`: 공개 v1.0·v1.1 실제 규칙 적용 검증 통과
- `submit_check.sh`: 제출물 구성·Pipeline 변환·결정론 통과
