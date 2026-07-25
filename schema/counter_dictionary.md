# 표준 카운터 · 파라미터 사전 (Unified Schema v1.0)

본 사전은 `unified_v1.schema.json` 과 한 몸이다. 통합 결과물의 필드명·타입·단위는 **오직 이 문서만이** 정의한다.
확정 후에는 벤더 문서가 무엇이라 말하든 이 사전이 우선한다.

---

## 0. 단위 정책 (Unit Policy) — 예외 없음

| 구분 | 정책 |
|---|---|
| 비율(rate/utilization) | **percent, 0~100** (`0.83` 이 아니라 `83.0`) |
| 시간 길이(duration) | **밀리초(ms)** 로 통일. 벤더가 초/분으로 주면 변환한다. |
| 시각(point in time) | **KST ISO 8601 `+09:00`** (`2026-06-01T10:05:00+09:00`) |
| 건수(count) | 무차원 정수. **해당 수집 주기 동안의 증분값**(누적값 아님) |
| 표준명 네이밍 | `도메인.대상.타입` — 소문자·숫자·`_` 와 점(`.`) 구분. 정규식 `^[a-z0-9_]+(\.[a-z0-9_]+)+$` |

---

## 1. PM 카운터 (record_type = PM, `counters` 맵)

| # | 표준명 | 의미 | 타입 | 단위 | 값 범위 | 필수 |
|---|---|---|---|---|---|---|
| 1 | `sip.register.attempt` | 수집 주기 내 SIP REGISTER 시도 건수 | integer | count | 0 ~ 10,000,000 | 필수 |
| 2 | `sip.register.success` | REGISTER 성공(2xx 응답) 건수 | integer | count | 0 ~ `sip.register.attempt` | 필수 |
| 3 | `sip.register.fail` | REGISTER 실패 건수 | integer | count | 0 ~ 10,000,000 | 필수 |
| 4 | `sip.invite.attempt` | INVITE(세션 설정) 시도 건수 | integer | count | 0 ~ 10,000,000 | 필수 |
| 5 | `sip.invite.success` | INVITE 성공(200 OK) 건수 | integer | count | 0 ~ `sip.invite.attempt` | 필수 |
| 6 | `sip.invite.fail` | INVITE 실패 건수 | integer | count | 0 ~ 10,000,000 | 필수 |
| 7 | `sip.response.4xx` | 4xx 계열 응답 송출 건수 (클라이언트 오류) | integer | count | 0 ~ 10,000,000 | 필수 |
| 8 | `sip.response.5xx` | 5xx 계열 응답 송출 건수 (서버 오류) | integer | count | 0 ~ 10,000,000 | 필수 |
| 9 | `sip.response.6xx` | 6xx 계열 응답 송출 건수 (글로벌 실패) | integer | count | 0 ~ 10,000,000 | 필수 |
| 10 | `session.active.count` | 수집 시점의 동시 활성 세션 수 (게이지) | integer | count | 0 ~ 2,000,000 | 필수 |
| 11 | `session.setup.time_ms` | 세션 설정 소요시간 평균 (INVITE→200 OK) | number | ms | 0 ~ 60,000 | 필수 |
| 12 | `resource.cpu.usage` | CPU 사용률 평균 | number | percent | 0 ~ 100 | 필수 |
| 13 | `resource.memory.usage` | 메모리 사용률 평균 | number | percent | 0 ~ 100 | 필수 |
| 14 | `traffic.msg.rx` | 수신 SIP 메시지 총 건수 | integer | count | 0 ~ 100,000,000 | 필수 |
| 15 | `traffic.msg.tx` | 송신 SIP 메시지 총 건수 | integer | count | 0 ~ 100,000,000 | 필수 |
| 16 | `sip.register.success_rate` | REGISTER 성공률 (파생) | number | percent | 0 ~ 100 | **선택** |
| 17 | `sip.invite.fail_5xx` | 5xx 응답으로 인한 INVITE 실패 건수 | integer | count | 0 ~ 10,000,000 | **선택** |

> **선택 필드(16, 17)**: 벤더 문서가 해당 값을 직접 제공하거나 산출식을 명시한 경우에만 채운다.
> 문서에 근거가 없으면 **채우지 말 것**(추측 금지 — 환각으로 감점된다).
> `sip.register.success_rate` 는 명시된 산출식이 있을 때만 사용하며, 표준 산출식은
> `sip.register.success / sip.register.attempt * 100` (분모 0이면 필드 자체를 생략).

### 카운터 불변식 (Data Invariants)

수집 주기가 같은 하나의 PM 레코드 안에서 항상 성립한다. 검증기(`validate.py`)가 이를 검사한다.

1. `sip.register.success ≤ sip.register.attempt`
2. `sip.invite.success ≤ sip.invite.attempt`
3. `sip.response.4xx + sip.response.5xx + sip.response.6xx == sip.register.fail + sip.invite.fail`
4. `sip.register.attempt == sip.register.success + sip.register.fail`
5. `sip.invite.attempt == sip.invite.success + sip.invite.fail`
6. `traffic.msg.rx ≥ sip.register.attempt + sip.invite.attempt`
7. 정상 구간의 성공률은 97~99.5% 범위. 장애 구간에서만 이를 벗어난다.

---

## 2. CM 파라미터 (record_type = CM, `parameters` 맵)

| # | 표준명 | 의미 | 타입 | 단위 | 값 범위 | 필수 |
|---|---|---|---|---|---|---|
| 1 | `sip.timer.t1_ms` | SIP T1 (RTT 추정치, 재전송 기준 타이머) | integer | ms | 100 ~ 2,000 | 필수 |
| 2 | `sip.timer.t2_ms` | SIP T2 (비-INVITE 재전송 최대 간격) | integer | ms | 1,000 ~ 8,000 | 필수 |
| 3 | `sip.timer.invite_timeout_ms` | INVITE 트랜잭션 타임아웃 (Timer B) | integer | ms | 4,000 ~ 64,000 | 필수 |
| 4 | `registration.expire_sec` | REGISTER 기본 만료 시간 | integer | sec | 60 ~ 86,400 | 필수 |
| 5 | `session.max_count` | 노드 최대 동시 세션 수 | integer | count | 1,000 ~ 5,000,000 | 필수 |
| 6 | `session.expire_sec` | 세션 타이머(Session-Expires) 기본값 | integer | sec | 90 ~ 7,200 | 필수 |
| 7 | `overload.cpu_threshold` | 과부하 제어 진입 CPU 임계치 | number | percent | 50 ~ 100 | 필수 |
| 8 | `transport.sip.port` | SIP 시그널링 수신 포트 | integer | count(포트번호) | 1 ~ 65,535 | 필수 |
| 9 | `ha.heartbeat_interval_ms` | 이중화 heartbeat 주기 | integer | ms | 100 ~ 10,000 | 필수 |
| 10 | `qos.dscp.value` | 시그널링 패킷 DSCP 마킹 값 | integer | count(코드포인트) | 0 ~ 63 | 필수 |

> CM 값은 스냅샷당 전량 기록한다. 벤더가 초 단위로 표기한 타이머는 **ms 로 변환**해서 넣는다(단위 정책 우선).

---

## 3. FM 코드 테이블 (record_type = FM)

### 3.1 severity (표준 enum)

`CRITICAL` · `MAJOR` · `MINOR` · `WARNING` · `CLEARED`

- 벤더가 숫자/약어 코드를 쓰면 위 5개 중 하나로 매핑한다.
- 알람 해제(clear) 이벤트는 벤더가 어떤 방식으로 표현하든 **`severity = CLEARED`** 로 정규화한다.

### 3.2 probable_cause (표준 enum, 8종)

| 코드 | 의미 |
|---|---|
| `LINK_FAILURE` | 시그널링 링크/인터페이스 단절 |
| `CPU_OVERLOAD` | CPU 과부하로 인한 호 처리 지연·거절 |
| `MEMORY_EXHAUSTION` | 메모리 고갈 / 세션 테이블 포화 |
| `LICENSE_EXPIRY` | 라이선스 만료 또는 용량 초과 |
| `REGISTRATION_STORM` | 대량 재등록 폭주 |
| `SIP_TIMEOUT` | 상대 노드 무응답에 의한 SIP 트랜잭션 타임아웃 |
| `DATABASE_UNAVAILABLE` | HSS/가입자 DB 접근 실패 |
| `CONFIG_MISMATCH` | 노드 간 설정 불일치 |

### 3.3 기타 FM 필드

| 표준명 | 의미 | 타입 | 형식 |
|---|---|---|---|
| `alarm_id` | 알람 종류 식별자 | string | `ALM` + 4자리 숫자 (`ALM1002`) |
| `managed_object` | 알람이 발생한 관리 객체 경로 | string | 벤더 표기를 그대로 문자열로 보존 |
| `event_time` | 알람이 **실제로 발생/해제된** 시각 | string | KST ISO 8601 |
| `timestamp` | 레코드 관측(수집) 시각 | string | KST ISO 8601. 벤더가 하나의 시각만 주면 `event_time` 과 동일 값을 넣는다 |
| `additional_text` | 원문 설명 텍스트 | string | 선택. 없으면 필드 생략 |
