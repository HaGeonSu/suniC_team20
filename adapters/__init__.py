"""벤더 원본 포맷 파서 (스타터 킷 제공)

이 모듈이 하는 일은 딱 하나다: **원본 파일 → `{원본필드명: 값}` 평면 딕셔너리.**

표준 스키마가 무엇인지, 어떤 원본 필드가 어떤 표준 필드에 대응하는지, 단위를 어떻게
바꿔야 하는지는 **전혀 모른다.** 그건 여러분이 만들 매핑 규칙과 변환 엔진의 몫이다.
포맷 파싱은 지루한 잡일이라 대신 해준다. 진짜 문제는 그 다음부터다.

사용법:

    from adapters import parse_file, vendor_of, kind_of

    for raw, err in parse_file("data/public/raw/A_IMS-CSCF-A01_PM_20260601_0000.csv"):
        if err:                      # 깨진 행 등 파싱 불가 → 사유 문자열
            print("버림:", err)
            continue
        print(raw)                   # {'NEName': 'IMS-CSCF-A01', 'RegAtt': '1263', ...}

값은 전부 **문자열 또는 원본 JSON 타입 그대로**다. 형변환도 여러분 몫이다.
"""

import csv
import json
import os
import re
import xml.etree.ElementTree as ET

__all__ = ["parse_file", "vendor_of", "kind_of", "ADAPTERS", "ParseError"]


class ParseError(Exception):
    pass


FILE_RE = re.compile(r"^(?P<v>[ABC])_(?P<ne>[\w-]+)_(?P<kind>PM|FM|CM)_")
VENDOR_OF = {"A": "VENDOR_A", "B": "VENDOR_B", "C": "VENDOR_C"}


def vendor_of(filename):
    """파일명에서 벤더를 알아낸다. 인식 못 하면 None."""
    m = FILE_RE.match(os.path.basename(filename))
    return VENDOR_OF[m.group("v")] if m else None


def kind_of(filename):
    """파일명에서 레코드 종별(PM/FM/CM)을 알아낸다. 인식 못 하면 None."""
    m = FILE_RE.match(os.path.basename(filename))
    return m.group("kind") if m else None


def parse_file(path):
    """(원본레코드 dict, None) 또는 (None, 실패사유) 를 순서대로 내놓는다."""
    vendor, kind = vendor_of(path), kind_of(path)
    if vendor is None:
        return iter([(None, "파일명 규칙에 맞지 않음: %s" % os.path.basename(path))])
    return ADAPTERS[vendor](path, kind)


# --------------------------------------------------------------- VENDOR_A
# CSV(PM) / syslog 텍스트(FM) / INI(CM)

def adapt_vendor_a(path, kind):
    if kind == "PM":
        with open(path, encoding="utf-8") as fh:
            reader = csv.reader(fh)
            header = next(reader)
            for lineno, row in enumerate(reader, 2):
                if len(row) != len(header):
                    yield None, "CSV 컬럼 수 불일치 (기대 %d, 실제 %d) @line %d" % (
                        len(header), len(row), lineno)
                    continue
                yield dict(zip(header, row)), None

    elif kind == "FM":
        # 20260601041445 IMS-CSCF-A01 IMSALARM: NETYPE=.. ALM_ID=.. SEV=.. PC=.. MO=".." ...
        token_re = re.compile(r'(\w+)=("([^"]*)"|\S+)')
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                head = line.split(" IMSALARM:", 1)
                if len(head) != 2:
                    yield None, "FM 라인 형식 불일치: %s" % line[:60]
                    continue
                prefix = head[0].split()
                rec = {"NEName": prefix[1]}
                for m in token_re.finditer(head[1]):
                    rec[m.group(1)] = m.group(3) if m.group(3) is not None else m.group(2)
                yield rec, None

    else:  # CM — INI. [NE] 섹션 키는 그대로, 나머지는 "섹션.키" 로 준다.
        rec, section = {}, ""
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("[") and line.endswith("]"):
                    section = line[1:-1]
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                rec[k if section == "NE" else "%s.%s" % (section, k)] = v
        yield rec, None


# --------------------------------------------------------------- VENDOR_B
# XML. 3GPP measCollec 계열이라 네임스페이스가 붙는다 — 태그명만 떼어 쓴다.

def _tag(elem):
    return elem.tag.split("}")[-1]


def _find(root, name):
    return [e for e in root.iter() if _tag(e) == name]


def adapt_vendor_b(path, kind):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        yield None, "XML 파싱 실패: %s" % e
        return

    if kind == "PM":
        me = _find(root, "managedElement")
        if not me:
            yield None, "managedElement 없음"
            return
        base = {"localDn": me[0].get("localDn"), "neType": me[0].get("neType")}
        for mi in _find(root, "measInfo"):
            gp = [e for e in mi if _tag(e) == "granularityPeriod"]
            if not gp:
                yield None, "granularityPeriod 없음"
                continue
            rec = dict(base)
            rec["endTime"] = gp[0].get("endTime")
            rec["duration"] = gp[0].get("duration")
            # measType@p 인덱스와 r@p 값을 짝지어 평면화한다.
            names = {}
            for mt in [e for e in mi if _tag(e) == "measType"]:
                names[mt.get("p")] = (mt.text or "").strip()
            for mv in [e for e in mi if _tag(e) == "measValue"]:
                for r in mv:
                    p = r.get("p")
                    if p in names:
                        rec[names[p]] = (r.text or "").strip()
            yield rec, None

    elif kind == "FM":
        for al in _find(root, "alarm"):
            rec = dict(al.attrib)
            rec["localDn"] = rec.get("managedElement")
            txt = [e for e in al if _tag(e) == "additionalText"]
            if txt:
                rec["additionalText"] = (txt[0].text or "").strip()
            yield rec, None

    else:  # CM — <param name= value= unit=/> 를 name: value 로 평면화
        rec = dict(root.attrib)
        rec["localDn"] = rec.get("managedElement")
        for p in _find(root, "param"):
            rec[p.get("name")] = p.get("value")
        yield rec, None


# --------------------------------------------------------------- VENDOR_C
# JSON 배열. CM 은 설정값이 cfg 객체 안에 중첩돼 있어 평면화해준다.

def adapt_vendor_c(path, kind):
    try:
        with open(path, encoding="utf-8") as fh:
            items = json.load(fh)
    except json.JSONDecodeError as e:
        yield None, "JSON 파싱 실패: %s" % e
        return
    for item in items if isinstance(items, list) else [items]:
        rec = dict(item)
        cfg = rec.pop("cfg", None)
        if isinstance(cfg, dict):
            rec.update(cfg)
        yield rec, None


ADAPTERS = {
    "VENDOR_A": adapt_vendor_a,
    "VENDOR_B": adapt_vendor_b,
    "VENDOR_C": adapt_vendor_c,
}
