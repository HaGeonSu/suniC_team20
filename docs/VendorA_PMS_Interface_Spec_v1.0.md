# PMS/FMS/CMS 북바운드 인터페이스 규격서

**문서번호** VA-OSS-ICD-2026-011
**제품** IMS Core CSCF Series
**버전** v1.0
**공개등급** 고객사 제한 배포

---

## 1. 개요

### 1.1 목적
본 규격서는 당사 IMS Core 장비(이하 "NE")가 상위 운용지원시스템(OSS)으로 제공하는
성능(PM)·장애(FM)·설정(CM) 데이터의 파일 인터페이스를 정의한다.

### 1.2 적용 범위
본 규격은 EMS R6.2 이상에서 생성되는 북바운드 파일에 적용한다.

### 1.3 개정 이력

| 판번호 | 일자 | 개정 내용 | 작성 |
|---|---|---|---|
| v1.0 | 2026-05-20 | 최초 제정 | OSS 연동팀 |

---

## 2. 공통 사항

### 2.1 파일 규약

| 항목 | 규격 |
|---|---|
| 문자 인코딩 | UTF-8 (BOM 없음) |
| 개행 | LF |
| 파일명 | `A_{NE명}_{종별}_{yyyyMMdd_HHmm}.{확장자}` |
| 종별/확장자 | PM → `.csv`, FM → `.log`, CM → `.cfg` |
| 파일 생성 주기 | 일 1회 (00:00 기준, 당일 데이터 전량) |

### 2.2 시각 표기
모든 시각 필드는 **한국 표준시(KST, UTC+9)** 기준이며, 표기 형식은 구분자 없는
14자리 `yyyyMMddHHmmss` 이다. 별도의 타임존 오프셋을 파일에 기재하지 않는다.

> 예: `20260601102500` = 2026년 6월 1일 10시 25분 00초 (KST)

### 2.3 수치 표기
- 사용률(Load) 계열은 **백분율(0~100)** 로 기재하며 소수 둘째 자리까지 표기한다.
- 시간 계열(SetupTime)은 **밀리초(ms)** 단위 정수 또는 소수로 기재한다.
- 건수 계열은 해당 수집 주기 동안의 **증분값**이며 누적값이 아니다.

---

## 3. 성능 데이터 (PM)

### 3.1 파일 구조
CSV 형식이며 첫 행은 헤더이다. 수집 주기는 **5분**이다.
`Interval` 컬럼은 수집 주기를 **분(minute) 단위**로 기재한다. (5분 주기 → `5`)

### 3.2 필드 정의

| 컬럼명 | 형식 | 단위 | 값 범위 | 필수 | 설명 |
|---|---|---|---|---|---|
| `NEName` | String(64) | - | - | Y | 장비 식별자 |
| `NeType` | String(16) | - | P_CSCF/I_CSCF/S_CSCF | Y | 장비 종별 |
| `CollectTime` | String(14) | KST | `yyyyMMddHHmmss` | Y | 수집 구간 **시작** 시각 |
| `Interval` | Integer | **minute** | 5 | Y | 수집 주기 |
| `RegAtt` | Integer | 건 | 0~10,000,000 | Y | SIP REGISTER 시도 호수 |
| `RegSucc` | Integer | 건 | 0~`RegAtt` | Y | REGISTER 성공 호수 (2xx 수신) |
| `RegFail` | Integer | 건 | 0~10,000,000 | Y | REGISTER 실패 호수 |
| `InvAtt` | Integer | 건 | 0~10,000,000 | Y | INVITE 시도 호수 |
| `InvSucc` | Integer | 건 | 0~`InvAtt` | Y | INVITE 성공 호수 (200 OK 수신) |
| `InvFail` | Integer | 건 | 0~10,000,000 | Y | INVITE 실패 호수 |
| `Rsp4xx` | Integer | 건 | 0~10,000,000 | Y | 4xx 계열 응답 송출 건수 |
| `Rsp5xx` | Integer | 건 | 0~10,000,000 | Y | 5xx 계열 응답 송출 건수 |
| `Rsp6xx` | Integer | 건 | 0~10,000,000 | Y | 6xx 계열 응답 송출 건수 |
| `ActSess` | Integer | 건 | 0~2,000,000 | Y | 수집 시점 동시 활성 세션 수 |
| `SetupTime` | Float | **ms** | 0~60,000 | Y | 세션 설정 평균 소요시간 |
| `CpuLoad` | Float | **percent** | 0~100 | Y | CPU 사용률 평균 |
| `MemLoad` | Float | **percent** | 0~100 | Y | 메모리 사용률 평균 |
| `MsgRx` | Integer | 건 | 0~100,000,000 | Y | 수신 SIP 메시지 총 건수 |
| `MsgTx` | Integer | 건 | 0~100,000,000 | Y | 송신 SIP 메시지 총 건수 |

### 3.3 데이터 예시

```
NEName,NeType,CollectTime,Interval,RegAtt,RegSucc,RegFail,InvAtt,InvSucc,InvFail,Rsp4xx,Rsp5xx,Rsp6xx,ActSess,SetupTime,CpuLoad,MemLoad,MsgRx,MsgTx
IMS-CSCF-A01,P_CSCF,20260601000000,5,1263,1253,10,782,769,13,18,4,1,2708,144.49,32.26,43.17,13017,11471
IMS-CSCF-A01,P_CSCF,20260601000500,5,1279,1255,24,792,772,20,34,8,2,2742,145.14,31.94,44.08,12455,12209
IMS-CSCF-A01,P_CSCF,20260601001000,5,1290,1272,18,798,787,11,25,3,1,2764,142.87,33.05,43.55,12902,11888
```

---

## 4. 장애 데이터 (FM)

### 4.1 파일 구조
Syslog 형태의 텍스트 라인이며, 1행 = 1 알람 이벤트이다.

```
{ETIME} {NEName} IMSALARM: NETYPE={종별} ALM_ID={알람ID} SEV={심각도코드} CLR={해제여부} PC={발생원인} MO="{관리객체}" ETIME={발생시각} TEXT="{설명}"
```

### 4.2 필드 정의

| 토큰 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `NETYPE` | String | Y | 장비 종별 |
| `ALM_ID` | String | Y | 알람 종류 식별자. `ALM` + 4자리 숫자 |
| `SEV` | Integer | Y | 심각도 코드 (§4.3) |
| `CLR` | Integer | Y | 알람 해제 여부. `0`=발생, `1`=해제 |
| `PC` | String | Y | 발생 원인 코드 (§4.4) |
| `MO` | String | Y | 관리 객체 경로 |
| `ETIME` | String(14) | Y | 알람 발생/해제 시각 (KST) |
| `TEXT` | String | N | 부가 설명 원문 |

### 4.3 심각도 코드표

| 코드 | 의미 |
|---|---|
| `1` | Critical |
| `2` | Major |
| `3` | Minor |
| `4` | Warning |

> **주의**: 알람 해제 이벤트는 별도의 심각도 코드를 사용하지 않는다. 해제 시에는
> 발생 시점의 심각도 코드를 그대로 유지한 채 `CLR=1` 로 기재한다.

### 4.4 발생 원인 코드표

| 알람ID | PC 코드 | 의미 |
|---|---|---|
| ALM1001 | `LINK_FAILURE` | 시그널링 링크 단절 |
| ALM1002 | `CPU_OVERLOAD` | CPU 과부하 |
| ALM1003 | `MEMORY_EXHAUSTION` | 메모리 고갈 |
| ALM1004 | `SIP_TIMEOUT` | SIP 트랜잭션 타임아웃 |
| ALM1005 | `REGISTRATION_STORM` | 재등록 폭주 |
| ALM1006 | `LICENSE_EXPIRY` | 라이선스 만료/용량 초과 |
| ALM1007 | `DATABASE_UNAVAILABLE` | 가입자 DB 접근 실패 |
| ALM1008 | `CONFIG_MISMATCH` | 노드 간 설정 불일치 |

### 4.5 데이터 예시

```
20260601041445 IMS-CSCF-A01 IMSALARM: NETYPE=P_CSCF ALM_ID=ALM1005 SEV=4 CLR=0 PC=REGISTRATION_STORM MO="ManagedElement=IMS-CSCF-A01,Subsystem=SIP,Board=3" ETIME=20260601041445 TEXT="Abnormal registration rate detected"
20260602101500 IMS-CSCF-A01 IMSALARM: NETYPE=P_CSCF ALM_ID=ALM1002 SEV=1 CLR=0 PC=CPU_OVERLOAD MO="ManagedElement=IMS-CSCF-A01,Subsystem=SIP,Board=3" ETIME=20260602101500 TEXT="Fault scenario: CPU utilization exceeded configured threshold"
20260602111500 IMS-CSCF-A01 IMSALARM: NETYPE=P_CSCF ALM_ID=ALM1002 SEV=1 CLR=1 PC=CPU_OVERLOAD MO="ManagedElement=IMS-CSCF-A01,Subsystem=SIP,Board=3" ETIME=20260602111500 TEXT="Alarm cleared, service restored"
```

---

## 5. 설정 데이터 (CM)

### 5.1 파일 구조
INI 형태의 `키=값` 텍스트이며, 섹션([SIP], [REG] 등)으로 구분한다.
스냅샷은 **일 1회 03:00** 에 생성한다.

### 5.2 필드 정의

| 섹션 | 키 | 형식 | 단위 | 설명 |
|---|---|---|---|---|
| `[NE]` | `NEName` | String | - | 장비 식별자 |
| `[NE]` | `NeType` | String | - | 장비 종별 |
| `[NE]` | `SnapshotId` | String | - | 스냅샷 식별자 |
| `[NE]` | `CollectTime` | String(14) | KST | 스냅샷 생성 시각 |
| `[SIP]` | `TimerT1` | Integer | **ms** | SIP T1 (RTT 추정 타이머) |
| `[SIP]` | `TimerT2` | Integer | **ms** | SIP T2 (재전송 최대 간격) |
| `[SIP]` | `TimerB` | Integer | **ms** | INVITE 트랜잭션 타임아웃 |
| `[REG]` | `ExpireSec` | Integer | **sec** | REGISTER 기본 만료 시간 |
| `[SESSION]` | `MaxSession` | Integer | 건 | 최대 동시 세션 수 |
| `[SESSION]` | `ExpireSec` | Integer | **sec** | 세션 타이머 기본값 |
| `[OVERLOAD]` | `CpuThreshold` | Float | **percent** | 과부하 제어 진입 CPU 임계치 |
| `[TRANSPORT]` | `SipPort` | Integer | - | SIP 시그널링 수신 포트 |
| `[HA]` | `HeartbeatMs` | Integer | **ms** | 이중화 heartbeat 주기 |
| `[QOS]` | `Dscp` | Integer | - | 시그널링 DSCP 마킹 값 |

### 5.3 데이터 예시

```ini
[NE]
NEName=IMS-CSCF-A01
NeType=P_CSCF
SnapshotId=IMS-CSCF-A01-20260601-01
CollectTime=20260601030000

[SIP]
TimerT1=500
TimerT2=4000
TimerB=32000

[REG]
ExpireSec=3600

[SESSION]
MaxSession=200000
ExpireSec=1800

[OVERLOAD]
CpuThreshold=80.0

[TRANSPORT]
SipPort=5060

[HA]
HeartbeatMs=2000

[QOS]
Dscp=46
```

---

## 6. 유의 사항

1. 장비 재기동 시 일부 카운터가 0부터 재시작될 수 있다.
2. 파일 전송 중 오류로 동일 레코드가 중복 전송될 수 있으므로, 수신 측에서
   장비명·수집시각 기준 중복 제거를 권고한다.
3. 본 규격은 예고 없이 개정될 수 있으며, 개정 시 §1.3 개정 이력에 기재한다.
