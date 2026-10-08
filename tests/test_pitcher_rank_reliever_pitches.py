"""架空球団用の日本人投手の、ランク特能の役割の差と救援の球種数（投手のランク特能と救援の球種数_改修指示.md）。

定数は球団生成で合わせており、正式な判定は scripts/check_pitcher_rank_pitches.py（球団生成300球団）。
ここでは個別生成で、役割ごとの重みが使われること、救援だけ球種が減ること、決め球が残ること、ほかの区分が変わらないことを確かめる。
"""
from __future__ import annotations

import pytest

import app

MASTER = app.load_master_data()
SEEDS = range(1, 601)
NEUTRAL_MOVEMENT = {role: {**cfg, "B": 0.0, "O": 0.0} for role, cfg in app.FICTIONAL_MOVEMENT_QUALITY.items()}
ALWAYS = (1.0, 1.0, 1.0, 1.0)
NEVER = (0.0, 0.0, 0.0, 0.0)


class CountingRandom:
    """random() の呼び出し回数を数え、決まった値を返す。"""

    def __init__(self, value: float):
        self.value = value
        self.calls = 0

    def random(self) -> float:
        self.calls += 1
        return self.value


def primaries(player: dict) -> list[dict]:
    return app.primary_breaking_balls(player["breaking_balls"])


def domestic_pitchers() -> list[dict]:
    players = (app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in SEEDS)
    return [player for player in players if player["roster_origin"] == "domestic"]


def test_weights_key_splits_nobi_and_recovery_by_role_and_left_batters_by_hand():
    key = app.fictional_pitcher_ranked_weights_key
    assert key("ノビ", "先発", "右投右打") == "ノビ_先発"
    assert key("ノビ", "中継ぎ", "右投右打") == "ノビ_救援"
    assert key("回復", "抑え", "左投左打") == "回復_救援"
    assert key("回復", "先発", "左投左打") == "回復_先発"
    assert key("対左打者", "中継ぎ", "左投左打") == "対左打者_左投"
    assert key("対左打者", "先発", "右投左打") == "対左打者"
    assert key("対ピンチ", "中継ぎ", "左投左打") == "対ピンチ"
    for name in ("ノビ_先発", "ノビ_救援", "回復_先発", "回復_救援", "対左打者", "対左打者_左投"):
        assert name in app.FICTIONAL_PITCHER_RANKED_WEIGHTS


def test_role_weights_are_used(monkeypatch):
    weights = dict(app.FICTIONAL_PITCHER_RANKED_WEIGHTS)
    weights["ノビ_先発"] = {"C": 1.0}
    weights["ノビ_救援"] = {"F": 1.0}
    weights["回復_先発"] = {"F": 1.0}
    weights["回復_救援"] = {"C": 1.0}
    monkeypatch.setattr(app, "FICTIONAL_PITCHER_RANKED_WEIGHTS", weights)
    for player in domestic_pitchers():
        ranked = player["abilities"]["ranked_specials"]
        nobi, recovery = ranked.get("ノビ", "ノビD")[-1], ranked.get("回復", "回復D")[-1]
        if player["position"] == "先発":
            assert nobi in "BCD" and recovery in "EFG", (player.get("seed"), nobi, recovery)
        else:
            assert nobi in "EFG" and recovery in "BCD", (player.get("seed"), nobi, recovery)


def test_role_weights_do_not_change_the_random_stream(monkeypatch):
    current = domestic_pitchers()
    weights = {key: ({"D": 1.0} if key.startswith(("ノビ", "回復")) else value) for key, value in app.FICTIONAL_PITCHER_RANKED_WEIGHTS.items()}
    monkeypatch.setattr(app, "FICTIONAL_PITCHER_RANKED_WEIGHTS", weights)
    changed = domestic_pitchers()
    for a, b in zip(current, changed):
        assert {k: v for k, v in a.items() if k != "abilities"} == {k: v for k, v in b.items() if k != "abilities"}
        for key in ("球速", "コントロール", "スタミナ"):
            assert a["abilities"][key] == b["abilities"][key]
        groups = set(a["abilities"]["ranked_specials"]) - {"ノビ", "回復"}
        assert {g: a["abilities"]["ranked_specials"][g] for g in groups} == {g: b["abilities"]["ranked_specials"][g] for g in groups}


@pytest.mark.parametrize(("speed", "count_after"), [(145, 3), (156, 1)])
def test_reliever_pitch_count_draws_twice_and_follows_the_band(speed, count_after):
    balls = [
        app.make_breaking_ball("スライダー", 5, False, 1), app.make_breaking_ball("フォーク", 2, False, 1),
        app.make_breaking_ball("カーブ", 3, False, 1), app.make_breaking_ball("Hスライダー", 1, True, 2),
    ]
    rng = CountingRandom(0.0)
    result = app.fictional_reliever_pitch_count(rng, balls, speed)
    assert rng.calls == 2
    assert len(app.primary_breaking_balls(result)) == count_after
    assert [ball["name"] for ball in balls] == ["スライダー", "フォーク", "カーブ", "Hスライダー"]  # 渡した球は書き換えない
    if count_after == 1:
        assert [ball["name"] for ball in result] == ["スライダー", "Hスライダー"]  # 決め球と、同じ方向の第二球種は残る
    rng = CountingRandom(0.99)
    assert app.fictional_reliever_pitch_count(rng, balls, 160) == balls and rng.calls == 2


def test_only_relievers_lose_pitches_and_keep_the_finisher(monkeypatch):
    monkeypatch.setattr(app, "FICTIONAL_MOVEMENT_QUALITY", NEUTRAL_MOVEMENT)
    monkeypatch.setattr(app, "FICTIONAL_RELIEVER_DROP_THIRD", NEVER)
    monkeypatch.setattr(app, "FICTIONAL_RELIEVER_DROP_SECOND", NEVER)
    kept = domestic_pitchers()
    monkeypatch.setattr(app, "FICTIONAL_RELIEVER_DROP_THIRD", ALWAYS)
    monkeypatch.setattr(app, "FICTIONAL_RELIEVER_DROP_SECOND", ALWAYS)
    dropped = domestic_pitchers()
    reduced = 0
    for a, b in zip(kept, dropped):
        for key in ("name", "age", "position", "batting_throwing"):
            assert a[key] == b[key]
        for key in ("球速", "コントロール", "スタミナ", "ranked_specials"):
            assert a["abilities"][key] == b["abilities"][key]
        if a["position"] == "先発":
            assert a == b
            continue
        before, after = primaries(a), primaries(b)
        if len(before) <= 1:
            assert a["breaking_balls"] == b["breaking_balls"]
            continue
        reduced += 1
        assert len(after) == 1
        if a["age"] > app.FICTIONAL_YOUNG_BREAKING_MAX_AGE:
            assert app.pitch_movement(after[0]) == max(app.pitch_movement(ball) for ball in before)
            assert after[0]["name"] in {ball["name"] for ball in before}
        directions = {ball.get("direction_code") for ball in after}
        for ball in b["breaking_balls"]:
            if ball.get("is_second_pitch"):
                assert ball.get("direction_code") in directions
    assert reduced > 0


@pytest.mark.parametrize(("role", "category"), [
    ("投手", "助っ人外国人用"), ("野手", "助っ人外国人用"),
    ("投手", "ドラフト候補用"), ("野手", "ドラフト候補用"),
    ("野手", "架空球団用"),
])
def test_other_categories_ignore_the_new_settings(monkeypatch, role, category):
    seeds = range(1, 101)
    current = [app.generate_player(role, category, MASTER, seed=seed) for seed in seeds]
    monkeypatch.setattr(app, "FICTIONAL_RELIEVER_DROP_THIRD", ALWAYS)
    monkeypatch.setattr(app, "FICTIONAL_RELIEVER_DROP_SECOND", ALWAYS)
    monkeypatch.setattr(app, "FICTIONAL_PITCHER_RANKED_WEIGHTS", {key: {"G": 1.0} for key in app.FICTIONAL_PITCHER_RANKED_WEIGHTS})
    assert [app.generate_player(role, category, MASTER, seed=seed) for seed in seeds] == current


def test_foreign_pitchers_in_fictional_category_are_unchanged(monkeypatch):
    seeds = range(1, 301)
    current = [app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in seeds]
    monkeypatch.setattr(app, "FICTIONAL_RELIEVER_DROP_THIRD", ALWAYS)
    monkeypatch.setattr(app, "FICTIONAL_RELIEVER_DROP_SECOND", ALWAYS)
    monkeypatch.setattr(app, "FICTIONAL_PITCHER_RANKED_WEIGHTS", {key: {"G": 1.0} for key in app.FICTIONAL_PITCHER_RANKED_WEIGHTS})
    changed = [app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in seeds]
    foreign = [(a, b) for a, b in zip(current, changed) if a["roster_origin"] != "domestic"]
    assert foreign and all(a == b for a, b in foreign)
