"""Build Neo4j graph from Layer 1 data."""

import json
from typing import Dict, List

from .models import Layer1Graph, DimensionNode, AnchorNode
from .config import Config


class GraphBuilder:
    """Builds Neo4j knowledge graph for Layer 1."""

    def __init__(self, config: Config):
        self.config = config
        self.driver = None

    def connect(self) -> None:
        try:
            from neo4j import GraphDatabase
            self.driver = GraphDatabase.driver(
                self.config.neo4j_uri,
                auth=(self.config.neo4j_user, self.config.neo4j_password)
            )
            self.driver.verify_connectivity()
        except ImportError:
            raise ImportError("neo4j package not installed. Run: pip install neo4j")

    def disconnect(self) -> None:
        if self.driver:
            self.driver.close()
            self.driver = None

    def build(self, graph: Layer1Graph) -> Dict[str, int]:
        """Build the complete Layer 1 graph in Neo4j."""
        self.connect()
        try:
            self._clear_graph()
            self._create_constraints()

            # Create nodes
            dim_count = self._create_dimension_nodes(graph.dimensions)
            anchor_count = self._create_anchor_nodes(graph.anchors)

            # Create relationships
            child_of_count = self._create_child_of_relations(graph.dimensions)

            return {
                "dimensions": dim_count,
                "anchors": anchor_count,
                "child_of": child_of_count,
            }
        finally:
            self.disconnect()

    def _clear_graph(self) -> None:
        with self.driver.session(database=self.config.neo4j_database) as session:
            session.run("MATCH (n) DETACH DELETE n")

    def _create_constraints(self) -> None:
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Dimension) REQUIRE d.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Anchor) REQUIRE a.id IS UNIQUE",
        ]
        with self.driver.session(database=self.config.neo4j_database) as session:
            for constraint in constraints:
                try:
                    session.run(constraint)
                except Exception:
                    pass

    def _create_dimension_nodes(self, dimensions: List[DimensionNode]) -> int:
        """Create Dimension nodes with their type as additional label."""
        with self.driver.session(database=self.config.neo4j_database) as session:
            for dim in dimensions:
                # Create node with both :Dimension and :DimensionType labels
                # properties를 JSON 문자열로 저장
                session.run(f"""
                    CREATE (d:Dimension:{dim.dimension_type.value} {{
                        id: $id,
                        name: $name,
                        dimension_type: $dimension_type,
                        properties_json: $properties_json
                    }})
                """,
                    id=dim.id,
                    name=dim.name,
                    dimension_type=dim.dimension_type.value,
                    properties_json=json.dumps(dim.properties, ensure_ascii=False),
                )
        return len(dimensions)

    def _create_anchor_nodes(self, anchors: List[AnchorNode]) -> int:
        """Create Anchor nodes."""
        with self.driver.session(database=self.config.neo4j_database) as session:
            for anchor in anchors:
                session.run("""
                    CREATE (a:Anchor {
                        id: $id,
                        name: $name,
                        metric_type: $metric_type,
                        description: $description,
                        source_table: $source_table,
                        source_column: $source_column
                    })
                """,
                    id=anchor.id,
                    name=anchor.name,
                    metric_type=anchor.metric_type.value,
                    description=anchor.description,
                    source_table=anchor.source_table,
                    source_column=anchor.source_column,
                )
        return len(anchors)

    def _create_child_of_relations(self, dimensions: List[DimensionNode]) -> int:
        """Create CHILD_OF relationships for dimension hierarchy."""
        count = 0
        with self.driver.session(database=self.config.neo4j_database) as session:
            for dim in dimensions:
                if dim.parent_id:
                    result = session.run("""
                        MATCH (child:Dimension {id: $child_id})
                        MATCH (parent:Dimension {id: $parent_id})
                        CREATE (child)-[:CHILD_OF]->(parent)
                        RETURN count(*) AS cnt
                    """,
                        child_id=dim.id,
                        parent_id=dim.parent_id,
                    )
                    record = result.single()
                    if record:
                        count += record["cnt"]
        return count

    def get_statistics(self) -> Dict[str, int]:
        """Get current graph statistics."""
        self.connect()
        try:
            with self.driver.session(database=self.config.neo4j_database) as session:
                result = session.run("""
                    MATCH (d:Dimension) WITH count(d) AS dimensions
                    MATCH (a:Anchor) WITH dimensions, count(a) AS anchors
                    MATCH ()-[r:CHILD_OF]->() WITH dimensions, anchors, count(r) AS child_of
                    RETURN dimensions, anchors, child_of
                """)
                record = result.single()
                return {
                    "dimensions": record["dimensions"],
                    "anchors": record["anchors"],
                    "child_of": record["child_of"],
                }
        finally:
            self.disconnect()
