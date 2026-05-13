"""Layer 2 데이터 모델 - Factor와 Anchor 관계

v2 개선사항:
- FactorState: Factor의 동적 상태 속성 (현재추세, 변동폭, 영향성)
- polarity/weight: 관계의 방향성과 영향력 정량화
"""

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum
from datetime import date, datetime


class FactorCategory(Enum):
    """Factor 카테고리 (9개 - Value Chain 기반)"""
    RAW_MATERIAL = "원자재_부품"      # 패널가격, DRAM, 원재료, 부품수급
    PRODUCTION = "생산"               # 공장가동률, 인건비, 생산효율
    LOGISTICS = "물류"                # 해상운임, 물류비, 공급망리스크
    MARKETING = "마케팅"              # 마케팅비, 프로모션, 브랜드
    DEMAND = "수요"                   # TV수요, 가전수요, 지역별수요, 계절성
    COMPETITION = "경쟁"              # 점유율, 경쟁심화, 가격경쟁, ASP
    MACRO_ECONOMY = "거시경제"        # 환율, 금리, 경기, 인플레이션
    POLICY = "정책_규제"              # 관세, 무역정책, 환경규제
    PRODUCT_TECH = "제품_기술"        # OLED, 프리미엄, WebOS, AI, B2B


class RelationType(Enum):
    """Factor → Anchor 관계 타입 (하위 호환용)"""
    PROPORTIONAL = "PROPORTIONAL"                    # 정비례 (Factor↑ → Anchor↑)
    INVERSELY_PROPORTIONAL = "INVERSELY_PROPORTIONAL"  # 반비례 (Factor↑ → Anchor↓)
    AFFECTS = "AFFECTS"                              # 통합 관계 (polarity로 방향 표현)


class TrendType(Enum):
    """Factor 추세 타입"""
    RISING = "상승"
    FALLING = "하락"
    STABLE = "안정"
    UNKNOWN = "unknown"


class ImpactDirection(Enum):
    """영향 방향"""
    POSITIVE = "긍정적"    # KPI에 긍정적 영향
    NEGATIVE = "부정적"    # KPI에 부정적 영향
    NEUTRAL = "중립"


@dataclass
class FactorState:
    """Factor의 현재 상태 (동적 속성)

    LLM이 답변 생성 시 해당 시점의 상태값을 읽어 문맥을 파악할 수 있음
    """
    current_trend: TrendType = TrendType.UNKNOWN  # 현재 추세
    change_rate: Optional[float] = None           # 변동폭 (%, e.g., -15.0)
    impact_direction: ImpactDirection = ImpactDirection.NEUTRAL  # 영향 방향
    last_updated: datetime = field(default_factory=datetime.now)
    confidence: float = 0.8                       # 상태 신뢰도 (0~1)
    source: str = ""                              # 상태 정보 출처

    def to_dict(self) -> dict:
        return {
            "current_trend": self.current_trend.value,
            "change_rate": self.change_rate,
            "impact_direction": self.impact_direction.value,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "confidence": self.confidence,
            "source": self.source,
        }


@dataclass
class SourceReference:
    """문서 출처 정보"""
    doc_name: str           # 파일명
    doc_date: date          # 문서 날짜
    doc_type: str           # consensus / dart
    paragraph: str          # 원문 문단
    page_num: Optional[int] = None

    def to_dict(self) -> dict:
        """출처 정보를 dict로 변환 (v2: 모든 출처 저장용)"""
        return {
            "doc_name": self.doc_name,
            "doc_date": self.doc_date.isoformat() if self.doc_date else None,
            "doc_type": self.doc_type,
            "paragraph": self.paragraph[:500] if self.paragraph else "",  # 최대 500자
            "page_num": self.page_num,
        }


@dataclass
class FactorMention:
    """Factor 언급 정보"""
    factor_name: str
    anchor_id: str          # revenue, cost
    relation_type: RelationType
    source: SourceReference
    confidence: float = 1.0  # 추출 신뢰도 (0~1)
    # v2: polarity만 추가 (weight는 mention_count에서 자동 계산)
    polarity: int = 0       # -1: 역상관, +1: 정상관, 0: 미지정
    # v4: category 추가
    category: str = ""      # 9개 카테고리 중 하나

    def __post_init__(self):
        """relation_type에서 polarity 자동 추론 (하위 호환)"""
        if self.polarity == 0 and self.relation_type:
            if self.relation_type == RelationType.PROPORTIONAL:
                self.polarity = 1
            elif self.relation_type == RelationType.INVERSELY_PROPORTIONAL:
                self.polarity = -1


@dataclass
class FactorNode:
    """Factor 노드

    v2: 동적 상태 속성 추가 (current_state)
    """
    id: str
    name: str
    category: FactorCategory
    mentions: List[FactorMention] = field(default_factory=list)
    # v2: 동적 상태 속성
    current_state: Optional[FactorState] = None
    historical_states: List[FactorState] = field(default_factory=list)

    @property
    def mention_count(self) -> int:
        return len(self.mentions)

    @property
    def sources(self) -> List[str]:
        return list(set(m.source.doc_name for m in self.mentions))

    @property
    def current_trend(self) -> str:
        """현재 추세 (Neo4j 속성용)"""
        if self.current_state:
            return self.current_state.current_trend.value
        return TrendType.UNKNOWN.value

    @property
    def change_rate(self) -> Optional[float]:
        """변동폭 (Neo4j 속성용)"""
        if self.current_state:
            return self.current_state.change_rate
        return None

    @property
    def impact_direction(self) -> str:
        """영향 방향 (Neo4j 속성용)"""
        if self.current_state:
            return self.current_state.impact_direction.value
        return ImpactDirection.NEUTRAL.value

    def update_state(self, new_state: FactorState) -> None:
        """상태 업데이트 (히스토리 보존)"""
        if self.current_state:
            self.historical_states.append(self.current_state)
        self.current_state = new_state

    def to_dict(self) -> dict:
        result = {
            "id": self.id,
            "name": self.name,
            "category": self.category.value,
            "mention_count": self.mention_count,
            "sources": self.sources,
            # v2: 상태 속성 추가
            "current_trend": self.current_trend,
            "change_rate": self.change_rate,
            "impact_direction": self.impact_direction,
        }
        if self.current_state:
            result["state"] = self.current_state.to_dict()
        return result


@dataclass
class FactorAnchorRelation:
    """Factor-Anchor 관계 (집계)

    v2: polarity/weight 속성 추가
    - polarity: 인과관계 방향 (-1: 역상관, +1: 정상관)
    - weight: 영향력 가중치 (0.0~1.0)
    """
    factor_id: str
    anchor_id: str
    relation_type: RelationType = RelationType.AFFECTS
    mention_count: int = 0
    sources: List[SourceReference] = field(default_factory=list)
    # v2: polarity/weight 추가
    polarity: int = 0       # -1: 역상관 (Factor↑→Anchor↓), +1: 정상관 (Factor↑→Anchor↑)
    weight: float = 1.0     # 영향력 가중치 (0.0~1.0)
    confidence: float = 0.8 # 관계 신뢰도

    def __post_init__(self):
        """relation_type에서 polarity 자동 추론 (하위 호환)"""
        if self.polarity == 0 and self.relation_type:
            if self.relation_type == RelationType.PROPORTIONAL:
                self.polarity = 1
            elif self.relation_type == RelationType.INVERSELY_PROPORTIONAL:
                self.polarity = -1

    @property
    def polarity_label(self) -> str:
        """polarity의 비즈니스 레이블"""
        if self.polarity > 0:
            return "정상관"
        elif self.polarity < 0:
            return "역상관"
        return "중립"

    def to_dict(self) -> dict:
        return {
            "factor_id": self.factor_id,
            "anchor_id": self.anchor_id,
            "relation_type": self.relation_type.value,
            "mention_count": self.mention_count,
            "source_count": len(self.sources),
            # v2: 모든 출처 저장
            "sources": [s.to_dict() for s in self.sources],
            # v2: polarity/weight 추가
            "polarity": self.polarity,
            "weight": self.weight,
            "confidence": self.confidence,
        }


@dataclass
class Layer2Graph:
    """Layer 2 그래프 데이터"""
    factors: List[FactorNode] = field(default_factory=list)
    relations: List[FactorAnchorRelation] = field(default_factory=list)

    def add_mention(self, mention: FactorMention) -> None:
        """Factor 언급 추가"""
        # Factor 찾기 또는 생성
        factor = self._get_or_create_factor(mention.factor_name)
        factor.mentions.append(mention)

    def _get_or_create_factor(self, name: str) -> FactorNode:
        """Factor 노드 조회 또는 생성"""
        factor_id = self._name_to_id(name)
        for f in self.factors:
            if f.id == factor_id:
                return f

        # 새로 생성
        new_factor = FactorNode(
            id=factor_id,
            name=name,
            category=FactorCategory.MACRO_ECONOMY,  # 기본값, 나중에 분류
        )
        self.factors.append(new_factor)
        return new_factor

    def _name_to_id(self, name: str) -> str:
        """이름을 ID로 변환"""
        return name.lower().replace(" ", "_").replace("/", "_")

    def aggregate_relations(self) -> None:
        """Factor-Anchor 관계 집계 (v2: polarity 포함, weight는 mention_count 기반 자동 계산)"""
        relation_map = {}

        for factor in self.factors:
            for mention in factor.mentions:
                # v2: polarity 기준으로 그룹화
                key = (factor.id, mention.anchor_id, mention.polarity)
                if key not in relation_map:
                    relation_map[key] = {
                        "factor_id": factor.id,
                        "anchor_id": mention.anchor_id,
                        "relation_type": mention.relation_type,
                        "polarity": mention.polarity,
                        "sources": [],
                    }
                relation_map[key]["sources"].append(mention.source)

        # mention_count 기반 weight 계산 (정규화)
        if relation_map:
            max_mentions = max(len(v["sources"]) for v in relation_map.values())
        else:
            max_mentions = 1

        self.relations = [
            FactorAnchorRelation(
                factor_id=v["factor_id"],
                anchor_id=v["anchor_id"],
                relation_type=v["relation_type"],
                mention_count=len(v["sources"]),
                sources=v["sources"],
                polarity=v["polarity"],
                # weight = mention_count 정규화 (0.3 ~ 1.0 범위)
                weight=self._calculate_weight(len(v["sources"]), max_mentions),
            )
            for v in relation_map.values()
        ]

    def _calculate_weight(self, mention_count: int, max_mentions: int) -> float:
        """
        mention_count 기반 weight 계산

        공식: 0.3 + 0.7 * (mention_count / max_mentions)
        - 최소 weight: 0.3 (1회 언급)
        - 최대 weight: 1.0 (최다 언급)
        """
        if max_mentions <= 0:
            return 0.5
        normalized = mention_count / max_mentions
        return round(0.3 + 0.7 * normalized, 2)

    def summary(self) -> dict:
        return {
            "factors": len(self.factors),
            "relations": len(self.relations),
            "total_mentions": sum(f.mention_count for f in self.factors),
        }
