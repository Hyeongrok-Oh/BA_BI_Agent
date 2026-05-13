"""
Orchestrator - Intent 기반 Agent 라우팅

역할:
- Intent Classifier 결과를 받아 적절한 Agent로 라우팅
- Data Q&A Service: Descriptive → Search Agent, Diagnostic → Analysis Agent
- Report Generation Service: Report Agent
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

from config.settings import get_erp_db_path
from .base import AgentContext
from .search_agent import SearchAgent
from .analysis import AnalysisAgent
from .report import ReportAgent, ReportRequest, ReportType


class ServiceType(Enum):
    """서비스 유형"""
    DATA_QA = "data_qa"
    REPORT_GENERATION = "report_generation"


class AnalysisMode(Enum):
    """분석 모드"""
    DESCRIPTIVE = "descriptive"  # 단순 조회
    DIAGNOSTIC = "diagnostic"    # 원인 분석


class SubIntent(Enum):
    """하위 의도"""
    INTERNAL_DATA = "internal_data"   # ERP 데이터
    EXTERNAL_DATA = "external_data"   # Knowledge Graph
    HYBRID = "hybrid"                 # 둘 다


@dataclass
class IntentResult:
    """Intent Classifier 결과"""
    service_type: str       # data_qa, report_generation
    analysis_mode: str      # descriptive, diagnostic
    sub_intent: str         # internal_data, external_data, hybrid
    query: str              # 원본 질문
    entities: Dict = None   # 추출된 엔티티 (period, region, company 등)


class Orchestrator:
    """Intent 기반 Agent 라우터"""

    def __init__(self, api_key: str = None, db_path: str = None):
        self.api_key = api_key
        self.db_path = db_path or get_erp_db_path()

        # Agent들 초기화 (lazy loading)
        self._search_agent = None
        self._analysis_agent = None
        self._report_agent = None

    @property
    def search_agent(self) -> SearchAgent:
        if self._search_agent is None:
            self._search_agent = SearchAgent(self.api_key, self.db_path)
        return self._search_agent

    @property
    def analysis_agent(self) -> AnalysisAgent:
        if self._analysis_agent is None:
            self._analysis_agent = AnalysisAgent(self.api_key, self.db_path)
        return self._analysis_agent

    @property
    def report_agent(self) -> ReportAgent:
        if self._report_agent is None:
            self._report_agent = ReportAgent(self.api_key, self.db_path)
        return self._report_agent

    def route(self, intent_result: Dict, verbose: bool = True) -> Dict[str, Any]:
        """
        Intent 결과에 따라 적절한 Agent로 라우팅

        Args:
            intent_result: Intent Classifier 결과
                {
                    "service_type": "data_qa" | "report_generation",
                    "analysis_mode": "descriptive" | "diagnostic",
                    "sub_intent": "internal_data" | "external_data" | "hybrid",
                    "query": "원본 질문",
                    "extracted_entities": {...}
                }
            verbose: 상세 출력

        Returns:
            Agent 실행 결과
        """
        service_type = intent_result.get("service_type", "data_qa")
        analysis_mode = intent_result.get("analysis_mode", "descriptive")
        sub_intent = intent_result.get("sub_intent", "internal_data")
        is_event_query = intent_result.get("is_event_query", False)
        query = intent_result.get("query", "")
        entities = intent_result.get("extracted_entities", {}) or {}

        if verbose:
            print(f"\n[Orchestrator] 라우팅 시작")
            print(f"  서비스: {service_type}")
            print(f"  분석 모드: {analysis_mode}")
            print(f"  데이터 소스: {sub_intent}")
            print(f"  이벤트 질문: {is_event_query}")
            print(f"  질문: {query[:50]}...")

        # 서비스 유형에 따른 라우팅
        if service_type == "report_generation":
            return self._route_to_report(query, entities, verbose)
        else:
            return self._route_to_qa(query, analysis_mode, sub_intent, is_event_query, entities, verbose)

    def _route_to_qa(
        self,
        query: str,
        analysis_mode: str,
        sub_intent: str,
        is_event_query: bool,
        entities: Dict,
        verbose: bool
    ) -> Dict[str, Any]:
        """Data Q&A 서비스 라우팅"""

        # 메타데이터 구성
        period = entities.get("period", {"year": 2024, "quarter": 4})
        region = entities.get("region")
        if isinstance(region, list):
            region = region[0] if region else None

        # 분석 모드에 따른 Agent 선택
        if analysis_mode == "diagnostic":
            # 원인 분석 → Analysis Agent
            if verbose:
                print(f"\n[라우팅] Analysis Agent (원인 분석)")

            result = self.analysis_agent.analyze(
                question=query,
                period=period,
                region=region,
                company=entities.get("company", "LGE"),
                verbose=verbose
            )

            return {
                "agent": "analysis_agent",
                "mode": "diagnostic",
                "question": query,
                "summary": result.summary,
                "details": result.details,
                "validated_count": len(result.validated_hypotheses)
            }

        else:
            # 단순 조회 → Search Agent
            if verbose:
                print(f"\n[라우팅] Search Agent (데이터 조회)")

            # 데이터 소스 결정 (Intent Classifier 결과 사용)
            if is_event_query:
                source = "vector"
                if verbose:
                    print(f"  → 이벤트 질문 감지: Vector Search 사용")
            elif sub_intent == "external_data":
                source = "graph"
            elif sub_intent == "internal_data":
                source = "sql"
            else:
                source = None  # Search Agent가 자동 결정

            context = AgentContext(
                query=query,
                metadata={
                    "source": source,
                    "period": period,
                    "region": region,
                    "top_k": 5  # 벡터 검색시 상위 5개
                }
            )

            result = self.search_agent.run(context)

            return {
                "agent": "search_agent",
                "mode": "descriptive",
                "question": query,
                "source": result.get("source"),
                "data": result.get("data"),
                "query_used": result.get("query"),
                "success": result.get("success", False),
                "is_event_query": is_event_query
            }

    def _route_to_report(
        self,
        query: str,
        entities: Dict,
        verbose: bool
    ) -> Dict[str, Any]:
        """Report Generation 서비스 라우팅"""

        if verbose:
            print(f"\n[라우팅] Report Agent (보고서 생성)")

        period = entities.get("period", {"year": 2024, "quarter": 4})
        region = entities.get("region")
        if isinstance(region, list):
            region = region[0] if region else None

        request = ReportRequest(
            report_type=ReportType.INTEGRATED_KPI_REPORT,
            year=period.get("year", 2025),
            quarter=period.get("quarter", 4),
            region=region,
            company=entities.get("company", "LGE"),
        )
        report = self.report_agent.generate(request, verbose=verbose)

        return {
            "agent": "report_agent",
            "mode": "report",
            "title": report.get("title"),
            "period": report.get("period"),
            "sections_count": len(report.get("sections", [])),
            "summary": report.get("summary"),
            "markdown": report.get("markdown")
        }

    def process_query(self, query: str, verbose: bool = True) -> Dict[str, Any]:
        """
        질문을 직접 처리 (Intent Classification 포함)

        간단한 키워드 기반 Intent 분류 후 라우팅
        실제 운영에서는 Intent Classifier 모듈 사용 권장
        """
        # 간단한 Intent 분류
        intent = self._simple_classify(query)

        if verbose:
            print(f"\n[Intent 분류 결과]")
            print(f"  서비스: {intent['service_type']}")
            print(f"  분석 모드: {intent['analysis_mode']}")

        return self.route(intent, verbose)

    def _simple_classify(self, query: str) -> Dict:
        """
        키워드 기반 Intent 분류

        Returns:
            service_type: data_qa | report_generation
            analysis_mode: descriptive | diagnostic
            sub_intent: internal_data | external_data | hybrid
            is_event_query: True면 Vector Search 사용
        """
        import re

        # ===== 1. 서비스 유형 =====
        report_keywords = ["보고서", "리포트", "report", "요약본", "브리핑"]
        if any(kw in query for kw in report_keywords):
            service_type = "report_generation"
        else:
            service_type = "data_qa"

        # ===== 2. 내부 데이터 키워드 (ERP/SQL) =====
        # 구체적인 데이터 항목만 포함 (범용 표현 제외)
        internal_keywords = [
            # 재무 지표
            "매출", "원가", "비용", "수량", "실적", "금액", "합계", "총",
            "영업이익", "순이익", "마진", "수익",
            # 구체적 비용 항목
            "물류비", "재료비", "관세비", "운송비", "오버헤드",
            # 원가/가격 코드
            "MAT", "LOG", "TAR", "OH",
            "ZPR0", "ZPRO", "K007", "ZMDF",
            # 가격 조건
            "할인", "MDF", "Price Protection", "PP",
            # 기간 표현
            "Q1", "Q2", "Q3", "Q4", "분기", "월별", "연간",
            # 구체적 조회 표현
            "현황", "얼마"
            # 제외: "알려줘", "조회", "검색" - 범용 표현이라 이벤트 질문에도 사용됨
        ]

        # ===== 3. 이벤트/외부 키워드 (Vector/Graph) =====
        event_keywords = [
            # 이벤트 직접 언급
            "이벤트", "사건", "뉴스",
            # 질문 패턴
            "무슨 일", "어떤 일", "무슨일", "어떤일",
            # 외부 요인
            "동향", "트렌드", "이슈", "상황",
            # 시간 표현 (최근 이벤트)
            "최근", "요즘", "근래"
        ]

        # ===== 4. 분석 모드 키워드 =====
        diagnostic_keywords = [
            "왜", "원인", "이유", "분석",
            "하락", "증가", "감소", "변동",
            "영향", "때문"
        ]

        # ===== 키워드 매칭 =====
        has_internal = any(kw in query for kw in internal_keywords)
        has_event = any(kw in query for kw in event_keywords)
        has_diagnostic = any(kw in query for kw in diagnostic_keywords)

        # ===== 5. 분석 모드 결정 =====
        # diagnostic: 원인 분석 필요 (왜? 분석해줘)
        # descriptive: 단순 조회 (현황, 금액)
        if has_diagnostic and not has_event:
            # "왜 하락했어?" → diagnostic
            # But "최근 이슈가 뭐야?" → descriptive (이벤트 조회)
            analysis_mode = "diagnostic"
        else:
            analysis_mode = "descriptive"

        # ===== 6. 데이터 소스 & 이벤트 질문 결정 =====
        # 우선순위: 내부 데이터 키워드가 있으면 SQL
        if has_internal:
            sub_intent = "internal_data"
            is_event_query = False
        elif has_event:
            sub_intent = "external_data"
            is_event_query = True
        else:
            # 기본값: 내부 데이터
            sub_intent = "internal_data"
            is_event_query = False

        # ===== 7. 엔티티 추출 =====
        entities = {}

        # 연도 추출 (기본값: 2025)
        year_match = re.search(r'(\d{4})년?', query)
        year = int(year_match.group(1)) if year_match else 2025

        # 분기 추출 (기본값: 4)
        quarter_match = re.search(r'(\d)분기|Q(\d)', query, re.IGNORECASE)
        if quarter_match:
            quarter = int(quarter_match.group(1) or quarter_match.group(2))
        else:
            quarter = 4

        entities["period"] = {"year": year, "quarter": quarter}

        # 지역 추출
        region_map = {
            "북미": "NA", "NA": "NA", "미국": "NA",
            "유럽": "EU", "EU": "EU",
            "한국": "KR", "KR": "KR", "국내": "KR",
            "아시아": "ASIA", "ASIA": "ASIA"
        }
        for keyword, region_code in region_map.items():
            if keyword in query:
                entities["region"] = region_code
                break

        return {
            "service_type": service_type,
            "analysis_mode": analysis_mode,
            "sub_intent": sub_intent,
            "query": query,
            "extracted_entities": entities,
            "is_event_query": is_event_query
        }
