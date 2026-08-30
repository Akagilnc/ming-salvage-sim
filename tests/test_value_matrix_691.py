import copy

import pytest

import ming_sim.value_matrix as value_matrix


EXPECTED_MATRIX = {
    "东林": {"礼法名节": 2, "既得利益": -1, "实务事功": -1, "皇权依附": -2, "华夷战和": 1, "民本恤民": 1},
    "阉党": {"礼法名节": -1, "既得利益": 2, "实务事功": -1, "皇权依附": 2, "华夷战和": 0, "民本恤民": -2},
    "军队": {"礼法名节": -1, "既得利益": 1, "实务事功": 2, "皇权依附": -1, "华夷战和": 2, "民本恤民": -1},
    "皇党": {"礼法名节": -1, "既得利益": -1, "实务事功": 1, "皇权依附": 2, "华夷战和": 1, "民本恤民": -1},
    "宗室": {"礼法名节": 2, "既得利益": 2, "实务事功": -2, "皇权依附": 1, "华夷战和": 0, "民本恤民": -1},
    "西学": {"礼法名节": -1, "既得利益": -1, "实务事功": 2, "皇权依附": 1, "华夷战和": 1, "民本恤民": 0},
    "中立": {"礼法名节": -1, "既得利益": 0, "实务事功": 2, "皇权依附": 0, "华夷战和": 1, "民本恤民": 0},
}


def test_value_matrix_matches_adr_0011_3_and_routes_opposite_signs():
    assert value_matrix.matrix_snapshot() == EXPECTED_MATRIX
    assert value_matrix.mean_aligned_stance("阉党", "既得利益", direction=-1) == -2
    assert value_matrix.mean_aligned_stance("东林", "既得利益", direction=-1) == 1


@pytest.mark.parametrize(
    "corrupt",
    ["missing_cell", "extra_cell", "unknown_faction", "bool_value", "out_of_range", "string_value"],
)
def test_value_matrix_fails_closed_when_the_42_cell_closed_set_is_corrupt(monkeypatch, corrupt):
    raw = {
        "axes": list(value_matrix.value_axes()),
        "factions": copy.deepcopy(EXPECTED_MATRIX),
    }
    if corrupt == "missing_cell":
        del raw["factions"]["东林"]["礼法名节"]
    elif corrupt == "extra_cell":
        raw["factions"]["东林"]["新轴"] = 1
    elif corrupt == "unknown_faction":
        raw["factions"]["新党"] = raw["factions"].pop("中立")
    elif corrupt == "bool_value":
        raw["factions"]["东林"]["礼法名节"] = True
    elif corrupt == "out_of_range":
        raw["factions"]["东林"]["礼法名节"] = 3
    else:
        raw["factions"]["东林"]["礼法名节"] = "2"

    monkeypatch.setattr(value_matrix, "load_json_asset", lambda _path: raw)
    value_matrix._loaded.cache_clear()
    try:
        with pytest.raises(SystemExit):
            value_matrix.matrix_snapshot()
    finally:
        value_matrix._loaded.cache_clear()
