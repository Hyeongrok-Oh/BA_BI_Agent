"""Vector 저장소 - Event Embedding 생성 및 저장"""

import os
from typing import List, Optional
from dataclasses import dataclass

from .models import EventNode, EventChunk, Layer3Graph


@dataclass
class EmbeddingConfig:
    """Embedding 설정"""
    model: str = "text-embedding-3-small"
    dimensions: int = 1536
    chunk_size: int = 500
    chunk_overlap: int = 50


class EmbeddingGenerator:
    """OpenAI Embedding 생성"""

    def __init__(self, api_key: Optional[str] = None, config: Optional[EmbeddingConfig] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY 필요")
        self.config = config or EmbeddingConfig()

    def generate_embedding(self, text: str) -> List[float]:
        """단일 텍스트 임베딩 생성"""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai 패키지 필요: pip install openai")

        client = OpenAI(api_key=self.api_key)

        response = client.embeddings.create(
            model=self.config.model,
            input=text
        )

        return response.data[0].embedding

    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """배치 임베딩 생성"""
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai 패키지 필요: pip install openai")

        client = OpenAI(api_key=self.api_key)

        response = client.embeddings.create(
            model=self.config.model,
            input=texts
        )

        return [item.embedding for item in response.data]


class EventChunker:
    """Event 콘텐츠 청킹"""

    def __init__(self, chunk_size: int = 500, overlap: int = 50):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_event(self, event: EventNode) -> List[EventChunk]:
        """Event를 청크로 분할"""
        # Event 콘텐츠 생성
        content = self._create_event_content(event)

        # 청킹
        chunks = []
        start = 0
        chunk_index = 0

        while start < len(content):
            end = start + self.chunk_size
            chunk_text = content[start:end]

            # 문장 경계에서 자르기 시도
            if end < len(content):
                last_period = chunk_text.rfind(".")
                last_space = chunk_text.rfind(" ")
                if last_period > self.chunk_size // 2:
                    chunk_text = chunk_text[:last_period + 1]
                    end = start + last_period + 1
                elif last_space > self.chunk_size // 2:
                    chunk_text = chunk_text[:last_space]
                    end = start + last_space

            chunks.append(EventChunk(
                event_id=event.id,
                chunk_index=chunk_index,
                content=chunk_text.strip(),
                metadata={
                    "event_name": event.name,
                    "category": event.category.value,
                    "severity": event.severity.value
                }
            ))

            chunk_index += 1
            start = end - self.overlap if end < len(content) else end

        return chunks

    def _create_event_content(self, event: EventNode) -> str:
        """Event에서 검색 가능한 콘텐츠 생성"""
        parts = []

        # 기본 정보
        parts.append(f"이벤트: {event.name}")
        if event.name_en:
            parts.append(f"({event.name_en})")
        parts.append(f"카테고리: {event.category.value}")
        parts.append(f"심각도: {event.severity.value}")

        if event.start_date:
            parts.append(f"발생일: {event.start_date}")
        if event.is_ongoing:
            parts.append("상태: 진행중")

        # 영향 Factor
        if event.factor_relations:
            factors = [
                f"{r.factor_name}({r.impact_type.value})"
                for r in event.factor_relations
            ]
            parts.append(f"영향 요인: {', '.join(factors)}")

        # 타겟 Dimension
        if event.dimension_relations:
            dims = [r.dimension_name for r in event.dimension_relations]
            parts.append(f"타겟 지역/제품: {', '.join(dims)}")

        # 증거/설명
        if event.evidence:
            parts.append(f"설명: {event.evidence}")

        # 뉴스 소스 snippet
        for source in event.sources[:3]:
            if source.snippet:
                parts.append(f"뉴스: {source.snippet}")

        return " ".join(parts)


class VectorStore:
    """Vector 저장소"""

    def __init__(self, config: Optional[EmbeddingConfig] = None):
        self.config = config or EmbeddingConfig()
        self.embedder = EmbeddingGenerator(config=self.config)
        self.chunker = EventChunker(
            chunk_size=self.config.chunk_size,
            overlap=self.config.chunk_overlap
        )

    def process_events(
        self,
        events: List[EventNode],
        verbose: bool = True
    ) -> List[EventChunk]:
        """Event들을 청킹하고 임베딩 생성"""
        all_chunks = []

        if verbose:
            print(f"=== Vector 처리 시작 ===")
            print(f"총 Event: {len(events)}개")

        # 청킹
        for event in events:
            chunks = self.chunker.chunk_event(event)
            all_chunks.extend(chunks)

        if verbose:
            print(f"총 청크: {len(all_chunks)}개")

        # 배치 임베딩 생성
        batch_size = 100
        for i in range(0, len(all_chunks), batch_size):
            batch = all_chunks[i:i + batch_size]
            texts = [c.content for c in batch]

            try:
                embeddings = self.embedder.generate_embeddings_batch(texts)
                for chunk, emb in zip(batch, embeddings):
                    chunk.embedding = emb

                if verbose:
                    print(f"  임베딩 생성: {i + len(batch)}/{len(all_chunks)}")

            except Exception as e:
                print(f"  임베딩 오류: {e}")

        if verbose:
            embedded_count = sum(1 for c in all_chunks if c.embedding)
            print(f"\n=== 처리 완료 ===")
            print(f"임베딩 생성: {embedded_count}/{len(all_chunks)}개")

        return all_chunks

    def add_chunks_to_graph(self, graph: Layer3Graph, chunks: List[EventChunk]) -> None:
        """그래프에 청크 추가"""
        graph.chunks = chunks


def process_layer3_vectors(graph: Layer3Graph, verbose: bool = True) -> Layer3Graph:
    """Layer 3 그래프에 Vector 추가"""
    store = VectorStore()
    chunks = store.process_events(graph.events, verbose=verbose)
    store.add_chunks_to_graph(graph, chunks)
    return graph
