"""Node and Relationship type definitions for Layer 1.

Layer 1 Structure:
- Dimension: 분석 축 (Product, Customer, Subsidiary, TimePeriod 등)
- Anchor: KPI 중심점 (매출, 수량, 원가)

Layer 2/3에서 Event → Factor → Anchor 연결 시,
Event는 관련 Dimension에도 TARGETS 관계로 연결됨.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional


class NodeType(Enum):
    """Node types in Layer 1."""
    DIMENSION = "Dimension"
    ANCHOR = "Anchor"


class RelationType(Enum):
    """Relationship types."""
    # Layer 1
    CHILD_OF = "CHILD_OF"          # Dimension hierarchy (e.g., Product -> ProductCategory)

    # Layer 2 (for reference)
    PROPORTIONAL = "PROPORTIONAL"              # Factor → Anchor (비례)
    INVERSELY_PROPORTIONAL = "INVERSELY_PROPORTIONAL"  # Factor → Anchor (반비례)

    # Layer 3 (for reference)
    INCREASES = "INCREASES"        # Event → Factor
    DECREASES = "DECREASES"        # Event → Factor
    TARGETS = "TARGETS"            # Event → Dimension (LLM 태깅)


class DimensionType(Enum):
    """Types of Dimension nodes."""
    # 상위 레벨 (LLM 태깅용)
    PRODUCT_CATEGORY = "ProductCategory"   # OLED, QNED, LCD
    REGION = "Region"                       # NA, EU, KR
    CHANNEL = "Channel"                     # RETAIL, ONLINE

    # 하위 레벨 (DB 마스터)
    PRODUCT = "Product"
    CUSTOMER = "Customer"
    SUBSIDIARY = "Subsidiary"
    TIME_PERIOD = "TimePeriod"


class MetricType(Enum):
    """Type of metric for Anchor nodes."""
    REVENUE = "REVENUE"       # 매출
    QUANTITY = "QUANTITY"     # 수량
    COST = "COST"            # 원가
    PROFIT = "PROFIT"        # 이익 (계산)


@dataclass
class DimensionNode:
    """Represents a Dimension node for analysis axis."""

    id: str                          # Unique identifier
    dimension_type: DimensionType    # Type of dimension
    name: str                        # Display name
    properties: Dict[str, Any] = field(default_factory=dict)
    parent_id: Optional[str] = None  # For hierarchy (CHILD_OF)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "dimension_type": self.dimension_type.value,
            "name": self.name,
            "properties": self.properties,
            "parent_id": self.parent_id,
        }


@dataclass
class AnchorNode:
    """Represents an Anchor node (KPI center point).

    Anchors are the connection points for:
    - Layer 2: Factor → Anchor relationships
    - Analysis: "매출이 왜 떨어졌어?" queries
    """

    id: str
    metric_type: MetricType
    name: str                        # Display name (e.g., "매출", "수량")
    description: str = ""
    source_table: Optional[str] = None
    source_column: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "metric_type": self.metric_type.value,
            "name": self.name,
            "description": self.description,
            "source_table": self.source_table,
            "source_column": self.source_column,
        }


@dataclass
class Layer1Graph:
    """Container for Layer 1 graph data."""

    dimensions: List[DimensionNode] = field(default_factory=list)
    anchors: List[AnchorNode] = field(default_factory=list)

    def add_dimension(self, dimension: DimensionNode) -> None:
        self.dimensions.append(dimension)

    def add_anchor(self, anchor: AnchorNode) -> None:
        self.anchors.append(anchor)

    def get_dimensions_by_type(self, dim_type: DimensionType) -> List[DimensionNode]:
        return [d for d in self.dimensions if d.dimension_type == dim_type]

    def summary(self) -> Dict[str, int]:
        by_type = {}
        for d in self.dimensions:
            key = d.dimension_type.value
            by_type[key] = by_type.get(key, 0) + 1
        return {
            "dimensions": len(self.dimensions),
            "anchors": len(self.anchors),
            "by_dimension_type": by_type,
        }
