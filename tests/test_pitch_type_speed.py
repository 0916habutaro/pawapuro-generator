"""架空球団用の日本人投手の、変化球の方向と球種を球速で引き直す処理（変化球の種類と球速_改修指示.md）。

表は実在から作っており、正式な判定は scripts/check_pitcher_rank_pitches.py（球団生成300球団）の「変化球の種類と球速」の節。
ここでは、速い投手ほどフォーク方向・遅い投手ほどシンカー方向を持ちやすいこと、変化球数と変化量が変わらないこと、
投げ手専用の球種が出ないこと、第二球種の変化量、副乱数の名前、ほかの区分が変わらないことを確かめる。
"""
from __future__ import annotations

import random

import pytest

import app

MASTER = app.load_master_data()
SEEDS = range(1, 401)
RIGHT_ONLY = {"シンカー", "Hシンカー"}
LEFT_ONLY = {"スクリュー"}


def domestic_pitchers(seeds=SEEDS) -> list[dict]:
    players = (app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in seeds)
    return [player for player in players if player["roster_origin"] == "domestic"]


def sample_balls() -> list[list[dict]]:
    """引き直す前の形に近い変化球の並び（表を使わずに作った架空球団用の投手の変化球）。"""
    app.FICTIONAL_PITCH_TYPE_SPEED_OVERRIDE = {}
    try:
        return [(player["batting_throwing"], player["breaking_balls"]) for player in domestic_pitchers(range(1, 201))]
    finally:
        app.FICTIONAL_PITCH_TYPE_SPEED_OVERRIDE = None


def test_namespace_and_table():
    assert app.FICTIONAL_PITCH_TYPE_SPEED_NAMESPACE == "fictional_pitch_type_speed_v1"
    table = app.load_fictional_pitch_type_speed()
    assert table["中心"] == {"右投": 152.0, "左投": 149.0} and table["幅"] == 4.0 and table["x上限"] == 2.5
    assert "ナックル" not in {name for hand in table["球種の重み"].values() for items in hand.values() for name in items}
    assert app.pitch_type_speed_x(table, 170, "右投") == 2.5 and app.pitch_type_speed_x(table, 120, "左投") == -2.5


def test_fast_pitchers_get_more_fork_direction_and_slow_pitchers_more_sinker_direction():
    balls = [app.make_breaking_ball("スライダー", 3, False, 1), app.make_breaking_ball("シンカー", 2, False, 1)]
    shares = {}
    for speed in (142, 160):
        fork = sinker = 0
        for seed in range(2000):
            result = app.fictional_pitch_type_by_speed(random.Random(seed), balls, speed, "右投右打")
            codes = {ball["direction_code"] for ball in app.primary_breaking_balls(result)}
            fork += "3" in codes
            sinker += "4" in codes
        shares[speed] = (fork / 2000, sinker / 2000)
    assert shares[160][0] > shares[142][0] + 0.2
    assert shares[142][1] > shares[160][1] + 0.1


def test_count_and_movement_are_kept_and_hand_only_pitches_do_not_appear():
    clamped = 0
    for batting_throwing, balls in sample_balls():
        for speed in (140, 150, 158):
            result = app.fictional_pitch_type_by_speed(random.Random(speed), balls, speed, batting_throwing)
            before, after = app.primary_breaking_balls(balls), app.primary_breaking_balls(result)
            assert len(before) == len(after)
            assert [b for b in balls if b["kind"] != "breaking"] == [b for b in result if b["kind"] != "breaking"]
            for old, new in zip(before, after):
                master = app.BREAKING_BY_NAME[new["name"]]
                if app.pitch_movement(old) != app.pitch_movement(new):
                    clamped += 1
                    assert not master["min_movement"] <= app.pitch_movement(old) <= master["max_movement"]
                assert new["direction_code"] == master["direction_code"]
                assert app.is_pitch_allowed_for_generation(new["direction_code"], new["name"], batting_throwing)
            assert len({ball["direction_code"] for ball in after}) == len(after)
            names = {ball["name"] for ball in result if ball["kind"] == "breaking"}
            assert "ナックル" not in names
            assert not names & (RIGHT_ONLY if batting_throwing.startswith("左投") else LEFT_ONLY)
            primary_by_code = {ball["direction_code"]: ball for ball in after}
            for ball in result:
                if ball["kind"] == "breaking" and ball["is_second_pitch"]:
                    primary = primary_by_code[ball["direction_code"]]
                    assert ball["name"] != primary["name"]
                    assert app.BREAKING_BY_NAME[ball["name"]]["second_pitch_allowed"]
                    assert app.pitch_movement(ball) <= app.pitch_movement(primary)
    assert clamped < 30  # 範囲に収めるのはまれ


def test_generated_pitchers_change_only_in_pitch_types():
    app.FICTIONAL_PITCH_TYPE_SPEED_OVERRIDE = {}
    try:
        before = domestic_pitchers()
    finally:
        app.FICTIONAL_PITCH_TYPE_SPEED_OVERRIDE = None
    after = domestic_pitchers()
    changed = 0
    for a, b in zip(before, after):
        for key in ("name", "age", "position", "batting_throwing", "height", "weight"):
            assert a[key] == b[key]
        for key in ("球速", "コントロール", "スタミナ", "肩力"):
            assert a["abilities"][key] == b["abilities"][key]
        assert len(app.primary_breaking_balls(a["breaking_balls"])) == len(app.primary_breaking_balls(b["breaking_balls"]))
        changed += a["breaking_balls"] != b["breaking_balls"]
    assert changed > len(after) // 2


@pytest.mark.parametrize(("role", "category"), [
    ("投手", "助っ人外国人用"), ("野手", "助っ人外国人用"),
    ("投手", "ドラフト候補用"), ("野手", "ドラフト候補用"),
    ("野手", "架空球団用"),
])
def test_other_categories_ignore_the_table(monkeypatch, role, category):
    seeds = range(1, 101)
    current = [app.generate_player(role, category, MASTER, seed=seed) for seed in seeds]
    monkeypatch.setattr(app, "FICTIONAL_PITCH_TYPE_SPEED_OVERRIDE", {})
    assert [app.generate_player(role, category, MASTER, seed=seed) for seed in seeds] == current


def test_foreign_pitchers_in_fictional_category_are_unchanged(monkeypatch):
    seeds = range(1, 301)
    current = [app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in seeds]
    monkeypatch.setattr(app, "FICTIONAL_PITCH_TYPE_SPEED_OVERRIDE", {})
    changed = [app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in seeds]
    foreign = [(a, b) for a, b in zip(current, changed) if a["roster_origin"] != "domestic"]
    assert foreign and all(a == b for a, b in foreign)
