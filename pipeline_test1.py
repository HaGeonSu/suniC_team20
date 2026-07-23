import argparse
import os
import json
import glob
from datetime import datetime, timezone, timedelta

# 제공된 어댑터 모듈 임포트 (킷에 포함됨)
try:
    from adapters import parse_file
except ImportError:
    # 로컬 테스트용 가상 함수
    def parse_file(filepath):
        yield {}, None


def load_rules(rules_dir):
    """rules/ 디렉터리에 있는 모든 JSON 규칙 파일을 로드"""
    rules = {}
    if not os.path.exists(rules_dir):
        return rules

    for rule_file in glob.glob(os.path.join(rules_dir, "*.json")):
        with open(rule_file, "r", encoding="utf-8") as f:
            rule_data = json.load(f)
            vendor = rule_data.get("vendor")
            if vendor:
                rules[vendor] = rule_data
    return rules


def transform_value(value, transform_type):
    """규칙에 정의된 타입에 따른 값 변환 (단위 환산 등)"""
    if value is None:
        return None
    try:
        if transform_type == "multiply_100":
            return float(value) * 100.0
        elif transform_type == "string":
            return str(value)
        # 필요한 변환 로직 확장 가능
    except Exception:
        return value
    return value


def transform(input_dir, rules_dir, out_file, rejected_file):
    print(f"[Pipeline] 변환 시작 - 입력: {input_dir}, 규칙: {rules_dir}")

    # 1. 매핑 규칙 로드
    rules = load_rules(rules_dir)

    unified_records = []
    rejected_records = []

    # 2. 입력 디렉터리의 모든 원본 파일 순회
    raw_files = glob.glob(os.path.join(input_dir, "*.*"))

    for filepath in raw_files:
        filename = os.path.basename(filepath)
        # 벤더 식별 (파일명 규칙 예: A_... -> VendorA, 혹은 파일 내부 내용 기반)
        vendor = "VendorA" if filename.startswith("A") else ("VendorB" if filename.startswith("B") else "VendorC")

        vendor_rule = rules.get(vendor, {})
        mappings = vendor_rule.get("mappings", {})

        # 3. adapters를 통한 원본 파싱
        try:
            for raw_dict, err in parse_file(filepath):
                if err:
                    rejected_records.append({
                        "file": filename,
                        "raw": raw_dict,
                        "reason": f"Adapter parse error: {err}"
                    })
                    continue

                # 4. 정규화 및 필드 매핑 수행
                normalized_record = {}
                is_valid = True

                for src_field, tgt_field in mappings.items():
                    if src_field in raw_dict:
                        val = raw_dict[src_field]
                        # 예시: 특정 변환 타입 적용 가능
                        normalized_record[tgt_field] = transform_value(val, "string")
                    else:
                        # 필수 필드 누락 시 처리 정책 (여기서는 unmapped 혹은 기본값)
                        pass

                if is_valid and normalized_record:
                    unified_records.append(normalized_record)
                else:
                    rejected_records.append({
                        "file": filename,
                        "raw": raw_dict,
                        "reason": "Missing mandatory fields or mapping failure"
                    })

        except Exception as e:
            rejected_records.append({
                "file": filename,
                "reason": f"Exception during processing: {str(e)}"
            })

    # 5. 결정론적 정렬 (타임스탬프 기준 정렬 및 중복 제거 등)
    # unified_records = sorted(unified_records, key=lambda x: x.get("collect_time", ""))

    # 6. 결과물 출력 (unified.jsonl)
    os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        for rec in unified_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 7. 거부된 레코드 출력 (rejected.jsonl, 선택 인자)
    if rejected_file:
        os.makedirs(os.path.dirname(os.path.abspath(rejected_file)), exist_ok=True)
        with open(rejected_file, "w", encoding="utf-8") as f:
            for rej in rejected_records:
                f.write(json.dumps(rej, ensure_ascii=False) + "\n")

    print(f"[Pipeline] 변환 완료. 성공: {len(unified_records)}건, 거부: {len(rejected_records)}건")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Deterministic Pipeline Engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # transform 명령어 정의 (CLI 규약 엄수)
    transform_parser = subparsers.add_parser('transform')
    transform_parser.add_argument('--input', required=True, help="Raw data directory")
    transform_parser.add_argument('--rules', required=True, help="Rules directory")
    transform_parser.add_argument('--out', required=True, help="Output unified.jsonl file")
    transform_parser.add_argument('--rejected', required=False, help="Output rejected.jsonl file")

    args = parser.parse_args()

    if args.command == 'transform':
        transform(args.input, args.rules, args.out, args.rejected)