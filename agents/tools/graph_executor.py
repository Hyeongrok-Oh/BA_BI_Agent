"""
Graph Executor Tool - Cypher 쿼리 실행만 담당

특징:
- 입력: Cypher 쿼리 문자열
- 출력: 노드/관계 리스트
- 결정권 없음 (어떤 쿼리를 실행할지는 Agent가 결정)
"""

import os
from typing import List, Dict, Any
from neo4j import GraphDatabase

from config.settings import get_settings
from ..base import BaseTool, ToolResult
from .query_guard import validate_read_only_cypher


class GraphExecutor(BaseTool):
    """Neo4j Cypher 쿼리 실행 Tool"""

    name = "graph_executor"
    description = "Neo4j 데이터베이스에서 Cypher 쿼리를 실행하고 결과를 반환합니다."

    def __init__(
        self,
        uri: str = None,
        user: str = None,
        password: str = None,
        database: str = "neo4j"
    ):
        settings = get_settings()
        self.uri = uri or os.getenv("NEO4J_URI") or settings.neo4j_uri
        self.user = user or os.getenv("NEO4J_USER") or settings.neo4j_user
        self.password = password or os.getenv("NEO4J_PASSWORD") or settings.neo4j_password
        self.database = database or settings.neo4j_database
        self._driver = None

    @property
    def driver(self):
        """Lazy driver initialization"""
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password)
            )
        return self._driver

    def close(self):
        """드라이버 종료"""
        if self._driver:
            self._driver.close()
            self._driver = None

    def execute(self, query: str, params: Dict = None) -> ToolResult:
        """
        Cypher 쿼리 실행

        Args:
            query: 실행할 Cypher 쿼리 문자열
            params: 쿼리 파라미터 딕셔너리

        Returns:
            ToolResult with records list or error
        """
        if not query or not query.strip():
            return ToolResult(success=False, error="빈 쿼리입니다.")

        guard_error = validate_read_only_cypher(query)
        if guard_error:
            return ToolResult(success=False, error=f"Cypher guard: {guard_error}")

        params = params or {}

        try:
            with self.driver.session(database=self.database) as session:
                result = session.run(query, **params)
                records = []
                for record in result:
                    record_dict = {}
                    for key in record.keys():
                        value = record[key]
                        # Neo4j Node/Relationship 객체 처리
                        if hasattr(value, 'labels'):  # Node
                            record_dict[key] = {
                                "id": value.element_id,
                                "labels": list(value.labels),
                                **dict(value)  # Node properties
                            }
                        elif hasattr(value, 'type'):  # Relationship
                            record_dict[key] = {
                                "type": value.type,
                                **dict(value)  # Relationship properties
                            }
                        else:
                            record_dict[key] = value
                    records.append(record_dict)

                return ToolResult(
                    success=True,
                    data=records
                )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Cypher 실행 오류: {str(e)}"
            )

    def get_schema(self) -> str:
        """그래프 스키마 정보 반환"""
        schema_query = """
        CALL db.schema.visualization()
        """

        # 노드 라벨 조회
        labels_result = self.execute("CALL db.labels()")
        labels = [r['label'] for r in labels_result.data] if labels_result.success else []

        # 관계 타입 조회
        rels_result = self.execute("CALL db.relationshipTypes()")
        rel_types = [r['relationshipType'] for r in rels_result.data] if rels_result.success else []

        schema_lines = [
            "=== GRAPH SCHEMA ===\n",
            "Node Labels:",
            *[f"  - {label}" for label in labels],
            "\nRelationship Types:",
            *[f"  - {rel}" for rel in rel_types]
        ]

        return "\n".join(schema_lines)

    def get_node_count(self, label: str = None) -> int:
        """노드 수 반환"""
        if label:
            query = f"MATCH (n:{label}) RETURN count(n) as count"
        else:
            query = "MATCH (n) RETURN count(n) as count"

        result = self.execute(query)
        if result.success and result.data:
            return result.data[0]['count']
        return 0

    def get_sample_nodes(self, label: str, limit: int = 5) -> List[Dict]:
        """샘플 노드 반환"""
        query = f"MATCH (n:{label}) RETURN n LIMIT {limit}"
        result = self.execute(query)
        return result.data if result.success else []
