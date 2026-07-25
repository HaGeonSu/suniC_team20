agent 실행 방법

Bash에 아래 명령어 입력

# Vender A
CM 레코드 규칙 생성
python agent.py propose --doc docs/VendorA_PMS_Interface_Spec_v1.0.md --vendor VENDOR_A --record_type CM --out rules

PM 레코드 규칙 생성
python agent.py propose --doc docs/VendorA_PMS_Interface_Spec_v1.0.md --vendor VENDOR_A --record_type PM --out rules

FM 레코드 규칙 생성
python agent.py propose --doc docs/VendorA_PMS_Interface_Spec_v1.0.md --vendor VENDOR_A --record_type FM --out rules


# Vender B
CM 레코드 규칙 생성
python agent.py propose --doc docs/VendorB_NBI_ICD_v1.0.md --vendor VENDOR_B --record_type CM --out rules

PM 레코드 규칙 생성
python agent.py propose --doc docs/VendorB_NBI_ICD_v1.0.md --vendor VENDOR_B --record_type PM --out rules

FM 레코드 규칙 생성
python agent.py propose --doc docs/VendorB_NBI_ICD_v1.0.md --vendor VENDOR_B --record_type FM --out rules


# Vender C
CM 레코드 규칙 생성
python agent.py propose --doc docs/VendorC_API_Guide_v1.0.md --vendor VENDOR_C --record_type CM --out rules

PM 레코드 규칙 생성
python agent.py propose --doc docs/VendorC_API_Guide_v1.0.md --vendor VENDOR_C --record_type PM --out rules

FM 레코드 규칙 생성
python agent.py propose --doc docs/VendorC_API_Guide_v1.0.md --vendor VENDOR_C --record_type FM --out rules


