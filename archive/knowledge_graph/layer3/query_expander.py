"""Upstream Factor 기반 동적 검색 쿼리 생성"""

import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

sys.path.append(str(Path(__file__).parent.parent.parent))
from knowledge_graph.config import BaseConfig

from neo4j import GraphDatabase


@dataclass
class UpstreamRelation:
    """Upstream → Core Factor 관계"""
    upstream_factor: str
    core_factor: str
    polarity: int  # +1 or -1
    mention_count: int


# Factor별 검색 키워드 확장 매핑
FACTOR_KEYWORDS = {
    # TV 수요 관련
    "TV 수요": ["TV 판매", "TV 출하량", "TV 시장"],
    "소비 심리": ["소비자 심리", "소비심리지수", "소비 위축"],
    "경쟁 심화": ["가격 경쟁", "점유율 경쟁", "프로모션 전쟁"],

    # 비용 관련
    "패널 가격": ["LCD 패널 가격", "OLED 패널 가격", "디스플레이 패널"],
    "원재료 가격": ["원자재 가격", "구리 가격", "레진 가격"],
    "물류비": ["물류 비용", "운송비", "배송비"],
    "해상 운임": ["컨테이너 운임", "해운 운임", "SCFI"],
    "인건비": ["인건비 상승", "최저임금", "노동 비용"],

    # 거시경제
    "환율": ["원달러 환율", "환율 변동", "달러 강세"],
    "금리": ["기준금리", "금리 인상", "금리 인하"],
    "경기": ["경기 침체", "경기 회복", "GDP"],
    "인플레이션": ["물가 상승", "인플레", "CPI"],

    # 정책/규제
    "관세": ["관세율", "수입 관세", "무역 관세"],
    "무역 정책": ["무역 분쟁", "무역 규제", "수출입 규제"],

    # 제품/기술
    "OLED": ["OLED TV", "올레드", "WOLED"],
    "프리미엄 제품": ["프리미엄 TV", "고가 TV", "하이엔드"],
    "WebOS": ["웹OS", "스마트TV 플랫폼", "TV 플랫폼"],
    "B2B 사업": ["B2B", "기업 향", "상업용"],
}

# Upstream Factor 검색어 확장
UPSTREAM_KEYWORDS = {
    "스포츠 이벤트": ["올림픽", "월드컵", "유로", "슈퍼볼"],
    "AI 데이터센터": ["AI 서버", "데이터센터", "GPU 서버"],
    "전기차 수요": ["EV 시장", "전기차 판매", "전기차 배터리"],
    "무역전쟁": ["미중 무역", "무역 분쟁", "관세 전쟁"],
    "해상물류 지연": ["홍해 사태", "수에즈 운하", "해운 대란"],
    "전방산업 재고조정": ["반도체 재고", "IT 재고", "부품 재고"],
    "IT 수요": ["PC 수요", "모니터 수요", "IT 시장"],
    "미국 시장": ["미국 가전", "북미 TV", "US TV market"],
    "히트펌프 수요": ["히트펌프", "열펌프", "난방기기"],
    "전방 수요 감소": ["수요 부진", "수요 위축", "수요 둔화"],
}


class UpstreamQueryExpander:
    """Upstream Factor 기반 검색 쿼리 동적 생성"""

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

    def get_upstream_relations(self) -> List[UpstreamRelation]:
        """Neo4j에서 Upstream → Core Factor 관계 조회"""
        query = """
        MATCH (u:Factor)-[r:INFLUENCES]->(c:Factor)
        WHERE (u.category = 'upstream' OR u.is_core = false)
          AND (c.is_core = true OR c.is_core IS NULL)
          AND NOT (c.category = 'upstream')
        RETURN u.name as upstream, c.name as core,
               r.polarity as polarity, r.mention_count as mentions
        ORDER BY r.mention_count DESC
        """

        relations = []
        with self.driver.session(database=self.config.neo4j_database) as session:
            result = session.run(query)
            for record in result:
                relations.append(UpstreamRelation(
                    upstream_factor=record["upstream"],
                    core_factor=record["core"],
                    polarity=record["polarity"] or 1,
                    mention_count=record["mentions"] or 1
                ))

        return relations

    def expand_queries(
        self,
        max_queries: int = 100,
        include_english: bool = False,
        date_range: Optional[List[str]] = None
    ) -> List[str]:
        """검색 쿼리 동적 생성

        Args:
            max_queries: 최대 쿼리 수
            include_english: 영문 쿼리 포함 여부
            date_range: 월별 날짜 리스트 (예: ["2025년 6월", "2025년 7월"])

        Returns:
            생성된 검색 쿼리 리스트
        """
        relations = self.get_upstream_relations()
        queries = []
        seen = set()

        for rel in relations:
            # 1. 기본 조합: upstream + core
            q1 = f"{rel.upstream_factor} {rel.core_factor}"
            if q1 not in seen:
                queries.append(q1)
                seen.add(q1)

            # 2. upstream + TV/LG전자 맥락
            for context in ["TV", "LG전자", "가전"]:
                q2 = f"{rel.upstream_factor} {context}"
                if q2 not in seen:
                    queries.append(q2)
                    seen.add(q2)

            # 3. upstream 키워드 확장
            upstream_keywords = UPSTREAM_KEYWORDS.get(rel.upstream_factor, [])
            for keyword in upstream_keywords[:2]:  # 최대 2개
                q3 = f"{keyword} TV"
                if q3 not in seen:
                    queries.append(q3)
                    seen.add(q3)

            # 4. core factor 키워드 확장
            core_keywords = FACTOR_KEYWORDS.get(rel.core_factor, [])
            for keyword in core_keywords[:1]:  # 최대 1개
                q4 = f"{rel.upstream_factor} {keyword}"
                if q4 not in seen:
                    queries.append(q4)
                    seen.add(q4)

            if len(queries) >= max_queries:
                break

        # 추가 고정 쿼리 (중요 이벤트 검색용)
        fixed_queries = [
            "LG전자 TV 실적",
            "글로벌 TV 시장 전망",
            "TV 패널 가격 동향",
            "미국 관세 가전",
            "트럼프 관세 TV",
            "중국 TV 시장",
            "OLED TV 판매",
            "삼성 LG TV 경쟁",
        ]

        for q in fixed_queries:
            if q not in seen and len(queries) < max_queries:
                queries.append(q)
                seen.add(q)

        # 날짜 범위가 지정된 경우, 각 쿼리에 월별 날짜 추가
        if date_range:
            dated_queries = []
            for month in date_range:
                for q in queries:
                    dated_q = f"{q} {month}"
                    if dated_q not in seen:
                        dated_queries.append(dated_q)
                        seen.add(dated_q)
            # 날짜 없는 쿼리도 포함 (최신 결과용)
            return (queries + dated_queries)[:max_queries]

        return queries[:max_queries]

    def preview(self, limit: int = 30):
        """생성될 쿼리 미리보기"""
        print("=" * 60)
        print("Upstream Factor 기반 검색 쿼리 미리보기")
        print("=" * 60)

        relations = self.get_upstream_relations()
        print(f"\nUpstream → Core 관계: {len(relations)}개")

        queries = self.expand_queries(max_queries=limit)
        print(f"\n생성된 쿼리 ({len(queries)}개):")
        for i, q in enumerate(queries, 1):
            print(f"  {i:2d}. {q}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Upstream Factor 기반 쿼리 생성")
    parser.add_argument("--preview", action="store_true", help="쿼리 미리보기")
    parser.add_argument("--max", type=int, default=100, help="최대 쿼리 수")
    parser.add_argument("--output", type=str, help="쿼리 저장 파일")
    args = parser.parse_args()

    with UpstreamQueryExpander() as expander:
        if args.preview:
            expander.preview(limit=args.max)
        else:
            queries = expander.expand_queries(max_queries=args.max)

            if args.output:
                import json
                with open(args.output, "w", encoding="utf-8") as f:
                    json.dump({"queries": queries}, f, ensure_ascii=False, indent=2)
                print(f"저장: {args.output} ({len(queries)}개 쿼리)")
            else:
                for q in queries:
                    print(q)


if __name__ == "__main__":
    main()
