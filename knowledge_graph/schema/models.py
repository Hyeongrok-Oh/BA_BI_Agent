"""Knowledge Graph Schema v3 - KPI / Driver / Event 모델

구조:
- 노드: KPI, Driver, Event (3개)
- 관계: HYPOTHESIZED_TO_AFFECT, EVIDENCE_FOR (2개)
"""

from dataclasses import dataclass, field
from typing import List, Optional, Literal
from enum import Enum


# ============================================================
# Enums
# ============================================================

class ValidationTier(str, Enum):
    """Driver 검증 등급"""
    T1 = "T1"  # ERP 직접 검증
    T2 = "T2"  # Proxy 기반 검증
    T3 = "T3"  # Event 기반


class ValidationMethod(str, Enum):
    """Driver 검증 방법"""
    ERP = "ERP"
    PROXY = "PROXY"
    EVENT = "EVENT"


class EffectType(str, Enum):
    """Driver→KPI 영향 유형"""
    PRICE = "price"
    VOLUME = "volume"
    COST = "cost"
    MIX = "mix"
    DEMAND = "demand"
    FX = "fx"


class Polarity(str, Enum):
    """영향 방향"""
    POSITIVE = "+"
    NEGATIVE = "-"
    MIXED = "mixed"


class EventType(str, Enum):
    """Event 유형"""
    PRICE_CHANGE = "PRICE_CHANGE"
    SUPPLY_CHAIN_DISRUPTION = "SUPPLY_CHAIN_DISRUPTION"
    COMPETITOR_ACTION = "COMPETITOR_ACTION"
    REGULATION = "REGULATION"
    MACRO_EVENT = "MACRO_EVENT"
    SPORTS_EVENT = "SPORTS_EVENT"
    PRODUCT_LAUNCH = "PRODUCT_LAUNCH"
    BRAND_EVENT = "BRAND_EVENT"


# ============================================================
# Node Models
# ============================================================

@dataclass
class KPI:
    """KPI 노드 - 분석 대상 결과 변수"""
    id: str
    name: str
    name_kr: str
    category: str  # 성과, 매출구조, 가격/믹스, 비용/리스크
    description: str
    erp_table: Optional[str] = None
    erp_column: Optional[str] = None
    unit: Optional[str] = None


@dataclass
class Driver:
    """Driver 노드 - 원인 후보 (가설 단위)"""
    id: str
    name: str
    name_kr: str
    category: str  # Volume/Mix, Price/Promotion, Cost, FX, Platform, 수요/시장, 경쟁/가격, 비용/환경, 거시
    validation_tier: ValidationTier
    validation_method: ValidationMethod
    description: str
    example_sentence: str
    # ERP 매핑 (Tier 1만 해당)
    erp_table: Optional[str] = None
    erp_column: Optional[str] = None
    # Proxy 지표 (Tier 2만 해당)
    proxy_source: Optional[str] = None
    proxy_indicator: Optional[str] = None


@dataclass
class Event:
    """Event 노드 - 사실/사건/뉴스/지표 (근거)"""
    event_id: str
    driver_id: str  # 관련 Driver
    event_type: EventType
    title: str
    direction: Literal["up", "down", "neutral"]
    magnitude: Optional[str] = None  # "5%", "200%" 등
    time_window: Optional[str] = None  # "2024Q1", "2025-01"
    region: str = "Global"
    source: str = "news"
    source_url: Optional[str] = None
    confidence: float = 0.8


# ============================================================
# Relationship Models
# ============================================================

@dataclass
class HypothesizedToAffect:
    """Driver → KPI 관계 속성"""
    driver_id: str
    kpi_id: str
    polarity: Polarity
    effect_type: EffectType
    # Consensus 관련
    consensus_support: int = 0  # 지지 리포트 수
    consensus_total: int = 0  # 전체 리포트 수
    consensus_ratio: float = 0.0  # support / total
    source_diversity: int = 0  # 다양한 출처 수
    confidence: float = 0.0  # 최종 신뢰도
    # 시간 정보
    first_seen: Optional[str] = None  # "2024Q3"
    last_seen: Optional[str] = None  # "2025Q1"
    # 근거
    evidence_sentences: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)


@dataclass
class EvidenceFor:
    """Event → Driver 관계 속성"""
    event_id: str
    driver_id: str
    relevance_score: float = 0.8
    evidence_text: Optional[str] = None


# ============================================================
# Claim (리포트에서 추출)
# ============================================================

@dataclass
class Claim:
    """리포트에서 추출한 단일 주장"""
    driver_id: str
    kpi_id: str
    polarity: Polarity
    effect_type: EffectType
    evidence: str  # 근거 문장
    source: str  # 출처 파일명
    source_date: Optional[str] = None  # 출처 날짜


# ============================================================
# Consensus 계산
# ============================================================

def calculate_confidence(
    consensus_ratio: float,
    source_diversity: int,
    conflict_ratio: float = 0.0,
    max_diversity: int = 15
) -> float:
    """
    Confidence 계산 공식:
    confidence = 0.5 * consensus_ratio + 0.3 * (source_diversity / max_diversity) + 0.2 * (1 - conflict_ratio)
    """
    diversity_score = min(source_diversity / max_diversity, 1.0)
    conflict_penalty = 1.0 - conflict_ratio

    confidence = (
        0.5 * consensus_ratio +
        0.3 * diversity_score +
        0.2 * conflict_penalty
    )

    return round(min(max(confidence, 0.0), 1.0), 3)


def get_consensus_grade(consensus_ratio: float, source_diversity: int) -> str:
    """
    Consensus 등급 판정:
    - Strong: ratio >= 0.35 AND diversity >= 8
    - Medium: ratio >= 0.20
    - Weak: ratio >= 0.10
    - Drop: < 0.10
    """
    if consensus_ratio >= 0.35 and source_diversity >= 8:
        return "Strong"
    elif consensus_ratio >= 0.20:
        return "Medium"
    elif consensus_ratio >= 0.10:
        return "Weak"
    else:
        return "Drop"
