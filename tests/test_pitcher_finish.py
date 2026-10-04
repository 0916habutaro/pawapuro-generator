"""架空球団用の日本人投手の仕上げ（先発のスタミナ・総変化量。投手の仕上げ_改修指示.md）。

定数は球団生成で合わせており、正式な判定は scripts/check_pitcher_control.py（球団生成300球団）。
ここでは個別生成で、左右差・幅・良し悪しとの結びつきの向きと、ほかの区分・項目が変わらないことを確かめる。
"""
from __future__ import annotations

import random
import statistics

import pytest

import app

MASTER = app.load_master_data()
SEEDS = range(1, 2001)
NEUTRAL_STAMINA = {"S0": 57.0, "A": 1.0, "D": {"右": 0.0, "左": 0.0}}
NEUTRAL_MOVEMENT = {role: {**cfg, "B": 0.0, "O": 0.0} for role, cfg in app.FICTIONAL_MOVEMENT_QUALITY.items()}


def ability(player: dict, key: str) -> int:
    return app.ability_numeric_value(player["abilities"], key)


def total_movement(player: dict) -> int:
    return sum(app.pitch_movement(ball) for ball in app.primary_breaking_balls(player["breaking_balls"]))


@pytest.fixture(scope="module")
def pitchers() -> list[dict]:
    players = (app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in SEEDS)
    return [player for player in players if player["roster_origin"] == "domestic"]


def adult_starters(pitchers: list[dict], hand: str) -> list[int]:
    return [
        ability(p, "スタミナ") for p in pitchers
        if p["position"] == "先発" and p["age"] > app.FICTIONAL_YOUNG_MAX_AGE and p["batting_throwing"].startswith(hand)
    ]


def test_starter_stamina_has_hand_gap_and_wide_spread(pitchers):
    right, left = adult_starters(pitchers, "右投"), adult_starters(pitchers, "左投")
    # 実在（2024〜2026年版の日本人）は左が約2.4低く、標準偏差は右11.6・左9.8。個別生成は二軍級が多いので幅は広めに見る。
    assert -4.5 <= statistics.fmean(left) - statistics.fmean(right) <= -0.8
    assert statistics.pstdev(right) >= 10.0
    assert statistics.pstdev(left) >= 9.0


def test_total_movement_follows_pitcher_quality(pitchers):
    # 実在は良い投手ほど総変化量が多い（先発: ×コントロール 0.46、×スタミナ 0.62。救援: ×コントロール 0.31）。
    starters = [p for p in pitchers if p["position"] == "先発"]
    relievers = [p for p in pitchers if p["position"] != "先発"]
    assert statistics.correlation([ability(p, "コントロール") for p in starters], [total_movement(p) for p in starters]) >= 0.30
    assert statistics.correlation([ability(p, "スタミナ") for p in starters], [total_movement(p) for p in starters]) >= 0.30
    assert statistics.correlation([ability(p, "コントロール") for p in relievers], [total_movement(p) for p in relievers]) >= 0.20


def test_starter_stamina_transform_touches_only_adult_starter_stamina(monkeypatch):
    seeds = range(1, 401)
    current = [app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in seeds]
    monkeypatch.setattr(app, "FICTIONAL_STARTER_STAMINA_TRANSFORM", NEUTRAL_STAMINA)
    neutral = [app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in seeds]
    changed = 0
    for a, b in zip(current, neutral):
        adult_starter = a["roster_origin"] == "domestic" and a["position"] == "先発" and a["age"] > app.FICTIONAL_YOUNG_MAX_AGE
        if not adult_starter:
            assert a == b  # 救援・21歳以下・外国人は同じ
            continue
        for key in ("name", "age", "position", "batting_throwing"):
            assert a[key] == b[key]
        for key in ("球速", "コントロール"):
            assert a["abilities"][key] == b["abilities"][key]
        # 総変化量は最終的なスタミナで増減するので、変化球の種類・方向だけ比べる
        assert [(x["name"], x.get("direction_code")) for x in a["breaking_balls"] if not x.get("is_second_pitch")] == [
            (x["name"], x.get("direction_code")) for x in b["breaking_balls"] if not x.get("is_second_pitch")
        ]
        changed += ability(a, "スタミナ") != ability(b, "スタミナ")
    assert changed > 0


def test_movement_by_quality_keeps_pitch_kinds_and_only_moves_primary_pitches(monkeypatch):
    seeds = range(1, 401)
    current = [app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in seeds]
    monkeypatch.setattr(app, "FICTIONAL_MOVEMENT_QUALITY", NEUTRAL_MOVEMENT)
    neutral = [app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in seeds]
    changed = 0
    for a, b in zip(current, neutral):
        if a["roster_origin"] != "domestic":
            assert a == b
            continue
        for key in ("name", "age", "position", "batting_throwing"):
            assert a[key] == b[key]
        for key in ("球速", "コントロール", "スタミナ"):
            assert a["abilities"][key] == b["abilities"][key]
        shape = lambda p: [(ball["name"], ball.get("direction_code"), ball.get("kind"), ball.get("is_second_pitch")) for ball in p["breaking_balls"]]
        # 第二球種は同じ方向の第一球種を超えないよう揃えるので、減ると消えることがある。種類・数・方向は第一球種で比べる。
        assert [s for s in shape(a) if not s[3]] == [s for s in shape(b) if not s[3]]
        changed += total_movement(a) != total_movement(b)
        assert abs(total_movement(a) - total_movement(b)) <= app.FICTIONAL_MOVEMENT_QUALITY_MAX_STEPS
        for ball in a["breaking_balls"]:
            if ball.get("kind") == "second_fastball":
                assert ball in b["breaking_balls"]
    assert changed > 0


@pytest.mark.parametrize("control, stamina, expected_sign", [(80, 90, 1), (20, 20, -1)])
def test_movement_steps_are_bounded_and_directional(control, stamina, expected_sign):
    balls = [
        app.make_breaking_ball("スライダー", 4, False, 1), app.make_breaking_ball("フォーク", 2, False, 1),
        app.make_breaking_ball("カーブ", 3, False, 1),
    ]
    before = {ball["name"]: app.pitch_movement(ball) for ball in balls}
    result = app.fictional_movement_by_quality(random.Random(1), balls, "先発", control, stamina)
    after = {ball["name"]: app.pitch_movement(ball) for ball in result}
    assert before == {ball["name"]: app.pitch_movement(ball) for ball in balls}  # 渡した球は書き換えない
    assert [b["name"] for b in result] == [b["name"] for b in balls]
    diff = sum(after.values()) - sum(before.values())
    assert diff * expected_sign > 0 and abs(diff) <= app.FICTIONAL_MOVEMENT_QUALITY_MAX_STEPS
    for ball in result:
        master = app.BREAKING_BY_NAME[ball["name"]]
        assert master.get("min_movement", 1) <= app.pitch_movement(ball) <= master.get("max_movement", 7)


@pytest.mark.parametrize(("role", "category"), [
    ("投手", "助っ人外国人用"), ("野手", "助っ人外国人用"),
    ("投手", "ドラフト候補用"), ("野手", "ドラフト候補用"),
    ("野手", "架空球団用"),
])
def test_other_categories_ignore_finish_settings(monkeypatch, role, category):
    seeds = range(1, 101)
    current = [app.generate_player(role, category, MASTER, seed=seed) for seed in seeds]
    monkeypatch.setattr(app, "FICTIONAL_STARTER_STAMINA_TRANSFORM", {"S0": 57.0, "A": 0.1, "D": {"右": -20.0, "左": -20.0}})
    monkeypatch.setattr(app, "FICTIONAL_MOVEMENT_QUALITY", {role_: {**cfg, "B": 5.0, "O": -5.0} for role_, cfg in app.FICTIONAL_MOVEMENT_QUALITY.items()})
    assert [app.generate_player(role, category, MASTER, seed=seed) for seed in seeds] == current
