"""Layer 2: Factor Extraction

Consensus/Dart 문서에서 Factor를 추출하여 Anchor와 연결
- Factor: 실적 변동 요인 (환율, 수요, 경쟁 등)
- Relationship: PROPORTIONAL / INVERSELY_PROPORTIONAL
"""

from .models import (
    FactorCategory,
    RelationType,
    SourceReference,
    FactorMention,
    FactorNode,
    FactorAnchorRelation,
    Layer2Graph,
)
from .pdf_extractor import PDFExtractor, DocumentProcessor, Paragraph
from .factor_extractor import FactorExtractor, Layer2Builder
from .normalizer import FactorNormalizer, normalize_layer2
from .neo4j_loader import Layer2Neo4jLoader, load_layer2_to_neo4j

__all__ = [
    # Models
    "FactorCategory",
    "RelationType",
    "SourceReference",
    "FactorMention",
    "FactorNode",
    "FactorAnchorRelation",
    "Layer2Graph",
    # PDF
    "PDFExtractor",
    "DocumentProcessor",
    "Paragraph",
    # Extractor
    "FactorExtractor",
    "Layer2Builder",
    # Normalizer
    "FactorNormalizer",
    "normalize_layer2",
    # Neo4j Loader
    "Layer2Neo4jLoader",
    "load_layer2_to_neo4j",
]
