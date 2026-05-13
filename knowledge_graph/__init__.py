"""Runtime Knowledge Graph configuration.

The active application uses the canonical KPI/Driver/Event schema under
``knowledge_graph/schema``. Historical layer1~3 build scripts live in
``archive/knowledge_graph``.
"""

from .config import BaseConfig

__all__ = [
    "BaseConfig",
]
