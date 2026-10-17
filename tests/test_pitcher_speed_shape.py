"""架空球団用の日本人投手の球速の分布の形（投手の球速の形_改修指示.md）。

正式な判定は scripts/check_pitcher_control.py（球団生成300球団）。ここでは写す処理の性質と、写しても変わらない項目を確かめる。
"""
from __future__ import annotations

import random

import pytest

import app

MASTER = app.load_master_data()
SEEDS = range(1, 301)
KEYS = ("先発|右", "先発|左", "救援|右", "救援|左")


def generate(role: str, category: str, seeds=SEEDS, table: dict | None = None, monkeypatch=None) -> list[dict]:
    monkeypatch.setattr(app, "FICTIONAL_PITCHER_SPEED_SHAPE_OVERRIDE", table)
    return [app.generate_player(role, category, MASTER, seed=seed) for seed in seeds]


def without(player: dict, keys: tuple[str, ...]) -> dict:
    return {k: v for k, v in player.items() if k not in keys}


def test_table_has_four_groups_with_increasing_points():
    table = app.load_fictional_pitcher_speed_shape()
    assert len(table["p"]) == 103
    for key in KEYS:
        for part in ("from", "to"):
            values = table[key][part]
            assert len(values) == 103
            assert all(a <= b for a, b in zip(values, values[1:])), (key, part)


def test_namespace_name():
    assert app.FICTIONAL_PITCHER_SPEED_SHAPE_NAMESPACE == "fictional_pitcher_speed_shape_v1"


def test_mapping_keeps_order():
    table = app.load_fictional_pitcher_speed_shape()
    rng = random.Random(1)
    for key in KEYS:
        xs = sorted(rng.uniform(125, 170) for _ in range(2000))
        ys = [app.map_speed_by_quantiles(x, table[key]["from"], table[key]["to"]) for x in xs]
        assert all(a <= b + 1e-12 for a, b in zip(ys, ys[1:])), key


def test_mapping_extends_outside_with_slope_one():
    source, target = [140.0, 150.0, 160.0], [135.0, 151.0, 165.0]
    assert app.map_speed_by_quantiles(130.0, source, target) == pytest.approx(125.0)
    assert app.map_speed_by_quantiles(170.0, source, target) == pytest.approx(175.0)
    assert app.map_speed_by_quantiles(145.0, source, target) == pytest.approx(143.0)
    assert app.map_speed_by_quantiles(150.0, source, target) == pytest.approx(151.0)


def test_mapping_uses_own_sub_rng(monkeypatch):
    # from と to が同じ表なら、写した値は「元の値 + 副乱数 − 0.5」になる
    points = [100.0, 200.0]
    monkeypatch.setattr(app, "FICTIONAL_PITCHER_SPEED_SHAPE_OVERRIDE", {key: {"from": points, "to": points} for key in KEYS})
    for seed in (1, 2, 3):
        expected = 150.25 + app.make_sub_rng(seed, "fictional_pitcher_speed_shape_v1").random() - 0.5
        assert app.fictional_pitcher_speed_shape(150.25, ("先発", "右"), seed) == pytest.approx(expected)


def test_shape_only_moves_speed_dependent_items_of_older_pitchers(monkeypatch):
    # 写さない場合と比べる。21歳以下は全項目一致。22歳以上も、名前・年齢・ポジション・投打・格・コントロール・スタミナは一致する。
    # 球速と球速から決まる項目（肩力・変化球・特能・ランク特能・査定）は動いてよい。身長・体重も、球速の帯で共通の乱数を引く回数が
    # 変わる（ノビのランクの連動など）ので、そのあとで共通の乱数から引く体格の調整がずれて動くことがある。
    current = generate("投手", "架空球団用", table=None, monkeypatch=monkeypatch)
    neutral = generate("投手", "架空球団用", table={}, monkeypatch=monkeypatch)
    moved = 0
    for a, b in zip(current, neutral):
        if a["roster_origin"] != "domestic" or a["age"] <= app.FICTIONAL_YOUNG_MAX_AGE:
            assert a == b
            continue
        for key in ("name", "age", "position", "batting_throwing", "player_class", "nationality", "birthplace"):
            assert a[key] == b[key]
        assert a["abilities"]["コントロール"] == b["abilities"]["コントロール"]
        assert a["abilities"]["スタミナ"] == b["abilities"]["スタミナ"]
        moved += app.pitcher_speed_value(a["abilities"]) != app.pitcher_speed_value(b["abilities"])
    assert moved > 0


@pytest.mark.parametrize("role,category", [("野手", "架空球団用"), ("投手", "ドラフト候補用"), ("野手", "ドラフト候補用"),
                                           ("投手", "助っ人外国人用"), ("野手", "助っ人外国人用")])
def test_other_categories_do_not_change(monkeypatch, role, category):
    seeds = range(1, 101)
    current = generate(role, category, seeds, table=None, monkeypatch=monkeypatch)
    neutral = generate(role, category, seeds, table={}, monkeypatch=monkeypatch)
    assert current == neutral
