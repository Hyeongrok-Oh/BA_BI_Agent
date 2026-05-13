# Multi-Agent BI System

LG전자 HE(Home Entertainment) TV 사업부 도메인을 예시로, ERP 정형 데이터와 Knowledge Graph 이벤트 데이터를 결합해 KPI 변동을 분석하는 AI BI 프로젝트입니다.

핵심 목표는 LLM이 바로 결론을 쓰게 하는 것이 아니라, 구조화된 에이전트 파이프라인 안에서 조회, 후보 요인 선별, 이벤트 매칭, 보고서 생성을 분리하는 것입니다. 최종 응답은 인과를 단정하지 않고, 데이터 정합성이 확인된 후보 요인과 출처를 제시합니다.

## Architecture

```text
User Query
   |
   v
Intent Classifier
   |-- DataQA / descriptive ----> Search Agent ----> SQL / Graph / Vector tools
   |-- DataQA / diagnostic -----> Analysis Agent --> SQL + Graph-RAG evidence
   |-- ReportGeneration --------> Report Agent ----> Analysis outputs reformatted
   |
   v
Orchestrator + AgentContext
```

## Agents

| Agent | Responsibility | Output |
| --- | --- | --- |
| Intent Classifier | 사용자 질의를 `DataQA` 또는 `ReportGeneration`으로 분류하고 기간, 지역, KPI를 추출 | `IntentClassification` |
| Search Agent | descriptive 질의를 SQL, Graph, Vector 검색으로 라우팅 | 조회 결과, 실행 쿼리 |
| SQL Agent | ERP SQLite Star Schema에 대한 Text-to-SQL 생성 및 읽기 전용 실행 | SQL, DataFrame/JSON |
| Graph-RAG Agent | Driver/Event 후보를 그래프 및 벡터 검색으로 매칭 | 이벤트 후보, score, source |
| Analysis Agent | KPI 변동과 Driver 변동의 방향 정합성을 검증 | 후보 요인, 제외 요인, 근거 |
| Report Agent | 새로운 분석 없이 Analysis Agent 결과를 보고서 형식으로 재구성 | Markdown report |
| Orchestrator | Intent 결과에 따라 결정론적으로 Agent 호출 경로를 선택 | 최종 응답 |

## Design Choices

- **Structured contracts first**: Intent 결과와 Agent 간 전달 데이터는 Pydantic/dataclass 기반 구조로 다룹니다.
- **Read-only query execution**: LLM이 생성한 SQL/Cypher는 guard를 통과해야 실행됩니다.
- **Deterministic validation**: 후보 요인은 회귀/인과 추론이 아니라 KPI와 Driver의 방향 정합성 기준으로 선별합니다.
- **No causal overclaiming**: 응답과 보고서는 "원인이다"가 아니라 "정합한 방향으로 함께 움직였다"는 표현을 사용합니다.
- **Small runtime surface**: 실험용 Knowledge Graph 구축 스크립트는 `archive/`로 분리했고, 실행 경로는 5-Agent 파이프라인 중심으로 유지합니다.

## Implementation Notes

The Streamlit entrypoint is intentionally kept thin. `app.py` owns application composition, session state, and user flow. Rendering details live in `ui/`, and backend workflow coordination lives in `services/`. This keeps the project readable during review: a reviewer can inspect routing in one place, UI fragments in another, and the agent pipeline without stepping through page-level HTML or CSS.

The diagnostic result view is split into small renderers under `ui/diagnostic/` because it has several independent sections: KPI movement, hypothesis generation, validation details, event evidence, and graph visualization. The split is deliberately pragmatic; these are plain functions rather than a component framework because the project only needs a focused Streamlit interface.

## Runtime Structure

```text
agents/
  analysis/          diagnostic analysis pipeline
  report/            integrated KPI report agent
  tools/             SQL, Cypher, vector search tools
  orchestrator.py    deterministic router
config/              environment-aware runtime settings
intent_classifier/   structured intent classifier
knowledge_graph/     runtime schema/config/visualizer
services/            app-facing service layer
ui/                  Streamlit renderers and global styles
scripts/             Neo4j initialization
tests/               focused contract and guard tests
archive/             historical KG build pipeline and experiments
```

## Quick Start

```bash
cp .env.example .env
# edit OPENAI_API_KEY and Neo4j settings if needed

docker-compose up -d
docker exec bi-app python scripts/init_neo4j.py
```

Then open:

- Streamlit app: http://localhost:8501
- Neo4j Browser: http://localhost:7474

Local Python execution is also supported:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Example Questions

- `2025년 Q3 북미 매출 보여줘`
- `2025년 Q3 영업이익이 왜 하락했는지 분석해줘`
- `최근 물류비와 관련된 외부 이벤트 알려줘`
- `2025년 Q4 통합 KPI 보고서 만들어줘`

## Verification

```bash
python -m unittest tests.test_query_guard tests.test_intent_service
python -m compileall .
```

## Project Boundaries

This repository intentionally does not try to be a full enterprise BI platform. It focuses on a practical AI/LLM architecture that demonstrates:

- explicit routing instead of opaque dynamic agent loops,
- source-aware analysis instead of unsupported causal claims,
- small and inspectable modules instead of broad framework abstraction,
- enough tests to protect the core safety and routing contracts.
