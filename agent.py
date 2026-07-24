import argparse
import os
import json
import re
import anthropic
from dotenv import load_dotenv

# .env 파일에서 환경 변수 로드
load_dotenv()


def call_llm_api(prompt: str) -> str:
    # 환경 변수에서 ANTHROPIC_API_KEY 인식
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)

    # claude-3-5-sonnet-20240620 모델 적용 및 max_tokens 4096 설정
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=8192,
        system="You are a data mapping agent. You must output strictly valid JSON only. Do not wrap the JSON in markdown blocks and do not include any other text.",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    # 응답 블록 중 텍스트 블록만 추출하여 반환
    for block in response.content:
        if getattr(block, "type", "") == "text":
            return block.text

    return ""  # 텍스트 블록이 없을 경우 빈 문자열 반환


def clean_json_output(text: str) -> str:
    """LLM 텍스트에서 순수 JSON 객체 블록만 강제 추출"""
    # 마크다운 기호 1차 제거
    cleaned = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
    cleaned = re.sub(r'^```\s*$', '', cleaned, flags=re.MULTILINE)

    # 첫 번째 '{' 와 마지막 '}' 사이의 문자열만 추출
    start_idx = cleaned.find('{')
    end_idx = cleaned.rfind('}')

    if start_idx != -1 and end_idx != -1:
        return cleaned[start_idx:end_idx + 1]

    return cleaned.strip()


def propose(doc_file, vendor, rules_in, rules_out, sample_dir):
    print(f"[{vendor}] ICD 문서 분석 시작: {doc_file}")

    # 1. 벤더 ICD 문서 로드
    with open(doc_file, "r", encoding="utf-8") as f:
        doc_content = f.read()

    # 2. 표준 카운터 사전 로드 (정확한 표준 매핑 기준)
    dict_path = os.path.join("schema", "counter_dictionary.md")
    dict_content = ""
    if os.path.exists(dict_path):
        with open(dict_path, "r", encoding="utf-8") as f:
            dict_content = f.read()

    # 3. 기존 규칙 병합용 로드 (v1.1 갱신 목적)
    existing_rules = {}
    rule_file_name = f"{vendor.lower()}_rules.json"
    rule_file_path = os.path.join(rules_in, rule_file_name) if rules_in else ""
    if rule_file_path and os.path.exists(rule_file_path):
        with open(rule_file_path, "r", encoding="utf-8") as f:
            existing_rules = json.load(f)
            print(f"기존 규칙 로드 완료: {rule_file_path}")

    # 4. 프롬프트 및 JSON 스키마 강제 구성
    prompt = f"""
    [Standard Dictionary Reference]
    {dict_content}

    [Existing Rules (if any)]
    {json.dumps(existing_rules, indent=2)}

    [Vendor ICD Document to Analyze/Update]
    {doc_content}

    Task: 
    1. Analyze the vendor ICD document based on the standard dictionary.
    2. Create or update the field mapping rules.
    3. Output MUST BE strictly valid JSON format matching the exact structure below.
    4. Do not include markdown formatting or explanations outside the JSON.

    Required JSON Structure:
    {{
      "vendor": "{vendor}",
      "version": "1.1",
      "field_mappings": [
        {{
          "source_path": "Original field name or path in vendor data",
          "target_field": "Standard field name from dictionary",
          "transform": "Transformation type (e.g., 'string', 'multiply_100', 'iso8601_to_kst')",
          "reason": "Detailed logical reason for mapping and transform"
        }}
      ],
      "unmapped_fields": [
        {{
          "source_path": "Field in vendor data not mapped",
          "reason": "Why it is not mapped (e.g., 'No corresponding field found in unified_v1 schema')"
        }}
      ]
    }}
    """

    # 5. LLM API 실제 호출 및 마크다운 정제
    response_text = call_llm_api(prompt)
    cleaned_text = clean_json_output(response_text)

    # 6. JSON 파싱 검증 및 저장
    try:
        actual_llm_response = json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        print(f"JSON 파싱 에러 발생: {e}")
        print(f"원본 출력: {cleaned_text}")
        return

    os.makedirs(rules_out, exist_ok=True)
    out_path = os.path.join(rules_out, rule_file_name)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(actual_llm_response, f, indent=2, ensure_ascii=False)

    print(f"매핑 규칙 JSON 저장 완료: {out_path}")


def validate(rules_dir, input_dir):
    print(f"규칙 자체 검증 시작 - 규칙 경로: {rules_dir}, 입력 경로: {input_dir}")

    if not os.path.exists(rules_dir) or not os.listdir(rules_dir):
        print("검증 실패: rules 디렉터리가 비어 있거나 존재하지 않습니다.")
        return

    # 생성된 모든 규칙 파일 검증
    for rule_file in os.listdir(rules_dir):
        if not rule_file.endswith('.json'):
            continue

        rule_path = os.path.join(rules_dir, rule_file)
        try:
            with open(rule_path, "r", encoding="utf-8") as f:
                rules = json.load(f)

            # 필수 키 존재 여부 확인
            if "field_mappings" not in rules or "unmapped_fields" not in rules:
                print(f"[검증 실패] {rule_file}: 필수 키('field_mappings', 'unmapped_fields') 누락")
                continue

            # 원본 데이터 연관성 단순 대조
            vendor_prefix = rules.get("vendor", "")[0] if rules.get("vendor") else ""
            matched_files = [f for f in os.listdir(input_dir) if f.startswith(vendor_prefix)]

            print(f"[검증 통과] {rule_file} - 논리 구조 정상. 입력 데이터 매칭 {len(matched_files)}건 확인.")

        except json.JSONDecodeError:
            print(f"[검증 실패] {rule_file}: 유효하지 않은 JSON 구조입니다.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="LLM Agent for Rule Generation")
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
        propose(args.doc, args.vendor, args.rules, args.out, args.sample)
    elif args.command == 'validate':
        validate(args.rules, args.input)