"""架空球団用の日本人投手の、先発の球種の数と総変化量（変化球の数と変化量_改修指示.md）。

係数は球団生成で合わせており、正式な判定は scripts/check_pitcher_rank_pitches.py（球団生成300球団）の「先発の球種の数と総変化量」の節。
ここでは、23歳以下・コントロール50未満の先発に4球種が出ないこと、年長・コントロールの良い先発ほど球種が多いこと、
救援の球種数が変わらないこと、乱数を引く回数、総変化量の段階が −3〜+3 に収まること、ほかの区分が変わらないことを確かめる。
"""
from __future__ import annotations

import random

import pytest

import app

MASTER = app.load_master_data()
NEUTRAL_COUNT = {**app.FICTIONAL_PITCH_COUNT_AGE_CONTROL, "a_old": 0.0, "a_ctl": 0.0, "four_max_age": 0, "four_control_below": 0}


class CountingRandom(random.Random):
    """random() を呼んだ回数を数える。"""

    def __init__(self, seed: int):
        super().__init__(seed)
        self.calls = 0

    def random(self) -> float:
        self.calls += 1
        return super().random()


def balls_of(*items: tuple[str, int]) -> list[dict]:
    return [app.make_breaking_ball(name, movement, False, 1) for name, movement in items]


TWO = balls_of(("スライダー", 3), ("フォーク", 2))
THREE = balls_of(("スライダー", 3), ("カーブ", 2), ("フォーク", 4))
FOUR = balls_of(("スライダー", 3), ("カーブ", 2), ("フォーク", 4), ("シンカー", 1))


def primary_count(balls: list[dict]) -> int:
    return len(app.primary_breaking_balls(balls))


def domestic_pitchers(seeds) -> list[dict]:
    players = (app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in seeds)
    return [player for player in players if player["roster_origin"] == "domestic"]


def test_namespace_and_constants():
    assert app.FICTIONAL_PITCH_COUNT_AGE_CONTROL_NAMESPACE == "fictional_pitch_count_age_control_v1"
    cfg = app.FICTIONAL_PITCH_COUNT_AGE_CONTROL
    assert (cfg["four_max_age"], cfg["four_control_below"], cfg["four_min_age"], cfg["four_min_control"]) == (23, 50, 25, 55)
    starter = app.FICTIONAL_MOVEMENT_QUALITY["先発"]
    assert starter["count"][1] == 2.65 and starter["speed"][1:] == (151.0, 4.0) and starter["pull"][1] == 6.5
    assert app.FICTIONAL_MOVEMENT_QUALITY["救援"]["speed"][1:] == (151.0, 4.0)


@pytest.mark.parametrize(("age", "control"), [(22, 80), (23, 60), (30, 49), (35, 30)])
def test_young_or_low_control_starters_drop_the_fourth_pitch(age, control):
    smallest = min(app.primary_breaking_balls(FOUR), key=app.pitch_movement)["name"]
    for seed in range(50):
        result = app.fictional_pitch_count_by_age_control(random.Random(seed), FOUR, age, control, "右投右打")
        assert primary_count(result) == 3
        assert smallest not in {ball["name"] for ball in result}


def test_fourth_pitch_needs_age_and_control():
    for age, control in ((24, 90), (34, 54), (22, 95)):
        for seed in range(300):
            assert primary_count(app.fictional_pitch_count_by_age_control(random.Random(seed), THREE, age, control, "右投右打")) == 3
    added = sum(primary_count(app.fictional_pitch_count_by_age_control(random.Random(seed), THREE, 35, 85, "右投右打")) == 4 for seed in range(2000))
    assert 0 < added < 2000 * 0.4


def test_older_and_better_control_starters_have_more_pitches():
    def mean_count(balls: list[dict], age: int, control: float) -> float:
        counts = [primary_count(app.fictional_pitch_count_by_age_control(random.Random(seed), balls, age, control, "左投左打")) for seed in range(1000)]
        return sum(counts) / len(counts)

    assert mean_count(TWO, 34, 70) > mean_count(TWO, 30, 58) > mean_count(TWO, 25, 55) == 2.0
    assert mean_count(THREE, 24, 35) < 3.0  # s < 0 なら 3→2 がある
    assert mean_count(TWO, 24, 35) == 2.0


def test_added_pitch_is_a_new_direction_and_allowed():
    for seed in range(300):
        for batting_throwing in ("右投右打", "左投左打"):
            result = app.fictional_pitch_count_by_age_control(random.Random(seed), TWO, 35, 80, batting_throwing)
            primaries = app.primary_breaking_balls(result)
            assert len({ball["direction_code"] for ball in primaries}) == len(primaries)
            for ball in primaries:
                assert app.is_pitch_allowed_for_generation(ball["direction_code"], ball["name"], batting_throwing)
                master = app.BREAKING_BY_NAME[ball["name"]]
                assert master["min_movement"] <= app.pitch_movement(ball) <= master["max_movement"]
    assert TWO == balls_of(("スライダー", 3), ("フォーク", 2))  # 渡した球は書き換えない


def test_no_pitch_is_added_when_four_are_visible():
    second = app.make_breaking_ball("Hスライダー", 2, True, 2)
    second["direction_code"] = "1"
    four_visible = [*THREE, second]
    for seed in range(300):
        assert app.fictional_pitch_count_by_age_control(random.Random(seed), four_visible, 35, 90, "右投右打") == four_visible


@pytest.mark.parametrize(("balls", "age", "control"), [
    (TWO, 35, 80), (TWO, 24, 40), (THREE, 35, 80), (THREE, 22, 30), (FOUR, 22, 80), (FOUR, 32, 70), (balls_of(("スライダー", 4)), 30, 60),
])
def test_count_draws_three_times(balls, age, control):
    for seed in range(20):
        rng = CountingRandom(seed)
        app.fictional_pitch_count_by_age_control(rng, balls, age, control, "右投右打")
        assert rng.calls == 3


def test_movement_by_quality_draws_once_and_steps_are_bounded():
    for balls in (TWO, THREE, FOUR):
        for role in ("先発", "救援"):
            for control, stamina, speed in ((95, 100, 165), (15, 15, 125), (55, 57, 151)):
                rng = CountingRandom(1)
                result = app.fictional_movement_by_quality(rng, balls, role, control, stamina, speed=speed)
                assert rng.calls == 1
                diff = sum(map(app.pitch_movement, app.primary_breaking_balls(result))) - sum(map(app.pitch_movement, app.primary_breaking_balls(balls)))
                assert abs(diff) <= app.FICTIONAL_MOVEMENT_QUALITY_MAX_STEPS
                assert [ball["name"] for ball in result] == [ball["name"] for ball in balls]


def test_movement_follows_speed_and_pitch_count():
    def mean_total(balls: list[dict], speed: float, role: str = "先発") -> float:
        totals = [sum(map(app.pitch_movement, app.fictional_movement_by_quality(random.Random(seed), balls, role, 55, 57, speed=speed)))
                  for seed in range(400)]
        return sum(totals) / len(totals)

    assert mean_total(THREE, 157) > mean_total(THREE, 151) > mean_total(THREE, 145)
    # 今の総変化量が同じ（6）なら、球種が多いほうが増える
    assert mean_total(balls_of(("スライダー", 3), ("フォーク", 3)), 151) < mean_total(balls_of(("スライダー", 2), ("カーブ", 2), ("フォーク", 2)), 151)
    assert mean_total(THREE, 157, "救援") > mean_total(THREE, 145, "救援")


def test_starters_change_only_in_pitch_count_and_relievers_keep_count(monkeypatch):
    seeds = range(1, 601)
    current = domestic_pitchers(seeds)
    monkeypatch.setattr(app, "FICTIONAL_PITCH_COUNT_AGE_CONTROL", NEUTRAL_COUNT)
    neutral = domestic_pitchers(seeds)
    changed = 0
    for a, b in zip(current, neutral):
        for key in ("name", "age", "position", "batting_throwing", "height", "weight"):
            assert a[key] == b[key]
        for key in ("球速", "コントロール", "スタミナ", "肩力"):
            assert a["abilities"][key] == b["abilities"][key]
        assert a["abilities"]["ranked_specials"] == b["abilities"]["ranked_specials"]
        if a["position"] != "先発":
            assert a["breaking_balls"] == b["breaking_balls"]
        else:
            changed += primary_count(a["breaking_balls"]) != primary_count(b["breaking_balls"])
    assert changed > 0


def test_generated_starters_have_no_fourth_pitch_when_young_or_low_control():
    starters = [p for p in domestic_pitchers(range(1, 3001)) if p["position"] == "先発"]
    assert starters
    for player in starters:
        if player["age"] <= 23 or app.ability_numeric_value(player["abilities"], "コントロール") < 50:
            assert primary_count(player["breaking_balls"]) <= 3


@pytest.mark.parametrize(("role", "category"), [
    ("投手", "助っ人外国人用"), ("野手", "助っ人外国人用"),
    ("投手", "ドラフト候補用"), ("野手", "ドラフト候補用"),
    ("野手", "架空球団用"),
])
def test_other_categories_ignore_count_and_movement_settings(monkeypatch, role, category):
    seeds = range(1, 101)
    current = [app.generate_player(role, category, MASTER, seed=seed) for seed in seeds]
    monkeypatch.setattr(app, "FICTIONAL_PITCH_COUNT_AGE_CONTROL", {**NEUTRAL_COUNT, "four_max_age": 99})
    monkeypatch.setattr(app, "FICTIONAL_MOVEMENT_QUALITY", {r: {**cfg, "speed": (5.0, 151.0, 4.0)} for r, cfg in app.FICTIONAL_MOVEMENT_QUALITY.items()})
    assert [app.generate_player(role, category, MASTER, seed=seed) for seed in seeds] == current


def test_foreign_pitchers_in_fictional_category_are_unchanged(monkeypatch):
    seeds = range(1, 301)
    current = [app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in seeds]
    monkeypatch.setattr(app, "FICTIONAL_PITCH_COUNT_AGE_CONTROL", {**NEUTRAL_COUNT, "four_max_age": 99})
    changed = [app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in seeds]
    foreign = [(a, b) for a, b in zip(current, changed) if a["roster_origin"] != "domestic"]
    assert foreign and all(a == b for a, b in foreign)
