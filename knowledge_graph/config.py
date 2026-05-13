"""공통 설정 - Neo4j, SQLite 연결 등"""

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass
class BaseConfig:
    """Knowledge Graph 공통 설정"""

    # Paths
    base_dir: Path = Path(__file__).parent.parent  # BI/

    @property
    def sqlite_path(self) -> Path:
        return self.base_dir / "erp_database" / "lge_he_erp.db"

    # Neo4j settings
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    neo4j_database: str = "neo4j"

    def __post_init__(self):
        """Load from environment variables if available."""
        self.neo4j_uri = os.getenv("NEO4J_URI", self.neo4j_uri)
        self.neo4j_user = os.getenv("NEO4J_USER", self.neo4j_user)
        self.neo4j_password = os.getenv("NEO4J_PASSWORD", self.neo4j_password)
