"""Layer 1 전용 설정 - Dimension, Anchor 정의

ERP 데이터베이스(lge_he_erp.db) 기반 구조
- Master Data: MD_PRODUCT, MD_ORG, MD_CHANNEL
- Transaction Data: TR_SALES, TR_PURCHASE, TR_EXPENSE
- External Data: EXT_MACRO, EXT_MARKET, EXT_TECH_LIFE_CYCLE, EXT_TRADE_POLICY
"""

from dataclasses import dataclass, field
from typing import List, Dict

from ..config import BaseConfig


@dataclass
class Layer1Config(BaseConfig):
    """Layer 1: Dimension & Anchor 설정 (ERP 기반)"""

    # ============================================================
    # Anchor definitions (KPI 중심점) - 2개: revenue, cost
    # ============================================================
    anchors: List[Dict] = field(default_factory=lambda: [
        {
            "id": "revenue",
            "metric_type": "REVENUE",
            "name": "매출",
            "description": "매출, 판매량, 수익, 탑라인 관련 KPI",
            "source_table": "TR_SALES",
            "source_column": "REVENUE_USD",
        },
        {
            "id": "cost",
            "metric_type": "COST",
            "name": "비용",
            "description": "원가, 비용, 물류비, 원재료비 관련 KPI",
            "source_table": "TR_PURCHASE",
            "source_column": "TOTAL_COGS_USD",
        },
    ])

    # ============================================================
    # Region Dimension (MD_ORG.REGION 기반)
    # ============================================================
    regions: List[Dict] = field(default_factory=lambda: [
        {"id": "region_americas", "name": "Americas", "description": "북미/중남미"},
        {"id": "region_europe", "name": "Europe", "description": "유럽"},
        {"id": "region_asia", "name": "Asia", "description": "아시아태평양"},
        {"id": "region_production", "name": "Production", "description": "생산법인"},
    ])

    # ============================================================
    # Country Dimension (MD_ORG.COUNTRY_CODE 기반)
    # ============================================================
    countries: List[Dict] = field(default_factory=lambda: [
        {"id": "country_us", "name": "US", "description": "미국", "region": "Americas"},
        {"id": "country_de", "name": "DE", "description": "독일", "region": "Europe"},
        {"id": "country_kr", "name": "KR", "description": "한국", "region": "Asia"},
        {"id": "country_jp", "name": "JP", "description": "일본", "region": "Asia"},
        {"id": "country_vn", "name": "VN", "description": "베트남", "region": "Production"},
        {"id": "country_in", "name": "IN", "description": "인도", "region": "Production"},
        {"id": "country_pl", "name": "PL", "description": "폴란드", "region": "Production"},
    ])

    # ============================================================
    # Channel Dimension (MD_CHANNEL.CHANNEL_TYPE 기반)
    # ============================================================
    channels: List[Dict] = field(default_factory=lambda: [
        {"id": "channel_retail", "name": "Retail", "description": "오프라인 리테일"},
        {"id": "channel_online", "name": "Online", "description": "온라인 채널"},
        {"id": "channel_b2b", "name": "B2B", "description": "B2B 사업"},
    ])

    # ============================================================
    # Display Type Dimension (MD_PRODUCT.DISPLAY_TYPE 기반)
    # ============================================================
    display_types: List[Dict] = field(default_factory=lambda: [
        {"id": "display_oled", "name": "OLED", "description": "OLED TV"},
        {"id": "display_lcd", "name": "LCD", "description": "LCD/LED TV"},
        {"id": "display_qned", "name": "QNED", "description": "QNED Mini LED TV"},
    ])

    # ============================================================
    # Screen Size Dimension (MD_PRODUCT.SCREEN_SIZE 기반)
    # ============================================================
    screen_sizes: List[Dict] = field(default_factory=lambda: [
        {"id": "size_43", "name": "43", "description": "43인치"},
        {"id": "size_48", "name": "48", "description": "48인치"},
        {"id": "size_55", "name": "55", "description": "55인치"},
        {"id": "size_65", "name": "65", "description": "65인치"},
        {"id": "size_75", "name": "75", "description": "75인치"},
        {"id": "size_77", "name": "77", "description": "77인치"},
        {"id": "size_83", "name": "83", "description": "83인치"},
        {"id": "size_97", "name": "97", "description": "97인치"},
    ])

    # ============================================================
    # Product Category Dimension (MD_PRODUCT.CATEGORY 기반)
    # ============================================================
    product_categories: List[Dict] = field(default_factory=lambda: [
        {"id": "cat_tv", "name": "TV", "description": "TV 제품군"},
        {"id": "cat_monitor", "name": "Monitor", "description": "모니터 제품군"},
    ])

    # ============================================================
    # Product Attribute Dimension (MD_PRODUCT 플래그 기반)
    # ============================================================
    product_attributes: List[Dict] = field(default_factory=lambda: [
        {"id": "attr_premium", "name": "premium", "description": "프리미엄 제품", "column": "IS_PREMIUM"},
        {"id": "attr_b2b", "name": "b2b", "description": "B2B 적용 가능", "column": "IS_B2B_ELIGIBLE"},
        {"id": "attr_webos", "name": "webos", "description": "WebOS 탑재", "column": "HAS_WEBOS"},
    ])

    # ============================================================
    # ERP Table Mappings
    # ============================================================
    erp_table_map: Dict[str, str] = field(default_factory=lambda: {
        # Master Data
        "product": "MD_PRODUCT",
        "org": "MD_ORG",
        "channel": "MD_CHANNEL",
        # Transaction Data
        "sales": "TR_SALES",
        "purchase": "TR_PURCHASE",
        "expense": "TR_EXPENSE",
        # External Data
        "macro": "EXT_MACRO",
        "market": "EXT_MARKET",
        "tech": "EXT_TECH_LIFE_CYCLE",
        "trade": "EXT_TRADE_POLICY",
    })

    # ============================================================
    # Country → Region 매핑
    # ============================================================
    country_region_map: Dict[str, str] = field(default_factory=lambda: {
        "US": "Americas",
        "DE": "Europe",
        "KR": "Asia",
        "JP": "Asia",
        "VN": "Production",
        "IN": "Production",
        "PL": "Production",
    })


# Alias for backward compatibility
Config = Layer1Config
