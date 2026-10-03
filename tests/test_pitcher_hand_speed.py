"""架空球団用の日本人投手の球速の左右差・先発と救援の差（投手球速左右差_改修指示.md）。

正式な判定は scripts/check_fictional_balance.py（5000人）。ここでは2000人で主な項目を少し広めの範囲で確かめる。
"""
from __future__ import annotations

import statistics

import pytest

import app

MASTER = app.load_master_data()
SEEDS = range(1, 2001)
# 実在（2024〜2026年版の日本人投手）
REAL_MEANS = {("先発", "右"): 151.39, ("先発", "左"): 148.69, ("救援", "右"): 153.23, ("救援", "左"): 149.74}


def speed_key(player: dict) -> tuple[str, str]:
    return ("先発" if player["position"] == "先発" else "救援", "左" if player["batting_throwing"].startswith("左投") else "右")


def speed(player: dict) -> int:
    return app.pitcher_speed_value(player["abilities"])


@pytest.fixture(scope="module")
def pitchers() -> list[dict]:
    players = (app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in SEEDS)
    return [player for player in players if player["roster_origin"] == "domestic"]


def group_means(players: list[dict]) -> dict[tuple[str, str], float]:
    groups: dict[tuple[str, str], list[int]] = {}
    for player in players:
        groups.setdefault(speed_key(player), []).append(speed(player))
    return {key: statistics.fmean(values) for key, values in groups.items()}


def test_speed_means_by_role_and_hand_follow_real(pitchers):
    means = group_means(pitchers)
    for key, real in REAL_MEANS.items():
        assert abs(means[key] - real) <= 0.8, (key, means[key])
    assert -3.5 <= means[("先発", "左")] - means[("先発", "右")] <= -1.9
    assert -4.3 <= means[("救援", "左")] - means[("救援", "右")] <= -2.7
    assert 1.0 <= means[("救援", "右")] - means[("先発", "右")] <= 2.6
    assert abs(statistics.fmean(speed(player) for player in pitchers) - 151.37) <= 0.4


def test_left_pitchers_rarely_reach_155(pitchers):
    left = [speed(player) for player in pitchers if player["batting_throwing"].startswith("左投")]
    assert sum(value >= 155 for value in left) / len(left) <= 0.06


def test_young_pitchers_keep_hand_gap(pitchers):
    young = [player for player in pitchers if player["age"] <= app.FICTIONAL_YOUNG_MAX_AGE]
    right = [speed(player) for player in young if not player["batting_throwing"].startswith("左投")]
    left = [speed(player) for player in young if player["batting_throwing"].startswith("左投")]
    assert statistics.fmean(right) - statistics.fmean(left) >= 2.0


def test_hand_shift_does_not_move_control_or_stamina(monkeypatch):
    # 左右のずらし・裾はコントロール・スタミナの連動に入れない。ずらしを0にしても制球・スタミナ・変化球は同じ。
    seeds = range(1, 201)
    current = [app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in seeds]
    monkeypatch.setattr(app, "FICTIONAL_PITCHER_HAND_SPEED_SHIFTS", {key: 0.0 for key in app.FICTIONAL_PITCHER_HAND_SPEED_SHIFTS})
    monkeypatch.setattr(app, "FICTIONAL_PITCHER_HAND_SPEED_TAILS", {key: () for key in app.FICTIONAL_PITCHER_HAND_SPEED_TAILS})
    neutral = [app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in seeds]
    changed = 0
    for a, b in zip(current, neutral):
        for key in ("name", "age", "position", "batting_throwing"):
            assert a[key] == b[key]
        assert [ball["name"] for ball in a["breaking_balls"]] == [ball["name"] for ball in b["breaking_balls"]]
        if a["roster_origin"] == "domestic":
            assert a["abilities"]["コントロール"] == b["abilities"]["コントロール"]
            assert a["abilities"]["スタミナ"] == b["abilities"]["スタミナ"]
            changed += speed(a) != speed(b)
        else:
            assert a == b
    assert changed > 0


@pytest.mark.parametrize(("role", "category"), [
    ("投手", "助っ人外国人用"), ("野手", "助っ人外国人用"),
    ("投手", "ドラフト候補用"), ("野手", "ドラフト候補用"),
    ("野手", "架空球団用"),
])
def test_other_categories_ignore_hand_speed_settings(monkeypatch, role, category):
    seeds = range(1, 101)
    current = [app.generate_player(role, category, MASTER, seed=seed) for seed in seeds]
    monkeypatch.setattr(app, "FICTIONAL_PITCHER_HAND_SPEED_SHIFTS", {key: -5.0 for key in app.FICTIONAL_PITCHER_HAND_SPEED_SHIFTS})
    monkeypatch.setattr(app, "FICTIONAL_PITCHER_HAND_SPEED_TAILS", {key: ((150.0, 0.1, True),) for key in app.FICTIONAL_PITCHER_HAND_SPEED_TAILS})
    assert [app.generate_player(role, category, MASTER, seed=seed) for seed in seeds] == current
