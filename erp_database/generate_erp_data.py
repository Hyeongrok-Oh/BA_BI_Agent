"""
LG Electronics HE Division ERP Data Generator
NEW Schema: TR_SALES, TR_EXPENSE, TR_PURCHASE, MD_PRODUCT, MD_ORG, MD_CHANNEL, EXT_*

데이터 범위: 2023-01-01 ~ 2025-12-31
"""

import sqlite3
import random
from datetime import datetime, timedelta
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "lge_he_erp.db")

# =============================================================================
# Schema Definition
# =============================================================================

SCHEMA = """
-- Master Data Tables
CREATE TABLE IF NOT EXISTS MD_PRODUCT (
    PRODUCT_ID TEXT PRIMARY KEY,
    PRODUCT_NAME TEXT,
    CATEGORY TEXT,
    DISPLAY_TYPE TEXT,
    SCREEN_SIZE INTEGER,
    MODEL_YEAR INTEGER,
    IS_PREMIUM TEXT,
    HAS_WEBOS TEXT
);

CREATE TABLE IF NOT EXISTS MD_ORG (
    ORG_ID TEXT PRIMARY KEY,
    ORG_NAME TEXT,
    REGION TEXT,
    COUNTRY_CODE TEXT,
    ORG_TYPE TEXT
);

CREATE TABLE IF NOT EXISTS MD_CHANNEL (
    CHANNEL_ID TEXT PRIMARY KEY,
    CHANNEL_NAME TEXT,
    CHANNEL_TYPE TEXT,
    TIER TEXT
);

-- Transaction Tables
CREATE TABLE IF NOT EXISTS TR_SALES (
    SALES_ID INTEGER PRIMARY KEY AUTOINCREMENT,
    SALES_DATE TEXT,
    PRODUCT_ID TEXT,
    ORG_ID TEXT,
    CHANNEL_ID TEXT,
    QTY INTEGER,
    REVENUE_USD REAL,
    REVENUE_KRW REAL,
    WEBOS_REV_USD REAL,
    IS_B2B_SALES TEXT,
    EXCHANGE_RATE REAL,
    FOREIGN KEY (PRODUCT_ID) REFERENCES MD_PRODUCT(PRODUCT_ID),
    FOREIGN KEY (ORG_ID) REFERENCES MD_ORG(ORG_ID),
    FOREIGN KEY (CHANNEL_ID) REFERENCES MD_CHANNEL(CHANNEL_ID)
);

CREATE TABLE IF NOT EXISTS TR_PURCHASE (
    PURCHASE_ID INTEGER PRIMARY KEY AUTOINCREMENT,
    PURCHASE_DATE TEXT,
    PRODUCT_ID TEXT,
    ORG_ID TEXT,
    QTY INTEGER,
    PANEL_PRICE_USD REAL,
    DRAM_PRICE_USD_PER_GB REAL,
    RAW_MATERIAL_INDEX REAL,
    TOTAL_COGS_USD REAL,
    FOREIGN KEY (PRODUCT_ID) REFERENCES MD_PRODUCT(PRODUCT_ID),
    FOREIGN KEY (ORG_ID) REFERENCES MD_ORG(ORG_ID)
);

CREATE TABLE IF NOT EXISTS TR_EXPENSE (
    EXPENSE_ID INTEGER PRIMARY KEY AUTOINCREMENT,
    EXPENSE_DATE TEXT,
    ORG_ID TEXT,
    EXPENSE_TYPE TEXT,
    LOGISTICS_COST REAL,
    MARKETING_COST REAL,
    PROMOTION_COST REAL,
    LABOR_COST REAL,
    TOTAL_EXPENSE_KRW REAL,
    FOREIGN KEY (ORG_ID) REFERENCES MD_ORG(ORG_ID)
);

-- External Data Tables
CREATE TABLE IF NOT EXISTS EXT_MACRO (
    DATA_DATE TEXT,
    COUNTRY_CODE TEXT,
    EXCHANGE_RATE_KRW_USD REAL,
    INTEREST_RATE REAL,
    MORTGAGE_RATE REAL,
    INFLATION_RATE REAL,
    GDP_GROWTH_RATE REAL,
    CSI_INDEX REAL,
    HOUSING_STARTS REAL,
    PRIMARY KEY (DATA_DATE, COUNTRY_CODE)
);

CREATE TABLE IF NOT EXISTS EXT_MARKET (
    DATA_DATE TEXT,
    REGION TEXT,
    TOTAL_SHIPMENT_10K REAL,
    LGE_MARKET_SHARE REAL,
    COMPETITOR_PROMO_IDX REAL,
    SEASONALITY_INDEX REAL,
    SCFI_INDEX REAL,
    BDI_INDEX REAL,
    OTT_SUBSCRIBER_GROWTH REAL,
    PRIMARY KEY (DATA_DATE, REGION)
);

CREATE TABLE IF NOT EXISTS EXT_TECH_LIFE_CYCLE (
    DATA_DATE TEXT,
    DISPLAY_TYPE TEXT,
    SCREEN_SIZE_RANGE TEXT,
    AVG_REPLACEMENT_YEARS REAL,
    PREMIUM_MIX_RATIO REAL,
    FACTORY_UTILIZATION REAL,
    PRIMARY KEY (DATA_DATE, DISPLAY_TYPE, SCREEN_SIZE_RANGE)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_sales_date ON TR_SALES(SALES_DATE);
CREATE INDEX IF NOT EXISTS idx_sales_product ON TR_SALES(PRODUCT_ID);
CREATE INDEX IF NOT EXISTS idx_sales_org ON TR_SALES(ORG_ID);
CREATE INDEX IF NOT EXISTS idx_expense_date ON TR_EXPENSE(EXPENSE_DATE);
CREATE INDEX IF NOT EXISTS idx_purchase_date ON TR_PURCHASE(PURCHASE_DATE);
"""

# =============================================================================
# Master Data
# =============================================================================

PRODUCTS = [
    # OLED TVs
    ("OLED_G4_65", "LG OLED evo G4 65", "TV", "OLED", 65, 2024, "Y", "Y"),
    ("OLED_G4_77", "LG OLED evo G4 77", "TV", "OLED", 77, 2024, "Y", "Y"),
    ("OLED_C4_55", "LG OLED evo C4 55", "TV", "OLED", 55, 2024, "Y", "Y"),
    ("OLED_C4_65", "LG OLED evo C4 65", "TV", "OLED", 65, 2024, "Y", "Y"),
    ("OLED_C4_77", "LG OLED evo C4 77", "TV", "OLED", 77, 2024, "Y", "Y"),
    ("OLED_B4_55", "LG OLED B4 55", "TV", "OLED", 55, 2024, "N", "Y"),
    ("OLED_B4_65", "LG OLED B4 65", "TV", "OLED", 65, 2024, "N", "Y"),
    # QNED TVs
    ("QNED_90_65", "LG QNED90 65", "TV", "QNED", 65, 2024, "Y", "Y"),
    ("QNED_90_75", "LG QNED90 75", "TV", "QNED", 75, 2024, "Y", "Y"),
    ("QNED_85_55", "LG QNED85 55", "TV", "QNED", 55, 2024, "N", "Y"),
    ("QNED_85_65", "LG QNED85 65", "TV", "QNED", 65, 2024, "N", "Y"),
    # LCD TVs
    ("LCD_UT80_50", "LG UT80 50", "TV", "LCD", 50, 2024, "N", "Y"),
    ("LCD_UT80_55", "LG UT80 55", "TV", "LCD", 55, 2024, "N", "Y"),
    ("LCD_UT80_65", "LG UT80 65", "TV", "LCD", 65, 2024, "N", "Y"),
    ("LCD_UT80_75", "LG UT80 75", "TV", "LCD", 75, 2024, "N", "Y"),
    # Monitors
    ("MON_32GS95", "LG UltraGear 32GS95", "Monitor", "OLED", 32, 2024, "Y", "N"),
    ("MON_27GP950", "LG UltraGear 27GP950", "Monitor", "LCD", 27, 2024, "Y", "N"),
    # Signage
    ("SIG_86UH5F", "LG Signage 86UH5F", "Signage", "LCD", 86, 2024, "N", "N"),
    ("SIG_98UM3F", "LG Signage 98UM3F", "Signage", "LCD", 98, 2024, "Y", "N"),
    # 2023 Models
    ("OLED_C3_65", "LG OLED evo C3 65", "TV", "OLED", 65, 2023, "Y", "Y"),
    ("OLED_B3_55", "LG OLED B3 55", "TV", "OLED", 55, 2023, "N", "Y"),
]

ORGS = [
    ("LGEUS", "LG Electronics USA", "Americas", "US", "Regional"),
    ("LGEKR", "LG Electronics Korea", "Asia", "KR", "HQ"),
    ("LGEDG", "LG Electronics Germany", "Europe", "DE", "Regional"),
    ("LGEJP", "LG Electronics Japan", "Asia", "JP", "Local"),
    ("LGEVN", "LG Electronics Vietnam", "Asia", "VN", "Production"),
    ("LGEIN", "LG Electronics India", "Asia", "IN", "Local"),
    ("LGEPL", "LG Electronics Poland", "Europe", "PL", "Production"),
    ("LGECN", "LG Electronics China", "Asia", "CN", "Local"),
]

CHANNELS = [
    ("CH_BESTBUY", "Best Buy", "Retail", "Premium"),
    ("CH_AMAZON", "Amazon", "Online", "Mass"),
    ("CH_COSTCO", "Costco", "Retail", "Mass"),
    ("CH_WALMART", "Walmart", "Retail", "Budget"),
    ("CH_TARGET", "Target", "Retail", "Mass"),
    ("CH_SAMSUNG", "Samsung.com", "Online", "Premium"),
    ("CH_LG", "LG.com", "Direct", "Premium"),
    ("CH_MEDIAMARKT", "MediaMarkt", "Retail", "Premium"),
    ("CH_COUPANG", "Coupang", "Online", "Mass"),
    ("CH_HIMART", "Himart", "Retail", "Premium"),
    ("CH_YODOBASHI", "Yodobashi Camera", "Retail", "Premium"),
    ("CH_BICCAMERA", "Bic Camera", "Retail", "Mass"),
    ("CH_B2B_US", "B2B Americas", "B2B", "Premium"),
    ("CH_B2B_EU", "B2B Europe", "B2B", "Premium"),
    ("CH_B2B_ASIA", "B2B Asia", "B2B", "Premium"),
    ("CH_FLIPKART", "Flipkart", "Online", "Mass"),
    ("CH_JD", "JD.com", "Online", "Mass"),
    ("CH_TMALL", "Tmall", "Online", "Mass"),
]

# Product pricing (base ASP in USD)
PRODUCT_ASP = {
    "OLED_G4_65": 2500, "OLED_G4_77": 3500, "OLED_C4_55": 1300, "OLED_C4_65": 1800,
    "OLED_C4_77": 2800, "OLED_B4_55": 1100, "OLED_B4_65": 1500,
    "QNED_90_65": 1200, "QNED_90_75": 1800, "QNED_85_55": 800, "QNED_85_65": 1000,
    "LCD_UT80_50": 400, "LCD_UT80_55": 500, "LCD_UT80_65": 650, "LCD_UT80_75": 900,
    "MON_32GS95": 1400, "MON_27GP950": 700,
    "SIG_86UH5F": 4000, "SIG_98UM3F": 8000,
    "OLED_C3_65": 1600, "OLED_B3_55": 1000,
}

# COGS as % of ASP
COGS_RATIO = {"OLED": 0.65, "QNED": 0.60, "LCD": 0.55}

# =============================================================================
# Data Generation Functions
# =============================================================================

def generate_date_range(start_date, end_date):
    """Generate list of dates"""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    dates = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates

def get_seasonality(month):
    """Seasonality factor by month"""
    factors = {
        1: 0.7, 2: 0.6, 3: 0.8, 4: 0.9, 5: 0.85, 6: 0.8,
        7: 0.75, 8: 0.8, 9: 0.9, 10: 1.0, 11: 1.3, 12: 1.4
    }
    return factors.get(month, 1.0)

def get_region_weight(region):
    """Sales weight by region"""
    weights = {"Americas": 0.35, "Europe": 0.25, "Asia": 0.40}
    return weights.get(region, 0.1)

def generate_master_data(conn):
    """Insert master data"""
    cursor = conn.cursor()

    # Products
    cursor.executemany(
        "INSERT OR REPLACE INTO MD_PRODUCT VALUES (?,?,?,?,?,?,?,?)",
        PRODUCTS
    )

    # Orgs
    cursor.executemany(
        "INSERT OR REPLACE INTO MD_ORG VALUES (?,?,?,?,?)",
        ORGS
    )

    # Channels
    cursor.executemany(
        "INSERT OR REPLACE INTO MD_CHANNEL VALUES (?,?,?,?)",
        CHANNELS
    )

    conn.commit()
    print(f"Master data: {len(PRODUCTS)} products, {len(ORGS)} orgs, {len(CHANNELS)} channels")

def generate_sales_data(conn, start_date, end_date):
    """Generate TR_SALES data"""
    cursor = conn.cursor()
    dates = generate_date_range(start_date, end_date)

    records = []
    for date_str in dates:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        seasonality = get_seasonality(dt.month)

        # Skip some days randomly
        if random.random() > 0.3:  # ~70% of days have sales
            continue

        for product in PRODUCTS:
            product_id = product[0]
            display_type = product[3]
            is_premium = product[6]

            for org in ORGS:
                org_id = org[0]
                region = org[2]

                # Skip production facilities
                if org[4] == "Production":
                    continue

                region_weight = get_region_weight(region)

                # Random channel selection (weighted by region)
                channel = random.choice(CHANNELS)
                channel_id = channel[0]

                # Base quantity
                base_qty = random.randint(1, 10)
                qty = int(base_qty * seasonality * region_weight)
                if qty < 1:
                    continue

                # Pricing with variation
                base_asp = PRODUCT_ASP.get(product_id, 1000)
                price_variation = random.uniform(0.9, 1.1)
                unit_price = base_asp * price_variation

                # Calculate revenue
                revenue_usd = qty * unit_price
                exchange_rate = random.uniform(1250, 1400)  # KRW/USD
                revenue_krw = revenue_usd * exchange_rate

                # webOS revenue (only for TVs with webOS)
                webos_rev = 0
                if product[7] == "Y":
                    webos_rev = qty * random.uniform(5, 15)  # $5-15 per unit

                # B2B flag
                is_b2b = "Y" if "B2B" in channel_id else "N"

                records.append((
                    date_str, product_id, org_id, channel_id,
                    qty, round(revenue_usd, 2), round(revenue_krw, 2),
                    round(webos_rev, 2), is_b2b, round(exchange_rate, 2)
                ))

    cursor.executemany("""
        INSERT INTO TR_SALES
        (SALES_DATE, PRODUCT_ID, ORG_ID, CHANNEL_ID, QTY, REVENUE_USD, REVENUE_KRW, WEBOS_REV_USD, IS_B2B_SALES, EXCHANGE_RATE)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, records)
    conn.commit()
    print(f"TR_SALES: {len(records)} records")

def generate_purchase_data(conn, start_date, end_date):
    """Generate TR_PURCHASE data"""
    cursor = conn.cursor()

    # Generate monthly data
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    records = []
    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")

        for product in PRODUCTS:
            product_id = product[0]
            display_type = product[3]

            # Only for production facilities
            for org in ORGS:
                if org[4] != "Production":
                    continue
                org_id = org[0]

                # Monthly production quantity
                qty = random.randint(100, 1000)

                # Panel pricing (varies by type)
                if display_type == "OLED":
                    panel_price = random.uniform(200, 400)
                elif display_type == "QNED":
                    panel_price = random.uniform(100, 200)
                else:
                    panel_price = random.uniform(50, 100)

                dram_price = random.uniform(2, 5)  # per GB
                raw_material_idx = random.uniform(90, 120)

                # Total COGS
                base_asp = PRODUCT_ASP.get(product_id, 1000)
                cogs_ratio = COGS_RATIO.get(display_type, 0.6)
                total_cogs = qty * base_asp * cogs_ratio

                records.append((
                    date_str, product_id, org_id, qty,
                    round(panel_price, 2), round(dram_price, 2),
                    round(raw_material_idx, 2), round(total_cogs, 2)
                ))

        current += timedelta(days=30)  # Monthly

    cursor.executemany("""
        INSERT INTO TR_PURCHASE
        (PURCHASE_DATE, PRODUCT_ID, ORG_ID, QTY, PANEL_PRICE_USD, DRAM_PRICE_USD_PER_GB, RAW_MATERIAL_INDEX, TOTAL_COGS_USD)
        VALUES (?,?,?,?,?,?,?,?)
    """, records)
    conn.commit()
    print(f"TR_PURCHASE: {len(records)} records")

def generate_expense_data(conn, start_date, end_date):
    """Generate TR_EXPENSE data"""
    cursor = conn.cursor()

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    expense_types = ["LOGISTICS", "MARKETING", "PROMOTION", "LABOR"]
    records = []

    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")

        for org in ORGS:
            org_id = org[0]
            region = org[2]

            for expense_type in expense_types:
                # Base costs vary by region and type
                if expense_type == "LOGISTICS":
                    base = 50000 * get_region_weight(region)
                elif expense_type == "MARKETING":
                    base = 100000 * get_region_weight(region)
                elif expense_type == "PROMOTION":
                    base = 80000 * get_region_weight(region)
                else:  # LABOR
                    base = 200000 * get_region_weight(region)

                # Add variation
                amount = base * random.uniform(0.8, 1.2)

                logistics = amount if expense_type == "LOGISTICS" else 0
                marketing = amount if expense_type == "MARKETING" else 0
                promotion = amount if expense_type == "PROMOTION" else 0
                labor = amount if expense_type == "LABOR" else 0

                exchange_rate = random.uniform(1250, 1400)
                total_krw = amount * exchange_rate

                records.append((
                    date_str, org_id, expense_type,
                    round(logistics, 2), round(marketing, 2),
                    round(promotion, 2), round(labor, 2),
                    round(total_krw, 2)
                ))

        current += timedelta(days=30)  # Monthly

    cursor.executemany("""
        INSERT INTO TR_EXPENSE
        (EXPENSE_DATE, ORG_ID, EXPENSE_TYPE, LOGISTICS_COST, MARKETING_COST, PROMOTION_COST, LABOR_COST, TOTAL_EXPENSE_KRW)
        VALUES (?,?,?,?,?,?,?,?)
    """, records)
    conn.commit()
    print(f"TR_EXPENSE: {len(records)} records")

def generate_external_data(conn, start_date, end_date):
    """Generate EXT_* tables data"""
    cursor = conn.cursor()

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    # EXT_MACRO
    countries = ["US", "DE", "KR", "JP", "CN"]
    macro_records = []
    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        for country in countries:
            macro_records.append((
                date_str, country,
                random.uniform(1250, 1400),  # Exchange rate
                random.uniform(3, 6),  # Interest rate
                random.uniform(5, 8),  # Mortgage rate
                random.uniform(2, 5),  # Inflation
                random.uniform(-1, 4),  # GDP growth
                random.uniform(90, 110),  # CSI
                random.uniform(1000, 1500) if country == "US" else None  # Housing starts
            ))
        current += timedelta(days=30)

    cursor.executemany("""
        INSERT OR REPLACE INTO EXT_MACRO VALUES (?,?,?,?,?,?,?,?,?)
    """, macro_records)

    # EXT_MARKET
    regions = ["Global", "Americas", "Europe", "Asia"]
    market_records = []
    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        for region in regions:
            market_records.append((
                date_str, region,
                random.uniform(400, 600),  # Shipment 10K
                random.uniform(10, 15),  # LGE market share
                random.uniform(80, 120),  # Competitor promo
                get_seasonality(current.month),  # Seasonality
                random.uniform(800, 1500),  # SCFI
                random.uniform(1000, 2000),  # BDI
                random.uniform(5, 15)  # OTT growth
            ))
        current += timedelta(days=30)

    cursor.executemany("""
        INSERT OR REPLACE INTO EXT_MARKET VALUES (?,?,?,?,?,?,?,?,?)
    """, market_records)

    # EXT_TECH_LIFE_CYCLE
    display_types = ["OLED", "QNED", "LCD"]
    size_ranges = ["<55", "55-65", "65-75", ">75"]
    tech_records = []
    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        for dt in display_types:
            for sr in size_ranges:
                tech_records.append((
                    date_str, dt, sr,
                    random.uniform(5, 8),  # Replacement years
                    random.uniform(0.2, 0.4) if dt == "OLED" else random.uniform(0.1, 0.2),  # Premium mix
                    random.uniform(70, 95)  # Factory utilization
                ))
        current += timedelta(days=30)

    cursor.executemany("""
        INSERT OR REPLACE INTO EXT_TECH_LIFE_CYCLE VALUES (?,?,?,?,?,?)
    """, tech_records)

    conn.commit()
    print(f"EXT_MACRO: {len(macro_records)}, EXT_MARKET: {len(market_records)}, EXT_TECH: {len(tech_records)}")

def main():
    """Main function"""
    print("=" * 60)
    print("LG HE ERP Data Generator (NEW Schema)")
    print("=" * 60)

    # Remove existing DB
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Removed existing DB: {DB_PATH}")

    # Create connection
    conn = sqlite3.connect(DB_PATH)

    # Create schema
    conn.executescript(SCHEMA)
    print("Schema created")

    # Generate data
    START_DATE = "2023-01-01"
    END_DATE = "2025-12-31"

    generate_master_data(conn)
    generate_sales_data(conn, START_DATE, END_DATE)
    generate_purchase_data(conn, START_DATE, END_DATE)
    generate_expense_data(conn, START_DATE, END_DATE)
    generate_external_data(conn, START_DATE, END_DATE)

    # Summary
    cursor = conn.cursor()
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    for table in ["MD_PRODUCT", "MD_ORG", "MD_CHANNEL", "TR_SALES", "TR_EXPENSE", "TR_PURCHASE"]:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"{table}: {count} records")

    conn.close()
    print("\n" + "=" * 60)
    print(f"Database created: {DB_PATH}")
    print("=" * 60)

if __name__ == "__main__":
    main()
