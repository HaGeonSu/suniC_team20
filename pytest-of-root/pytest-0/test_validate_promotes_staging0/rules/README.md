# 규칙 저장소 운영 구조

`pipeline.py transform --rules rules`는 다음 규칙만 실행에 사용한다.

```text
rules/
├── active/      # 검증과 회귀 테스트를 통과한 실행 규칙
├── staging/     # Agent가 새로 만든 후보 규칙
├── artifacts/   # prompt snapshot, 분석 보고서, adapter profile 등 보조 JSON
└── archive/     # 교체된 이전 규칙
```

## 활성화 정책

1. Agent는 새 규칙을 `staging/`에 먼저 쓴다.
2. 규칙 스키마 검증, 샘플 검증, v1.0/v1.1 회귀 테스트를 수행한다.
3. 성공한 규칙만 `active/`에 원자적으로 교체한다.
4. 동일한 Vendor/record type/match signature의 이전 규칙은 `archive/`로 이동한다.
5. `active/` 안에 동일 signature 규칙이 둘 이상 있으면 Pipeline은 전역 오류로 중단한다.

`active/`가 없는 예전 저장소는 하위 호환을 위해 전달된 규칙 디렉터리 자체를 읽는다.
`active/`가 존재하면 `staging/`, `artifacts/`, `archive/`의 JSON은 절대 실행 규칙으로 읽지 않는다.
