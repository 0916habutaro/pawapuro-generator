import random
import sqlite3

import pandas as pd

import app


def test_physique_same_seed_is_deterministic():
    for role, position in [("投手", "先発"), ("野手", "捕手"), ("野手", "外野手")]:
        assert app.generate_physique(202609280001, role, position) == app.generate_physique(202609280001, role, position)


def test_physique_does_not_consume_main_rng():
    master = app.load_master_data()
    protected = ["name", "age", "position", "archetype", "position_style", "batting_throwing", "breaking_balls"]
    for role, seed in [("投手", 202609280101), ("野手", 202709280101)]:
        with_physique = app.generate_player(role, "架空球団用", master, seed)
        without_effect = app.generate_player(role, "架空球団用", master, seed, apply_physique=False)
        assert {key: with_physique[key] for key in protected} == {key: without_effect[key] for key in protected}


def test_all_positions_generate_height_in_valid_range():
    for position, params in app.POSITION_PHYSIQUE.items():
        for seed in range(200):
            value = app.generate_height(position, app.make_sub_rng(seed, f"height:{position}"))
            assert params["height_min"] <= value <= params["height_max"]


def test_all_positions_generate_weight_in_valid_range():
    for position, params in app.POSITION_PHYSIQUE.items():
        for seed in range(200):
            rng = app.make_sub_rng(seed, f"weight:{position}")
            height = app.generate_height(position, rng)
            value = app.generate_weight(position, height, rng)
            assert params["weight_min"] <= value <= params["weight_max"]


def test_weight_is_correlated_with_height():
    for position in app.POSITION_PHYSIQUE:
        samples = [app.generate_physique(seed, "投手" if position == "投手" else "野手", position) for seed in range(1000)]
        heights, weights = zip(*samples)
        assert pd.Series(heights).corr(pd.Series(weights)) > 0.20


def test_large_fielder_gets_positive_power_adjustment():
    values = {key: 50 for key in app.FIELDER_ABILITY_KEYS}
    app.apply_fielder_physique_effects(values, 2.0, 2.0)
    assert values["パワー"] > 50


def test_large_fielder_gets_negative_speed_adjustment():
    values = {key: 50 for key in app.FIELDER_ABILITY_KEYS}
    app.apply_fielder_physique_effects(values, 2.0, 2.0)
    assert values["走力"] < 50


def test_physique_does_not_modify_contact():
    values = {key: 50 for key in app.FIELDER_ABILITY_KEYS}
    app.apply_fielder_physique_effects(values, 2.5, 2.5)
    assert values["ミート"] == 50


def test_tall_pitcher_gets_velocity_bonus():
    values = {"球速": 145, "コントロール": 50, "スタミナ": 50}
    app.apply_pitcher_physique_effects(values, 2.0, 0.0)
    assert values["球速"] > 145


def test_physique_does_not_modify_pitcher_stamina():
    values = {"球速": 145, "コントロール": 50, "スタミナ": 50}
    app.apply_pitcher_physique_effects(values, 2.5, 2.5)
    assert values["スタミナ"] == 50


def test_physique_adjustment_is_capped():
    fielder = app.physique_effect_deltas(app.FIELDER_PHYSIQUE_EFFECTS, 100.0, 100.0)
    pitcher = app.physique_effect_deltas(app.PITCHER_PHYSIQUE_EFFECTS, 100.0, 100.0)
    assert all(abs(fielder[key]) <= effect["cap"] for key, effect in app.FIELDER_PHYSIQUE_EFFECTS.items())
    assert all(abs(pitcher[key]) <= effect["cap"] for key, effect in app.PITCHER_PHYSIQUE_EFFECTS.items())


def test_height_weight_sqlite_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "players.sqlite3")
    player = app.generate_player("野手", "架空球団用", app.load_master_data(), seed=987654)
    app.save_players([player])
    loaded = app.player_from_history_row(app.load_history().iloc[0])
    assert loaded["height_cm"] == player["height_cm"]
    assert loaded["weight_kg"] == player["weight_kg"]


def test_legacy_sqlite_rows_can_have_null_physique(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE players (id INTEGER PRIMARY KEY, name TEXT, height INTEGER, weight INTEGER)")
        conn.execute("INSERT INTO players (name, height, weight) VALUES ('旧選手', 180, 80)")
    monkeypatch.setattr(app, "DB_PATH", db_path)
    app.init_db()
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT height_cm, weight_kg FROM players WHERE name = '旧選手'").fetchone()
    assert row == (None, None)


def test_generation_info_uses_new_physique_and_handles_legacy_nulls():
    # 身長・体重はプロフィールから生成情報へ移した（C-2）
    html = app.render_generation_info_html({"name": "選手", "height_cm": 184, "weight_kg": 91})
    assert "184cm" in html and "91kg" in html
    legacy_html = app.render_generation_info_html({"name": "旧選手", "height_cm": None, "weight_kg": None, "height": 180, "weight": 80})
    assert legacy_html.count('<span class="pp-generation-value">-</span>') == 2
