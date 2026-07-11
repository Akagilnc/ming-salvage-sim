#!/usr/bin/env python3
"""把手工距离图烘焙成运行时只读的全对耗时矩阵。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH = ROOT / "content/distance_graph.json"
DEFAULT_OUTPUT = ROOT / "content/distance_matrix.json"
sys.path.insert(0, str(ROOT))

from ming_sim.distance import bake_distance_matrix


def bake_file(graph_path: Path, output_path: Path) -> None:
    with graph_path.open(encoding="utf-8") as file:
        graph = json.load(file)
    matrix = bake_distance_matrix(graph)
    asset = {
        "schema_version": 1,
        "unit": "months",
        "source": "distance_graph.json",
        "matrix": matrix,
    }
    output_path.write_text(
        json.dumps(asset, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    bake_file(args.graph, args.output)


if __name__ == "__main__":
    main()
