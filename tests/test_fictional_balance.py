from __future__ import annotations

import app

MASTER = app.load_master_data()
SEEDS = range(1, 401)
PITCHERS = [p for p in (app.generate_player("投手", "架空球団用", MASTER, seed=seed) for seed in SEEDS) if p["roster_origin"] == "domestic"]
FIELDERS = [p for p in (app.generate_player("野手", "架空球団用", MASTER, seed=seed) for seed in SEEDS) if p["roster_origin"] == "domestic"]


def rate(players: list[dict], condition) -> float:
    return sum(1 for player in players if condition(player)) / len(players)


def test_fictional_balance_is_deterministic():
    for role in ("投手", "野手"):
        first = app.generate_player(role, "架空球団用", MASTER, seed=20260930)
        second = app.generate_player(role, "架空球団用", MASTER, seed=20260930)
        assert first == second


def test_fictional_batting_throwing_follows_throwing_hand():
    for player in PITCHERS:
        if player["batting_throwing"].startswith("左投"):
            assert player["batting_throwing"] in {"左投左打", "左投右打"}
    assert rate(PITCHERS, lambda p: p["batting_throwing"] == "左投右打") <= 0.03
    for player in FIELDERS:
        if player["batting_throwing"].startswith("左投"):
            assert player["batting_throwing"] == "左投左打"
            assert player["position"] in {"一塁手", "外野手"}
            assert all(sub["position"] in {"一塁手", "外野手"} for sub in player["sub_positions"])


def test_fictional_pitcher_aptitudes_include_starter_reliever_swingmen():
    both = rate(PITCHERS, lambda p: p["starter_aptitude"] == "◎" and p["reliever_aptitude"] == "◎")
    assert 0.18 <= both <= 0.40
    for player in PITCHERS:
        if player["position"] == "抑え":
            assert player["closer_aptitude"] == "◎"


def test_fictional_players_have_no_specials_missing_from_real_japanese_players():
    # 対ランナー×（赤）は、最初の抽選では出さないが、青特の型の補正（実在の投げ手ごとの保有率）で付ける。
    for player in PITCHERS:
        assert not set(player["special_abilities"]) & (app.FICTIONAL_NOT_REAL_SPECIALS["投手"] - {"対ランナー×"})
    for player in FIELDERS:
        assert not set(player["special_abilities"]) & app.FICTIONAL_NOT_REAL_SPECIALS["野手"]


def test_fictional_specials_respect_groups_positions_and_class_bounds():
    groups = {str(row["name"]): str(row.get("group", "")) for row in MASTER.abilities}
    for role, players in (("投手", PITCHERS), ("野手", FIELDERS)):
        for player in players:
            names = player["special_abilities"]
            assert len(names) == len(set(names))
            exclusive = [groups[name] for name in names if groups.get(name, "").startswith("g")]
            assert len(exclusive) == len(set(exclusive))
            aptitudes = {key: player.get(key, "") for key in app.PITCHER_APTITUDE_KEYS}
            assert all(app.is_special_allowed_for_player(name, role, player["position"], player["sub_positions"], aptitudes) for name in names)
            low, high = app.special_count_bounds("架空球団用", player["player_class"])
            assert low <= sum(app.is_countable_special(name) for name in names) <= high


def test_fictional_pitch_hand_rules_are_kept():
    for player in PITCHERS:
        names = {ball["name"] for ball in player["breaking_balls"] if ball.get("kind") == "breaking"}
        if player["batting_throwing"].startswith("左投"):
            assert not names & {"シンカー", "Hシンカー"}
        else:
            assert "スクリュー" not in names
        primaries = {ball["direction_code"]: ball for ball in player["breaking_balls"] if ball.get("kind") == "breaking" and not ball.get("is_second_pitch")}
        for ball in player["breaking_balls"]:
            if ball.get("kind") == "breaking":
                master = app.BREAKING_BY_NAME[ball["name"]]
                assert master["min_movement"] <= ball["movement"] <= master["max_movement"]
                if ball.get("is_second_pitch"):
                    assert ball["movement"] <= primaries[ball["direction_code"]]["movement"]


def test_fictional_fielder_trajectory_and_sub_positions():
    for player in FIELDERS:
        trajectory = player["abilities"]["弾道"]
        assert trajectory in {1, 2, 3, 4}
        if trajectory == 1:
            assert player["abilities"]["パワー"]["value"] <= app.FICTIONAL_TRAJECTORY_ONE_MAX_POWER
        subs = [sub["position"] for sub in player["sub_positions"]]
        assert player["position"] not in subs
        assert len(subs) == len(set(subs))
        assert all(sub["aptitude"] in {"◎", "○", "△"} for sub in player["sub_positions"])
        ranked = player["abilities"]["ranked_specials"]
        assert ("キャッチャー" in ranked) == app.has_position_aptitude(player["position"], player["sub_positions"], {"捕手"})


def test_fictional_young_material_is_young():
    for player in PITCHERS + FIELDERS:
        if player["player_class"] == "若手素材型":
            assert player["age"] <= app.FICTIONAL_YOUNG_MATERIAL_MAX_AGE
            assert player["pro_years"] <= app.FICTIONAL_YOUNG_MATERIAL_MAX_PRO_YEARS


def test_draft_candidates_keep_old_batting_and_position_rules():
    # 架空球団用の調整はドラフト候補には掛けない。
    players = [app.generate_player("野手", "ドラフト候補用", MASTER, seed=seed) for seed in range(1, 201)]
    assert any(p["batting_throwing"].endswith("両打") for p in players)
    assert all(p["position"] in app.POSITIONS["野手"] for p in players)
