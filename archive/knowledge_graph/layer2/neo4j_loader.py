"""Layer 2 Neo4j 로더 - Factor 노드 및 관계 적재

v2 개선사항:
- Factor 노드에 동적 상태 속성 추가 (current_trend, change_rate, impact_direction)
- 관계에 polarity/weight 속성 추가
"""

import json
from pathlib import Path
from typing import Optional

from neo4j import GraphDatabase

import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
from knowledge_graph.config import BaseConfig


class Layer2Neo4jLoader:
    """Layer 2 데이터를 Neo4j에 적재"""

    def __init__(self, config: Optional[BaseConfig] = None):
        self.config = config or BaseConfig()
        self.driver = GraphDatabase.driver(
            self.config.neo4j_uri,
            auth=(self.config.neo4j_user, self.config.neo4j_password)
        )

    def close(self):
        self.driver.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def setup_constraints(self):
        """Factor 노드 제약조건 설정"""
        constraints = [
            "CREATE CONSTRAINT factor_id IF NOT EXISTS FOR (f:Factor) REQUIRE f.id IS UNIQUE",
        ]

        with self.driver.session(database=self.config.neo4j_database) as session:
            for constraint in constraints:
                try:
                    session.run(constraint)
                except Exception as e:
                    print(f"Constraint 설정 중 오류 (무시): {e}")

    def clear_layer2_data(self):
        """기존 Layer 2 데이터 삭제 (모든 관계 먼저 삭제)"""
        with self.driver.session(database=self.config.neo4j_database) as session:
            # 1. Factor의 모든 관계 삭제 (AFFECTS, IMPACTS 등)
            result = session.run("MATCH (f:Factor)-[r]-() DELETE r RETURN count(r) as count")
            rel_count = result.single()["count"]
            print(f"  관계 삭제: {rel_count}개")

            # 2. Factor 노드 삭제
            result = session.run("MATCH (f:Factor) DELETE f RETURN count(f) as count")
            node_count = result.single()["count"]
            print(f"  Factor 노드 삭제: {node_count}개")

    def load_factors(self, factors: list) -> int:
        """Factor 노드 생성 (v2: 모든 출처 저장 + 동적 상태 속성)"""
        query = """
        UNWIND $factors AS factor
        MERGE (f:Factor {id: factor.id})
        SET f.name = factor.name,
            f.category = factor.category,
            f.mention_count = factor.mention_count,
            f.original_names = factor.original_names,
            // v2: 모든 출처 저장 (문서명 리스트)
            f.sources = COALESCE(factor.sources, []),
            f.source_count = CASE WHEN factor.sources IS NOT NULL THEN size(factor.sources) ELSE 0 END,
            // v2: 동적 상태 속성
            f.current_trend = COALESCE(factor.current_trend, 'unknown'),
            f.change_rate = factor.change_rate,
            f.impact_direction = COALESCE(factor.impact_direction, '중립'),
            f.state_updated_at = datetime()
        RETURN count(f) as count
        """

        with self.driver.session(database=self.config.neo4j_database) as session:
            result = session.run(query, factors=factors)
            record = result.single()
            return record["count"] if record else 0

    def load_relations(self, relations: list, max_mentions: int = 1) -> int:
        """Factor → Anchor 관계 생성 (v2: polarity/weight + 모든 출처 저장)"""
        import json

        # sources를 JSON 문자열로 변환 (Neo4j는 복잡한 객체 저장 불가)
        relations_converted = []
        for rel in relations:
            rel_copy = dict(rel)
            if 'sources' in rel_copy and rel_copy['sources']:
                rel_copy['sources_json'] = json.dumps(rel_copy['sources'], ensure_ascii=False)
            else:
                rel_copy['sources_json'] = '[]'
            relations_converted.append(rel_copy)

        # Anchor ID는 이미 revenue, quantity, cost로 되어 있음
        query = """
        UNWIND $relations AS rel
        MATCH (f:Factor {id: rel.factor_id})
        MATCH (a:Anchor {id: rel.anchor_id})
        MERGE (f)-[r:AFFECTS]->(a)
        SET r.type = rel.relation_type,
            r.mention_count = rel.mention_count,
            r.source_count = rel.source_count,
            // v2: 모든 출처를 JSON 문자열로 저장
            r.sources = rel.sources_json,
            // v2: polarity/weight 속성
            r.polarity = COALESCE(rel.polarity, 0),
            // weight = mention_count 기반 정규화 (0.3 ~ 1.0)
            r.weight = CASE
                WHEN $max_mentions <= 0 THEN 0.5
                ELSE round((0.3 + 0.7 * (toFloat(rel.mention_count) / $max_mentions)) * 100) / 100
            END,
            r.confidence = COALESCE(rel.confidence, 0.8)
        RETURN count(r) as count
        """

        with self.driver.session(database=self.config.neo4j_database) as session:
            result = session.run(query, relations=relations_converted, max_mentions=max_mentions)
            record = result.single()
            return record["count"] if record else 0

    def verify_load(self) -> dict:
        """적재 결과 검증 (v2: polarity/weight 포함)"""
        queries = {
            "factor_count": "MATCH (f:Factor) RETURN count(f) as count",
            "relation_count": "MATCH (:Factor)-[r:AFFECTS]->(:Anchor) RETURN count(r) as count",
            "top_factors": """
                MATCH (f:Factor)
                RETURN f.name as name, f.mention_count as mentions,
                       f.current_trend as trend, f.change_rate as change_rate
                ORDER BY f.mention_count DESC
                LIMIT 5
            """,
            "top_relations": """
                MATCH (f:Factor)-[r:AFFECTS]->(a:Anchor)
                RETURN f.name as factor, a.name as anchor,
                       r.polarity as polarity, r.weight as weight,
                       r.mention_count as mentions
                ORDER BY r.mention_count DESC
                LIMIT 5
            """,
        }

        results = {}
        with self.driver.session(database=self.config.neo4j_database) as session:
            for key, query in queries.items():
                result = session.run(query)
                if key.endswith("_count"):
                    record = result.single()
                    results[key] = record["count"] if record else 0
                else:
                    results[key] = [dict(record) for record in result]

        return results


def load_layer2_to_neo4j(
    input_file: str = "layer2_normalized.json",
    clear_existing: bool = True
):
    """Layer 2 정규화 데이터를 Neo4j에 적재 (v2: 모든 출처 + mention_count 기반 weight)"""
    layer2_dir = Path(__file__).parent
    input_path = layer2_dir / input_file

    # 데이터 로드
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    factors = data.get("factors", [])
    relations = data.get("relations", [])

    # v2: weight 계산을 위한 max_mentions 계산
    max_mentions = max((r.get("mention_count", 1) for r in relations), default=1)

    print("=== Layer 2 Neo4j 적재 시작 (v2: 출처 + polarity/weight) ===")
    print(f"입력 파일: {input_path}")
    print(f"Factor 수: {len(factors)}")
    print(f"관계 수: {len(relations)}")
    print(f"최대 언급 횟수: {max_mentions}")

    with Layer2Neo4jLoader() as loader:
        # 제약조건 설정
        print("\n1. 제약조건 설정...")
        loader.setup_constraints()

        # 기존 데이터 삭제
        if clear_existing:
            print("\n2. 기존 Layer 2 데이터 삭제...")
            loader.clear_layer2_data()

        # Factor 노드 생성
        print("\n3. Factor 노드 생성 (모든 출처 포함)...")
        factor_count = loader.load_factors(factors)
        print(f"  생성된 Factor: {factor_count}개")

        # 관계 생성 (mention_count 기반 weight)
        print("\n4. Factor → Anchor 관계 생성 (polarity + weight)...")
        relation_count = loader.load_relations(relations, max_mentions=max_mentions)
        print(f"  생성된 관계: {relation_count}개")

        # 검증
        print("\n5. 적재 결과 검증...")
        verification = loader.verify_load()

        print(f"\n=== 적재 완료 ===")
        print(f"Factor 노드: {verification['factor_count']}개")
        print(f"AFFECTS 관계: {verification['relation_count']}개")

        print("\n--- 상위 Factor ---")
        for f in verification.get("top_factors", []):
            trend = f.get('trend', 'unknown')
            change = f.get('change_rate')
            change_str = f" ({change:+.1f}%)" if change else ""
            print(f"  {f['name']}: {f['mentions']}회, 추세: {trend}{change_str}")

        print("\n--- 상위 관계 (v2: polarity/weight) ---")
        for r in verification.get("top_relations", []):
            polarity = r.get('polarity', 0)
            polarity_str = "정상관(+1)" if polarity > 0 else "역상관(-1)" if polarity < 0 else "미지정"
            weight = r.get('weight', 1.0)
            print(f"  {r['factor']} --[polarity:{polarity_str}, weight:{weight:.1f}]--> {r['anchor']}: {r['mentions']}회")

    return verification


if __name__ == "__main__":
    load_layer2_to_neo4j()
