"""架空球団用の日本人投手のコントロールの役割・左右と救援の幅（救援投手コントロール_改修指示.md）。

定数は球団生成で合わせており、正式な判定は scripts/check_pitcher_control.py（球団生成300球団）。
ここでは個別生成2000人で、個別生成の下限（実在−2.5以上、救援の60以上が9%以上）と主な形を確かめる。
"""
from __future__ import annotations

import statistics

import pytest

import app

MASTER = app.load_master_data()
SEEDS = range(1, 2001)
# 実在（2024〜2026年版の日本人投手）
REAL_MEANS = {("先発", "右"): 54.47, ("先発", "左"): 56.67, ("救援", "右"): 48.54, ("救援", "左"): 47.01}


def group_key(player: dict) -> tuple[str, str]:
    return ("先発" if player["position"] == "先発" else "救援", "左" if player["batting_throwing"].startswith("左投") else "右")


def control(player: dict) -> int:
    return app.ability_numeric_value(player["abilities"], "コントロール")


@pytest.fixture(scope="module")
def pitchers() -> list[dict]:
    players = (app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in SEEDS)
    return [player for player in players if player["roster_origin"] == "domestic"]


def test_control_means_by_role_and_hand(pitchers):
    groups: dict[tuple[str, str], list[int]] = {}
    for player in pitchers:
        groups.setdefault(group_key(player), []).append(control(player))
    means = {key: statistics.fmean(values) for key, values in groups.items()}
    for key, real in REAL_MEANS.items():
        # 個別生成は二軍級が多く球団生成より低い。下限は実在−2.5（2000人なので少し広め）、上は実在+0.8まで。
        assert real - 2.8 <= means[key] <= real + 0.8, (key, means[key])
    assert means[("先発", "左")] - means[("先発", "右")] > 0
    assert means[("救援", "左")] - means[("救援", "右")] < 0
    assert -7.0 <= means[("救援", "右")] - means[("先発", "右")] <= -4.9


def test_reliever_control_spread_follows_real(pitchers):
    relievers = [control(player) for player in pitchers if player["position"] != "先発"]
    assert 9.0 <= statistics.pstdev(relievers) <= 11.5
    assert 0.09 <= sum(value >= 60 for value in relievers) / len(relievers) <= 0.19
    assert sum(value >= 70 for value in relievers) / len(relievers) <= 0.04


def test_reliever_squeeze_keeps_stamina_and_other_values(monkeypatch):
    # 救援の縮め・左右のずらしはスタミナの連動に入れない。縮めない設定にしても、コントロール以外の能力・球速・変化球は同じ。
    seeds = range(1, 201)
    current = [app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in seeds]
    monkeypatch.setattr(app, "FICTIONAL_RELIEVER_CONTROL_SCALES", {key: (1.0, 1.0) for key in app.FICTIONAL_RELIEVER_CONTROL_SCALES})
    monkeypatch.setattr(app, "FICTIONAL_PITCHER_HAND_CONTROL_SHIFTS", {key: 0.0 for key in app.FICTIONAL_PITCHER_HAND_CONTROL_SHIFTS})
    neutral = [app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in seeds]
    changed = 0
    for a, b in zip(current, neutral):
        for key in ("name", "age", "position", "batting_throwing"):
            assert a[key] == b[key]
        assert [ball["name"] for ball in a["breaking_balls"]] == [ball["name"] for ball in b["breaking_balls"]]
        if a["roster_origin"] == "domestic":
            for key in ("球速", "スタミナ", "肩力"):
                assert a["abilities"][key] == b["abilities"][key]
            changed += control(a) != control(b)
        else:
            assert a == b
    assert changed > 0


@pytest.mark.parametrize(("role", "category"), [
    ("投手", "助っ人外国人用"), ("野手", "助っ人外国人用"),
    ("投手", "ドラフト候補用"), ("野手", "ドラフト候補用"),
    ("野手", "架空球団用"),
])
def test_other_categories_ignore_reliever_control_settings(monkeypatch, role, category):
    seeds = range(1, 101)
    current = [app.generate_player(role, category, MASTER, seed=seed) for seed in seeds]
    monkeypatch.setattr(app, "FICTIONAL_RELIEVER_CONTROL_SCALES", {key: (0.1, 0.1) for key in app.FICTIONAL_RELIEVER_CONTROL_SCALES})
    monkeypatch.setattr(app, "FICTIONAL_PITCHER_HAND_CONTROL_SHIFTS", {key: -20.0 for key in app.FICTIONAL_PITCHER_HAND_CONTROL_SHIFTS})
    assert [app.generate_player(role, category, MASTER, seed=seed) for seed in seeds] == current
