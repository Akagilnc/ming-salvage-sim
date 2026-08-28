import json
from pathlib import Path

import pytest

from ming_sim.distance import DistanceMatrix, bake_distance_matrix


ROOT = Path(__file__).resolve().parents[1]


def test_bake_uses_half_endpoint_weights_and_zero_diagonal():
    graph = {
        "nodes": {"a": {"weight": 2.0}, "b": {"weight": 4.0}},
        "edges": [{"from": "a", "to": "b", "cost": 1.5}],
    }

    matrix = bake_distance_matrix(graph)

    assert matrix["a"]["a"] == 0
    assert matrix["b"]["b"] == 0
    assert matrix["a"]["b"] == pytest.approx(4.5)
    assert matrix["b"]["a"] == pytest.approx(4.5)


def test_bake_selects_fastest_route_and_preserves_triangle_inequality():
    graph = {
        "nodes": {
            "a": {"weight": 2.0},
            "b": {"weight": 10.0},
            "c": {"weight": 2.0},
        },
        "edges": [
            {"from": "a", "to": "b", "cost": 0.0},
            {"from": "a", "to": "c", "cost": 0.0},
            {"from": "c", "to": "b", "cost": 0.0},
        ],
    }

    matrix = bake_distance_matrix(graph)

    assert matrix["a"]["b"] == pytest.approx(6.0)
    assert matrix["a"]["b"] <= matrix["a"]["c"] + matrix["c"]["b"]


def test_runtime_reader_is_lookup_only(tmp_path):
    path = tmp_path / "distance_matrix.json"
    path.write_text(
        json.dumps({"matrix": {"a": {"a": 0, "b": 3.5}, "b": {"a": 3.5, "b": 0}}}),
        encoding="utf-8",
    )

    distances = DistanceMatrix.from_file(path)

    assert distances.travel_time("a", "b") == pytest.approx(3.5)
    with pytest.raises(KeyError):
        distances.travel_time("a", "missing")


def test_baked_content_covers_all_regions_and_three_golden_anchors():
    graph = json.loads((ROOT / "content/distance_graph.json").read_text(encoding="utf-8"))
    matrix = json.loads((ROOT / "content/distance_matrix.json").read_text(encoding="utf-8"))["matrix"]
    region_ids = {
        row["id"] for row in json.loads((ROOT / "content/regions.json").read_text(encoding="utf-8"))["regions"]
    }

    assert set(graph["nodes"]) == region_ids
    assert set(matrix) == region_ids
    assert all(set(row) == region_ids for row in matrix.values())
    assert bake_distance_matrix(graph) == matrix
    assert matrix["beizhili"]["beizhili"] == 0
    assert matrix["henan"]["beizhili"] == 1.0
    assert matrix["nanzhili"]["beizhili"] == 1.6
    assert matrix["guangdong"]["beizhili"] == 3.0
    assert matrix["guangdong"]["beizhili"] > matrix["nanzhili"]["beizhili"] > matrix["henan"]["beizhili"]
    dongjiang = DistanceMatrix(matrix)
    assert dongjiang.travel_time("dongjiang_area", "liaodong") <= 2.0
    assert dongjiang.travel_time("dongjiang_area", "liaodong") < dongjiang.travel_time("dongjiang_area", "guangdong")
    assert dongjiang.travel_time("dongjiang_area", "shandong") < dongjiang.travel_time("dongjiang_area", "guangdong")
    for origin, row in matrix.items():
        for destination, value in row.items():
            assert value == matrix[destination][origin]
            assert value <= matrix[origin]["henan"] + matrix["henan"][destination] + 1e-9
