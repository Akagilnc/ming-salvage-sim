"""离线烘焙的地区耗时矩阵及其唯一运行时读口。"""

from __future__ import annotations

import heapq
import json
from pathlib import Path
from typing import Mapping


def _number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a non-negative number")
    result = float(value)
    if result < 0:
        raise ValueError(f"{path} must be a non-negative number")
    return result


def _graph_edges(graph: Mapping[str, object]) -> dict[str, list[tuple[str, float]]]:
    raw_nodes = graph.get("nodes")
    raw_edges = graph.get("edges")
    if not isinstance(raw_nodes, Mapping) or not isinstance(raw_edges, list):
        raise ValueError("distance graph must contain nodes object and edges array")

    nodes = set(raw_nodes)
    adjacency = {node: [] for node in nodes}
    for index, raw_edge in enumerate(raw_edges):
        if not isinstance(raw_edge, Mapping):
            raise ValueError(f"edges[{index}] must be an object")
        start = raw_edge.get("from")
        end = raw_edge.get("to")
        if not isinstance(start, str) or not isinstance(end, str):
            raise ValueError(f"edges[{index}] endpoints must be strings")
        if start not in nodes or end not in nodes:
            raise ValueError(f"edges[{index}] references an unknown node")
        cost = _number(raw_edge.get("cost"), f"edges[{index}].cost")
        adjacency[start].append((end, cost))
        adjacency[end].append((start, cost))
    return adjacency


def bake_distance_matrix(graph: Mapping[str, object]) -> dict[str, dict[str, float | int]]:
    """Bake all-pairs shortest travel times from a weighted region graph.

    Node weights are the cost of crossing a region.  The first and last node
    count half, while intermediate nodes count in full.  A node-to-itself
    route is explicitly zero because the graph is province-granularity data.
    """

    raw_nodes = graph.get("nodes")
    if not isinstance(raw_nodes, Mapping) or not raw_nodes:
        raise ValueError("distance graph must contain a non-empty nodes object")
    node_weights = {
        node: _number(config.get("weight") if isinstance(config, Mapping) else None, f"nodes.{node}.weight")
        for node, config in raw_nodes.items()
        if isinstance(node, str)
    }
    if len(node_weights) != len(raw_nodes):
        raise ValueError("distance graph node ids must be strings")
    adjacency = _graph_edges(graph)
    matrix: dict[str, dict[str, float | int]] = {}

    for source in node_weights:
        distances = {source: 0.0}
        queue: list[tuple[float, str]] = [(0.0, source)]
        while queue:
            cost_so_far, current = heapq.heappop(queue)
            if cost_so_far != distances[current]:
                continue
            for neighbor, edge_cost in adjacency[current]:
                # The source endpoint is half-weighted immediately.  An
                # intermediate node is full-weighted; the destination half is
                # corrected when the candidate is read into the matrix.
                node_cost = node_weights[current] if current != source else node_weights[source] / 2
                candidate = cost_so_far + edge_cost + node_cost
                if neighbor not in distances or candidate < distances[neighbor]:
                    distances[neighbor] = candidate
                    heapq.heappush(queue, (candidate, neighbor))

        row: dict[str, float | int] = {}
        for destination in node_weights:
            if destination == source:
                row[destination] = 0
                continue
            if destination not in distances:
                raise ValueError(f"distance graph is disconnected: {source} -> {destination}")
            row[destination] = distances[destination] + node_weights[destination] / 2
        matrix[source] = row

    return matrix


class DistanceMatrix:
    """Runtime read-only access to the baked matrix; it never performs routing."""

    def __init__(self, matrix: Mapping[str, Mapping[str, object]]):
        self._matrix = {
            str(start): {str(end): float(value) for end, value in row.items()}
            for start, row in matrix.items()
        }

    @classmethod
    def from_file(cls, path: str | Path) -> "DistanceMatrix":
        with Path(path).open(encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, Mapping) or not isinstance(data.get("matrix"), Mapping):
            raise ValueError("distance matrix asset must contain a matrix object")
        return cls(data["matrix"])

    def travel_time(self, origin: str, destination: str) -> float:
        try:
            return self._matrix[origin][destination]
        except KeyError as error:
            raise KeyError(f"no baked travel time for {origin!r} -> {destination!r}") from error

