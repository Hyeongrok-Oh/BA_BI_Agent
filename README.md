# Multi-Agent BI System

본 프로젝트는 LLM(대규모 언어 모델) 기반 비즈니스 인텔리전스(BI) 질의응답 파이프라인을 검증하기 위한 Streamlit 애플리케이션입니다. LG전자 HE 사업부 도메인을 예시로 사용하며, ERP 정형 데이터와 Neo4j Knowledge Graph 이벤트 데이터를 통합하여 KPI 조회, 변동 요인 분석, Markdown 기반 보고서 생성을 수행합니다.

시스템의 핵심 설계 목표는 LLM의 환각(Hallucination)을 통제하고 분석 과정의 추적 가능성을 확보하는 것입니다. 이를 위해 의도 분류, SQL 기반 조회, Graph-RAG 검색, 후보 요인 검증, 보고서 재구성 단계를 독립적인 모듈로 분리했습니다. 최종 응답은 단정적인 인과 결론을 배제하고, 데이터 정합성 검증을 통과한 후보 요인과 출처를 제공합니다.

## 주요 기능

- 자연어 의도 분류: 사용자 질의를 `DataQA`와 `ReportGeneration`으로 분류하고, 분석 모드와 주요 엔티티를 추출합니다.
- 안전한 데이터 조회: 단순 조회 질의는 ERP SQLite 데이터베이스에 대한 read-only SQL 생성 및 실행으로 처리합니다.
- 진단형 분석 파이프라인: KPI와 Driver의 변화량, 임계값, 기대 부호를 비교하여 정합한 후보 요인을 선별합니다.
- Graph-RAG 기반 근거 연결: Neo4j Knowledge Graph와 Vector Index를 활용해 외부 이벤트 데이터를 검색하고 분석 근거로 연결합니다.
- 보고서 자동 생성: KPI 스냅샷과 분석 결과를 재구성하여 Markdown 형식의 보고서를 생성합니다.

## 시스템 아키텍처

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
   |-- [Descriptive] DataQA ----> Search Agent ---> SQL / Graph / Vector Tools
   |-- [Diagnostic] DataQA -----> Analysis Agent -> Hypothesis + Validation + Events
   |-- ReportGeneration --------> Report Agent ---> Markdown Report
```

오케스트레이터는 의도 분류 결과에 따라 사전 정의된 실행 경로를 결정론적으로 선택합니다. 개방형 autonomous agent loop를 사용하지 않고, 각 단계의 책임과 입출력 계약을 명확히 제한하여 실행 흐름의 예측 가능성을 확보합니다.

## 에이전트 책임 정의

| 에이전트 | 책임 | 주요 출력 |
| --- | --- | --- |
| Intent Classifier | 사용자 질의에서 서비스 유형, 분석 모드, 데이터 소스, 엔티티를 추출 | `IntentClassification` 객체 |
| Search Agent | 단순 조회 질의를 SQL, Graph, Vector 검색 도구로 라우팅 | 조회 결과, 실행 쿼리 |
| SQL Agent | ERP SQLite 스키마 기반 read-only SQL 생성 및 실행 | SQL 구문, 테이블형 결과 |
| Graph-RAG Agent | Neo4j 그래프와 Vector Index 기반 Driver/Event 탐색 | 이벤트 후보, 점수, 출처 |
| Analysis Agent | KPI와 Driver의 변동 방향에 대한 정합성 검증 | 유효 후보 요인, 제외 요인 |
| Report Agent | KPI 현황과 분석 결과를 문서 형식으로 재구성 | Markdown 보고서 |
| Orchestrator | 의도 분류 결과에 따른 파이프라인 제어 | 최종 응답 payload |

## 검증 파이프라인

진단형 분석 파이프라인은 엄밀한 인과 추론 엔진이 아니라, 데이터 기반 후보 요인 선별기 역할을 수행합니다.

1. 변화량 산출: 분석 대상 KPI의 전분기 대비(QoQ) 및 전년 동기 대비(YoY) 변화량을 계산합니다.
2. 후보군 추출: whitelist 기반 그래프 스키마에서 분석 대상 KPI와 연결된 Driver 후보군을 로드합니다.
3. 데이터 대조: ERP 또는 proxy 데이터를 참조하여 각 Driver의 실제 변화량을 산출합니다.
4. 방향성 검증: KPI와 Driver의 변동 방향이 사전 정의된 기대 부호와 일치하는지 확인합니다.
5. 이벤트 연결: Knowledge Graph를 탐색하여 관련 Event 근거를 연결합니다.
6. 추적성 확보: 임계값 미달 또는 방향성 불일치로 탈락한 Driver를 `excluded_drivers`에 기록합니다.

이 구조는 최종 결과에서 어떤 후보가 채택되었는지뿐 아니라, 어떤 후보가 검토 후 제외되었는지도 확인할 수 있도록 설계되었습니다.

## 데이터 모델

- ERP 데이터: `erp_database/lge_he_erp.db`
- ERP 스키마 명세: `erp_database/schema.dbml`
- Knowledge Graph 스키마: `knowledge_graph/schema/*.json`
- Neo4j 초기화 스크립트: `scripts/init_neo4j.py`
- 과거 KG 구축 실험 코드: `archive/knowledge_graph/`

런타임 그래프는 KPI, Driver, Event, Dimension 노드를 중심으로 구성됩니다. 현재 애플리케이션은 표준화된 스키마와 초기화 스크립트를 사용하며, 과거 Layer 1-3 구축 파이프라인은 재현성과 추적성을 위해 `archive/` 디렉터리에 보관합니다.

## 기술 스택

| 영역 | 기술 |
| --- | --- |
| Application & UI | Python, Streamlit |
| LLM Interface | OpenAI API |
| Structured Output | Pydantic |
| Database | SQLite, Neo4j 5.x |
| Graph Runtime | APOC, Neo4j Vector Index |
| Data Processing | pandas, numpy |
| Visualization | pyvis |
| Infrastructure | Docker Compose |

## 프로젝트 구조

```text
agents/
  analysis/          # 진단형 분석 파이프라인 모듈
  report/            # KPI 보고서 생성 모듈
  tools/             # SQL, Cypher, Vector 검색 도구
  orchestrator.py    # 의도 기반 라우터
config/              # 런타임 설정 및 환경 변수 관리
docs/                # 아키텍처 및 시스템 설계 문서
erp_database/        # ERP 샘플 데이터베이스 및 스키마 명세
intent_classifier/   # 사용자 의도 분류 모듈
knowledge_graph/     # 활성 그래프 스키마 및 시각화 도구
scripts/             # Neo4j 초기화 스크립트
services/            # Streamlit UI 연동 서비스 계층
tests/               # Guardrail, service contract, UI 테스트
ui/                  # Streamlit renderer 및 스타일 리소스
archive/             # 구버전 KG 구축 파이프라인 및 실험 코드
```

## 빠른 시작

### Docker 환경 실행

```bash
# 환경 변수 파일 복사 및 OPENAI_API_KEY 설정
cp .env.example .env

# 컨테이너 빌드 및 백그라운드 실행
docker compose up -d --build

# Neo4j 그래프 데이터베이스 초기화
docker compose exec app python scripts/init_neo4j.py
```

실행 완료 후 아래 주소로 접속합니다.

- Streamlit App: http://localhost:8501
- Neo4j Browser: http://localhost:7474
- Neo4j 기본 계정: `neo4j` / `password123`

구버전 Docker Compose CLI를 사용하는 환경에서는 `docker compose` 대신 `docker-compose` 명령어를 사용합니다.

### 로컬 가상환경 실행

```bash
# 가상환경 생성 및 활성화
python -m venv .venv
source .venv/bin/activate

# 패키지 의존성 설치
pip install -r requirements.txt

# 환경 변수 파일 복사 및 OPENAI_API_KEY 설정
cp .env.example .env

# Neo4j 컨테이너 실행 및 DB 초기화
docker compose up -d neo4j
python scripts/init_neo4j.py

# Streamlit 앱 실행
streamlit run app.py
```

Windows 환경에서는 가상환경 활성화 명령을 `.venv\Scripts\activate`로 변경합니다.

## 런타임 설정

애플리케이션은 `.env` 파일과 환경 변수를 통해 구동됩니다. 기본값은 `config/settings.py`에 정의되어 있습니다.

| 변수명 | 기본값 | 설명 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 없음 | 의도 분류, SQL 생성, 보고서 생성을 위한 OpenAI API 키 |
| `ERP_DB_PATH` | `erp_database/lge_he_erp.db` | 로컬 SQLite ERP 데이터베이스 경로 |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j 데이터베이스 접속 URI |
| `NEO4J_USER` | `neo4j` | Neo4j 인증 사용자명 |
| `NEO4J_PASSWORD` | `password123` | Neo4j 인증 비밀번호 |
| `NEO4J_DATABASE` | `neo4j` | Neo4j 대상 데이터베이스 이름 |

## 활용 예시

시스템 동작 확인을 위해 다음 질의를 사용할 수 있습니다.

- 단순 조회: `2025년 Q3 북미 지역 매출액 보여줘`
- 진단 분석: `2025년 Q3 영업이익이 하락한 요인을 분석해줘`
- Graph-RAG 검색: `최근 물류비 상승과 관련된 외부 이벤트나 이슈가 있어?`
- 보고서 생성: `2025년 Q4 기준 통합 KPI 보고서 작성해줘`

## 테스트 및 운영 관리

단위 테스트와 컴파일 검증은 아래 명령으로 실행합니다.

```bash
# 주요 모듈 단위 테스트 실행
python -m unittest tests.test_query_guard tests.test_intent_service tests.test_ui_renderers

# Python 구문 오류 검증
python -m compileall .
```

컨테이너 로그 확인과 종료 명령은 다음과 같습니다.

```bash
docker compose logs -f app
docker compose logs -f neo4j
docker compose down
```

## 프로젝트 범위

이 저장소는 전체 엔터프라이즈 BI 플랫폼이 아니라, LLM 기반 BI 아키텍처를 검증하기 위한 focused prototype입니다.

- 명시적인 라우팅을 사용하여 실행 경로를 예측 가능하게 유지합니다.
- SQL, graph path, source URL 등 검증 가능한 메타데이터를 가능한 범위에서 보존합니다.
- 근거 없는 인과 주장을 피하고 후보 요인 중심으로 응답합니다.
- 과거 연구 및 구축 스크립트는 런타임 경로와 분리하여 `archive/`에 보관합니다.
- 회귀 가능성이 큰 query guard, service contract, UI renderer를 중심으로 테스트를 구성합니다.
