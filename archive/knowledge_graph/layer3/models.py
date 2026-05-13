"""Layer 3 데이터 모델 - Event와 Factor/Dimension 관계

v2 개선사항:
- polarity/weight: 관계의 방향성과 영향력 정량화
- EventFactorRelation에 polarity 추가 (INCREASES/DECREASES 대체)
"""

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum
from datetime import date, datetime


class EventCategory(Enum):
    """Event 카테고리"""
    GEOPOLITICAL = "geopolitical"      # 지정학적 (홍해 사태, 전쟁)
    POLICY = "policy"                   # 정책/규제 (관세, 환경 규제)
    MARKET = "market"                   # 시장 (패널 가격, 유가)
    COMPANY = "company"                 # 기업 (실적 발표, 신제품)
    MACRO_ECONOMY = "macro_economy"     # 거시경제 (금리, 환율)
    TECHNOLOGY = "technology"           # 기술 (신기술, AI)
    NATURAL = "natural"                 # 자연재해/팬데믹


class ImpactType(Enum):
    """Event → Factor 영향 타입 (하위 호환용)"""
    INCREASES = "INCREASES"     # Event가 Factor를 증가시킴
    DECREASES = "DECREASES"     # Event가 Factor를 감소시킴
    AFFECTS = "AFFECTS"         # 통합 관계 (polarity로 방향 표현)


class Severity(Enum):
    """Event 심각도"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class EventSource:
    """뉴스 출처 정보"""
    url: str
    title: str
    snippet: str
    published_date: Optional[date] = None
    source_name: Optional[str] = None  # 뉴스 매체명
    search_query: Optional[str] = None  # 검색 쿼리


@dataclass
class EventFactorRelation:
    """Event → Factor 관계

    v2: polarity/weight 속성 추가
    - polarity: 인과관계 방향 (-1: Factor 감소, +1: Factor 증가)
    - weight: 영향력 가중치 (0.0~1.0)

    v3: impact_score 추가
    - impact_score = severity_weight × magnitude_weight × driver_importance
    """
    factor_name: str
    factor_id: str
    impact_type: ImpactType = ImpactType.AFFECTS
    magnitude: str = "medium"  # low, medium, high
    confidence: float = 0.8  # 정보 출처 신뢰도 (LLM 판단)
    confidence_reasoning: str = ""  # confidence 판단 근거
    evidence: str = ""
    # v2: polarity/weight 추가
    polarity: int = 0       # -1: Factor 감소, +1: Factor 증가
    weight: float = 1.0     # 영향력 가중치 (0.0~1.0)
    # v3: impact_score 추가
    impact_score: float = 0.0  # Event가 Driver에 미치는 영향도 점수

    # Impact Score 계산 상수
    SEVERITY_WEIGHTS = {"low": 0.25, "medium": 0.5, "high": 0.75, "critical": 1.0}
    MAGNITUDE_WEIGHTS = {"low": 0.5, "medium": 0.75, "high": 1.0}

    def __post_init__(self):
        """impact_type에서 polarity 자동 추론 (하위 호환)"""
        if self.polarity == 0 and self.impact_type:
            if self.impact_type == ImpactType.INCREASES:
                self.polarity = 1
            elif self.impact_type == ImpactType.DECREASES:
                self.polarity = -1
        # magnitude에서 weight 자동 추론
        if self.weight == 1.0 and self.magnitude:
            magnitude_weights = {"high": 1.0, "medium": 0.6, "low": 0.3}
            self.weight = magnitude_weights.get(self.magnitude, 0.6)

    def calculate_impact_score(
        self,
        severity: str = "medium",
        driver_importance: float = 1.0
    ) -> float:
        """Impact Score 계산

        Args:
            severity: Event 심각도 (low/medium/high/critical)
            driver_importance: Driver의 KPI 연결 중요도 (0.0~1.0)

        Returns:
            impact_score = severity_weight × magnitude_weight × driver_importance
        """
        severity_weight = self.SEVERITY_WEIGHTS.get(severity, 0.5)
        magnitude_weight = self.MAGNITUDE_WEIGHTS.get(self.magnitude, 0.75)
        self.impact_score = severity_weight * magnitude_weight * driver_importance
        return self.impact_score

    @property
    def polarity_label(self) -> str:
        """polarity의 비즈니스 레이블"""
        if self.polarity > 0:
            return "증가"
        elif self.polarity < 0:
            return "감소"
        return "중립"

    def to_dict(self) -> dict:
        return {
            "factor_name": self.factor_name,
            "factor_id": self.factor_id,
            "impact_type": self.impact_type.value,
            "magnitude": self.magnitude,
            "confidence": self.confidence,
            "confidence_reasoning": self.confidence_reasoning,  # v4: 신뢰도 판단 근거
            "evidence": self.evidence,
            # v2: polarity/weight 추가
            "polarity": self.polarity,
            "weight": self.weight,
            # v3: impact_score 추가
            "impact_score": self.impact_score,
        }


@dataclass
class EventDimensionRelation:
    """Event → Dimension 관계

    v4: dimension_id 추가 (dimension_definitions.json과 매칭)
    """
    dimension_name: str
    dimension_type: str  # Region, ProductCategory, TimePeriod
    dimension_id: str = ""  # v4: 정규화된 ID (예: "북미", "OLED_TV", "2025Q1")
    specificity: str = "medium"  # low, medium, high

    def to_dict(self) -> dict:
        return {
            "dimension_name": self.dimension_name,
            "dimension_type": self.dimension_type,
            "dimension_id": self.dimension_id,
            "specificity": self.specificity,
        }


@dataclass
class EventNode:
    """Event 노드

    v3: source_driver 추가
    - source_driver: Driver 기반 검색시 원본 Driver ID

    v4: source_confidence 추가
    - source_confidence: 정보 출처 신뢰도 (LLM 판단, 5단계)
    """
    id: str
    name: str
    name_en: Optional[str] = None
    category: EventCategory = EventCategory.MARKET
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_ongoing: bool = False
    severity: Severity = Severity.MEDIUM
    region_scope: List[str] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    sources: List[EventSource] = field(default_factory=list)
    factor_relations: List[EventFactorRelation] = field(default_factory=list)
    dimension_relations: List[EventDimensionRelation] = field(default_factory=list)
    evidence: str = ""
    extracted_at: datetime = field(default_factory=datetime.now)
    source_driver: Optional[str] = None  # v3: Driver 기반 검색시 원본 Driver ID
    # v4: 정보 출처 신뢰도 (5단계: 1.0/0.8/0.6/0.4/0.2)
    source_confidence: float = 0.8
    source_confidence_reasoning: str = ""  # 신뢰도 판단 근거

    @property
    def source_count(self) -> int:
        return len(self.sources)

    def calculate_impact_scores(self, driver_importance_map: dict = None) -> None:
        """모든 Factor 관계에 대해 Impact Score 계산

        Args:
            driver_importance_map: {driver_id: importance (0.0~1.0)}
                                  없으면 모든 Driver importance를 1.0으로 설정
        """
        driver_importance_map = driver_importance_map or {}
        severity_str = self.severity.value

        for relation in self.factor_relations:
            driver_importance = driver_importance_map.get(relation.factor_id, 1.0)
            relation.calculate_impact_score(
                severity=severity_str,
                driver_importance=driver_importance
            )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "name_en": self.name_en,
            "category": self.category.value,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "is_ongoing": self.is_ongoing,
            "severity": self.severity.value,
            "region_scope": self.region_scope,
            "aliases": self.aliases,
            "source_count": self.source_count,
            "source_driver": self.source_driver,  # v3: 원본 Driver ID
            # v4: 정보 출처 신뢰도
            "source_confidence": self.source_confidence,
            "source_confidence_reasoning": self.source_confidence_reasoning,
            "sources": [
                {
                    "url": s.url,
                    "title": s.title,
                    "snippet": s.snippet,
                    "source_name": s.source_name,
                    "search_query": s.search_query,  # v4: 검색 쿼리 추가
                }
                for s in self.sources
            ],
            # v4: source_urls, search_queries 편의 필드
            "source_urls": [s.url for s in self.sources if s.url],
            "search_queries": list(set(s.search_query for s in self.sources if s.search_query)),
            "factor_relations": [
                {
                    "factor": r.factor_name,
                    "impact": r.impact_type.value,
                    "magnitude": r.magnitude,
                    # v2: polarity/weight 추가
                    "polarity": r.polarity,
                    "weight": r.weight,
                    # v3: impact_score 추가
                    "impact_score": r.impact_score,
                }
                for r in self.factor_relations
            ],
            "dimension_relations": [
                {
                    "dimension": r.dimension_name,
                    "type": r.dimension_type,
                }
                for r in self.dimension_relations
            ],
            "evidence": self.evidence,
        }


@dataclass
class EventChunk:
    """Event 콘텐츠 청크 (Vector 저장용)"""
    event_id: str
    chunk_index: int
    content: str
    embedding: Optional[List[float]] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "chunk_index": self.chunk_index,
            "content": self.content,
            "has_embedding": self.embedding is not None,
            "metadata": self.metadata,
        }


@dataclass
class Layer3Graph:
    """Layer 3 그래프 데이터"""
    events: List[EventNode] = field(default_factory=list)
    chunks: List[EventChunk] = field(default_factory=list)

    def add_event(self, event: EventNode) -> None:
        """Event 추가 (중복 체크)"""
        # 중복 체크
        for existing in self.events:
            if existing.id == event.id:
                # 기존 이벤트에 소스 병합
                existing.sources.extend(event.sources)
                return
        self.events.append(event)

    def get_event_by_id(self, event_id: str) -> Optional[EventNode]:
        """ID로 Event 조회"""
        for event in self.events:
            if event.id == event_id:
                return event
        return None

    def get_events_by_category(self, category: EventCategory) -> List[EventNode]:
        """카테고리별 Event 조회"""
        return [e for e in self.events if e.category == category]

    def get_events_affecting_factor(self, factor_name: str) -> List[EventNode]:
        """특정 Factor에 영향을 주는 Event 조회"""
        return [
            e for e in self.events
            if any(r.factor_name == factor_name for r in e.factor_relations)
        ]

    def summary(self) -> dict:
        """요약 통계"""
        category_counts = {}
        for e in self.events:
            cat = e.category.value
            category_counts[cat] = category_counts.get(cat, 0) + 1

        impact_counts = {"INCREASES": 0, "DECREASES": 0}
        for e in self.events:
            for r in e.factor_relations:
                impact_counts[r.impact_type.value] += 1

        return {
            "total_events": len(self.events),
            "total_chunks": len(self.chunks),
            "by_category": category_counts,
            "impact_counts": impact_counts,
            "total_factor_relations": sum(len(e.factor_relations) for e in self.events),
            "total_dimension_relations": sum(len(e.dimension_relations) for e in self.events),
        }
