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
        max_tokens=4096,
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
    # 빈 객체를 기본으로 제공하여 플레이스홀더로 인한 Hallucination 방지
    if record_type == "CM":
        return f"""{{
  "vendor": "{vendor}",
  "icd_version": "<extracted_icd_version>",
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
  "value_multiplier": {{}},
  "parameter_mapping": {{}},
  "mapping_reason": {{}},
  "unmapped_fields": []
}}"""
    elif record_type == "FM":
        return f"""{{
  "vendor": "{vendor}",
  "icd_version": "<extracted_icd_version>",
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
    "severity": {{}}
  }},
  "mapping_reason": {{}},
  "unmapped_fields": []
}}"""
    elif record_type == "PM":
        return f"""{{
  "vendor": "{vendor}",
  "icd_version": "<extracted_icd_version>",
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
  "value_multiplier": {{}},
  "counter_mapping": {{}},
  "mapping_reason": {{}},
  "unmapped_fields": []
}}"""


def propose(doc_file, vendor, rules_dir, out_dir, sample_dir=None):
    print(f"[{vendor}] ICD 문서 분석 시작: {doc_file}")

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

    doc_filename = os.path.basename(doc_file)
    os.makedirs(out_dir, exist_ok=True)

    for record_type in ["CM", "PM", "FM"]:
        print(f"[{vendor} - {record_type}] 규칙 생성 진행 중...")
        json_template = get_json_template(record_type, vendor)

        rule_file_name = f"{vendor.lower()}_{record_type.lower()}_rules.json"
        existing_path = os.path.join(rules_dir, rule_file_name)
        out_path = os.path.join(out_dir, rule_file_name)

        existing_rule_content = ""
        if os.path.exists(existing_path):
            with open(existing_path, "r", encoding="utf-8") as f:
                existing_rule_content = f.read()

        # 원본 샘플 대조 기능을 위한 데이터 추출 로직
        sample_context = ""
        if sample_dir and os.path.exists(sample_dir):
            vendor_prefix = vendor.replace("VENDOR_", "")
            matched_sample_files = [
                f for f in os.listdir(sample_dir)
                if f.startswith(f"{vendor_prefix}_") and f"_{record_type}_" in f
            ]
            if matched_sample_files:
                sample_file_path = os.path.join(sample_dir, matched_sample_files[0])
                try:
                    with open(sample_file_path, "r", encoding="utf-8") as sf:
                        sample_text = sf.read(2048)
                    sample_context = f"\n[Sample Raw Data (First 2048 chars)]\n{sample_text}\n"
                    print(f"[{vendor} - {record_type}] 샘플 데이터 대조 성공: {matched_sample_files[0]}")
                except Exception:
                    pass

        prompt = f"""
        [Standard Dictionary Reference]
        {dict_content}

        [Standard Schema Constraints]
        {schema_content}

        [Vendor ICD Document Name]
        {doc_filename}

        [Vendor ICD Document Content]
        {doc_content}
        """

        if sample_context:
            prompt += sample_context

        if existing_rule_content:
            prompt += f"""
        [Existing Mapping Rules (Previous Version)]
        {existing_rule_content}
        """

        prompt += f"""
        Task: 
        1. Analyze the vendor ICD document and the provided Sample Raw Data (if any). The sample data reveals the actual field keys to map from.
        2. Extract the ICD document version (e.g., "1.0", "1.1", "v1.2") from the document text and populate the 'icd_version' field.
        3. Create a declarative mapping rule file for the '{record_type}' record type only.
        4. If [Existing Mapping Rules] are provided, update them. You MUST preserve existing valid mappings to ensure backward compatibility and prevent regression for older data formats. Merge new fields gracefully.
        5. Use the exact declarative JSON structure provided below.
        6. Map ALL relevant fields found in the vendor document to standard fields.
        7. In 'parameter_mapping', 'counter_mapping', or 'alarm_mapping', the values MUST strictly match the standard names from the Standard Dictionary.
        8. Replace ALL placeholder strings (like `<vendor_source_field>`) with actual field names. If a section like 'value_multiplier' is not needed, output an empty object `{{}}`.
        9. Output strictly valid JSON. No markdown wrappers or explanations outside JSON.
        10. For every entry in 'parameter_mapping', 'counter_mapping', or 'alarm_mapping', add a matching entry to 'mapping_reason' keyed by the vendor source field name, with a string value explaining why that field was mapped to that standard field.
        11. If a vendor field found in the document has no matching standard field for 'parameter_mapping', 'counter_mapping', or 'alarm_mapping', do NOT force a mapping. Instead, list it in 'unmapped_fields' as {{"source_field": "...", "reason": "..."}}.
        12. If there are no unmapped fields, output 'unmapped_fields' as an empty array [].

        Required JSON Structure:
        {json_template}
        """

        response_text = call_llm_api(prompt)
        cleaned_text = clean_json_output(response_text)

        try:
            actual_llm_response = json.loads(cleaned_text)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(actual_llm_response, f, indent=2, ensure_ascii=False)
            print(f"[{vendor} - {record_type}] 매핑 규칙 JSON 저장 완료: {out_path}")
        except json.JSONDecodeError as e:
            print(f"[{vendor} - {record_type}] JSON 파싱 에러 발생: {e}")
            print(f"원본 출력: {cleaned_text}")


def validate(rules_dir, input_dir):
    print(f"규칙 자체 검증 시작 - 규칙 경로: {rules_dir}, 입력 경로: {input_dir}")

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

            icd_version = rules.get("icd_version", "")
            if not icd_version or icd_version == "<extracted_icd_version>":
                print(f"[검증 경고] {rule_file}: 'icd_version' 정보가 누락되었거나 올바르게 추출되지 않았습니다.")

            validation_failed = False
            mappings_to_check = {}

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

            if not isinstance(mappings_to_check, dict):
                print(f"[검증 실패] {rule_file}: 매핑 데이터 구조가 올바른 JSON 객체(Dictionary) 형식이 아닙니다.")
                continue

            for source, target in mappings_to_check.items():
                if valid_target_fields and target not in valid_target_fields:
                    print(f"[검증 실패] {rule_file}: '{target}' 필드는 비표준 타겟 필드입니다.")
                    validation_failed = True

            if validation_failed:
                continue

            # 입력 데이터와 룰 파일이 매칭되는지 확인하기 위한 Prefix 필터링 로직 (버그 수정)
            vendor_prefix = vendor_name.replace("VENDOR_", "")
            matched_files = [f for f in os.listdir(input_dir) if f.startswith(f"{vendor_prefix}_")]

            print(f"[검증 통과] {rule_file} ({record_type}) - 선언적 논리 구조 정상. 입력 데이터 매칭 {len(matched_files)}건 확인.")

        except json.JSONDecodeError:
            print(f"[검증 실패] {rule_file}: 유효하지 않은 JSON 구조입니다.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="LLM Agent for Declarative Rule Generation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose_parser = subparsers.add_parser('propose')
    propose_parser.add_argument('--doc', required=True)
    propose_parser.add_argument('--vendor', required=True)
    propose_parser.add_argument('--rules', required=True)
    propose_parser.add_argument('--out', required=True)
    propose_parser.add_argument('--sample', required=False)

    validate_parser = subparsers.add_parser('validate')
    validate_parser.add_argument('--rules', required=True)
    validate_parser.add_argument('--input', required=True)

    args = parser.parse_args()

    if args.command == 'propose':
        propose(args.doc, args.vendor, args.rules, args.out, getattr(args, 'sample', None))
    elif args.command == 'validate':
        validate(args.rules, args.input)