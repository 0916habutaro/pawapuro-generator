from __future__ import annotations

import app

MASTER = app.load_master_data()
SEEDS = range(1, 401)
PLAYERS = [app.generate_player("野手", "助っ人外国人用", MASTER, seed=seed) for seed in SEEDS]


def value(player: dict, key: str) -> int:
    return app.ability_numeric_value(player["abilities"], key) or 0


def test_foreign_fielder_balance_is_deterministic():
    first = app.generate_player("野手", "助っ人外国人用", MASTER, seed=20260930)
    second = app.generate_player("野手", "助っ人外国人用", MASTER, seed=20260930)
    assert first == second


def test_foreign_fielder_values_stay_in_real_ranges():
    for player in PLAYERS:
        for key in ("ミート", "パワー", "守備力", "捕球"):
            assert value(player, key) <= 88
        assert value(player, "パワー") < 90
        assert value(player, "ミート") <= 70
        assert value(player, "守備力") <= 65
        assert value(player, "走力") <= 95 and value(player, "肩力") <= 95
        assert player["abilities"]["弾道"] in {2, 3, 4}
        assert 172 <= player["height_cm"] <= 205


def test_foreign_fielder_positions_handedness_and_sub_positions_are_consistent():
    for player in PLAYERS:
        position = player["position"]
        assert position in app.POSITIONS["野手"]
        assert player["handedness"] == app.handedness_from_batting_throwing(player["batting_throwing"])
        if player["batting_throwing"].startswith("左投"):
            assert position in {"一塁手", "外野手"}
            assert player["batting_throwing"] != "左投両打"
        subs = player["sub_positions"]
        assert len(subs) <= 2
        assert all(sub["position"] != position for sub in subs)
        assert len({sub["position"] for sub in subs}) == len(subs)
        assert player["acquisition_role"] in app.FIELDER_ACQUISITION_ROLES_BY_POSITION[position] + ["若手育成"]
        assert player["position_style"] in {style for style, _ in sum(app.FIELDER_POSITION_STYLE_WEIGHTS[position].values(), [])} | {app.FIELDER_STYLE_DEFAULTS[position]}


def test_foreign_fielder_specials_have_no_conflicts_and_valid_labels():
    allowed = app.role_allowed_specials(MASTER, "野手")
    group_of = {str(row["name"]): str(row.get("group", "")) for row in MASTER.abilities}
    for player in PLAYERS:
        specials = player["special_abilities"]
        assert len(specials) == len(set(specials))
        assert set(specials) <= allowed
        groups = [group_of[name] for name in specials if group_of[name].startswith("g")]
        assert len(groups) == len(set(groups))
        for left, right in app.FOREIGN_FIELDER_SPECIAL_CONFLICTS:
            assert not (left in specials and right in specials)
        assert not app.special_constraint_violations(player)
        ranked = player["abilities"]["ranked_specials"]
        assert ("キャッチャー" in ranked) == app.has_position_aptitude(player["position"], player["sub_positions"], {"捕手"})
        if player["acquisition_role"] == "若手育成":
            assert player["age"] <= app.FOREIGN_YOUNG_DEVELOPMENT_MAX_AGE
        if player["growth_type"] == "very_late":
            assert player["age"] <= 26


def test_foreign_fielder_distribution_leans_to_real_foreign_fielders():
    n = len(PLAYERS)
    power = [value(p, "パワー") for p in PLAYERS]
    mean = sum(power) / n
    sd = (sum((x - mean) ** 2 for x in power) / n) ** 0.5
    trajectory_four = sum(p["abilities"]["弾道"] == 4 for p in PLAYERS) / n
    strikeout = sum("三振" in p["special_abilities"] for p in PLAYERS) / n
    aggressive = sum("積極打法" in p["special_abilities"] for p in PLAYERS) / n
    right_right = sum(p["batting_throwing"] == "右投右打" for p in PLAYERS) / n
    throw_good = sum(p["abilities"]["ranked_specials"]["送球"][-1] in "ABC" for p in PLAYERS) / n
    height = sum(p["height_cm"] for p in PLAYERS) / n
    assert 7 <= sd <= 11
    assert 0.15 <= trajectory_four <= 0.30
    assert strikeout >= 0.58
    assert aggressive >= 0.33
    assert 0.60 <= right_right <= 0.80
    assert throw_good <= 0.15
    assert 185 <= height <= 190


def test_foreign_fielder_class_order_is_kept():
    totals: dict[str, list[int]] = {}
    for seed in range(1, 1201):
        player = app.generate_player("野手", "助っ人外国人用", MASTER, seed=seed)
        totals.setdefault(player["player_class"], []).append(sum(value(player, key) for key in app.FIELDER_ABILITY_KEYS))
    average = {key: sum(values) / len(values) for key, values in totals.items()}
    assert average["大物実績者"] > average["主力期待級"] > average["レギュラー競争級"] > average["保険・バックアップ級"]
