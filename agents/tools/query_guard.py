"""Read-only guards for generated SQL and Cypher queries."""

import re
from typing import Optional


_SQL_MUTATION_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|vacuum|reindex|pragma)\b",
    re.IGNORECASE,
)
_CYPHER_MUTATION_RE = re.compile(
    r"\b(create|merge|set|delete|detach|remove|drop|load\s+csv|foreach)\b",
    re.IGNORECASE,
)


def _strip_line_comments(query: str) -> str:
    lines = []
    for line in query.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or stripped.startswith("//"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _has_multiple_statements(query: str) -> bool:
    stripped = query.strip()
    if stripped.endswith(";"):
        stripped = stripped[:-1]
    return ";" in stripped


def validate_read_only_sql(query: str) -> Optional[str]:
    """Return an error message when SQL is not safe to run as read-only."""

    normalized = _strip_line_comments(query)
    if not normalized:
        return "빈 쿼리입니다."
    if _has_multiple_statements(normalized):
        return "여러 SQL 문을 한 번에 실행할 수 없습니다."
    if not normalized.lower().startswith(("select", "with")):
        return "읽기 전용 SELECT/CTE 쿼리만 실행할 수 있습니다."
    if _SQL_MUTATION_RE.search(normalized):
        return "데이터 변경 가능성이 있는 SQL 키워드는 실행할 수 없습니다."
    return None


def validate_read_only_cypher(query: str) -> Optional[str]:
    """Return an error message when Cypher is not safe to run as read-only."""

    normalized = _strip_line_comments(query)
    if not normalized:
        return "빈 쿼리입니다."
    if _has_multiple_statements(normalized):
        return "여러 Cypher 문을 한 번에 실행할 수 없습니다."

    lowered = normalized.lower()
    allowed_prefixes = (
        "match",
        "optional match",
        "return",
        "with",
        "call db.labels",
        "call db.relationshiptypes",
        "call db.schema.visualization",
        "call db.index.",
    )
    if not lowered.startswith(allowed_prefixes):
        return "읽기 전용 MATCH/CALL 쿼리만 실행할 수 있습니다."
    if _CYPHER_MUTATION_RE.search(normalized):
        return "데이터 변경 가능성이 있는 Cypher 키워드는 실행할 수 없습니다."
    if re.search(r"\bcall\s+(dbms|apoc)\.", normalized, re.IGNORECASE):
        return "관리/쓰기 가능성이 있는 프로시저 호출은 실행할 수 없습니다."
    return None
