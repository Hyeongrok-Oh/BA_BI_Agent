import unittest

from agents.tools.query_guard import validate_read_only_cypher, validate_read_only_sql
from agents.tools.sql_executor import SQLExecutor


class QueryGuardTests(unittest.TestCase):
    def test_sql_allows_select_and_cte(self):
        self.assertIsNone(validate_read_only_sql("SELECT * FROM TR_SALES LIMIT 5"))
        self.assertIsNone(validate_read_only_sql("WITH x AS (SELECT 1 AS n) SELECT n FROM x"))

    def test_sql_blocks_mutations_and_multiple_statements(self):
        self.assertIsNotNone(validate_read_only_sql("DELETE FROM TR_SALES"))
        self.assertIsNotNone(validate_read_only_sql("SELECT 1; DROP TABLE TR_SALES"))

    def test_sql_executor_rejects_mutation_before_execution(self):
        result = SQLExecutor(db_path=":memory:").execute("CREATE TABLE x(id INTEGER)")
        self.assertFalse(result.success)
        self.assertIn("SQL guard", result.error)

    def test_cypher_allows_read_queries(self):
        self.assertIsNone(validate_read_only_cypher("MATCH (n) RETURN n LIMIT 5"))
        self.assertIsNone(validate_read_only_cypher("RETURN 1 AS test"))
        self.assertIsNone(validate_read_only_cypher("CALL db.labels()"))
        self.assertIsNone(
            validate_read_only_cypher(
                "CALL db.index.vector.queryNodes('event_embedding', $top_k, $embedding) "
                "YIELD node, score RETURN node, score"
            )
        )

    def test_cypher_blocks_mutations_and_admin_calls(self):
        self.assertIsNotNone(validate_read_only_cypher("MATCH (n) DELETE n"))
        self.assertIsNotNone(validate_read_only_cypher("MERGE (n:Event {id: 'x'}) RETURN n"))
        self.assertIsNotNone(validate_read_only_cypher("CALL dbms.listConfig()"))


if __name__ == "__main__":
    unittest.main()
