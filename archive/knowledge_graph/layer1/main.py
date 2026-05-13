"""Main entry point for Knowledge Graph Layer 1 generation."""

import argparse
import json
from pathlib import Path

from .config import Config
from .dimension_extractor import DimensionExtractor
from .graph_builder import GraphBuilder


def extract(config: Config) -> None:
    """Extract and display Layer 1 data."""
    print("Extracting Layer 1 data...")
    print(f"Database: {config.sqlite_path}")

    extractor = DimensionExtractor(config)
    graph = extractor.extract()

    summary = graph.summary()
    print("\n=== Layer 1 Summary ===")
    print(f"Total Dimensions: {summary['dimensions']}")
    print(f"Total Anchors: {summary['anchors']}")

    print("\n=== Dimensions by Type ===")
    for dim_type, count in summary['by_dimension_type'].items():
        print(f"  {dim_type}: {count}")

    print("\n=== Anchors (KPI 중심점) ===")
    for anchor in graph.anchors:
        print(f"  [{anchor.metric_type.value}] {anchor.name}: {anchor.description}")

    print("\n=== Dimension Hierarchy (sample) ===")
    for dim in graph.dimensions[:10]:
        parent = f" -> {dim.parent_id}" if dim.parent_id else ""
        print(f"  [{dim.dimension_type.value}] {dim.name}{parent}")
    if len(graph.dimensions) > 10:
        print(f"  ... and {len(graph.dimensions) - 10} more")


def build(config: Config) -> None:
    """Build the knowledge graph in Neo4j."""
    print("Building Knowledge Graph Layer 1...")
    print(f"Database: {config.sqlite_path}")
    print(f"Neo4j: {config.neo4j_uri}")

    # Extract
    print("\n[1/2] Extracting dimensions and anchors...")
    extractor = DimensionExtractor(config)
    graph = extractor.extract()
    summary = graph.summary()
    print(f"  Dimensions: {summary['dimensions']}")
    print(f"  Anchors: {summary['anchors']}")

    # Build
    print("\n[2/2] Building Neo4j graph...")
    builder = GraphBuilder(config)
    result = builder.build(graph)

    print("\n=== Build Result ===")
    print(f"Nodes created:")
    print(f"  - Dimension: {result['dimensions']}")
    print(f"  - Anchor: {result['anchors']}")
    print(f"Relationships created:")
    print(f"  - CHILD_OF: {result['child_of']}")

    print("\nLayer 1 build complete!")
    print("Open Neo4j Browser at http://localhost:7474")


def export(config: Config, output_path: Path) -> None:
    """Export Layer 1 data to JSON."""
    print(f"Exporting Layer 1 to {output_path}...")

    extractor = DimensionExtractor(config)
    graph = extractor.extract()

    data = {
        "dimensions": [d.to_dict() for d in graph.dimensions],
        "anchors": [a.to_dict() for a in graph.anchors],
        "summary": graph.summary(),
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Exported to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Knowledge Graph Layer 1: Dimension & Anchor"
    )
    parser.add_argument(
        "command",
        choices=["extract", "build", "export"],
        help="Command to execute"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("layer1.json"),
        help="Output file for export command"
    )

    args = parser.parse_args()
    config = Config()

    if args.command == "extract":
        extract(config)
    elif args.command == "build":
        build(config)
    elif args.command == "export":
        export(config, args.output)


if __name__ == "__main__":
    main()
