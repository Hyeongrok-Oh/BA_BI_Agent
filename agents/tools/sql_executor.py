"""
SQL Executor Tool - SQL 쿼리 실행만 담당

특징:
- 입력: SQL 쿼리 문자열
- 출력: DataFrame
- 결정권 없음 (어떤 쿼리를 실행할지는 Agent가 결정)
"""

import sqlite3
import pandas as pd
from typing import Optional

from config.settings import get_erp_db_path
from ..base import BaseTool, ToolResult
from .query_guard import validate_read_only_sql


class SQLExecutor(BaseTool):
    """SQL 쿼리 실행 Tool"""

    name = "sql_executor"
    description = "SQLite 데이터베이스에서 SQL 쿼리를 실행하고 결과를 반환합니다."

    DEFAULT_DB_PATH = get_erp_db_path()

    def __init__(self, db_path: str = None, max_rows: int = 1000):
        self.db_path = db_path or get_erp_db_path()
        self.max_rows = max_rows

    def execute(self, query: str) -> ToolResult:
        """
        SQL 쿼리 실행

        Args:
            query: 실행할 SQL 쿼리 문자열

        Returns:
            ToolResult with DataFrame or error
        """
        if not query or not query.strip():
            return ToolResult(success=False, error="빈 쿼리입니다.")

        guard_error = validate_read_only_sql(query)
        if guard_error:
            return ToolResult(success=False, error=f"SQL guard: {guard_error}")

        try:
            with sqlite3.connect(self.db_path) as conn:
                df = pd.read_sql_query(query, conn)
                if self.max_rows and len(df) > self.max_rows:
                    df = df.head(self.max_rows)

            return ToolResult(
                success=True,
                data=df
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"SQL 실행 오류: {str(e)}"
            )

    def get_schema(self) -> str:
        """데이터베이스 스키마 정보 반환"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()

        schema_lines = ["=== DATABASE SCHEMA ===\n"]

        for (table_name,) in tables:
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()

            schema_lines.append(f"\nTable: {table_name}")
            schema_lines.append("Columns:")
            for col in columns:
                col_id, name, col_type, not_null, default_val, pk = col
                pk_marker = " (PK)" if pk else ""
                schema_lines.append(f"  - {name}: {col_type}{pk_marker}")

        conn.close()
        return "\n".join(schema_lines)

    def get_sample_data(self, table_name: str, limit: int = 5) -> Optional[pd.DataFrame]:
        """테이블 샘플 데이터 반환"""
        if not table_name.replace("_", "").isalnum():
            return None
        result = self.execute(f"SELECT * FROM {table_name} LIMIT {limit}")
        return result.data if result.success else None
