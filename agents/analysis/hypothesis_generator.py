"""
Hypothesis Generator Agent - Graph-Based 가설 생성 에이전트 (V3 Schema + Whitelist)

역할:
- LLM을 활용한 KPI 식별 (Neo4j KPI 목록 기반)
- Knowledge Graph에서 KPI 관련 모든 Driver 조회 (Whitelist 기반)
- Driver → Hypothesis 직접 변환
- Status 및 Confidence 기반 신뢰도 정렬
- expected_polarity를 기본 방향으로 사용, 실제 polarity로 보정
"""

from typing import Dict, Any, List, Optional, Literal
from dataclasses import dataclass, field
from pydantic import BaseModel, Field

from ..base import BaseAgent, AgentContext
from ..tools import GraphExecutor


# =============================================================================
# LLM 기반 KPI 식별을 위한 Pydantic 모델
# =============================================================================

class KPIExtraction(BaseModel):
    """사용자 질문에서 분석 대상 KPI 추출"""
    kpi_id: Literal[
        "매출", "판매량", "영업이익", "영업이익률", "매출총이익률",
        "OLED매출", "플랫폼매출", "평균판매가", "프리미엄믹스",
        "매출원가", "판관비", "재고리스크"
    ] = Field(
        description="분석 대상 KPI. Neo4j Knowledge Graph에 정의된 12개 KPI 중 하나"
    )
    reasoning: str = Field(
        description="해당 KPI를 선택한 이유 (질문의 어떤 부분에서 추론했는지)"
    )


# Neo4j KPI 정의 (LLM 프롬프트용)
NEO4J_KPI_DEFINITIONS = """
## LG전자 HE사업부 KPI 목록 (Neo4j Knowledge Graph 기준)

| KPI ID | 설명 | ERP 테이블 | 관련 키워드 |
|--------|------|-----------|-------------|
| 매출 | TV 제품 총 매출액 | TR_SALES.REVENUE_USD | 매출, revenue, 수익, sales, 실적 |
| 판매량 | TV 제품 판매 수량 | TR_SALES.QTY | 판매량, 판매수량, 수량, quantity, volume, 출하량 |
| 영업이익 | HE사업부 영업이익 | TR_SALES.OPERATING_PROFIT_USD | 영업이익, operating profit, 이익 |
| 영업이익률 | 영업이익 / 매출액 (%) | TR_SALES.OPERATING_MARGIN | 영업이익률, OPM, 마진, margin |
| 매출총이익률 | (매출-원가) / 매출 (%) | TR_SALES.GROSS_MARGIN | 매출총이익률, gross margin, GPM |
| OLED매출 | OLED TV 제품 매출액 | TR_SALES (DISPLAY_TYPE='OLED') | OLED, 올레드 |
| 플랫폼매출 | webOS 콘텐츠/광고 매출 | TR_SALES.WEBOS_REV_USD | webOS, 플랫폼, platform, 콘텐츠 |
| 평균판매가 | TV 평균 판매 단가 (ASP) | TR_SALES.REVENUE_USD/QTY | ASP, 평균판매가, 단가 |
| 프리미엄믹스 | 프리미엄 제품 매출 비중 (%) | EXT_TECH_LIFE_CYCLE.PREMIUM_MIX_RATIO | 프리미엄, premium, 고급 |
| 매출원가 | 제품 원가 총액 (COGS) | TR_PURCHASE.TOTAL_COGS_USD | 원가, cost, COGS, 제조원가 |
| 판관비 | 마케팅, 물류, 관리비 등 | TR_EXPENSE.TOTAL_OPEX_USD | 판관비, OPEX, 물류비, 마케팅비 |
| 재고리스크 | 재고 수준 및 진부화 위험 | TR_INVENTORY.INVENTORY_WEEKS | 재고, inventory |
"""


@dataclass
class EventDetail:
    """이벤트 상세 정보 (V3: Event→AFFECTS→Driver 기반)"""
    id: str = ""            # Event ID (v2)
    name: str = ""
    category: str = ""      # geopolitical, policy, market, macro_economy, company
    severity: str = ""      # critical, high, medium, low
    is_ongoing: bool = False  # 현재 진행 중인지 (v2)
    polarity: int = 0       # Event→Driver 영향 방향: +1 or -1 (v2)
    weight: float = 0.5     # Event→Driver 영향력 (v2)
    evidence: str = ""      # 이벤트 설명/근거
    # Legacy 호환
    impact_direction: str = ""  # INCREASES, DECREASES
    target_regions: List[str] = field(default_factory=list)


@dataclass
class KPINode:
    """KPI 노드 정보 (GraphDB 기준)"""
    id: str
    name: str
    name_kr: str
    category: str
    description: str
    erp_table: str
    erp_column: str
    unit: str
    # LLM 추론 정보
    extraction_method: str = ""  # "llm" or "keyword"
    extraction_reasoning: str = ""


@dataclass
class DriverInfo:
    """Driver 상세 정보 (GraphDB 기준)"""
    id: str
    name: str
    name_kr: str
    category: str
    description: str
    validation_tier: str  # T1, T2, T3
    validation_method: str  # ERP, PROXY, EVENT
    # ERP 매핑 (T1)
    erp_table: str = ""
    erp_column: str = ""
    # Proxy 정보 (T2)
    proxy_source: str = ""
    proxy_indicator: str = ""
    # 관계 정보
    polarity: str = ""  # +, -
    effect_type: str = ""  # volume, price, cost, mix
    relationship_strength: str = ""  # strong, medium, weak
    # Whitelist
    is_whitelisted: bool = False
    whitelist_rationale: str = ""


@dataclass
class Hypothesis:
    """가설 데이터 클래스 (V3 Schema + Whitelist)"""
    id: str
    category: str           # revenue, cost, pricing, external
    driver: str             # 관련 Driver
    driver_id: str          # Driver ID
    direction: str          # increase, decrease
    description: str        # 가설 설명 (상세)
    reasoning: str = ""     # 인과관계 설명
    sql_template: str = ""  # 검증용 SQL 힌트
    validated: bool = None
    validation_data: Dict = field(default_factory=dict)
    # Graph 정보 (V3)
    graph_evidence: Dict = field(default_factory=dict)
    # Consensus 정보 (Whitelist 기반)
    confidence: float = 0.0
    status: str = ""        # unvalidated, weak, medium, strong
    consensus_grade: str = ""  # Legacy 호환
    # Whitelist 정보
    is_whitelisted: bool = False
    expected_polarity: str = ""  # Whitelist에서 예상 방향
    whitelist_rationale: str = ""  # Whitelist 등록 이유
    # 관련 이벤트 상세
    related_events: List[EventDetail] = field(default_factory=list)
    # Driver 상세 정보 (V4 추가)
    driver_info: Optional[DriverInfo] = None
    # Legacy 호환성
    factor: str = ""


@dataclass
class HypothesisResult:
    """가설 생성 결과 (KPI + Driver + Hypotheses)"""
    target_kpi: KPINode
    hypotheses: List[Hypothesis]
    driver_count: int
    relationship_count: int


# KPI 매핑 (V3 Schema - Neo4j KPI 기준, 11개)
# 순서 중요: 구체적인 KPI (영업이익률, OLED매출 등)를 먼저 체크
KPI_MAPPING = {
    # 구체적인 KPI를 먼저 체크 (키워드 충돌 방지)
    "영업이익률": {"kpi_id": "영업이익률", "keywords": ["영업이익률", "opm", "margin", "마진", "수익률"]},
    "매출총이익률": {"kpi_id": "매출총이익률", "keywords": ["매출총이익률", "gross margin", "gpm", "총이익률"]},
    "OLED매출": {"kpi_id": "OLED매출", "keywords": ["oled매출", "oled sales", "oled tv", "올레드", "oled"]},
    "플랫폼매출": {"kpi_id": "플랫폼매출", "keywords": ["webos", "플랫폼", "platform", "콘텐츠", "플랫폼매출", "플랫폼 수익"]},
    "평균판매가": {"kpi_id": "평균판매가", "keywords": ["asp", "평균판매가", "판매가", "단가"]},
    "프리미엄믹스": {"kpi_id": "프리미엄믹스", "keywords": ["프리미엄", "premium", "믹스", "고급"]},
    "재고": {"kpi_id": "재고리스크", "keywords": ["재고", "inventory", "재고리스크"]},
    # 일반적인 KPI를 나중에 체크
    "영업이익": {"kpi_id": "영업이익", "keywords": ["영업이익", "operating profit", "op", "이익"]},
    "원가": {"kpi_id": "매출원가", "keywords": ["원가", "cost", "cogs", "비용", "제조원가"]},
    "판관비": {"kpi_id": "판관비", "keywords": ["판관비", "opex", "판매관리비", "sg&a", "물류비", "마케팅비"]},
    "매출": {"kpi_id": "매출", "keywords": ["매출", "revenue", "수익", "sales", "실적", "판매액", "매출액"]},
}

# Driver Category 매핑
DRIVER_CATEGORY_MAP = {
    "Volume/Mix": "revenue",
    "Price/Promotion": "pricing",
    "Cost": "cost",
    "FX": "external",
    "Platform": "revenue",
    "수요/시장": "external",
    "경쟁/가격": "external",
    "비용/환경": "cost",
    "거시": "external",
    "Event": "external",
}


class HypothesisGenerator(BaseAgent):
    """Graph-Enhanced 가설 생성 에이전트 (V3 Schema)"""

    name = "hypothesis_generator"
    description = "Knowledge Graph를 활용하여 KPI 변동에 대한 가설을 생성합니다."

    def __init__(self, api_key: str = None):
        super().__init__(api_key)
        self.graph_executor = GraphExecutor()

    def generate(
        self,
        question: str,
        company: str = "LGE",
        period: str = None,
        region: str = None,
        return_result: bool = False
    ) -> List[Hypothesis]:
        """
        Graph-Based 가설 생성 (V4: KPI + Driver 정보 포함)

        Args:
            question: 분석 질문
            company: 회사 코드
            period: 분석 기간 (예: "2024년 Q4")
            region: 분석 지역 (예: "NA", "EU")
            return_result: True면 HypothesisResult 반환

        Returns:
            가설 목록 (또는 HypothesisResult)
        """
        # 1. 질문에서 KPI 추출 (LLM 기반)
        target_kpi, kpi_id, extraction_method, extraction_reasoning = self._extract_kpi_full(question)
        print(f"[HypothesisGenerator] 대상 KPI: {target_kpi} ({kpi_id})")
        print(f"[HypothesisGenerator] 추출 방식: {extraction_method}")

        # 2. GraphDB에서 KPI 노드 정보 조회
        kpi_node = self._get_kpi_node(kpi_id, extraction_method, extraction_reasoning)
        if kpi_node:
            print(f"[HypothesisGenerator] KPI 노드: {kpi_node.name_kr} | ERP: {kpi_node.erp_table}.{kpi_node.erp_column}")

        # 3. Graph에서 해당 KPI와 연결된 모든 Driver 조회
        drivers = self._get_drivers_for_kpi(kpi_id)
        print(f"[HypothesisGenerator] 연결된 Driver 수: {len(drivers)}개")

        # 4. 각 Driver를 Hypothesis로 변환 (Driver 상세 정보 포함)
        hypotheses = []
        for i, driver_data in enumerate(drivers):
            hypothesis = self._convert_driver_to_hypothesis(
                index=i + 1,
                driver_data=driver_data,
                target_kpi=target_kpi
            )
            if hypothesis:
                hypotheses.append(hypothesis)

        # 5. Confidence 기준 정렬
        hypotheses.sort(key=lambda h: h.confidence, reverse=True)

        print(f"[HypothesisGenerator] 생성된 가설 수: {len(hypotheses)}개")

        # 6. 결과 반환
        if return_result:
            return HypothesisResult(
                target_kpi=kpi_node,
                hypotheses=hypotheses,
                driver_count=len(drivers),
                relationship_count=len(drivers)
            )

        # Legacy: hypotheses만 반환 (기존 호환성)
        return hypotheses

    def _extract_kpi_full(self, question: str) -> tuple:
        """
        질문에서 KPI 추출 (LLM 기반 + 키워드 폴백)

        Returns:
            (kpi_name, kpi_id, method, reasoning) 튜플
        """
        # 1. LLM 기반 추출 시도
        try:
            kpi_id, reasoning = self._extract_kpi_with_llm(question)
            if kpi_id:
                print(f"[KPI-LLM] 식별: {kpi_id} | 이유: {reasoning}")
                return kpi_id, kpi_id, "llm", reasoning
        except Exception as e:
            print(f"[KPI-LLM] 오류, 키워드 폴백: {e}")

        # 2. 키워드 기반 폴백
        kpi_name, kpi_id = self._extract_kpi_by_keyword(question)
        return kpi_name, kpi_id, "keyword", "키워드 매칭"

    def _get_kpi_node(self, kpi_id: str, extraction_method: str = "", extraction_reasoning: str = "") -> Optional[KPINode]:
        """GraphDB에서 KPI 노드 정보 조회"""
        query = """
        MATCH (k:KPI {id: $kpi_id})
        RETURN
            k.id as id,
            k.name as name,
            k.name_kr as name_kr,
            k.category as category,
            k.description as description,
            k.erp_table as erp_table,
            k.erp_column as erp_column,
            k.unit as unit
        """
        try:
            result = self.graph_executor.execute(query, {"kpi_id": kpi_id})
            if result.success and result.data and len(result.data) > 0:
                row = result.data[0]
                return KPINode(
                    id=row.get("id", kpi_id),
                    name=row.get("name", ""),
                    name_kr=row.get("name_kr", kpi_id),
                    category=row.get("category", ""),
                    description=row.get("description", ""),
                    erp_table=row.get("erp_table", ""),
                    erp_column=row.get("erp_column", ""),
                    unit=row.get("unit", ""),
                    extraction_method=extraction_method,
                    extraction_reasoning=extraction_reasoning
                )
        except Exception as e:
            print(f"[HypothesisGenerator] KPI 노드 조회 오류: {e}")

        # 폴백: 기본 KPINode 반환
        return KPINode(
            id=kpi_id, name=kpi_id, name_kr=kpi_id,
            category="", description="", erp_table="", erp_column="", unit="",
            extraction_method=extraction_method, extraction_reasoning=extraction_reasoning
        )

    def _get_drivers_for_kpi(self, kpi_id: str) -> List[Dict]:
        """
        Graph에서 KPI와 연결된 모든 Driver 조회 (V3: Event 기반)

        V3 개선사항:
        - Event→AFFECTS→Driver 경로 포함
        - 각 Driver에 연결된 Event 정보 수집
        - Event 기반 confidence 계산
        """

        query = """
        MATCH (d:Driver)-[r:HYPOTHESIZED_TO_AFFECT]->(k:KPI {id: $kpi_id})

        // V3: Event→AFFECTS→Driver 관계 조회 (OPTIONAL - Event 없는 Driver도 포함)
        OPTIONAL MATCH (e:Event)-[r1:AFFECTS]->(d)

        WITH d, r, k,
             collect(DISTINCT CASE WHEN e IS NOT NULL THEN {
                 event_id: e.id,
                 event_name: e.name,
                 event_category: e.category,
                 event_severity: e.severity,
                 is_ongoing: e.is_ongoing,
                 polarity: r1.polarity,
                 weight: r1.weight,
                 evidence: substring(coalesce(e.evidence, ''), 0, 200)
             } END) as related_events_raw

        // NULL 제거
        WITH d, r, k,
             [evt IN related_events_raw WHERE evt IS NOT NULL] as related_events

        RETURN
            d.id as driver_id,
            d.name as driver_name,
            d.name_kr as driver_name_kr,
            d.category as driver_category,
            d.validation_tier as validation_tier,
            d.validation_method as validation_method,
            d.description as driver_description,
            d.erp_table as erp_table,
            d.erp_column as erp_column,
            r.polarity as polarity,
            r.expected_polarity as expected_polarity,
            r.effect_type as effect_type,
            r.consensus_support as consensus_support,
            r.consensus_total as consensus_total,
            r.consensus_ratio as consensus_ratio,
            r.source_diversity as source_diversity,
            r.confidence as confidence,
            r.status as status,
            r.grade as grade,
            r.is_whitelisted as is_whitelisted,
            r.whitelist_rationale as whitelist_rationale,
            r.relationship_strength as relationship_strength,
            r.evidence_sentences as evidence_sentences,
            r.sources as sources,
            k.name_kr as kpi_name,
            // V3: Event 정보 추가
            related_events,
            size(related_events) as event_count
        ORDER BY
            size(related_events) DESC,  // Event 많은 Driver 우선
            CASE r.status
                WHEN 'strong' THEN 1
                WHEN 'medium' THEN 2
                WHEN 'weak' THEN 3
                ELSE 4
            END,
            r.confidence DESC
        """

        try:
            result = self.graph_executor.execute(query, {"kpi_id": kpi_id})
            if result.success and result.data:
                return result.data
        except Exception as e:
            print(f"[HypothesisGenerator] Driver 조회 오류: {e}")

        return []

    def _convert_driver_to_hypothesis(
        self,
        index: int,
        driver_data: Dict,
        target_kpi: str
    ) -> Optional[Hypothesis]:
        """Driver 데이터를 Hypothesis 객체로 변환 (V3: Event 기반)"""
        driver_id = driver_data.get("driver_id", "")
        driver_name_kr = driver_data.get("driver_name_kr", "")
        driver_category = driver_data.get("driver_category", "")
        validation_tier = driver_data.get("validation_tier", "T3")

        # Whitelist 정보
        is_whitelisted = driver_data.get("is_whitelisted", False) or False
        expected_polarity = driver_data.get("expected_polarity", "")
        whitelist_rationale = driver_data.get("whitelist_rationale", "")
        relationship_strength = driver_data.get("relationship_strength", "medium")

        # Polarity: 실제 관측값 우선, 없으면 expected 사용
        observed_polarity = driver_data.get("polarity", "")
        polarity = observed_polarity if observed_polarity else expected_polarity

        effect_type = driver_data.get("effect_type", "")
        driver_confidence = driver_data.get("confidence", 0.0) or 0.0
        status = driver_data.get("status", "unvalidated")
        grade = driver_data.get("grade", "")  # Legacy

        # Consensus 정보
        consensus_ratio = driver_data.get("consensus_ratio", 0.0) or 0.0
        consensus_support = driver_data.get("consensus_support", 0) or 0
        source_diversity = driver_data.get("source_diversity", 0) or 0
        evidence_sentences = driver_data.get("evidence_sentences", []) or []
        sources = driver_data.get("sources", []) or []

        erp_table = driver_data.get("erp_table")
        erp_column = driver_data.get("erp_column")

        if not driver_id:
            return None

        # V3: Event 정보 추출
        raw_events = driver_data.get("related_events", []) or []
        event_count = driver_data.get("event_count", 0) or 0

        # V3: EventDetail 객체 생성
        related_events = []
        event_weights = []
        for evt in raw_events:
            if evt:
                weight = evt.get("weight", 0.5) or 0.5
                evt_polarity = evt.get("polarity", 0) or 0
                impact_dir = "INCREASES" if evt_polarity > 0 else ("DECREASES" if evt_polarity < 0 else "")

                related_events.append(EventDetail(
                    id=evt.get("event_id", ""),
                    name=evt.get("event_name", ""),
                    category=evt.get("event_category", ""),
                    severity=evt.get("event_severity", "medium"),
                    is_ongoing=evt.get("is_ongoing", False) or False,
                    polarity=evt_polarity,
                    weight=weight,
                    evidence=evt.get("evidence", ""),
                    impact_direction=impact_dir,
                    target_regions=[]
                ))
                event_weights.append(weight)

        # V3: Event 기반 복합 confidence 계산
        if event_weights:
            avg_event_weight = sum(event_weights) / len(event_weights)
            # 복합: Event 60% + Driver-KPI 40%
            composite_confidence = avg_event_weight * 0.6 + driver_confidence * 0.4
            # Event 개수 보너스 (최대 20%)
            event_bonus = min(0.2, event_count * 0.03)
            composite_confidence = min(1.0, composite_confidence + event_bonus)
        else:
            # Event 없으면 기존 confidence 유지
            composite_confidence = driver_confidence

        # 카테고리 결정
        category = DRIVER_CATEGORY_MAP.get(driver_category, "external")

        # 방향 결정: polarity 기반 (mixed면 기본 +)
        if polarity == "mixed":
            direction = "mixed"
        elif polarity == "-":
            direction = "decrease"
        else:
            direction = "increase"

        # 설명 생성 (V3: Event 개수 포함)
        polarity_map = {"+": "증가", "-": "감소", "mixed": "복합"}
        polarity_kr = polarity_map.get(polarity, "증가")

        # Status 기반 신뢰도 표시
        status_label = {
            "strong": "[강함]",
            "medium": "[중간]",
            "weak": "[약함]",
            "unvalidated": "[미검증]"
        }.get(status, "[미검증]")

        event_info = f" (관련 이벤트 {event_count}개)" if event_count > 0 else ""
        description = f"{status_label} {driver_name_kr}이(가) {target_kpi}에 영향 ({polarity_kr}, {effect_type}){event_info}"

        # Graph Evidence 구성 (V3: Event 정보 추가)
        graph_evidence = {
            "from_graph": True,
            "driver_id": driver_id,
            "validation_tier": validation_tier,
            # Whitelist 정보
            "is_whitelisted": is_whitelisted,
            "expected_polarity": expected_polarity,
            "observed_polarity": observed_polarity,
            "whitelist_rationale": whitelist_rationale,
            "relationship_strength": relationship_strength,
            # Polarity 및 Effect
            "polarity": polarity,
            "effect_type": effect_type,
            # Consensus 정보
            "consensus_support": consensus_support,
            "consensus_ratio": consensus_ratio,
            "source_diversity": source_diversity,
            "sources": sources[:5],  # 상위 5개
            "evidence_sentences": evidence_sentences[:3],  # 상위 3개
            # ERP 정보
            "erp_table": erp_table,
            "erp_column": erp_column,
            # V3: Event 기반 정보
            "event_count": event_count,
            "event_based_confidence": round(composite_confidence, 3),
            "driver_confidence": driver_confidence,
            "events_summary": [
                {"id": e.id, "name": e.name, "severity": e.severity, "polarity": e.polarity}
                for e in related_events[:5]
            ]
        }

        # SQL 힌트 생성
        sql_hint = ""
        if erp_table and erp_column:
            sql_hint = f"{erp_table}.{erp_column}"
        else:
            sql_hint = self._generate_sql_hint(driver_name_kr, category)

        # V4: DriverInfo 객체 생성
        driver_info = DriverInfo(
            id=driver_id,
            name=driver_data.get("driver_name", ""),
            name_kr=driver_name_kr,
            category=driver_category,
            description=driver_data.get("driver_description", ""),
            validation_tier=validation_tier.replace("TIER", "T") if validation_tier else "T3",
            validation_method=driver_data.get("validation_method", "EVENT"),
            erp_table=erp_table or "",
            erp_column=erp_column or "",
            proxy_source=driver_data.get("proxy_source", "") or "",
            proxy_indicator=driver_data.get("proxy_indicator", "") or "",
            polarity=polarity,
            effect_type=effect_type,
            relationship_strength=relationship_strength,
            is_whitelisted=is_whitelisted,
            whitelist_rationale=whitelist_rationale
        )

        return Hypothesis(
            id=f"H{index}",
            category=category,
            driver=driver_name_kr,
            driver_id=driver_id,
            factor=driver_name_kr,  # Legacy 호환
            direction=direction,
            description=description,
            reasoning="",  # 답변 생성 시 채워짐
            sql_template=sql_hint,
            graph_evidence=graph_evidence,
            confidence=composite_confidence,  # V3: Event 기반 복합 confidence
            status=status,
            consensus_grade=grade,  # Legacy 호환
            # Whitelist 정보
            is_whitelisted=is_whitelisted,
            expected_polarity=expected_polarity,
            whitelist_rationale=whitelist_rationale,
            related_events=related_events,  # V3: Event 정보 채움
            driver_info=driver_info  # V4: Driver 상세 정보
        )

    def _generate_sql_hint(self, driver_name: str, category: str) -> str:
        """SQL 검증 힌트 생성 (erp_database 스키마 기준)"""
        hints = {
            "cost": {
                "물류비": "TR_EXPENSE.LOGISTICS_COST",
                "마케팅비": "TR_EXPENSE.MARKETING_COST",
                "프로모션비": "TR_EXPENSE.PROMOTION_COST",
                "인건비": "TR_EXPENSE.LABOR_COST",
                "패널": "TR_PURCHASE.PANEL_PRICE_USD",
                "원가": "TR_PURCHASE.TOTAL_COGS_USD",
            },
            "pricing": {
                "할인": "TR_EXPENSE.PROMOTION_COST",
                "프로모션": "TR_EXPENSE.PROMOTION_COST",
            },
            "revenue": {
                "판매량": "TR_SALES.QTY",
                "매출": "TR_SALES.REVENUE_USD",
                "webOS": "TR_SALES.WEBOS_REV_USD",
            },
            "external": {
                "환율": "EXT_MACRO.EXCHANGE_RATE_KRW_USD",
                "금리": "EXT_MACRO.INTEREST_RATE",
                "운임": "EXT_MARKET.SCFI_INDEX",
                "관세": "EXT_TRADE_POLICY.TARIFF_RATE",
            }
        }

        category_hints = hints.get(category, {})
        for key, hint in category_hints.items():
            if key in driver_name:
                return hint

        return f"{driver_name} 기간 비교"

    def _extract_kpi(self, question: str) -> tuple:
        """
        질문에서 KPI 추출 (LLM 기반 + 키워드 폴백)

        1. LLM을 사용하여 질문 의도 파악 및 KPI 식별
        2. LLM 실패 시 키워드 기반 폴백
        """
        # 1. LLM 기반 추출 시도
        try:
            kpi_id, reasoning = self._extract_kpi_with_llm(question)
            if kpi_id:
                print(f"[KPI-LLM] 식별: {kpi_id} | 이유: {reasoning}")
                return kpi_id, kpi_id
        except Exception as e:
            print(f"[KPI-LLM] 오류, 키워드 폴백: {e}")

        # 2. 키워드 기반 폴백
        return self._extract_kpi_by_keyword(question)

    def _extract_kpi_with_llm(self, question: str) -> tuple:
        """
        LLM을 사용하여 질문에서 KPI 추출 (Structured Output)

        Returns:
            (kpi_id, reasoning) 튜플
        """
        system_prompt = f"""당신은 LG전자 HE사업부의 비즈니스 분석가입니다.
사용자의 질문을 분석하여 어떤 KPI에 대해 묻고 있는지 파악하세요.

{NEO4J_KPI_DEFINITIONS}

## 분석 지침
1. 질문의 핵심 의도를 파악하세요
2. 명시적으로 언급된 KPI가 있으면 해당 KPI를 선택하세요
3. 간접적으로 언급된 경우:
   - "왜 돈을 못 벌어?" → 영업이익 또는 영업이익률
   - "물류비가 올랐어" → 판관비 (물류비는 판관비의 하위 항목)
   - "패널 가격이 올랐어" → 매출원가 (패널원가는 원가의 하위 항목)
   - "OLED TV가 안 팔려" → OLED매출
4. 불명확한 경우 가장 관련성 높은 KPI를 선택하세요
"""

        try:
            response = self.llm.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"질문: {question}"}
                ],
                response_format=KPIExtraction,
                temperature=0
            )

            result = response.choices[0].message.parsed
            return result.kpi_id, result.reasoning

        except Exception as e:
            print(f"[KPI-LLM] 파싱 오류: {e}")
            return None, None

    def _extract_kpi_by_keyword(self, question: str) -> tuple:
        """키워드 기반 KPI 추출 (폴백)"""
        question_lower = question.lower()

        for kpi_name, info in KPI_MAPPING.items():
            for keyword in info["keywords"]:
                if keyword in question_lower:
                    return kpi_name, info["kpi_id"]

        # 기본값: 매출 (가장 일반적인 KPI)
        return "매출", "매출"

    def run(self, context: AgentContext) -> Dict[str, Any]:
        """Agent 실행"""
        question = context.query
        metadata = context.metadata or {}

        hypotheses = self.generate(
            question=question,
            company=metadata.get("company", "LGE"),
            period=metadata.get("period"),
            region=metadata.get("region")
        )

        result = {
            "hypotheses": [
                {
                    "id": h.id,
                    "category": h.category,
                    "driver": h.driver,
                    "driver_id": h.driver_id,
                    "factor": h.factor,  # Legacy
                    "direction": h.direction,
                    "description": h.description,
                    "reasoning": h.reasoning,
                    "confidence": h.confidence,
                    "status": h.status,  # Whitelist 기반 status
                    "consensus_grade": h.consensus_grade,  # Legacy
                    # Whitelist 정보
                    "is_whitelisted": h.is_whitelisted,
                    "expected_polarity": h.expected_polarity,
                    "whitelist_rationale": h.whitelist_rationale,
                    "graph_evidence": h.graph_evidence,
                    "related_events": [
                        {
                            "name": e.name,
                            "category": e.category,
                            "severity": e.severity,
                            "impact_direction": e.impact_direction,
                            "evidence": e.evidence,
                            "target_regions": e.target_regions
                        }
                        for e in h.related_events
                    ]
                }
                for h in hypotheses
            ],
            "count": len(hypotheses)
        }

        context.add_step("hypothesis_generation", result)
        return {"hypotheses": hypotheses, **result}
