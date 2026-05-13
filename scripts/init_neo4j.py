"""Initialize Neo4j with the canonical KPI / Driver / Event graph."""

import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from neo4j import GraphDatabase

from config.settings import get_settings


SCHEMA_DIR = PROJECT_ROOT / "knowledge_graph" / "schema"


SAMPLE_EVENTS = [
    {
        "id": "red_sea_crisis_2024",
        "name": "홍해 사태",
        "name_en": "Red Sea Crisis",
        "category": "supply_chain",
        "start_date": "2023-11-19",
        "is_ongoing": True,
        "severity": "high",
        "evidence": "홍해 항로 불안으로 우회 운항이 늘며 해상운임과 물류비가 상승했다.",
        "source_titles": ["Red Sea shipping disruption"],
        "source_urls": ["https://example.com/red-sea-crisis"],
        "sources": ["demo_seed"],
        "source_confidence": 0.8,
        "targets": ["유럽", "아시아", "글로벌", "2024Q4"],
        "drivers": [
            {"id": "해상운임", "polarity": 1, "weight": 0.9, "impact_score": 0.85},
            {"id": "물류비", "polarity": 1, "weight": 0.85, "impact_score": 0.8},
            {"id": "공급망차질", "polarity": 1, "weight": 0.7, "impact_score": 0.75},
        ],
    },
    {
        "id": "trump_tariff_2025",
        "name": "미국 관세 정책 강화",
        "name_en": "US Tariff Policy Tightening",
        "category": "policy",
        "start_date": "2025-01-20",
        "is_ongoing": True,
        "severity": "high",
        "evidence": "미국 수입 관세 강화 가능성이 원가와 무역 규제 리스크를 높였다.",
        "source_titles": ["US tariff policy update"],
        "source_urls": ["https://example.com/us-tariff-policy"],
        "sources": ["demo_seed"],
        "source_confidence": 0.75,
        "targets": ["북미", "글로벌", "2025Q1"],
        "drivers": [
            {"id": "무역규제", "polarity": 1, "weight": 0.9, "impact_score": 0.85},
            {"id": "원재료비", "polarity": 1, "weight": 0.55, "impact_score": 0.55},
        ],
    },
    {
        "id": "lcd_panel_oversupply_2024",
        "name": "LCD 패널 공급과잉",
        "name_en": "LCD Panel Oversupply",
        "category": "component_market",
        "start_date": "2024-06-01",
        "is_ongoing": True,
        "severity": "medium",
        "evidence": "중국 패널 업체 증설로 LCD 패널 가격지수가 하락했다.",
        "source_titles": ["LCD panel oversupply"],
        "source_urls": ["https://example.com/lcd-oversupply"],
        "sources": ["demo_seed"],
        "source_confidence": 0.8,
        "targets": ["글로벌", "2024Q4"],
        "drivers": [
            {"id": "패널가격지수", "polarity": -1, "weight": 0.8, "impact_score": 0.75},
            {"id": "패널원가", "polarity": -1, "weight": 0.7, "impact_score": 0.7},
        ],
    },
    {
        "id": "usd_krw_surge_2024",
        "name": "원/달러 환율 급등",
        "name_en": "USD/KRW Exchange Rate Surge",
        "category": "macro",
        "start_date": "2024-10-01",
        "is_ongoing": True,
        "severity": "high",
        "evidence": "달러 강세로 원/달러 환율이 상승하며 수입 원가와 환산 매출에 영향을 줬다.",
        "source_titles": ["USD/KRW exchange rate surge"],
        "source_urls": ["https://example.com/usd-krw-surge"],
        "sources": ["demo_seed"],
        "source_confidence": 0.8,
        "targets": ["한국", "글로벌", "2024Q4"],
        "drivers": [
            {"id": "달러환율", "polarity": 1, "weight": 0.9, "impact_score": 0.85},
            {"id": "원재료비", "polarity": 1, "weight": 0.6, "impact_score": 0.6},
        ],
    },
    {
        "id": "black_friday_2024",
        "name": "블랙프라이데이 TV 판매 확대",
        "name_en": "Black Friday TV Demand Lift",
        "category": "demand",
        "start_date": "2024-11-29",
        "is_ongoing": False,
        "severity": "medium",
        "evidence": "미국 블랙프라이데이 프로모션 기간 TV 판매량과 북미 수요가 증가했다.",
        "source_titles": ["Black Friday TV demand"],
        "source_urls": ["https://example.com/black-friday-tv"],
        "sources": ["demo_seed"],
        "source_confidence": 0.7,
        "targets": ["북미", "2024Q4"],
        "drivers": [
            {"id": "판매량", "polarity": 1, "weight": 0.75, "impact_score": 0.7},
            {"id": "북미TV수요", "polarity": 1, "weight": 0.7, "impact_score": 0.7},
            {"id": "프로모션비용", "polarity": 1, "weight": 0.45, "impact_score": 0.5},
        ],
    },
]


def load_json(filename: str) -> Dict:
    with open(SCHEMA_DIR / filename, encoding="utf-8") as file:
        return json.load(file)


def wait_for_neo4j(uri: str, user: str, password: str, max_retries: int = 30) -> bool:
    """Wait until Neo4j is reachable."""

    print("Waiting for Neo4j to be ready...")
    for i in range(max_retries):
        try:
            driver = GraphDatabase.driver(uri, auth=(user, password))
            driver.verify_connectivity()
            driver.close()
            print("Neo4j is ready!")
            return True
        except Exception as exc:
            print(f"Attempt {i + 1}/{max_retries}: Neo4j not ready yet... ({exc})")
            time.sleep(2)
    return False


def run_statements(driver, statements: Iterable[str]) -> None:
    with driver.session() as session:
        for statement in statements:
            try:
                session.run(statement)
                print(f"Created: {statement[:72]}...")
            except Exception as exc:
                print(f"Skipped: {statement[:72]}... ({exc})")


def init_constraints(driver) -> None:
    """Create constraints and indexes for the active graph schema."""

    constraints = [
        "CREATE CONSTRAINT kpi_id IF NOT EXISTS FOR (k:KPI) REQUIRE k.id IS UNIQUE",
        "CREATE CONSTRAINT driver_id IF NOT EXISTS FOR (d:Driver) REQUIRE d.id IS UNIQUE",
        "CREATE CONSTRAINT event_id IF NOT EXISTS FOR (e:Event) REQUIRE e.id IS UNIQUE",
        "CREATE CONSTRAINT region_id IF NOT EXISTS FOR (r:Region) REQUIRE r.id IS UNIQUE",
        "CREATE CONSTRAINT product_category_id IF NOT EXISTS FOR (p:ProductCategory) REQUIRE p.id IS UNIQUE",
        "CREATE CONSTRAINT time_period_id IF NOT EXISTS FOR (t:TimePeriod) REQUIRE t.id IS UNIQUE",
    ]
    indexes = [
        "CREATE INDEX driver_category IF NOT EXISTS FOR (d:Driver) ON (d.category)",
        "CREATE INDEX driver_validation_tier IF NOT EXISTS FOR (d:Driver) ON (d.validation_tier)",
        "CREATE INDEX event_category IF NOT EXISTS FOR (e:Event) ON (e.category)",
        "CREATE INDEX event_date IF NOT EXISTS FOR (e:Event) ON (e.start_date)",
        "CREATE VECTOR INDEX event_embedding IF NOT EXISTS FOR (e:Event) ON (e.embedding) OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}",
    ]
    run_statements(driver, constraints + indexes)


def init_kpis(driver) -> None:
    data = load_json("kpi_definitions.json")
    kpis = data.get("kpis", [])

    with driver.session() as session:
        for kpi in kpis:
            session.run(
                """
                MERGE (k:KPI {id: $id})
                SET k.name = $name,
                    k.name_kr = $name_kr,
                    k.category = $category,
                    k.description = $description,
                    k.erp_table = $erp_table,
                    k.erp_column = $erp_column,
                    k.unit = $unit,
                    k.layer = 1
                """,
                kpi,
            )
    print(f"Created/updated {len(kpis)} KPI nodes")


def iter_driver_groups() -> Iterable[Dict]:
    data = load_json("driver_definitions.json")
    for tier_key, group in data.get("drivers", {}).items():
        validation_tier = tier_key.upper().replace("TIER", "T")
        validation_method = group.get("validation_method", "")
        for driver in group.get("drivers", []):
            item = dict(driver)
            item["validation_tier"] = validation_tier
            item["validation_method"] = validation_method
            yield item


def init_drivers(driver) -> None:
    drivers = list(iter_driver_groups())

    with driver.session() as session:
        for item in drivers:
            session.run(
                """
                MERGE (d:Driver {id: $id})
                SET d.name = $name,
                    d.name_kr = $name_kr,
                    d.category = $category,
                    d.validation_tier = $validation_tier,
                    d.validation_method = $validation_method,
                    d.description = $description,
                    d.example_sentence = $example_sentence,
                    d.erp_table = $erp_table,
                    d.erp_column = $erp_column,
                    d.proxy_source = $proxy_source,
                    d.proxy_indicator = $proxy_indicator,
                    d.layer = 2
                """,
                {
                    "id": item.get("id"),
                    "name": item.get("name", ""),
                    "name_kr": item.get("name_kr", item.get("id", "")),
                    "category": item.get("category", ""),
                    "validation_tier": item.get("validation_tier", ""),
                    "validation_method": item.get("validation_method", ""),
                    "description": item.get("description", ""),
                    "example_sentence": item.get("example_sentence", ""),
                    "erp_table": item.get("erp_table"),
                    "erp_column": item.get("erp_column"),
                    "proxy_source": item.get("proxy_source"),
                    "proxy_indicator": item.get("proxy_indicator"),
                },
            )
    print(f"Created/updated {len(drivers)} Driver nodes")


def init_dimensions(driver) -> None:
    data = load_json("dimension_definitions.json")
    dimensions = data.get("dimensions", {})
    label_by_key = {
        "region": "Region",
        "product_category": "ProductCategory",
        "time_period": "TimePeriod",
    }

    total = 0
    with driver.session() as session:
        for key, group in dimensions.items():
            label = label_by_key.get(key)
            if not label:
                continue
            for node in group.get("nodes", []):
                session.run(
                    f"""
                    MERGE (d:{label}:Dimension {{id: $id}})
                    SET d += $props,
                        d.dimension_type = $dimension_type,
                        d.layer = 1
                    """,
                    {
                        "id": node["id"],
                        "props": node,
                        "dimension_type": key,
                    },
                )
                total += 1
    print(f"Created/updated {total} Dimension nodes")


def _confidence_from_strength(strength: str) -> float:
    return {"strong": 0.9, "medium": 0.7, "weak": 0.5}.get(strength, 0.6)


def init_kpi_driver_relations(driver) -> None:
    data = load_json("kpi_driver_whitelist.json")
    whitelists = data.get("whitelists", {})
    count = 0

    with driver.session() as session:
        for kpi_id, item in whitelists.items():
            for relation in item.get("allowed_drivers", []):
                strength = relation.get("strength", "medium")
                session.run(
                    """
                    MATCH (d:Driver {id: $driver_id})
                    MATCH (k:KPI {id: $kpi_id})
                    MERGE (d)-[r:HYPOTHESIZED_TO_AFFECT]->(k)
                    SET r.expected_polarity = $expected_polarity,
                        r.polarity = $expected_polarity,
                        r.effect_type = $effect_type,
                        r.status = $strength,
                        r.grade = $strength,
                        r.relationship_strength = $strength,
                        r.confidence = $confidence,
                        r.consensus_support = 1,
                        r.consensus_total = 1,
                        r.consensus_ratio = 1.0,
                        r.source_diversity = 1,
                        r.is_whitelisted = true,
                        r.whitelist_rationale = $rationale,
                        r.evidence_sentences = [$rationale],
                        r.sources = ['kpi_driver_whitelist.json']
                    """,
                    {
                        "driver_id": relation.get("driver_id"),
                        "kpi_id": kpi_id,
                        "expected_polarity": relation.get("expected_polarity"),
                        "effect_type": relation.get("effect_type", ""),
                        "strength": strength,
                        "confidence": _confidence_from_strength(strength),
                        "rationale": relation.get("rationale", ""),
                    },
                )
                count += 1
    print(f"Created/updated {count} Driver-KPI relationships")


def init_events(driver) -> None:
    with driver.session() as session:
        for event in SAMPLE_EVENTS:
            session.run(
                """
                MERGE (e:Event {id: $id})
                SET e.name = $name,
                    e.name_en = $name_en,
                    e.category = $category,
                    e.start_date = date($start_date),
                    e.is_ongoing = $is_ongoing,
                    e.severity = $severity,
                    e.evidence = $evidence,
                    e.source_titles = $source_titles,
                    e.source_urls = $source_urls,
                    e.sources = $sources,
                    e.source_confidence = $source_confidence,
                    e.layer = 3
                """,
                event,
            )

            for relation in event["drivers"]:
                session.run(
                    """
                    MATCH (e:Event {id: $event_id})
                    MATCH (d:Driver {id: $driver_id})
                    MERGE (e)-[r:AFFECTS]->(d)
                    SET r.polarity = $polarity,
                        r.weight = $weight,
                        r.confidence = $confidence,
                        r.impact_score = $impact_score
                    """,
                    {
                        "event_id": event["id"],
                        "driver_id": relation["id"],
                        "polarity": relation["polarity"],
                        "weight": relation["weight"],
                        "confidence": relation.get("confidence", 0.8),
                        "impact_score": relation.get("impact_score", 0.6),
                    },
                )

            for target_id in event.get("targets", []):
                session.run(
                    """
                    MATCH (e:Event {id: $event_id})
                    MATCH (d:Dimension {id: $target_id})
                    MERGE (e)-[:TARGETS]->(d)
                    """,
                    {"event_id": event["id"], "target_id": target_id},
                )

    rel_count = sum(len(event["drivers"]) for event in SAMPLE_EVENTS)
    target_count = sum(len(event.get("targets", [])) for event in SAMPLE_EVENTS)
    print(f"Created/updated {len(SAMPLE_EVENTS)} Event nodes")
    print(f"Created/updated {rel_count} Event-Driver relationships")
    print(f"Created/updated {target_count} Event-Dimension relationships")


def print_summary(driver) -> None:
    with driver.session() as session:
        node_result = session.run(
            """
            MATCH (n)
            RETURN labels(n)[0] as label, count(*) as count
            ORDER BY label
            """
        )
        print("\n=== Nodes ===")
        for record in node_result:
            print(f"  {record['label']}: {record['count']}")

        rel_result = session.run(
            """
            MATCH ()-[r]->()
            RETURN type(r) as rel_type, count(*) as count
            ORDER BY rel_type
            """
        )
        print("\n=== Relationships ===")
        for record in rel_result:
            print(f"  {record['rel_type']}: {record['count']}")


def main() -> None:
    settings = get_settings()
    uri = os.getenv("NEO4J_URI", settings.neo4j_uri)
    user = os.getenv("NEO4J_USER", settings.neo4j_user)
    password = os.getenv("NEO4J_PASSWORD", settings.neo4j_password or "password123")

    print(f"Connecting to Neo4j at {uri}")
    if not wait_for_neo4j(uri, user, password):
        print("Failed to connect to Neo4j")
        sys.exit(1)

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        init_constraints(driver)
        init_kpis(driver)
        init_drivers(driver)
        init_dimensions(driver)
        init_kpi_driver_relations(driver)
        init_events(driver)
        print_summary(driver)
        print("\nNeo4j initialization complete.")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
