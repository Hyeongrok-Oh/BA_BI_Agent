"""
Vector Search Tool - Neo4j Vector Index를 사용한 유사도 검색

특징:
- 입력: 자연어 쿼리
- 출력: 유사한 Event 노드 리스트
- OpenAI Embedding + Neo4j Vector Index 사용
"""

import os
from typing import List, Dict, Any
from dataclasses import dataclass
from neo4j import GraphDatabase
from openai import OpenAI

from config.settings import get_settings
from ..base import BaseTool, ToolResult


@dataclass
class SimilarEvent:
    """유사 이벤트 결과"""
    name: str
    category: str
    evidence: str
    severity: str
    score: float  # 유사도 점수
    related_factors: List[str]
    source_urls: List[str] = None  # 출처 URL
    source_titles: List[str] = None  # 출처 제목


class VectorSearchTool(BaseTool):
    """Neo4j Vector 유사도 검색 Tool"""

    name = "vector_search"
    description = "자연어 쿼리와 유사한 Event를 Neo4j Vector Index에서 검색합니다."

    def __init__(
        self,
        uri: str = None,
        user: str = None,
        password: str = None,
        database: str = "neo4j",
        api_key: str = None
    ):
        settings = get_settings()
        self.uri = uri or os.getenv("NEO4J_URI") or settings.neo4j_uri
        self.user = user or os.getenv("NEO4J_USER") or settings.neo4j_user
        self.password = password or os.getenv("NEO4J_PASSWORD") or settings.neo4j_password
        self.database = database or settings.neo4j_database
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or settings.openai_api_key

        self._driver = None
        self._openai = None

    @property
    def driver(self):
        """Lazy driver initialization"""
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password)
            )
        return self._driver

    @property
    def openai(self):
        """Lazy OpenAI client initialization"""
        if self._openai is None:
            self._openai = OpenAI(api_key=self.api_key)
        return self._openai

    def close(self):
        """드라이버 종료"""
        if self._driver:
            self._driver.close()
            self._driver = None

    def _get_embedding(self, text: str) -> List[float]:
        """텍스트를 embedding으로 변환"""
        response = self.openai.embeddings.create(
            input=text,
            model="text-embedding-3-small"
        )
        return response.data[0].embedding

    def execute(self, query: str, top_k: int = 5) -> ToolResult:
        """
        벡터 유사도 검색 실행

        Args:
            query: 검색할 자연어 쿼리
            top_k: 반환할 최대 결과 수

        Returns:
            ToolResult with SimilarEvent list
        """
        if not query or not query.strip():
            return ToolResult(success=False, error="빈 쿼리입니다.")

        try:
            # 1. Query를 embedding으로 변환
            query_embedding = self._get_embedding(query)

            # 2. Neo4j Vector Index 검색
            cypher = """
            CALL db.index.vector.queryNodes('event_embedding', $top_k, $embedding)
            YIELD node, score
            OPTIONAL MATCH (node)-[r:AFFECTS]->(d:Driver)
            WITH node, score, collect(DISTINCT d.name_kr) as factors
            RETURN
                node.name as name,
                node.category as category,
                node.evidence as evidence,
                node.severity as severity,
                score,
                factors,
                node.source_urls as source_urls,
                node.source_titles as source_titles
            ORDER BY score DESC
            """
            events = []

            with self.driver.session(database=self.database) as session:
                result = session.run(
                    cypher,
                    embedding=query_embedding,
                    top_k=top_k
                )

                for record in result:
                    events.append(SimilarEvent(
                        name=record["name"] or "",
                        category=record["category"] or "",
                        evidence=record["evidence"] or "",
                        severity=record["severity"] or "medium",
                        score=record["score"],
                        related_factors=record["factors"] or [],
                        source_urls=record["source_urls"] or [],
                        source_titles=record["source_titles"] or []
                    ))

            return ToolResult(
                success=True,
                data=events
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"벡터 검색 오류: {str(e)}"
            )

    def search(self, query: str, top_k: int = 5) -> List[SimilarEvent]:
        """
        간편 검색 메서드

        Args:
            query: 검색 쿼리
            top_k: 결과 수

        Returns:
            SimilarEvent 리스트
        """
        result = self.execute(query, top_k)
        if result.success:
            return result.data
        return []

    def search_by_category(
        self,
        query: str,
        category: str,
        top_k: int = 5
    ) -> List[SimilarEvent]:
        """
        카테고리 필터링 검색

        Args:
            query: 검색 쿼리
            category: 필터링할 카테고리 (policy, market, macro_economy 등)
            top_k: 결과 수
        """
        try:
            query_embedding = self._get_embedding(query)

            cypher = """
            CALL db.index.vector.queryNodes('event_embedding', $top_k * 2, $embedding)
            YIELD node, score
            WHERE node.category = $category
            OPTIONAL MATCH (node)-[r:INCREASES|DECREASES]->(f:Factor)
            WITH node, score, collect(DISTINCT f.name) as factors
            RETURN
                node.name as name,
                node.category as category,
                node.evidence as evidence,
                node.severity as severity,
                score,
                factors,
                node.source_urls as source_urls,
                node.source_titles as source_titles
            ORDER BY score DESC
            LIMIT $top_k
            """

            events = []

            with self.driver.session(database=self.database) as session:
                result = session.run(
                    cypher,
                    embedding=query_embedding,
                    category=category,
                    top_k=top_k
                )

                for record in result:
                    events.append(SimilarEvent(
                        name=record["name"] or "",
                        category=record["category"] or "",
                        evidence=record["evidence"] or "",
                        severity=record["severity"] or "medium",
                        score=record["score"],
                        related_factors=record["factors"] or [],
                        source_urls=record["source_urls"] or [],
                        source_titles=record["source_titles"] or []
                    ))

            return events

        except Exception:
            return []
