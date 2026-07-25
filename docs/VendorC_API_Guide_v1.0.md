# IMS CSCF — Data Export Guide (v1.0)

안녕하세요 👋 저희 EMS의 데이터 익스포트 연동 가이드입니다.
JSON만 다루면 되니까 어렵지 않아요. 5분이면 첫 파싱까지 끝납니다.

---

## Quick Start

EMS는 NE별·일별로 파일 3개를 떨궈줍니다.

```
C_IMS-CSCF-C01_PM_20260601.json    # 성능
C_IMS-CSCF-C01_FM_20260601.json    # 알람
C_IMS-CSCF-C01_CM_20260601.json    # 설정 스냅샷
```

세 파일 모두 **최상위가 배열**입니다. 그냥 `json.load()` 하시면 됩니다.

```python
import json
rows = json.load(open("C_IMS-CSCF-C01_PM_20260601.json"))
print(rows[0]["reg_try_cnt"])
```

---

## 시간은 전부 epoch millis 입니다 ⏱

`ts`, `evt_ts` 같은 시각 필드는 **Unix epoch milliseconds(정수)** 입니다.
초가 아니라 **밀리초**예요. 여기서 제일 많이 실수하십니다.

```python
from datetime import datetime, timezone, timedelta
KST = timezone(timedelta(hours=9))
dt = datetime.fromtimestamp(rows[0]["ts"] / 1000, KST)   # 1000 으로 나누기!
```

---

## PM 파일

수집 주기는 **5분**입니다. `gran` 필드에 주기가 **초 단위**로 들어갑니다 (5분 → `300`).

```jsonc
{
  "ne": "IMS-CSCF-C01",       // NE 이름
  "kind": "S_CSCF",           // NE 종류: P_CSCF / I_CSCF / S_CSCF
  "ts": 1780239600000,        // 수집 구간 시작 시각 (epoch ms)
  "gran": 300,                // 수집 주기 (초)

  "reg_try_cnt": 1160,        // REGISTER 시도 건수
  "reg_ok_cnt": 1136,         // REGISTER 성공 건수 (2xx)
  "reg_ng_cnt": 24,           // REGISTER 실패 건수

  "inv_try_cnt": 718,         // INVITE 시도 건수
  "inv_ok_cnt": 712,          // INVITE 성공 건수 (200 OK)
  "inv_ng_cnt": 6,            // INVITE 실패 건수

  "rsp_4xx_cnt": 24,          // 4xx 응답 송출 건수
  "rsp_5xx_cnt": 5,           // 5xx 응답 송출 건수
  "rsp_6xx_cnt": 1,           // 6xx 응답 송출 건수

  "sess_act": 2487,           // 수집 시점 동시 활성 세션 수
  "setup_ms": 135.82,         // 세션 설정 평균 소요시간, 밀리초(ms)
  "cpu_pct": 34.26,           // CPU 사용률, 퍼센트(0~100)
  "mem_pct": 43.62,
  "msg_in": 11343,
  "msg_out": 10618
}
```

`*_cnt` 계열은 전부 **해당 5분 구간의 증분값**입니다. 누적값 아닙니다.

---

## FM 파일

알람 1건 = 객체 1개.

```jsonc
{
  "ne": "IMS-CSCF-C01",
  "kind": "S_CSCF",
  "alm": "ALM1008",           // 알람 종류 ID
  "sev": "MN",                // 심각도 (아래 표)
  "clr": false,               // 해제 이벤트인지 여부
  "cause": "CONFIG_MISMATCH", // 발생 원인 코드
  "obj": "ManagedElement=IMS-CSCF-C01,Subsystem=SIP,Board=1",   // 관리 객체 경로
  "evt_ts": 1780258472000,    // 알람이 실제 발생/해제된 시각
  "ts": 1780258472000,        // 레코드 수집 시각
  "msg": "Configuration mismatch between mated nodes"
}
```

### 심각도 코드 (`sev`)

| 코드 | 뜻 |
|---|---|
| `CR` | Critical |
| `MJ` | Major |
| `MN` | Minor |
| `WN` | Warning |

### 원인 코드 (`cause`) ↔ 알람 ID (`alm`)

| `alm` | `cause` |
|---|---|
| ALM1001 | `LINK_FAILURE` |
| ALM1002 | `CPU_OVERLOAD` |
| ALM1003 | `MEMORY_EXHAUSTION` |
| ALM1004 | `SIP_TIMEOUT` |
| ALM1005 | `REGISTRATION_STORM` |
| ALM1006 | `LICENSE_EXPIRY` |
| ALM1007 | `DATABASE_UNAVAILABLE` |
| ALM1008 | `CONFIG_MISMATCH` |

---

## CM 파일

하루 한 번(03:00) 찍히는 설정 스냅샷입니다. 실제 설정값은 `cfg` 객체 **안에** 들어 있습니다.

```jsonc
{
  "ne": "IMS-CSCF-C01",
  "kind": "S_CSCF",
  "ts": 1780250400000,
  "snap_id": "IMS-CSCF-C01-20260601-01",
  "cfg": {
    "t1_ms": 500,                 // SIP T1 타이머 (ms)
    "t2_ms": 4000,                // SIP T2 타이머 (ms)
    "invite_timeout_ms": 32000,   // INVITE 트랜잭션 타임아웃 (ms)
    "reg_expire_sec": 3600,       // REGISTER 만료 시간 (초)
    "max_sess": 180000,           // 최대 동시 세션 수
    "sess_expire_sec": 1800,      // 세션 타이머 (초)
    "cpu_ovld_pct": 80.0,         // 과부하 제어 진입 CPU 임계치 (퍼센트)
    "sip_port": 5060,
    "hb_ms": 1000,
    "dscp": 46
  }
}
```

---

## FAQ

**Q. `mem_pct` 랑 `cpu_pct` 는 0~1 스케일인가요?**
아니요. 저희는 **퍼센트(0~100)** 로 내보냅니다. `mem_pct` 는 메모리 사용률 평균이고
`cpu_pct` 와 동일한 스케일·소수 둘째 자리입니다.

**Q. `msg_in` / `msg_out` 이 뭔가요?**
각각 해당 구간에 **수신한 SIP 메시지 총 건수 / 송신한 SIP 메시지 총 건수**입니다.
리트랜스미션도 포함되기 때문에 시도 호수보다 훨씬 큽니다.

**Q. `sess_act` 는 합산해도 되나요?**
안 됩니다. 게이지(gauge)라서 수집 시점의 스냅샷 값입니다. 합산하지 말고 평균 내세요.

**Q. 알람 해제(clear)는 어떻게 알아보나요?**
`clr: true` 인 레코드가 해제 이벤트입니다. 이때 `sev` 는 **발생 당시 값이 그대로 남아
있으니**, 해제 여부는 `sev` 가 아니라 반드시 `clr` 로 판단하세요.
(v1.0 에는 "해제"를 뜻하는 별도 `sev` 코드가 없습니다.)

**Q. `hb_ms`, `dscp`, `sip_port` 는요?**
`hb_ms` 는 이중화 heartbeat 주기(ms), `dscp` 는 시그널링 패킷 DSCP 마킹 값,
`sip_port` 는 SIP 시그널링 수신 포트입니다.

**Q. 같은 레코드가 두 번 들어왔어요.**
전송 재시도 시 중복이 생길 수 있습니다. `ne` + `ts` 기준으로 dedupe 하세요.

**Q. 카운터가 갑자기 0으로 떨어졌어요.**
장비 재기동 시 해당 구간 카운터가 0부터 다시 시작합니다. 정상 동작입니다.

---

문의: ims-support@vendorc.example
