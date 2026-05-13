# Database Schema Definition for LLM Prompt
# Updated to match new ERP schema (TR_SALES, MD_PRODUCT, etc.)
# Synced with Neo4j KPI definitions

DB_SCHEMA_PROMPT = """
You have access to a SQLite database 'lge_he_erp.db' - LG Electronics HE (Home Entertainment) Division ERP system.

## Database Schema

### 1. Master Data Tables

**MD_PRODUCT** (Product Catalog - 21 products)
- PRODUCT_ID (PK): Unique product identifier (e.g., OLED_G4_77)
- PRODUCT_NAME: Display name (e.g., "LG OLED evo G4 77")
- CATEGORY: Product category (TV, Monitor, Signage)
- DISPLAY_TYPE: Panel technology (OLED, LCD, QNED)
- SCREEN_SIZE: Size in inches (43, 50, 55, 65, 75, 77, 86, 98)
- MODEL_YEAR: Year introduced (2023, 2024, 2025)
- IS_PREMIUM: Premium flag (Y/N)
- HAS_WEBOS: webOS platform flag (Y/N)

**MD_ORG** (Sales Organizations - 8 entities)
- ORG_ID (PK): Organization code (LGEUS, LGEKR, LGEDG, LGEJP)
- ORG_NAME: Organization name
- REGION: Geographic region (Americas, Europe, Asia, Production)
- COUNTRY_CODE: Country code (US, KR, DE, JP, VN, IN, PL)
- ORG_TYPE: Type (HQ, Regional, Local, Production)

**MD_CHANNEL** (Sales Channels - 18 channels)
- CHANNEL_ID (PK): Channel identifier
- CHANNEL_NAME: Channel name (Best Buy, Amazon, Costco, etc.)
- CHANNEL_TYPE: Type (Retail, Online, B2B, Direct)
- TIER: Tier level (Premium, Mass, Budget)

### 2. Transaction Tables

**TR_SALES** (Sales Transactions - ~10K records)
- SALES_ID (PK): Transaction ID
- SALES_DATE: Transaction date (YYYY-MM-DD)
- PRODUCT_ID (FK): Product reference
- ORG_ID (FK): Organization reference
- CHANNEL_ID (FK): Channel reference
- QTY: Quantity sold
- REVENUE_USD: Revenue in USD
- REVENUE_KRW: Revenue in KRW
- WEBOS_REV_USD: webOS platform revenue
- IS_B2B_SALES: B2B flag (Y/N)
- EXCHANGE_RATE: KRW/USD rate

**TR_PURCHASE** (Purchase/COGS - ~2K records)
- PURCHASE_ID (PK): Purchase ID
- PURCHASE_DATE: Purchase date
- PRODUCT_ID (FK): Product reference
- ORG_ID (FK): Organization reference
- QTY: Quantity purchased
- PANEL_PRICE_USD: Panel cost
- DRAM_PRICE_USD_PER_GB: DRAM cost per GB
- RAW_MATERIAL_INDEX: Raw material index
- TOTAL_COGS_USD: Total cost of goods sold

**TR_EXPENSE** (Operating Expenses - ~600 records)
- EXPENSE_ID (PK): Expense ID
- EXPENSE_DATE: Expense date
- ORG_ID (FK): Organization reference
- EXPENSE_TYPE: Type (LOGISTICS, MARKETING, PROMOTION, LABOR)
- LOGISTICS_COST: Logistics/shipping cost
- MARKETING_COST: Marketing spend
- PROMOTION_COST: Promotion spend
- LABOR_COST: Labor cost
- TOTAL_EXPENSE_KRW: Total expense in KRW

### 3. External Data Tables

**EXT_MACRO** (Macro Economic Indicators)
- DATA_DATE: Data date
- COUNTRY_CODE: Country (US, DE, KR, JP)
- EXCHANGE_RATE_KRW_USD: KRW/USD exchange rate
- INTEREST_RATE: Interest rate
- MORTGAGE_RATE: Mortgage rate (US)
- INFLATION_RATE: Inflation rate
- GDP_GROWTH_RATE: GDP growth
- CSI_INDEX: Consumer Sentiment Index
- HOUSING_STARTS: Housing starts (US)

**EXT_MARKET** (Market Data)
- DATA_DATE: Data date
- REGION: Region (Global, Americas, Europe, Asia)
- TOTAL_SHIPMENT_10K: Global TV shipments (10K units)
- LGE_MARKET_SHARE: LG market share (%)
- COMPETITOR_PROMO_IDX: Competitor promotion intensity
- SEASONALITY_INDEX: Seasonality index
- SCFI_INDEX: Shipping freight index
- BDI_INDEX: Baltic Dry Index
- OTT_SUBSCRIBER_GROWTH: OTT subscriber growth (%)

**EXT_TECH_LIFE_CYCLE** (Product Lifecycle)
- DATA_DATE: Data date
- DISPLAY_TYPE: Display type (OLED, LCD, QNED)
- SCREEN_SIZE_RANGE: Size range (<55, 55-65, 65-75, >75)
- AVG_REPLACEMENT_YEARS: Average replacement cycle
- PREMIUM_MIX_RATIO: Premium product mix ratio
- FACTORY_UTILIZATION: Factory utilization (%)

## Available KPIs (from Knowledge Graph)

| KPI | ERP Table | Column | Unit | Description |
|-----|-----------|--------|------|-------------|
| 매출 | TR_SALES | REVENUE_USD | USD | Total revenue |
| 영업이익 | TR_SALES | OPERATING_PROFIT_USD | USD | Operating profit |
| 영업이익률 | TR_SALES | OPERATING_MARGIN | % | Operating margin |
| 매출총이익률 | TR_SALES | GROSS_MARGIN | % | Gross margin |
| OLED매출 | TR_SALES | REVENUE_USD | USD | OLED TV revenue (filter: DISPLAY_TYPE='OLED') |
| 플랫폼매출 | TR_SALES | WEBOS_REV_USD | USD | webOS platform revenue |
| 평균판매가 | TR_SALES | REVENUE_USD/QTY | USD | Average selling price |
| 매출원가 | TR_PURCHASE | TOTAL_COGS_USD | USD | Cost of goods sold |
| 판관비 | TR_EXPENSE | SUM(costs) | USD | Operating expenses |
| 프리미엄믹스 | EXT_TECH_LIFE_CYCLE | PREMIUM_MIX_RATIO | % | Premium product mix |
| 재고리스크 | TR_INVENTORY | INVENTORY_WEEKS | weeks | Inventory weeks |

## Key Relationships for Analysis

1. **Revenue by Region**: TR_SALES JOIN MD_ORG ON ORG_ID → GROUP BY REGION
2. **Revenue by Product Type**: TR_SALES JOIN MD_PRODUCT ON PRODUCT_ID → GROUP BY DISPLAY_TYPE
3. **OLED Revenue**: TR_SALES JOIN MD_PRODUCT WHERE DISPLAY_TYPE = 'OLED'
4. **Profitability**: TR_SALES.REVENUE_USD - TR_PURCHASE.TOTAL_COGS_USD - TR_EXPENSE.total
5. **Logistics Impact**: TR_EXPENSE.LOGISTICS_COST correlated with EXT_MARKET.SCFI_INDEX

## Region Mapping
- 북미 (North America): REGION = 'Americas' (LGEUS)
- 유럽 (Europe): REGION = 'Europe' (LGEDG)
- 한국 (Korea): REGION = 'Asia' AND COUNTRY_CODE = 'KR' (LGEKR)
- 아시아 (Asia): REGION = 'Asia'

## Data Availability
- **Date Range**: 2023-01-01 to 2025-12-31
- **Total Records**: ~12,900 transactions
- Data outside this range is NOT available.

## Defined Reports (Standard Templates)
1. **분기 실적 보고서** (Quarterly Performance Report)
2. **반기 실적 보고서** (Half-yearly Performance Report)
3. **연간 사업 계획서** (Annual Business Plan)
4. **수익성 분석 보고서** (Profitability Analysis Report)
"""

# Available data information for UI components
AVAILABLE_DATA_INFO = {
    "date_range": {
        "start": "2023-01-01",
        "end": "2025-12-31",
        "display": "2023년 ~ 2025년"
    },
    "company": "LG전자 HE사업부",
    "regions": ["북미 (Americas)", "유럽 (Europe)", "한국 (Korea)", "아시아 (Asia)"],
    "products": ["OLED TV", "QNED TV", "LCD TV", "Signage"],
    "kpis": [
        "매출", "영업이익", "영업이익률", "매출총이익률",
        "OLED매출", "플랫폼매출", "평균판매가", "프리미엄믹스",
        "매출원가", "판관비", "재고리스크"
    ],
    "metrics": {
        "revenue": ["매출", "OLED매출", "플랫폼매출", "평균판매가"],
        "profit": ["영업이익", "영업이익률", "매출총이익률"],
        "cost": ["매출원가", "판관비", "물류비", "패널원가"],
        "drivers": ["판매량", "출하량", "할인율", "프리미엄비중"]
    },
    "service_description": """
이 서비스는 **LG전자 HE(Home Entertainment) 사업부**의 데이터 분석 에이전트입니다.

**제공 기능:**
1. 📊 **보고서 생성**: 수익성 분석, 전략 분석, 리스크 분석 등 종합 보고서
2. 📈 **데이터 QA**: 매출, 판매량, 영업이익 등 특정 지표 조회
3. 🔍 **원인 분석**: KPI 변동 원인을 Knowledge Graph와 ERP 데이터로 분석
""",
    "sample_questions": {
        "Report Generation": [
            "2025년 3분기 북미 OLED TV 수익성 분석 보고서 만들어줘",
            "2025년 상반기 물류비 증가 원인 분석해줘"
        ],
        "Data QA": [
            "2025년 3분기 북미 매출액 알려줘",
            "Best Buy 대상 2025년 거래액은 얼마야?"
        ],
        "Diagnostic": [
            "2025년 3분기 북미 매출이 왜 감소했어?",
            "영업이익률이 하락한 원인이 뭐야?"
        ]
    }
}
