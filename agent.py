import argparse
import os
import sys
import json
import re
import anthropic
from dotenv import load_dotenv

# .env 파일에서 환경 변수 로드
load_dotenv()


def call_llm_api(prompt: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=8192,
        system="You are a data mapping agent. You must output strictly valid JSON only. Do not wrap the JSON in markdown blocks and do not include any other text.",
        messages=[{"role": "user", "content": prompt}]
    )

    for block in response.content:
        if getattr(block, "type", "") == "text":
            return block.text

    return ""


def clean_json_output(text: str) -> str:
    cleaned = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
    cleaned = re.sub(r'^```\s*$', '', cleaned, flags=re.MULTILINE)

    start_idx = cleaned.find('{')
    end_idx = cleaned.rfind('}')

    if start_idx != -1 and end_idx != -1:
        return cleaned[start_idx:end_idx + 1]

    return cleaned.strip()


def get_json_template(record_type, vendor):
    if record_type == "CM":
        return f"""{{
  "vendor": "{vendor}",
  "record_type": "CM",
  "metadata_mapping": {{
    "ne_id": "<vendor_source_field>",
    "ne_type": "<vendor_source_field>",
    "snapshot_id": "<vendor_source_field>"
  }},
  "time_mapping": {{
    "timestamp_field": "<vendor_source_field>",
    "raw_format": "<time_format_string>"
  }},
  "value_multiplier": {{
    "<vendor_source_field_requiring_multiplication>": 100
  }},
  "parameter_mapping": {{
    "<vendor_source_field_1>": "<standard_parameter_name_1>",
    "<vendor_source_field_2>": "<standard_parameter_name_2>"
  }}
}}"""
    elif record_type == "FM":
        return f"""{{
  "vendor": "{vendor}",
  "record_type": "FM",
  "metadata_mapping": {{
    "ne_id": "<vendor_source_field>",
    "ne_type": "<vendor_source_field>"
  }},
  "time_mapping": {{
    "timestamp_field": "<vendor_source_field>",
    "raw_format": "<time_format_string>"
  }},
  "alarm_mapping": {{
    "alarm_id": "<vendor_source_field>",
    "severity": "<vendor_source_field>",
    "probable_cause": "<vendor_source_field>",
    "managed_object": "<vendor_source_field>",
    "additional_text": "<vendor_source_field>"
  }},
  "enum_mapping": {{
    "severity": {{
      "<vendor_critical_code>": "CRITICAL",
      "<vendor_major_code>": "MAJOR",
      "<vendor_clear_code>": "CLEARED"
    }}
  }}
}}"""
    elif record_type == "PM":
        return f"""{{
  "vendor": "{vendor}",
  "record_type": "PM",
  "metadata_mapping": {{
    "ne_id": "<vendor_source_field>",
    "ne_type": "<vendor_source_field>"
  }},
  "time_mapping": {{
    "timestamp_field": "<vendor_source_field>",
    "raw_format": "<time_format_string>",
    "interval_field": "<vendor_source_field>",
    "interval_unit": "<unit_string>"
  }},
  "value_multiplier": {{
    "<vendor_source_field_requiring_multiplication>": 100
  }},
  "counter_mapping": {{
    "<vendor_source_field_1>": "<standard_counter_name_1>",
    "<vendor_source_field_2>": "<standard_counter_name_2>"
  }}
}}"""


def propose(doc_file, vendor, record_type, rules_out):
    print(f"[{vendor} - {record_type}] ICD 문서 분석 시작: {doc_file}")

    if not os.path.exists(doc_file):
        print(f"작업 중단: 입력 문서 파일이 존재하지 않습니다. ({doc_file})")
        sys.exit(1)

    with open(doc_file, "r", encoding="utf-8") as f:
        doc_content = f.read()

    dict_path = os.path.join("schema", "counter_dictionary.md")
    if not os.path.exists(dict_path):
        print(f"작업 중단: 필수 사전 파일이 존재하지 않습니다. ({dict_path})")
        sys.exit(1)

    with open(dict_path, "r", encoding="utf-8") as f:
        dict_content = f.read()

    schema_path = os.path.join("schema", "unified_v1.schema.json")
    if not os.path.exists(schema_path):
        print(f"작업 중단: 필수 스키마 파일이 존재하지 않습니다. ({schema_path})")
        sys.exit(1)

    with open(schema_path, "r", encoding="utf-8") as f:
        schema_content = f.read()

    json_template = get_json_template(record_type, vendor)
    doc_filename = os.path.basename(doc_file)

    prompt = f"""
    [Standard Dictionary Reference]
    {dict_content}

    [Standard Schema Constraints]
    {schema_content}

    [Vendor ICD Document Name]
    {doc_filename}

    [Vendor ICD Document Content]
    {doc_content}

    Task: 
    1. Analyze the vendor ICD document.
    2. Create a declarative mapping rule file for the '{record_type}' record type only.
    3. Use the exact declarative JSON structure provided below.
    4. Map ALL relevant fields found in the vendor document to standard fields. Do not limit to the number of keys shown in the template.
    5. In 'parameter_mapping', 'counter_mapping', or 'alarm_mapping', the values MUST strictly match the standard names from the Standard Dictionary.
    6. Output strictly valid JSON. No markdown wrappers or explanations outside JSON.

    Required JSON Structure:
    {json_template}
    """

    response_text = call_llm_api(prompt)
    cleaned_text = clean_json_output(response_text)

    try:
        actual_llm_response = json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        print(f"JSON 파싱 에러 발생: {e}")
        print(f"원본 출력: {cleaned_text}")
        return

    os.makedirs(rules_out, exist_ok=True)
    rule_file_name = f"{vendor.lower()}_{record_type.lower()}_rules.json"
    out_path = os.path.join(rules_out, rule_file_name)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(actual_llm_response, f, indent=2, ensure_ascii=False)

    print(f"매핑 규칙 JSON 저장 완료: {out_path}")


def validate(rules_dir, input_dir):
    print(f"규칙 자체 검증 시작 - 규칙 경로: {rules_dir}, 입력 경로: {input_dir}")

    # 입력 디렉터리 경로 무결성 검증 추가
    if not os.path.exists(input_dir):
        print(f"검증 실패: 입력 데이터 디렉터리가 존재하지 않거나 경로가 잘못되었습니다. ({input_dir})")
        sys.exit(1)

    if not os.path.exists(rules_dir) or not os.listdir(rules_dir):
        print(f"검증 실패: rules 디렉터리가 비어 있거나 존재하지 않습니다. ({rules_dir})")
        sys.exit(1)

    dict_path = os.path.join("schema", "counter_dictionary.md")
    if not os.path.exists(dict_path):
        print(f"작업 중단: 필수 사전 파일이 존재하지 않습니다. ({dict_path})")
        sys.exit(1)

    valid_target_fields = set()
    with open(dict_path, "r", encoding="utf-8") as f:
        for line in f:
            match = re.search(r'\|\s*`([a-z0-9_.]+)`\s*\|', line)
            if match:
                valid_target_fields.add(match.group(1))

    # FM 전용 표준 필드명 및 기타 예약어 추가
    fm_standard_fields = {"alarm_id", "severity", "probable_cause", "managed_object", "additional_text"}
    valid_target_fields.update(fm_standard_fields)

    for rule_file in os.listdir(rules_dir):
        if not rule_file.endswith('.json'):
            continue

        rule_path = os.path.join(rules_dir, rule_file)
        try:
            with open(rule_path, "r", encoding="utf-8") as f:
                rules = json.load(f)

            vendor_name = rules.get("vendor", "")
            if not vendor_name:
                print(f"[검증 실패] {rule_file}: 'vendor' 키가 누락되었거나 값이 비어 있습니다.")
                continue

            record_type = rules.get("record_type")
            if record_type not in ["PM", "CM", "FM"]:
                print(f"[검증 실패] {rule_file}: 'record_type' 키 누락 또는 잘못된 값 ({record_type})")
                continue

            validation_failed = False
            mappings_to_check = {}

            # 레코드 타입별 타겟 매핑 블록 설정
            if record_type == "PM" and "counter_mapping" in rules:
                mappings_to_check = rules["counter_mapping"]
            elif record_type == "CM" and "parameter_mapping" in rules:
                mappings_to_check = rules["parameter_mapping"]
            elif record_type == "FM" and "alarm_mapping" in rules:
                mappings_to_check = rules["alarm_mapping"]
            else:
                print(f"[검증 실패] {rule_file}: {record_type}에 대응하는 필수 매핑 딕셔너리가 누락되었습니다.")
                validation_failed = True

            if validation_failed:
                continue

            # JSON 객체 타입 검증 추가 (AttributeError 차단)
            if not isinstance(mappings_to_check, dict):
                print(f"[검증 실패] {rule_file}: 매핑 데이터 구조가 올바른 JSON 객체(Dictionary) 형식이 아닙니다.")
                continue

            # 타겟 필드가 표준 사전에 존재하는지 검증
            for source, target in mappings_to_check.items():
                if valid_target_fields and target not in valid_target_fields:
                    print(f"[검증 실패] {rule_file}: '{target}' 필드는 비표준 타겟 필드입니다.")
                    validation_failed = True

            if validation_failed:
                continue

            matched_files = [f for f in os.listdir(input_dir) if f.startswith(vendor_name)]

            print(f"[검증 통과] {rule_file} ({record_type}) - 선언적 논리 구조 정상. 입력 데이터 매칭 {len(matched_files)}건 확인.")

        except json.JSONDecodeError:
            print(f"[검증 실패] {rule_file}: 유효하지 않은 JSON 구조입니다.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="LLM Agent for Declarative Rule Generation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose_parser = subparsers.add_parser('propose')
    propose_parser.add_argument('--doc', required=True)
    propose_parser.add_argument('--vendor', required=True)
    propose_parser.add_argument('--record_type', choices=['CM', 'PM', 'FM'], required=True)
    propose_parser.add_argument('--out', required=True)

    validate_parser = subparsers.add_parser('validate')
    validate_parser.add_argument('--rules', required=True)
    validate_parser.add_argument('--input', required=True)

    args = parser.parse_args()

    if args.command == 'propose':
        propose(args.doc, args.vendor, args.record_type, args.out)
    elif args.command == 'validate':
        validate(args.rules, args.input)