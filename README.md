# Multi-Agent BI System

LLM 기반 BI 질의응답을 실험하기 위한 Streamlit 애플리케이션입니다. 예시 도메인은 LG전자 HE TV 사업부이며, ERP 정형 데이터와 Neo4j Knowledge Graph 이벤트 데이터를 함께 사용해 KPI 조회, 변동 요인 분석, Markdown 보고서 생성을 처리합니다.

이 프로젝트의 핵심은 LLM에게 바로 결론을 쓰게 하지 않는 것입니다. 의도 분류, SQL 조회, Graph-RAG 검색, 후보 요인 검증, 보고서 재구성을 분리하고, 최종 응답에서는 확정 원인이 아니라 데이터 정합성이 확인된 후보 요인과 출처를 제공합니다.

## 주요 기능

- 자연어 질문을 `DataQA` 또는 `ReportGeneration`으로 분류합니다.
- 단순 조회 질문은 ERP SQLite 데이터베이스에 대한 read-only SQL 실행으로 처리합니다.
- 진단형 질문은 KPI 변화량, Driver 변화량, 기대 부호를 비교해 후보 요인을 선별합니다.
- Neo4j Knowledge Graph와 Vector Index에서 관련 외부 이벤트를 찾아 근거로 연결합니다.
- 분석 결과를 재사용해 통합 KPI 보고서를 Markdown으로 생성합니다.

## 아키텍처

```text
User Query
   |
   v
Streamlit App
   |
   v
Intent Classifier
   |
   v
Orchestrator
   |-- DataQA / descriptive ---> Search Agent ---> SQL / Graph / Vector tools
   |-- DataQA / diagnostic ----> Analysis Agent -> Hypothesis + validation + events
   |-- ReportGeneration -------> Report Agent ---> Markdown report
```

오케스트레이터는 의도 분류 결과에 따라 실행 경로를 결정론적으로 선택합니다. 열려 있는 autonomous agent loop를 돌리지 않고, 각 단계의 책임과 입출력을 명확하게 유지하는 구조입니다.

## 에이전트 책임

| 에이전트 | 책임 | 주요 출력 |
| --- | --- | --- |
| Intent Classifier | 사용자 질문에서 서비스 유형, 분석 모드, 데이터 소스, 엔티티를 분류 | `IntentClassification` |
| Search Agent | 단순 조회 질문을 SQL, Graph, Vector 검색으로 라우팅 | 조회 결과와 실행 쿼리 |
| SQL Agent | ERP SQLite 스키마에 대한 read-only SQL 생성 및 실행 | SQL과 테이블형 결과 |
| Graph-RAG Agent | Neo4j 그래프와 Vector Index에서 Driver/Event 근거 검색 | 이벤트 후보, 점수, 출처 |
| Analysis Agent | KPI와 Driver의 변동 방향이 사전 정의된 기대 관계와 맞는지 검증 | 후보 요인과 제외 요인 |
| Report Agent | KPI 스냅샷과 분석 결과를 보고서 형식으로 재구성 | Markdown 보고서 |
| Orchestrator | 의도 분류 결과에 따라 실행 경로 선택 | 최종 응답 payload |

## 검증 방식

진단형 분석 파이프라인은 인과 추론 엔진이 아니라 후보 요인 선별기입니다.

1. 분석 대상 KPI의 QoQ, YoY 변화량을 계산합니다.
2. whitelist 기반 그래프 스키마에서 KPI-Driver 후보를 불러옵니다.
3. ERP 또는 proxy 데이터에서 Driver 변화량을 계산합니다.
4. KPI와 Driver의 변동 방향이 기대 부호와 정합한지 확인합니다.
5. Knowledge Graph에서 관련 Event 근거를 찾아 연결합니다.

임계값 또는 방향성 검증을 통과하지 못한 Driver는 버리지 않고 제외 후보로 남깁니다. 덕분에 최종 결과에서 어떤 후보가 검토되었고 왜 제외되었는지 확인할 수 있습니다.

## 데이터 모델

- ERP 데이터: `erp_database/lge_he_erp.db`
- ERP 스키마 참고: `erp_database/schema.dbml`
- Knowledge Graph 스키마: `knowledge_graph/schema/*.json`
- Neo4j 초기화 스크립트: `scripts/init_neo4j.py`
- 과거 KG 구축 실험: `archive/knowledge_graph/`

런타임 그래프는 KPI, Driver, Event, Dimension 노드를 중심으로 구성됩니다. 현재 앱은 canonical schema와 seed script를 사용하며, 과거 Layer 1-3 구축 실험 코드는 재현성과 추적성을 위해 `archive/`에 보관합니다.

## 기술 스택

- Python, Streamlit
- OpenAI API
- SQLite 기반 ERP 샘플 데이터
- Neo4j 5.x, APOC, Vector Index
- Pydantic 기반 structured output
- pandas / numpy 데이터 처리
- pyvis 그래프 시각화
- Docker Compose 로컬 실행 환경

## 프로젝트 구조

```text
agents/
  analysis/          진단형 분석 파이프라인
  report/            KPI 보고서 생성
  tools/             SQL, Cypher, Vector 검색 도구
  orchestrator.py    의도 기반 라우터
config/              런타임 설정과 환경 변수 해석
docs/                현재 런타임 코드 기준 설계 문서
erp_database/        ERP 샘플 DB와 스키마 참고 문서
intent_classifier/   구조화된 의도 분류 모듈
knowledge_graph/     활성 그래프 스키마와 시각화 도구
scripts/             Neo4j 초기화 스크립트
services/            Streamlit 화면에서 호출하는 서비스 계층
tests/               guard, service contract, UI renderer 테스트
ui/                  Streamlit renderer와 스타일
archive/             과거 KG 구축 파이프라인과 실험 코드
```

## 빠른 시작

### Docker 실행

```bash
cp .env.example .env
# .env 파일에 OPENAI_API_KEY를 설정합니다.

docker compose up -d --build
docker compose exec app python scripts/init_neo4j.py
```

실행 후 아래 주소를 엽니다.

- Streamlit 앱: http://localhost:8501
- Neo4j Browser: http://localhost:7474

기본 Neo4j 계정은 다음과 같습니다.

```text
username: neo4j
password: password123
```

구버전 Docker Compose CLI를 사용하는 환경에서는 `docker compose` 대신 `docker-compose`를 사용하면 됩니다.

### 로컬 Python 실행

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env 파일에 OPENAI_API_KEY를 설정합니다.

docker compose up -d neo4j
python scripts/init_neo4j.py
streamlit run app.py
```

## 설정

앱은 환경 변수에서 런타임 설정을 읽습니다. 기본값은 `config/settings.py`에 정의되어 있습니다.

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 없음 | 의도 분류, SQL 생성, 요약 생성에 필요한 OpenAI API 키 |
| `ERP_DB_PATH` | `erp_database/lge_he_erp.db` | SQLite ERP 데이터베이스 경로 |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j Bolt URI |
| `NEO4J_USER` | `neo4j` | Neo4j 사용자명 |
| `NEO4J_PASSWORD` | `password123` | Neo4j 비밀번호 |
| `NEO4J_DATABASE` | `neo4j` | Neo4j 데이터베이스 이름 |

## 예시 질문

- `2025년 Q3 북미 매출 보여줘`
- `2025년 Q3 영업이익이 왜 하락했는지 분석해줘`
- `최근 물류비와 관련된 외부 이벤트 알려줘`
- `2025년 Q4 통합 KPI 보고서 만들어줘`

## 검증

```bash
python -m unittest tests.test_query_guard tests.test_intent_service tests.test_ui_renderers
python -m compileall .
```

운영 중 로그 확인과 종료는 아래 명령을 사용합니다.

```bash
docker compose logs -f app
docker compose logs -f neo4j
docker compose down
```
