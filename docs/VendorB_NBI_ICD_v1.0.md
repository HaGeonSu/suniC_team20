# NBI Interface Control Document — IMS CSCF EMS

Doc ID: NBI-ICD-IMS-0042 | Issue: 1.0 | Status: Released

## 1 Scope

This ICD specifies the northbound file interface exposed by the EMS for Performance
Management (PM), Fault Management (FM) and Configuration Management (CM) of IMS CSCF
network elements. The interface is aligned with 3GPP TS 32.435 (XML file format
definition for performance measurement) and TS 32.111-2 (Alarm IRP) where applicable.

## 2 References

| Ref | Document |
|---|---|
| [1] | 3GPP TS 32.435 — Performance measurement: XML file format definition |
| [2] | 3GPP TS 32.401 — Performance Management concept and requirements |
| [3] | 3GPP TS 32.111-2 — Alarm Integration Reference Point (IRP) |
| [4] | ITU-T X.733 — Information technology, Systems Management, Alarm reporting |

## 3 Common Conventions

**3.1 Encoding.** All files are UTF-8 XML 1.0.

**3.2 File naming.** `B_<managedElement>_<PM|FM|CM>_<yyyyMMdd>.xml`, one file per NE per day.

**3.3 Time representation.** All time values are ISO 8601 with **UTC** designator `Z`
(see [1] §5.2). No local-time form is emitted. Consumers requiring local time shall
apply the operator's own offset.

**3.4 Granularity period.** PM reporting period is **PT15M** (15 minutes), per [2] §4.2.
`granularityPeriod@endTime` carries the **end** of the reporting interval; the interval
start is derived as `endTime − duration`. See §4.2.

**3.5 Ratio scale.** Utilisation and ratio-type measurements are reported on a
**0.0 – 1.0** scale, not as a percentage. This applies to both PM (`VS.*Ratio`) and
CM (`unit="ratio"`) values.

## 4 Performance Management

### 4.1 Structure

Per [1], the file consists of `measCollecFile / measData / measInfo`. Each `measInfo`
carries one granularity period. `measType@p` indexes the corresponding `r@p` result value.

```xsd
<xs:element name="measInfo">
  <xs:complexType>
    <xs:sequence>
      <xs:element name="granularityPeriod">
        <xs:complexType>
          <xs:attribute name="duration" type="xs:duration" use="required"/>
          <xs:attribute name="endTime"  type="xs:dateTime" use="required"/>
        </xs:complexType>
      </xs:element>
      <xs:element name="measType" maxOccurs="unbounded"/>
      <xs:element name="measValue" maxOccurs="unbounded"/>
    </xs:sequence>
  </xs:complexType>
</xs:element>
```

### 4.2 Key attributes

| Attribute | XPath | Note |
|---|---|---|
| NE identifier | `measData/managedElement/@localDn` | |
| NE class | `measData/managedElement/@neType` | `P_CSCF` \| `I_CSCF` \| `S_CSCF` |
| Interval end | `measInfo/granularityPeriod/@endTime` | UTC. **Interval start = endTime − duration** |
| Interval length | `measInfo/granularityPeriod/@duration` | ISO 8601 duration, fixed `PT15M` |

### 4.3 Measurement types (`measType`)

| measType | Type | Unit | Range | Description |
|---|---|---|---|---|
| `VS.RegisterAttempt` | int | count | 0..1e7 | REGISTER requests received in the period |
| `VS.RegisterSuccess` | int | count | 0..1e7 | REGISTER transactions terminated with 2xx |
| `VS.RegisterFailure` | int | count | 0..1e7 | REGISTER transactions not terminated with 2xx |
| `VS.InviteAttempt` | int | count | 0..1e7 | Initial INVITE requests received |
| `VS.InviteSuccess` | int | count | 0..1e7 | INVITE transactions terminated with 200 OK |
| `VS.InviteFailure` | int | count | 0..1e7 | INVITE transactions not terminated with 200 OK |
| `VS.Response4xx` | int | count | 0..1e7 | 4xx class responses emitted |
| `VS.Response5xx` | int | count | 0..1e7 | 5xx class responses emitted |
| `VS.Response6xx` | int | count | 0..1e7 | 6xx class responses emitted |
| `VS.ActiveSessions` | int | count | 0..2e6 | Concurrent sessions, sampled at interval end |
| `VS.SessionSetupTimeMean` | float | **ms** | 0..60000 | Mean INVITE→200 OK elapsed time |
| `VS.CpuUtilRatio` | float | **ratio** | 0.0..1.0 | Mean CPU utilisation (cf. §3.5) |
| `VS.MemUtilRatio` | float | **ratio** | 0.0..1.0 | Mean memory utilisation (cf. §3.5) |
| `VS.MessagesReceived` | int | count | 0..1e8 | Total SIP messages received |
| `VS.MessagesSent` | int | count | 0..1e8 | Total SIP messages sent |

Counter values are **delta** values over the granularity period; cumulative reporting
mode (TS 32.401 §5.5) is not used on this interface.

### 4.4 Sample

```xml
<?xml version="1.0" encoding="UTF-8"?>
<measCollecFile xmlns="http://www.3gpp.org/ftp/specs/archive/32_series/32.435#measCollec">
  <fileHeader fileFormatVersion="32.435 V10.0" vendorName="VENDOR_B" dnPrefix="IMS"/>
  <measData>
    <managedElement localDn="IMS-CSCF-B01" neType="P_CSCF" swVersion="1.0"/>
    <measInfo measInfoId="IMS_PM">
      <granularityPeriod duration="PT15M" endTime="2026-05-31T15:15:00Z"/>
      <measType p="1">VS.RegisterAttempt</measType>
      <measType p="2">VS.RegisterSuccess</measType>
      <measType p="12">VS.CpuUtilRatio</measType>
      <measValue measObjLdn="IMS-CSCF-B01">
        <r p="1">5182</r>
        <r p="2">5121</r>
        <r p="12">0.3391</r>
      </measValue>
    </measInfo>
  </measData>
</measCollecFile>
```

## 5 Fault Management

Alarm semantics follow [3] / [4]. One `alarm` element per notification.

| Attribute | Type | Description |
|---|---|---|
| `managedElement` | string | NE identifier |
| `neType` | string | NE class |
| `alarmId` | string | Alarm type identifier, `ALM` + 4 digits |
| `perceivedSeverity` | enum | See §5.1 |
| `probableCause` | enum | See §5.2 |
| `objectInstance` | string | Distinguished name of the affected object |
| `eventTime` | dateTime | UTC, per §3.3 |
| `additionalText` | string | Free text, child element |

### 5.1 perceivedSeverity

`Critical` | `Major` | `Minor` | `Warning` | `Cleared`

`Cleared` is emitted on alarm clearance carrying the same `alarmId` and `objectInstance`
as the original notification (X.733 clearing correlation).

### 5.2 probableCause

`LINK_FAILURE` (ALM1001), `CPU_OVERLOAD` (ALM1002), `MEMORY_EXHAUSTION` (ALM1003),
`SIP_TIMEOUT` (ALM1004), `REGISTRATION_STORM` (ALM1005), `LICENSE_EXPIRY` (ALM1006),
`DATABASE_UNAVAILABLE` (ALM1007), `CONFIG_MISMATCH` (ALM1008).

### 5.3 Sample

```xml
<alarmList vendorName="VENDOR_B">
  <alarm managedElement="IMS-CSCF-B01" neType="P_CSCF" alarmId="ALM1002"
         perceivedSeverity="Warning" probableCause="CPU_OVERLOAD"
         objectInstance="ManagedElement=IMS-CSCF-B01,Subsystem=SIP,Board=3"
         eventTime="2026-06-01T16:08:27Z">
    <additionalText>CPU utilization exceeded configured threshold</additionalText>
  </alarm>
</alarmList>
```

## 6 Configuration Management

One snapshot per NE per day. Each parameter is a `param` element carrying `name`,
`value` and `unit`. The `unit` attribute is normative — consumers shall not assume a
unit from the parameter name.

| `name` | Type | `unit` | Description |
|---|---|---|---|
| `sipTimerT1` | int | `ms` | SIP T1, RTT estimate |
| `sipTimerT2` | int | `ms` | SIP T2, maximum retransmit interval |
| `sipInviteTimeout` | int | `ms` | INVITE transaction timeout (Timer B) |
| `regExpire` | int | `sec` | Default REGISTER expiry |
| `maxSessions` | int | `count` | Maximum concurrent sessions |
| `sessionExpire` | int | `sec` | Default Session-Expires |
| `cpuOverloadThreshold` | float | `ratio` | Overload control entry threshold (cf. §3.5) |
| `sipPort` | int | `port` | SIP signalling listening port |
| `haHeartbeat` | int | `ms` | Redundancy heartbeat interval |
| `dscpValue` | int | `codepoint` | DSCP marking for signalling |

### 6.1 Sample

```xml
<configData managedElement="IMS-CSCF-B01" neType="P_CSCF"
            snapshotId="IMS-CSCF-B01-20260601-01" collectTime="2026-05-31T18:00:00Z">
  <param name="sipTimerT1" value="500" unit="ms"/>
  <param name="regExpire" value="3600" unit="sec"/>
  <param name="cpuOverloadThreshold" value="0.8" unit="ratio"/>
  <param name="dscpValue" value="46" unit="codepoint"/>
</configData>
```

## 7 Known limitations

- Duplicate delivery of a `measInfo` block is possible after a transfer retry.
- On NE restart, counters restart from zero within the affected granularity period.

*End of document.*
