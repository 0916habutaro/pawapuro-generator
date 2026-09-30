from __future__ import annotations

import app

MASTER = app.load_master_data()
SEEDS = range(1, 401)
PITCHERS = [app.generate_player("投手", "ドラフト候補用", MASTER, seed=seed) for seed in SEEDS]
FIELDERS = [app.generate_player("野手", "ドラフト候補用", MASTER, seed=seed) for seed in SEEDS]


def rate(players: list[dict], condition) -> float:
    return sum(1 for player in players if condition(player)) / len(players)


def value(player: dict, key: str) -> int:
    return int(app.ability_numeric_value(player["abilities"], key))


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def test_draft_balance_is_deterministic():
    for role in ("投手", "野手"):
        first = app.generate_player(role, "ドラフト候補用", MASTER, seed=20260930)
        second = app.generate_player(role, "ドラフト候補用", MASTER, seed=20260930)
        assert first == second


def test_draft_batting_throwing_follows_throwing_hand():
    players = PITCHERS + FIELDERS
    assert rate(players, lambda p: p["batting_throwing"] == "左投右打") <= 0.02
    assert rate(players, lambda p: p["batting_throwing"].endswith("両打")) <= 0.04
    assert 0.24 <= rate(PITCHERS, lambda p: p["batting_throwing"].startswith("左投")) <= 0.35
    for player in FIELDERS:
        if player["batting_throwing"].startswith("左投"):
            assert player["batting_throwing"] == "左投左打"
            assert player["position"] in {"一塁手", "外野手"}
            assert all(sub["position"] in {"一塁手", "外野手"} for sub in player["sub_positions"])


def test_draft_pitcher_speed_keeps_class_order():
    by_class: dict[str, list[int]] = {}
    for player in PITCHERS:
        by_class.setdefault(player["player_class"], []).append(value(player, "球速"))
    assert mean(by_class["育成候補"]) < mean(by_class["下位候補"]) < mean(by_class["中位候補"]) < mean(by_class["上位候補"])
    regular = [value(p, "球速") for p in PITCHERS if p["player_class"] != "育成候補"]
    assert 149.5 <= mean(regular) <= 153.0


def test_draft_pitcher_ranges_and_breaking_balls():
    for player in PITCHERS:
        route = app.draft_route_group(player["entry_route"])
        breaking = [ball for ball in player["breaking_balls"] if ball.get("kind") == "breaking"]
        assert 1 <= len(breaking) <= 3
        assert value(player, "コントロール") >= 15
        assert value(player, "スタミナ") <= app.DRAFT_PITCHER_STAMINA_MAPS[route][3]
        if route == "高卒":
            assert max(ball["movement"] for ball in breaking) <= app.DRAFT_HIGH_SCHOOL_MAX_MOVEMENT


def test_draft_fielder_caps_trajectory_and_sub_positions():
    for player in FIELDERS:
        route = app.draft_route_group(player["entry_route"])
        if player["player_class"] != "超上位候補":
            for key, cap in app.DRAFT_FIELDER_CAPS[route].items():
                assert value(player, key) <= cap
        if player["abilities"]["弾道"] == 1:
            assert value(player, "パワー") <= app.DRAFT_TRAJECTORY_ONE_MAX_POWER
        subs = [sub["position"] for sub in player["sub_positions"]]
        assert len(subs) <= 2 and len(subs) == len(set(subs))
        assert player["position"] not in subs
        has_catcher = app.has_position_aptitude(player["position"], player["sub_positions"], {"捕手"})
        assert ("キャッチャー" in player["abilities"]["ranked_specials"]) == has_catcher
    assert rate(FIELDERS, lambda p: p["abilities"]["弾道"] == 1) <= 0.04
    assert 0.18 <= rate(FIELDERS, lambda p: p["position"] == "遊撃手") <= 0.34


def test_draft_specials_respect_groups_positions_and_class_bounds():
    groups = {str(row["name"]): str(row.get("group", "")) for row in MASTER.abilities}
    for role, players in (("投手", PITCHERS), ("野手", FIELDERS)):
        for player in players:
            names = player["special_abilities"]
            assert len(names) == len(set(names))
            exclusive = [groups[name] for name in names if groups.get(name, "").startswith("g")]
            assert len(exclusive) == len(set(exclusive))
            aptitudes = {key: player.get(key, "") for key in app.PITCHER_APTITUDE_KEYS}
            assert all(app.is_special_allowed_for_player(name, role, player["position"], player["sub_positions"], aptitudes) for name in names)
            low, high = app.special_count_bounds("ドラフト候補用", player["player_class"])
            assert low <= sum(app.is_countable_special(name) for name in names) <= high
    assert rate(FIELDERS, lambda p: "エラー" in p["special_abilities"]) <= 0.08
    assert rate(FIELDERS, lambda p: "併殺" in p["special_abilities"]) <= 0.08


def test_draft_abilities_keep_realistic_spread():
    def sd(values: list[float]) -> float:
        center = mean(values)
        return (sum((item - center) ** 2 for item in values) / (len(values) - 1)) ** 0.5

    regular_pitchers = [p for p in PITCHERS if p["player_class"] != "育成候補"]
    regular_fielders = [p for p in FIELDERS if p["player_class"] != "育成候補"]
    assert sd([value(p, "球速") for p in regular_pitchers]) >= 2.5
    assert sd([value(p, "コントロール") for p in regular_pitchers]) >= 8.0
    for key in ("ミート", "パワー", "走力", "肩力", "守備力"):
        assert sd([value(p, key) for p in regular_fielders]) >= 7.0
    assert 0.02 <= rate(regular_fielders, lambda p: value(p, "走力") < 45) <= 0.12
    assert 0.02 <= rate(regular_fielders, lambda p: value(p, "肩力") < 50) <= 0.12
