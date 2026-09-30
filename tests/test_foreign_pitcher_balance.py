from __future__ import annotations

import app

MASTER = app.load_master_data()
SEEDS = range(1, 301)
PLAYERS = [app.generate_player("投手", "助っ人外国人用", MASTER, seed=seed) for seed in SEEDS]


def breaking(player: dict) -> list[dict]:
    return [ball for ball in player["breaking_balls"] if ball.get("kind") == "breaking"]


def speed(player: dict) -> int:
    return app.pitcher_speed_value(player["abilities"]) or 0


def test_foreign_pitcher_balance_is_deterministic():
    first = app.generate_player("投手", "助っ人外国人用", MASTER, seed=20260930)
    second = app.generate_player("投手", "助っ人外国人用", MASTER, seed=20260930)
    assert first == second


def test_foreign_pitcher_values_stay_in_real_ranges():
    for player in PLAYERS:
        assert 146 <= speed(player) <= 164
        if speed(player) >= 163:
            assert player["archetype"] == "速球" or player["position"] == "抑え"
        assert 22 <= app.ability_numeric_value(player["abilities"], "コントロール") <= 85
        stamina = app.ability_numeric_value(player["abilities"], "スタミナ")
        if player["position"] == "先発":
            assert stamina <= 80
        else:
            assert stamina >= 38
        assert 178 <= player["height_cm"] <= 210
        assert player["pitching_form_type"] != "アンダースロー"


def test_foreign_pitcher_repertoire_has_two_or_three_pitches_and_a_finisher():
    for player in PLAYERS:
        balls = breaking(player)
        assert 2 <= len(balls) <= 3
        assert max(app.pitch_movement(ball) for ball in balls) >= 3
        primary = {ball["direction_code"]: ball for ball in balls if not ball.get("is_second_pitch")}
        for ball in balls:
            if ball.get("is_second_pitch"):
                assert app.pitch_movement(ball) <= app.pitch_movement(primary[ball["direction_code"]])
            assert app.is_pitch_allowed_for_generation(ball["direction_code"], ball["name"], player["batting_throwing"])


def test_foreign_pitcher_specials_have_no_conflicts_and_valid_labels():
    allowed = app.role_allowed_specials(MASTER, "投手")
    for player in PLAYERS:
        specials = player["special_abilities"]
        assert len(specials) == len(set(specials))
        assert set(specials) <= allowed
        for left, right in app.FOREIGN_PITCHER_SPECIAL_CONFLICTS:
            assert not (left in specials and right in specials)
        assert not app.special_constraint_violations(player)
        if player["position"] == "先発":
            assert player["acquisition_role"] in app.FOREIGN_PITCHER_STARTER_ACQUISITIONS
        if player["acquisition_role"] == "若手育成":
            assert player["age"] <= 27
        if player["acquisition_role"] == "左腕補強":
            assert player["batting_throwing"].startswith("左投")
        if player["growth_type"] == "very_late":
            assert player["age"] <= 26
        assert player["handedness"] == app.handedness_from_batting_throwing(player["batting_throwing"])


def test_foreign_pitcher_distribution_leans_to_real_foreign_pitchers():
    n = len(PLAYERS)
    two_pitch = sum(len(breaking(p)) == 2 for p in PLAYERS) / n
    two_seam = sum(any(b["name"] == "ツーシームファスト" for b in p["breaking_balls"]) for p in PLAYERS) / n
    strikeout = sum("奪三振" in p["special_abilities"] for p in PLAYERS) / n
    quick_bad = sum(p["abilities"]["ranked_specials"].get("クイック", "D")[-1] in "EFG" for p in PLAYERS) / n
    height = sum(p["height_cm"] for p in PLAYERS) / n
    assert 0.40 <= two_pitch <= 0.70
    assert 0.25 <= two_seam <= 0.52
    assert 0.35 <= strikeout <= 0.60
    assert quick_bad >= 0.45
    assert 187 <= height <= 193


def test_foreign_pitcher_balance_does_not_touch_foreign_fielders():
    player = app.generate_player("野手", "助っ人外国人用", MASTER, seed=8080)
    assert player["breaking_balls"] == []
