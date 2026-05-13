# Thesis System Design

이 문서는 현재 런타임 코드 기준의 설계 요약이다. 과거 Knowledge Graph 구축 실험과 수집 파이프라인은 `archive/`에 보관하고, 실행 경로는 5개 에이전트와 중앙 오케스트레이터로 제한한다.

## 1. Scope

본 프로젝트는 LG전자 HE TV 사업부 도메인을 예시로 사용해, 사용자의 자연어 질의를 구조화된 분석 결과 또는 보고서로 변환하는 Multi-Agent BI 시스템을 구현한다.

시스템은 인과관계를 단정하지 않는다. 대신 KPI와 후보 Driver가 사전 정의된 방향 관계와 일관되게 움직였는지 확인하고, 관련 외부 Event를 출처와 함께 제시한다.

## 2. Agent Pipeline

```text
User Query
  -> Intent Classifier
  -> Orchestrator
      -> Search Agent       descriptive DataQA
      -> Analysis Agent     diagnostic DataQA
      -> Report Agent       report generation
```

## 3. Agent Responsibilities

### Intent Classifier

사용자 질의를 `DataQA`와 `ReportGeneration`으로 분류한다. `DataQA`는 다시 `descriptive`와 `diagnostic`으로 나뉜다. 출력은 `IntentClassification` 스키마를 따르며, 기간, 지역, KPI, Driver, confidence, clarifying question을 포함한다.

### SQL Agent

ERP SQLite Star Schema를 조회한다. SQL 생성은 LLM이 수행할 수 있지만, 실행 전 read-only guard를 통과해야 한다. 결과는 SQL 원문과 함께 후속 에이전트로 전달된다.

### Graph-RAG Agent

Neo4j Knowledge Graph와 Vector Index를 사용해 Driver와 관련된 Event 후보를 찾는다. Event는 score, source URL, graph path metadata와 함께 반환된다.

### Analysis Agent

KPI 변동과 Driver 변동의 방향 정합성을 검증한다. 검증 기준은 whitelist, threshold, QoQ/YoY 변화율, expected sign이다. 결과는 "확정 원인"이 아니라 "데이터 정합성이 확인된 후보 요인"이다.

### Report Agent

새로운 분석을 수행하지 않는다. 주요 KPI snapshot을 만든 뒤 유의미한 변동 KPI에 대해 Analysis Agent 결과를 재사용하고, 이를 경영진 보고서 형태의 Markdown으로 재구성한다.

## 4. Orchestration

`Orchestrator`는 Intent 결과에 따라 결정론적으로 라우팅한다.

- `DataQA + descriptive`: Search Agent
- `DataQA + diagnostic`: Analysis Agent
- `ReportGeneration`: Report Agent

각 단계는 `AgentContext`와 명시적인 metadata를 통해 필요한 정보만 전달한다. 자동 백트래킹이나 무한 재시도 루프는 두지 않는다. 결과가 부족하면 임계값을 완화하지 않고, 정합한 후보를 찾지 못했다고 보고한다.

## 5. Runtime Data

- ERP: `erp_database/lge_he_erp.db`
- ERP schema reference: `erp_database/schema.dbml`
- Knowledge Graph schema: `knowledge_graph/schema/*.json`
- Neo4j seed script: `scripts/init_neo4j.py`

## 6. Guardrails

- LLM structured output for intent classification
- SQL/Cypher read-only guards
- KPI/Driver whitelist validation
- Deterministic threshold and direction checks
- No causal language in final analysis/report prompts
- Source-preserving report generation

## 7. What Is Archived

`archive/knowledge_graph/layer1~3` contains historical KG construction scripts, event extraction experiments, and raw build utilities. They are kept for research traceability but are not part of the runtime app.
