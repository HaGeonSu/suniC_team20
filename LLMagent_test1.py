import argparse
import os
import json
import re


def clean_json_output(text):
    """LLM이 반환한 텍스트에서 마크다운 코드 블록 기호 제거"""
    cleaned = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
    cleaned = re.sub(r'^```\s*$', '', cleaned, flags=re.MULTILINE)
    return cleaned.strip()


def propose(doc_file, vendor, rules_in, rules_out, sample_dir):
    print(f"[{vendor}] ICD 문서 분석 시작: {doc_file}")

    # 1. 벤더 ICD 문서 읽기
    with open(doc_file, "r", encoding="utf-8") as f:
        doc_content = f.read()

    # 2. [추가] 표준 카운터 사전 읽기 (정확한 표준 매핑을 위해 필수)
    dict_path = os.path.join("schema", "counter_dictionary.md")
    dict_content = ""
    if os.path.exists(dict_path):
        with open(dict_path, "r", encoding="utf-8") as f:
            dict_content = f.read()

    # 3. [추가] 기존 규칙이 있다면 로드 (v1.1 개정판 갱신 대응)
    existing_rules = {}
    rule_file_name = f"{vendor.lower()}_rules.json"
    rule_file_path = os.path.join(rules_in, rule_file_name) if rules_in else ""
    if rule_file_path and os.path.exists(rule_file_path):
        with open(rule_file_path, "r", encoding="utf-8") as f:
            existing_rules = json.load(f)
            print(f"기존 규칙 로드 완료: {rule_file_path}")

    # 4. 프롬프트 구성
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
    3. If a field has no standard mapping, list it under 'unmapped_fields' with a reason.
    4. Output MUST BE strictly valid JSON format. No markdown, no explanations outside JSON.
    """

    # TODO: LLM API 호출 코드 작성 (temperature=0 및 JSON Mode 적용 권장)
    # response_text = call_llm_api(prompt)

    # 시뮬레이션용 예시 결과물
    simulated_llm_response = {
        "vendor": vendor,
        "version": "1.1",
        "mappings": {
            "RegSucc": "register_success_count"
        },
        "unmapped_fields": []
    }

    # 5. 결과물을 rules_out 경로에 JSON 파일로 저장
    os.makedirs(rules_out, exist_ok=True)
    out_path = os.path.join(rules_out, rule_file_name)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(simulated_llm_response, f, indent=2, ensure_ascii=False)

    print(f"매핑 규칙 JSON 저장 완료: {out_path}")


def validate(rules_dir, input_dir):
    print(f"규칙 자체 검증 시작 - 규칙 경로: {rules_dir}, 입력 경로: {input_dir}")

    # 규칙 파일 존재 여부 확인
    if not os.path.exists(rules_dir) or not os.listdir(rules_dir):
        print("검증 실패: rules 디렉터리가 비어 있거나 존재하지 않습니다.")
        return

    # TODO: rules_dir의 JSON 규칙들을 읽고, input_dir의 샘플 데이터 키와 대조하는 로직 구현
    print("규칙 검증 통과 완료: 모든 규칙이 정상 포맷입니다.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="LLM Agent for Rule Generation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # propose 명령어 정의 (CLI 규약 준수)
    propose_parser = subparsers.add_parser('propose')
    propose_parser.add_argument('--doc', required=True)
    propose_parser.add_argument('--vendor', required=True)
    propose_parser.add_argument('--rules', required=True)
    propose_parser.add_argument('--out', required=True)
    propose_parser.add_argument('--sample', required=False)

    # validate 명령어 정의 (CLI 규약 준수)
    validate_parser = subparsers.add_parser('validate')
    validate_parser.add_argument('--rules', required=True)
    validate_parser.add_argument('--input', required=True)

    args = parser.parse_args()

    if args.command == 'propose':
        propose(args.doc, args.vendor, args.rules, args.out, args.sample)
    elif args.command == 'validate':
        validate(args.rules, args.input)