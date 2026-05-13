"""
KPI Subgraph Visualizer - pyvis-based Neo4j Browser style visualization

분석 결과에서 검증된 Driver와 매칭된 Event만 포함하는 서브그래프를 시각화합니다.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
import json
import os
from neo4j import GraphDatabase

try:
    from pyvis.network import Network
    PYVIS_AVAILABLE = True
except ImportError:
    PYVIS_AVAILABLE = False

from .config import BaseConfig


@dataclass
class GraphNode:
    """Node representation"""
    id: str
    label: str
    node_type: str  # kpi, driver, event
    properties: Dict = field(default_factory=dict)
    color: str = ""
    size: int = 25
    title: str = ""  # Tooltip HTML


@dataclass
class GraphEdge:
    """Edge representation"""
    from_id: str
    to_id: str
    relation_type: str  # HYPOTHESIZED_TO_AFFECT, AFFECTS
    properties: Dict = field(default_factory=dict)
    color: str = "#999999"
    width: int = 1
    title: str = ""  # Tooltip HTML


@dataclass
class SubgraphData:
    """Complete subgraph data for visualization"""
    nodes: List[GraphNode] = field(default_factory=list)
    edges: List[GraphEdge] = field(default_factory=list)
    kpi_id: str = ""
    kpi_name: str = ""
    driver_count: int = 0
    event_count: int = 0


class KGVisualizer:
    """Knowledge Graph Subgraph Visualizer - Neo4j Browser Style"""

    # Color scheme (Neo4j Browser style)
    COLORS = {
        "kpi": "#8B5CF6",              # Purple (like Neo4j)
        "driver_positive": "#10B981",   # Teal/Green (+)
        "driver_negative": "#EF4444",   # Red (-)
        "driver_neutral": "#6B7280",    # Gray
        "event": "#F97316",             # Orange (like Neo4j)
    }

    # Node sizes
    SIZES = {
        "kpi": 45,
        "driver": 35,
        "event": 30
    }

    def __init__(self, uri: str = None, user: str = None, password: str = None):
        config = BaseConfig()
        self.uri = uri or config.neo4j_uri
        self.user = user or config.neo4j_user
        self.password = password or config.neo4j_password
        self._driver = None

    @property
    def driver(self):
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self.uri, auth=(self.user, self.password)
            )
        return self._driver

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None

    def build_subgraph(
        self,
        kpi_id: str,
        driver_ids: List[str] = None,
        event_ids: List[str] = None,
        max_drivers: int = 8,
        max_events_per_driver: int = 2
    ) -> SubgraphData:
        """Build subgraph data for visualization"""
        subgraph = SubgraphData(kpi_id=kpi_id)

        # 1. Get KPI node
        kpi_node = self._get_kpi_node(kpi_id)
        if kpi_node:
            subgraph.nodes.append(kpi_node)
            subgraph.kpi_name = kpi_node.label

        # 2. Get Driver nodes and KPI->Driver edges
        drivers, kpi_driver_edges = self._get_driver_nodes(
            kpi_id, driver_ids, max_drivers
        )
        subgraph.nodes.extend(drivers)
        subgraph.edges.extend(kpi_driver_edges)
        subgraph.driver_count = len(drivers)

        # 3. Get Event nodes and Event->Driver edges
        driver_id_list = [d.id.replace("driver_", "") for d in drivers]
        events, event_driver_edges = self._get_event_nodes(
            driver_id_list, event_ids, max_events_per_driver
        )
        subgraph.nodes.extend(events)
        subgraph.edges.extend(event_driver_edges)
        subgraph.event_count = len(events)

        return subgraph

    def _get_kpi_node(self, kpi_id: str) -> Optional[GraphNode]:
        """Query Neo4j for KPI node"""
        query = """
        MATCH (k:KPI {id: $kpi_id})
        RETURN k.id as id, k.name as name, k.name_kr as name_kr,
               k.category as category, k.description as description,
               k.erp_table as erp_table, k.erp_column as erp_column,
               k.unit as unit
        """

        try:
            with self.driver.session() as session:
                result = session.run(query, kpi_id=kpi_id)
                record = result.single()

                if not record:
                    return GraphNode(
                        id=f"kpi_{kpi_id}",
                        label=kpi_id,
                        node_type="kpi",
                        properties={"category": "KPI"},
                        color=self.COLORS["kpi"],
                        size=self.SIZES["kpi"],
                        title=f"<b>{kpi_id}</b>"
                    )

                props = {
                    "name": record.get('name', ''),
                    "name_kr": record.get('name_kr', ''),
                    "category": record.get('category', ''),
                    "description": record.get('description', ''),
                    "erp_table": record.get('erp_table', ''),
                    "erp_column": record.get('erp_column', ''),
                    "unit": record.get('unit', '')
                }

                return GraphNode(
                    id=f"kpi_{record['id']}",
                    label=record['name_kr'] or record['name'] or record['id'],
                    node_type="kpi",
                    properties=props,
                    color=self.COLORS["kpi"],
                    size=self.SIZES["kpi"],
                    title=self._build_tooltip("KPI", record['name_kr'] or record['id'], props)
                )
        except Exception as e:
            print(f"[KGVisualizer] KPI query error: {e}")
            return GraphNode(
                id=f"kpi_{kpi_id}",
                label=kpi_id,
                node_type="kpi",
                color=self.COLORS["kpi"],
                size=self.SIZES["kpi"],
                title=f"<b>{kpi_id}</b>"
            )

    def _get_driver_nodes(
        self,
        kpi_id: str,
        driver_ids: List[str] = None,
        max_drivers: int = 8
    ) -> tuple:
        """Query Neo4j for Driver nodes connected to KPI"""

        if not driver_ids:
            return [], []

        query = """
        MATCH (d:Driver)-[r:HYPOTHESIZED_TO_AFFECT]->(k:KPI {id: $kpi_id})
        WHERE d.id IN $driver_ids
        RETURN
            d.id as id,
            d.name as name,
            d.name_kr as name_kr,
            d.category as category,
            d.description as description,
            d.validation_tier as tier,
            d.validation_method as validation_method,
            d.erp_table as erp_table,
            d.erp_column as erp_column,
            r.polarity as polarity,
            r.expected_polarity as expected_polarity,
            r.effect_type as effect_type,
            r.weight as weight,
            r.confidence as confidence
        ORDER BY r.confidence DESC
        LIMIT $limit
        """

        nodes = []
        edges = []

        try:
            with self.driver.session() as session:
                result = session.run(
                    query,
                    kpi_id=kpi_id,
                    driver_ids=driver_ids,
                    limit=max_drivers
                )

                for record in result:
                    polarity = record.get('polarity') or record.get('expected_polarity', '+')
                    if polarity == '+' or polarity == 1:
                        color_key = "driver_positive"
                    elif polarity == '-' or polarity == -1:
                        color_key = "driver_negative"
                    else:
                        color_key = "driver_neutral"

                    props = {
                        "name": record.get('name', ''),
                        "name_kr": record.get('name_kr', ''),
                        "category": record.get('category', ''),
                        "description": record.get('description', ''),
                        "validation_tier": record.get('tier', ''),
                        "validation_method": record.get('validation_method', ''),
                        "erp_table": record.get('erp_table', ''),
                        "erp_column": record.get('erp_column', ''),
                        "polarity": '+' if polarity in ['+', 1] else ('-' if polarity in ['-', -1] else '±'),
                        "effect_type": record.get('effect_type', ''),
                        "confidence": round(record.get('confidence', 0) or 0, 3)
                    }

                    node = GraphNode(
                        id=f"driver_{record['id']}",
                        label=self._truncate(record['name_kr'] or record['name'] or record['id'], 12),
                        node_type="driver",
                        properties=props,
                        color=self.COLORS[color_key],
                        size=self.SIZES["driver"],
                        title=self._build_tooltip("Driver", record['name_kr'] or record['id'], props)
                    )
                    nodes.append(node)

                    weight = record.get('weight', 0.5) or 0.5
                    edge_width = max(1, int(weight * 3))

                    edge = GraphEdge(
                        from_id=f"driver_{record['id']}",
                        to_id=f"kpi_{kpi_id}",
                        relation_type="HYPOTHESIZED_TO_AFFECT",
                        properties={"polarity": props["polarity"], "weight": round(weight, 3)},
                        color=self.COLORS[color_key],
                        width=edge_width,
                        title=f"polarity: {props['polarity']}<br>weight: {round(weight, 3)}"
                    )
                    edges.append(edge)

        except Exception as e:
            print(f"[KGVisualizer] Driver query error: {e}")

        return nodes, edges

    def _get_event_nodes(
        self,
        driver_ids: List[str],
        event_ids: List[str] = None,
        max_per_driver: int = 2
    ) -> tuple:
        """Query Neo4j for Event nodes connected to Drivers"""

        if not driver_ids:
            return [], []

        event_filter = "AND e.id IN $event_ids" if event_ids else ""

        query = f"""
        MATCH (e:Event)-[r:AFFECTS]->(d:Driver)
        WHERE d.id IN $driver_ids {event_filter}
        RETURN
            e.id as event_id,
            e.name as event_name,
            e.category as category,
            e.severity as severity,
            e.is_ongoing as is_ongoing,
            e.evidence as evidence,
            e.start_date as start_date,
            d.id as driver_id,
            r.polarity as polarity,
            r.weight as weight
        ORDER BY
            CASE e.severity
                WHEN 'critical' THEN 1
                WHEN 'high' THEN 2
                WHEN 'medium' THEN 3
                ELSE 4
            END,
            r.weight DESC
        """

        nodes = []
        edges = []
        seen_events = set()
        driver_event_count = {}

        try:
            with self.driver.session() as session:
                params = {"driver_ids": driver_ids}
                if event_ids:
                    params["event_ids"] = event_ids

                result = session.run(query, **params)

                for record in result:
                    driver_id = record['driver_id']
                    event_id = record['event_id']

                    driver_event_count[driver_id] = driver_event_count.get(driver_id, 0)
                    if driver_event_count[driver_id] >= max_per_driver:
                        continue

                    driver_event_count[driver_id] += 1

                    if event_id not in seen_events:
                        seen_events.add(event_id)

                        severity = record.get('severity', 'medium')
                        size = self._severity_to_size(severity)
                        polarity = record.get('polarity', 0)

                        start_date = record.get('start_date', '')
                        if start_date and hasattr(start_date, 'isoformat'):
                            start_date = start_date.isoformat()
                        elif start_date:
                            start_date = str(start_date)

                        props = {
                            "name": record.get('event_name', ''),
                            "category": record.get('category', ''),
                            "severity": severity,
                            "is_ongoing": "Yes" if record.get('is_ongoing') else "No",
                            "start_date": start_date,
                            "evidence": self._truncate(record.get('evidence', ''), 100),
                        }

                        node = GraphNode(
                            id=f"event_{event_id}",
                            label=self._truncate(record['event_name'], 15),
                            node_type="event",
                            properties=props,
                            color=self.COLORS["event"],
                            size=size,
                            title=self._build_tooltip("Event", record['event_name'], props)
                        )
                        nodes.append(node)

                    polarity = record.get('polarity', 0)
                    weight = record.get('weight', 0.5) or 0.5
                    edge_width = max(1, int(weight * 2))

                    if polarity > 0 or polarity == '+':
                        edge_color = self.COLORS["driver_positive"]
                    elif polarity < 0 or polarity == '-':
                        edge_color = self.COLORS["driver_negative"]
                    else:
                        edge_color = self.COLORS["driver_neutral"]

                    polarity_str = '+' if polarity > 0 or polarity == '+' else ('-' if polarity < 0 or polarity == '-' else '±')

                    edge = GraphEdge(
                        from_id=f"event_{event_id}",
                        to_id=f"driver_{driver_id}",
                        relation_type="AFFECTS",
                        properties={"polarity": polarity_str, "weight": round(weight, 3)},
                        color=edge_color,
                        width=edge_width,
                        title=f"polarity: {polarity_str}<br>weight: {round(weight, 3)}"
                    )
                    edges.append(edge)

        except Exception as e:
            print(f"[KGVisualizer] Event query error: {e}")

        return nodes, edges

    def generate_html(
        self,
        subgraph: SubgraphData,
        height: str = "700px"
    ) -> str:
        """Generate pyvis HTML with Neo4j Browser-like styling"""

        if not subgraph.nodes:
            return ""

        if not PYVIS_AVAILABLE:
            return self._generate_fallback_html(subgraph, height)

        # Create pyvis Network
        net = Network(
            height=height,
            width="100%",
            bgcolor="#ffffff",
            font_color="#333333",
            directed=True,
            notebook=False,
            select_menu=False,
            filter_menu=False
        )

        # Physics configuration for Neo4j-like layout
        net.set_options("""
        {
            "nodes": {
                "borderWidth": 3,
                "borderWidthSelected": 5,
                "font": {
                    "size": 28,
                    "face": "Arial",
                    "color": "#ffffff",
                    "strokeWidth": 0
                },
                "shadow": {
                    "enabled": true,
                    "size": 10,
                    "x": 3,
                    "y": 3
                }
            },
            "edges": {
                "arrows": {
                    "to": {
                        "enabled": true,
                        "scaleFactor": 0.6
                    }
                },
                "color": {
                    "inherit": false
                },
                "font": {
                    "size": 22,
                    "face": "Arial",
                    "color": "#444444",
                    "strokeWidth": 4,
                    "strokeColor": "#ffffff",
                    "align": "middle"
                },
                "smooth": {
                    "enabled": true,
                    "type": "continuous"
                },
                "shadow": {
                    "enabled": true,
                    "size": 5
                }
            },
            "physics": {
                "enabled": true,
                "solver": "forceAtlas2Based",
                "forceAtlas2Based": {
                    "gravitationalConstant": -350,
                    "centralGravity": 0.003,
                    "springLength": 400,
                    "springConstant": 0.03,
                    "damping": 0.5,
                    "avoidOverlap": 1.0
                },
                "stabilization": {
                    "enabled": true,
                    "iterations": 300,
                    "fit": true
                },
                "minVelocity": 0.75
            },
            "interaction": {
                "hover": true,
                "tooltipDelay": 100,
                "hideEdgesOnDrag": false,
                "navigationButtons": false,
                "keyboard": {
                    "enabled": false
                },
                "zoomView": true
            }
        }
        """)

        # Add nodes
        for node in subgraph.nodes:
            # Node shape based on type - larger sizes and fonts for better visibility
            if node.node_type == "kpi":
                shape = "dot"
                size = 100
                font_size = 32
                border_width = 4
                x = 0  # Center
                y = 0
                fixed = True
            elif node.node_type == "driver":
                shape = "dot"
                size = 80
                font_size = 26
                border_width = 3
                x = None
                y = None
                fixed = False
            else:  # event
                shape = "dot"
                size = 70
                font_size = 24
                border_width = 2
                x = None
                y = None
                fixed = False

            net.add_node(
                node.id,
                label=node.label,
                title="",  # No tooltip on hover
                color={
                    "background": node.color,
                    "border": node.color,
                    "highlight": {
                        "background": node.color,
                        "border": "#000000"
                    }
                },
                size=size,
                shape=shape,
                font={"size": font_size, "color": "#ffffff"},
                borderWidth=border_width,
                x=x,
                y=y,
                fixed=fixed,
                physics=not fixed
            )

        # Add edges with labels (Neo4j style)
        for edge in subgraph.edges:
            # Shorter label for edges
            if edge.relation_type == "HYPOTHESIZED_TO_AFFECT":
                label = "AFFECTS"
            else:
                label = edge.relation_type

            net.add_edge(
                edge.from_id,
                edge.to_id,
                title="",  # No tooltip on hover
                label=label,
                color=edge.color,
                width=max(edge.width, 3),  # Minimum width for visibility
                arrows={"to": {"enabled": True, "scaleFactor": 1.0}},
                font={"size": 22, "color": "#333333", "strokeWidth": 5, "strokeColor": "#ffffff"}
            )

        # Generate HTML
        html = net.generate_html()

        # Add custom CSS for Neo4j-like properties panel (overlay style)
        custom_css = f"""
        <style>
            html, body {{ margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
            #mynetwork {{
                width: 100% !important;
                height: 100% !important;
                min-height: {height} !important;
                position: absolute !important;
                top: 0;
                left: 0;
                border: none !important;
            }}
            #props-panel {{
                position: absolute;
                top: 15px;
                right: 15px;
                width: 280px;
                max-height: calc(100% - 30px);
                background: rgba(255,255,255,0.97);
                overflow-y: auto;
                font-size: 12px;
                border-radius: 8px;
                border: 1px solid #e1e5e9;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                z-index: 100;
            }}
            .props-header {{
                padding: 12px 16px;
                border-bottom: 1px solid #e1e5e9;
                display: flex;
                align-items: center;
                gap: 10px;
                background: #fafbfc;
                border-radius: 8px 8px 0 0;
            }}
            .props-title {{ font-size: 13px; font-weight: 600; color: #37352f; }}
            .node-badge {{
                display: inline-block;
                padding: 3px 10px;
                border-radius: 12px;
                font-size: 11px;
                font-weight: 600;
                color: #fff;
                text-transform: uppercase;
            }}
            .props-content {{ padding: 0; }}
            .prop-row {{
                display: flex;
                padding: 10px 16px;
                border-bottom: 1px solid #f0f0f0;
                align-items: flex-start;
            }}
            .prop-row:hover {{ background: #fafbfc; }}
            .prop-key {{
                width: 90px;
                flex-shrink: 0;
                font-size: 12px;
                color: #6b7280;
                font-weight: 500;
            }}
            .prop-value {{
                flex: 1;
                font-size: 12px;
                color: #1f2937;
                word-break: break-word;
            }}
            .empty-state {{
                padding: 30px 16px;
                text-align: center;
                color: #9ca3af;
                font-size: 13px;
            }}
            .legend {{
                position: absolute;
                bottom: 15px;
                left: 15px;
                background: rgba(255,255,255,0.95);
                padding: 12px 16px;
                border-radius: 8px;
                font-size: 13px;
                border: 1px solid #e1e5e9;
                z-index: 100;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }}
            .legend-item {{ display: flex; align-items: center; margin: 5px 0; color: #37352f; font-weight: 500; }}
            .legend-color {{ width: 14px; height: 14px; border-radius: 50%; margin-right: 8px; }}
        </style>
        """

        # Properties panel HTML
        props_panel = f"""
        <div id="props-panel">
            <div class="empty-state">
                <div style="font-size: 32px; margin-bottom: 10px;">📊</div>
                <div>Click a node to view properties</div>
            </div>
        </div>
        <div class="legend">
            <div class="legend-item"><div class="legend-color" style="background: {self.COLORS['kpi']};"></div>KPI</div>
            <div class="legend-item"><div class="legend-color" style="background: {self.COLORS['driver_positive']};"></div>Driver (+)</div>
            <div class="legend-item"><div class="legend-color" style="background: {self.COLORS['driver_negative']};"></div>Driver (-)</div>
            <div class="legend-item"><div class="legend-color" style="background: {self.COLORS['event']};"></div>Event</div>
        </div>
        """

        # Node data for click handler
        node_data = {}
        for node in subgraph.nodes:
            node_data[node.id] = {
                "label": node.label,
                "type": node.node_type,
                "color": node.color,
                "properties": node.properties
            }

        click_handler = f"""
        <script>
        var nodeData = {json.dumps(node_data, ensure_ascii=False)};
        var colors = {{
            'kpi': '{self.COLORS["kpi"]}',
            'driver': '{self.COLORS["driver_positive"]}',
            'event': '{self.COLORS["event"]}'
        }};

        network.on('click', function(params) {{
            if (params.nodes.length > 0) {{
                var nodeId = params.nodes[0];
                var data = nodeData[nodeId];
                if (data) {{
                    var badgeColor = data.type === 'kpi' ? colors.kpi : (data.type === 'driver' ? colors.driver : colors.event);
                    var html = '<div class="props-header">';
                    html += '<span class="node-badge" style="background:' + badgeColor + '">' + data.type.toUpperCase() + '</span>';
                    html += '<span class="props-title">' + data.label + '</span>';
                    html += '</div><div class="props-content">';

                    var props = data.properties || {{}};
                    for (var key in props) {{
                        if (props[key] !== null && props[key] !== '' && props[key] !== undefined) {{
                            html += '<div class="prop-row"><div class="prop-key">' + key + '</div><div class="prop-value">' + props[key] + '</div></div>';
                        }}
                    }}
                    html += '</div>';
                    document.getElementById('props-panel').innerHTML = html;
                }}
            }}
        }});
        </script>
        """

        # Inject custom CSS and panel into HTML
        html = html.replace("</head>", custom_css + "</head>")
        html = html.replace("</body>", props_panel + click_handler + "</body>")

        return html

    def _generate_fallback_html(self, subgraph: SubgraphData, height: str) -> str:
        """Fallback when pyvis is not available"""
        return f"""
        <div style="height: {height}; display: flex; align-items: center; justify-content: center; background: #f5f5f5; border-radius: 8px;">
            <div style="text-align: center; color: #666;">
                <div style="font-size: 48px; margin-bottom: 16px;">📊</div>
                <div>pyvis not installed. Run: pip install pyvis</div>
            </div>
        </div>
        """

    def _build_tooltip(self, node_type: str, name: str, props: Dict) -> str:
        """Build HTML tooltip for node"""
        lines = [f"<b>{node_type}: {name}</b>"]
        for key, value in props.items():
            if value:
                lines.append(f"<br>{key}: {value}")
        return "".join(lines)

    def _severity_to_size(self, severity: str) -> int:
        sizes = {"critical": 35, "high": 30, "medium": 26, "low": 22}
        return sizes.get(severity, 26)

    def _truncate(self, text: str, max_len: int) -> str:
        if not text:
            return ""
        return text[:max_len] + "..." if len(text) > max_len else text
