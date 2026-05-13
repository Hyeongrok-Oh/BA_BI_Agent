"""Extract Dimension and Anchor nodes from database and config."""

import sqlite3
from typing import List

from .models import (
    DimensionNode, AnchorNode, Layer1Graph,
    DimensionType, MetricType
)
from .config import Config


class DimensionExtractor:
    """Extracts Dimension and Anchor nodes for Layer 1."""

    def __init__(self, config: Config):
        self.config = config
        self.connection = None

    def connect(self) -> None:
        if not self.config.sqlite_path.exists():
            raise FileNotFoundError(f"Database not found: {self.config.sqlite_path}")
        self.connection = sqlite3.connect(self.config.sqlite_path)
        self.connection.row_factory = sqlite3.Row

    def disconnect(self) -> None:
        if self.connection:
            self.connection.close()
            self.connection = None

    def extract(self) -> Layer1Graph:
        """Extract complete Layer 1 graph."""
        self.connect()
        try:
            graph = Layer1Graph()

            # 1. 상위 레벨 Dimension (config에서)
            self._add_categories(graph)
            self._add_regions(graph)
            self._add_channels(graph)

            # 2. 하위 레벨 Dimension (DB에서)
            self._add_products(graph)
            self._add_subsidiaries(graph)
            self._add_customers(graph)

            # 3. Anchor (config에서)
            self._add_anchors(graph)

            return graph
        finally:
            self.disconnect()

    def _add_categories(self, graph: Layer1Graph) -> None:
        """Add ProductCategory dimensions from config."""
        for cat in self.config.product_categories:
            graph.add_dimension(DimensionNode(
                id=cat["id"],
                dimension_type=DimensionType.PRODUCT_CATEGORY,
                name=cat["name"],
                properties={"description": cat.get("description", "")},
            ))

    def _add_regions(self, graph: Layer1Graph) -> None:
        """Add Region dimensions from config."""
        for region in self.config.regions:
            graph.add_dimension(DimensionNode(
                id=region["id"],
                dimension_type=DimensionType.REGION,
                name=region["name"],
                properties={"description": region.get("description", "")},
            ))

    def _add_channels(self, graph: Layer1Graph) -> None:
        """Add Channel dimensions from config."""
        for channel in self.config.channels:
            graph.add_dimension(DimensionNode(
                id=channel["id"],
                dimension_type=DimensionType.CHANNEL,
                name=channel["name"],
                properties={"description": channel.get("description", "")},
            ))

    def _add_products(self, graph: Layer1Graph) -> None:
        """Add Product dimensions from database."""
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT PRODUCT_ID, MODEL_NAME, SERIES, PANEL_TYPE, SCREEN_SIZE
            FROM TBL_MD_PRODUCT
        """)

        for row in cursor.fetchall():
            product_id = row["PRODUCT_ID"]
            series = row["SERIES"] or ""

            # Determine parent category
            parent_id = self._get_category_for_product(series)

            graph.add_dimension(DimensionNode(
                id=f"product_{product_id}",
                dimension_type=DimensionType.PRODUCT,
                name=row["MODEL_NAME"] or product_id,
                properties={
                    "product_id": product_id,
                    "series": series,
                    "panel_type": row["PANEL_TYPE"],
                    "screen_size": row["SCREEN_SIZE"],
                },
                parent_id=parent_id,
            ))

        cursor.close()

    def _get_category_for_product(self, series: str) -> str:
        """Determine ProductCategory based on series name."""
        for prefix, cat_id in self.config.product_category_rules.items():
            if series and prefix in series.upper():
                return cat_id
        return "cat_lcd"  # default

    def _add_subsidiaries(self, graph: Layer1Graph) -> None:
        """Add Subsidiary dimensions from database."""
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT SUBSIDIARY_ID, REGION, CURRENCY
            FROM TBL_ORG_SUBSIDIARY
        """)

        for row in cursor.fetchall():
            sub_id = row["SUBSIDIARY_ID"]
            parent_id = self.config.subsidiary_region_map.get(sub_id)

            graph.add_dimension(DimensionNode(
                id=f"sub_{sub_id}",
                dimension_type=DimensionType.SUBSIDIARY,
                name=sub_id,
                properties={
                    "subsidiary_id": sub_id,
                    "region": row["REGION"],
                    "currency": row["CURRENCY"],
                },
                parent_id=parent_id,
            ))

        cursor.close()

    def _add_customers(self, graph: Layer1Graph) -> None:
        """Add Customer dimensions from database."""
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT CUSTOMER_ID, CUST_NAME, SUBSIDIARY_ID, CHANNEL_TYPE
            FROM TBL_ORG_CUSTOMER
        """)

        for row in cursor.fetchall():
            cust_id = row["CUSTOMER_ID"]
            channel_type = row["CHANNEL_TYPE"] or "RETAIL"

            # Parent is channel
            parent_id = f"channel_{channel_type.lower()}"

            graph.add_dimension(DimensionNode(
                id=f"cust_{cust_id}",
                dimension_type=DimensionType.CUSTOMER,
                name=row["CUST_NAME"] or cust_id,
                properties={
                    "customer_id": cust_id,
                    "subsidiary_id": row["SUBSIDIARY_ID"],
                    "channel_type": channel_type,
                },
                parent_id=parent_id,
            ))

        cursor.close()

    def _add_anchors(self, graph: Layer1Graph) -> None:
        """Add Anchor nodes from config."""
        for anchor in self.config.anchors:
            graph.add_anchor(AnchorNode(
                id=anchor["id"],
                metric_type=MetricType(anchor["metric_type"]),
                name=anchor["name"],
                description=anchor.get("description", ""),
                source_table=anchor.get("source_table"),
                source_column=anchor.get("source_column"),
            ))
