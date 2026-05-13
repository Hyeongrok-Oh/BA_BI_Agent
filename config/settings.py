"""Centralized runtime settings for local, Docker, and test environments."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os
from typing import Optional


DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RuntimeSettings:
    """Resolved settings used by agents, tools, and the Streamlit app."""

    project_root: Path
    erp_db_path: Path
    openai_api_key: Optional[str]
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: Optional[str]
    neo4j_database: str


def _resolve_path(value: Optional[str], default: Path, root: Path) -> Path:
    if not value:
        return default

    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


@lru_cache(maxsize=1)
def get_settings() -> RuntimeSettings:
    """Return environment-aware settings with stable repo-relative defaults."""

    project_root = _resolve_path(
        os.getenv("PROJECT_ROOT"),
        DEFAULT_PROJECT_ROOT,
        DEFAULT_PROJECT_ROOT,
    )

    return RuntimeSettings(
        project_root=project_root,
        erp_db_path=_resolve_path(
            os.getenv("ERP_DB_PATH"),
            project_root / "erp_database" / "lge_he_erp.db",
            project_root,
        ),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "password123"),
        neo4j_database=os.getenv("NEO4J_DATABASE", "neo4j"),
    )


def get_erp_db_path() -> str:
    """Return the configured ERP SQLite database path as a string."""

    return str(get_settings().erp_db_path)
