"""Layer 3 설정"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Layer3Config:
    """Layer 3 설정"""
    # API Keys
    brave_api_key: str = field(default_factory=lambda: os.getenv("BRAVE_API_KEY", ""))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))

    # Search Settings
    max_results_per_query: int = 20
    search_languages: List[str] = field(default_factory=lambda: ["ko", "en"])
    search_regions: List[str] = field(default_factory=lambda: ["kr", "us"])

    # Time Settings
    lookback_days: int = 90  # 최근 3개월

    # Neo4j Settings
    neo4j_uri: str = field(default_factory=lambda: os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    neo4j_user: str = field(default_factory=lambda: os.getenv("NEO4J_USER", "neo4j"))
    neo4j_password: str = field(default_factory=lambda: os.getenv("NEO4J_PASSWORD", "password"))
    neo4j_database: str = field(default_factory=lambda: os.getenv("NEO4J_DATABASE", "neo4j"))

    # Vector Settings
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    chunk_size: int = 500
    chunk_overlap: int = 50

    # Paths
    layer3_dir: Path = field(default_factory=lambda: Path(__file__).parent)

    @property
    def search_queries_path(self) -> Path:
        return self.layer3_dir / "search_queries.yaml"

    @property
    def event_normalization_path(self) -> Path:
        return self.layer3_dir / "event_normalization.yaml"

    def validate(self) -> bool:
        """설정 유효성 검사"""
        if not self.brave_api_key:
            raise ValueError("BRAVE_API_KEY가 설정되지 않았습니다")
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다")
        return True


# Driver 목록 (V3 스키마 - driver_definitions.json 기반 40개)
CORE_DRIVERS = [
    # Tier1: ERP 직접 검증 가능 (18개)
    "출하량", "판매량", "OLED비중", "프리미엄비중", "모델믹스변화",
    "TV평균판매가", "할인율", "프로모션비용", "리베이트비용",
    "패널원가", "제조원가", "물류비", "품질보증비", "원재료비",
    "달러환율", "유로환율", "webOS인당매출", "webOS설치기반",
    # Tier2: Proxy 기반 검증 (14개)
    "글로벌TV수요", "북미TV수요", "유럽TV수요", "중국TV수요", "교체주기",
    "경쟁사가격", "경쟁사점유율", "중국업체압박",
    "패널가격지수", "해상운임", "에너지가격",
    "소비심리", "인플레이션", "금리",
    # Tier3: Event 기반 (8개)
    "경쟁사가격인하", "경쟁사신제품", "공급망차질", "무역규제",
    "스포츠이벤트", "브랜드이슈", "품질이슈", "플랫폼정책변경",
]

# Dimension 목록 (dimension_definitions.json 기반)
DIMENSIONS = {
    "Region": ["북미", "유럽", "아시아", "한국", "중국", "중동", "글로벌"],
    "ProductCategory": ["OLED_TV", "LCD_TV", "프리미엄_TV", "대형_TV", "TV_전체"],
    "TimePeriod": ["2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2025H1", "2025H2", "2025"],
}
