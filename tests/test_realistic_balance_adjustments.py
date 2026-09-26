import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app
from scripts import validate_ability_balance as balance


def test_fictional_fielder_audit_suppresses_extreme_allrounder():
    values = {"ミート": 82, "パワー": 95, "走力": 88, "肩力": 86, "守備力": 84, "捕球": 82}

    app.apply_fictional_fielder_realism_audit(
        random.Random(7),
        values,
        "架空球団用",
        27,
        "三塁手",
        "一軍主力級",
        "長打",
        "強打三塁手",
    )

    assert sum(values[key] for key in app.FIELDER_ABILITY_KEYS) <= 430
    assert values["パワー"] < 90
    assert min(values[key] for key in app.FIELDER_ABILITY_KEYS) < 70


def test_young_fictional_pitcher_speed_shape_keeps_non_fastball_types_under_control():
    values = {"球速": 152, "コントロール": 48, "スタミナ": 50}

    app.apply_fictional_pitcher_age_speed_shape(
        random.Random(3),
        values,
        "架空球団用",
        19,
        "若手素材型",
        "制球",
        "制球型先発",
        "低制球",
    )

    assert 149 <= values["球速"] <= 151


def test_relief_display_pitch_count_four_plus_is_limited():
    aptitudes = {"starter_aptitude": "-", "reliever_aptitude": "◎", "closer_aptitude": "-"}
    samples = [
        app.generate_breaking_balls(
            random.Random(seed),
            "変化球派",
            "架空球団用",
            aptitudes,
            "右投右打",
            age=28,
            player_class="一軍主力級",
            archetype="変化球",
            position_style="変化球型中継ぎ",
        )
        for seed in range(400)
    ]
    display_four_plus = sum(
        1
        for balls in samples
        if sum(1 for ball in balls if ball.get("kind") in {"breaking", "second_fastball"}) >= 4
    )

    assert display_four_plus / len(samples) <= 0.05


def test_usage_specials_are_excluded_from_validation_special_count():
    player = {
        "seed": 1,
        "role": "投手",
        "category": "架空球団用",
        "name": "山田 太郎",
        "age": 28,
        "nationality": "日本",
        "birthplace": "東京",
        "position": "先発",
        "player_type": "本格派",
        "player_class": "一軍主力級",
        "archetype": "総合",
        "position_style": "総合型先発",
        "development_stage": "完成型",
        "acquisition_role": "先発候補",
        "weakness_profile": "明確な弱点なし",
        "handedness": "右投",
        "batting_throwing": "右投右打",
        "height": 180,
        "weight": 82,
        "abilities": {
            "球速": "149 km/h",
            "コントロール": app.ability(60),
            "スタミナ": app.ability(65),
            "ranked_specials": {"ノビ": "ノビD", "対ピンチ": "対ピンチC"},
        },
        "breaking_balls": [{"kind": "breaking", "direction": "フォーク方向", "direction_code": "3", "name": "フォーク", "movement": 3}],
        "special_abilities": ["速球中心", "テンポ○", "奪三振", "四球"],
        "sub_positions": [],
    }

    df = balance.flatten_players([player])

    assert int(df.loc[0, "特殊能力数"]) == 2
    assert int(df.loc[0, "起用法数"]) == 2


def test_special_count_bounds_raise_only_top_fictional_classes():
    assert app.special_count_bounds("架空球団用", "スター級") == (4, 12)
    assert app.special_count_bounds("架空球団用", "一軍主力級")[0] == 2
    assert app.special_count_bounds("架空球団用", "ベテラン型")[0] == 2
    assert app.special_count_bounds("架空球団用", "二軍級")[0] == 0


def test_weighted_special_cap_never_exceeds_twelve():
    rng = random.Random(11)
    caps = [app.weighted_special_cap(rng, "架空球団用", "スター級", 80) for _ in range(200)]

    assert max(caps) <= 12
    assert min(caps) >= 4


def test_audit_removes_high_control_walk_and_wildness_specials():
    audited = app.audit_special_selection(
        random.Random(1),
        ["四球", "抜け球", "荒れ球"],
        "投手",
        "先発",
        {"コントロール": app.ability(65)},
    )

    assert "四球" not in audited
    assert "抜け球" not in audited


def test_audit_allows_low_control_unfinished_pitcher_specials():
    audited = app.audit_special_selection(
        random.Random(1),
        ["四球", "抜け球"],
        "投手",
        "先発",
        {"コントロール": app.ability(38)},
    )

    assert {"四球", "抜け球"}.issubset(set(audited))


def test_audit_suppresses_double_play_for_high_speed_fielders():
    audited = app.audit_special_selection(
        random.Random(1),
        ["併殺"],
        "野手",
        "二塁手",
        {"走力": app.ability(82), "パワー": app.ability(60), "ミート": app.ability(55)},
    )

    assert "併殺" not in audited


def test_position_restricted_specials_require_main_position_for_charge_and_laser():
    assert app.is_special_position_allowed("高速チャージ", "一塁手", [])
    assert not app.is_special_position_allowed("高速チャージ", "二塁手", [{"position": "一塁手", "aptitude": "○"}])
    assert app.is_special_position_allowed("レーザービーム", "外野手", [])
    assert not app.is_special_position_allowed("レーザービーム", "三塁手", [{"position": "外野手", "aptitude": "○"}])


def test_same_system_special_conflicts_are_removed():
    audited = app.audit_special_selection(
        random.Random(1),
        ["四球", "ストライク先行", "抜け球", "リリース○", "三振", "粘り打ち"],
        "投手",
        "先発",
        {"コントロール": app.ability(45)},
    )

    assert not {"四球", "ストライク先行"}.issubset(set(audited))
    assert not {"抜け球", "リリース○"}.issubset(set(audited))


def test_generate_specials_keeps_max_twelve_and_star_minimum():
    abilities = [
        {"name": f"通常特能{i}", "kind": "blue", "group": f"g{i}", "power": "normal", "weight": "100", "target_role": "野手"}
        for i in range(30)
    ]
    master = app.MasterData(names={}, places={}, abilities=abilities)

    selected = app.generate_specials(
        random.Random(2),
        master,
        "野手",
        "巧打型",
        "外野手",
        28,
        {"ミート": app.ability(75), "パワー": app.ability(65), "走力": app.ability(70), "肩力": app.ability(65), "守備力": app.ability(65), "捕球": app.ability(65)},
        category="架空球団用",
        player_class="スター級",
    )

    assert 4 <= len([name for name in selected if app.is_countable_special(name)]) <= 12


def test_generate_specials_allows_farm_player_zero_specials():
    abilities = [{"name": "通常特能", "kind": "blue", "group": "g1", "power": "normal", "weight": "0", "target_role": "野手"}]
    master = app.MasterData(names={}, places={}, abilities=abilities)

    selected = app.generate_specials(
        random.Random(3),
        master,
        "野手",
        "バランス型",
        "二塁手",
        24,
        {"ミート": app.ability(45), "パワー": app.ability(45), "走力": app.ability(45), "肩力": app.ability(45), "守備力": app.ability(45), "捕球": app.ability(45)},
        category="架空球団用",
        player_class="二軍級",
    )

    assert selected == []


def test_non_fictional_categories_keep_legacy_special_caps():
    abilities = [
        {"name": f"通常特能{i}", "kind": "blue", "group": f"g{i}", "power": "normal", "weight": "100", "target_role": "野手"}
        for i in range(30)
    ]
    master = app.MasterData(names={}, places={}, abilities=abilities)
    high_values = {"ミート": app.ability(80), "パワー": app.ability(80), "走力": app.ability(80), "肩力": app.ability(80), "守備力": app.ability(80), "捕球": app.ability(80)}

    foreign = app.generate_specials(
        random.Random(4),
        master,
        "野手",
        "長距離砲",
        "一塁手",
        28,
        high_values,
        category="助っ人外国人用",
        player_class="大物実績者",
    )
    draft = app.generate_specials(
        random.Random(5),
        master,
        "野手",
        "巧打型",
        "二塁手",
        22,
        high_values,
        category="ドラフト候補用",
        player_class="上位候補",
    )

    assert len([name for name in foreign if app.is_countable_special(name)]) <= 7
    assert len([name for name in draft if app.is_countable_special(name)]) <= 5


def test_realistic_special_rate_multipliers_are_fictional_only(monkeypatch):
    row = {"name": "カテゴリ限定テスト", "kind": "blue", "group": "g", "power": "normal", "weight": "5", "target_role": "野手"}
    abilities = {"ミート": app.ability(55), "パワー": app.ability(55), "走力": app.ability(55), "肩力": app.ability(55), "守備力": app.ability(55), "捕球": app.ability(55)}
    kwargs = {
        "role": "野手",
        "player_type": "バランス型",
        "position": "二塁手",
        "age": 27,
        "abilities": abilities,
        "player_class": "一軍主力級",
    }
    monkeypatch.setitem(app.FIELDER_REALISTIC_SPECIAL_BOOSTS, "カテゴリ限定テスト", 3.0)

    fictional = app.adjust_special_chance(row, 5, category="架空球団用", **kwargs)
    draft = app.adjust_special_chance(row, 5, category="ドラフト候補用", **kwargs)
    foreign = app.adjust_special_chance(row, 5, category="助っ人外国人用", **kwargs)

    assert fictional > draft * 2
    assert fictional > foreign * 2
    assert draft < fictional
    assert foreign < fictional


def test_pitcher_realistic_special_rate_multipliers_are_fictional_only(monkeypatch):
    row = {"name": "カテゴリ限定投手テスト", "kind": "blue", "group": "g", "power": "normal", "weight": "5", "target_role": "投手"}
    abilities = {"球速": "145 km/h", "コントロール": app.ability(55), "スタミナ": app.ability(55)}
    aptitudes = {"starter_aptitude": "◎", "reliever_aptitude": "-", "closer_aptitude": "-"}
    kwargs = {
        "role": "投手",
        "player_type": "本格派",
        "position": "先発",
        "age": 27,
        "abilities": abilities,
        "breaking_balls": [{"kind": "breaking", "movement": 3}],
        "player_class": "一軍主力級",
        "pitcher_aptitudes": aptitudes,
    }
    monkeypatch.setitem(app.PITCHER_REALISTIC_SPECIAL_BOOSTS, "カテゴリ限定投手テスト", 3.0)

    fictional = app.adjust_special_chance(row, 5, category="架空球団用", **kwargs)
    draft = app.adjust_special_chance(row, 5, category="ドラフト候補用", **kwargs)
    foreign = app.adjust_special_chance(row, 5, category="助っ人外国人用", **kwargs)

    assert fictional > draft * 2
    assert fictional > foreign * 2
    assert draft < fictional
    assert foreign < fictional


def test_non_fictional_pitch_count_weights_keep_legacy_role_and_archetype_shape():
    starter = {"starter_aptitude": "◎", "reliever_aptitude": "-", "closer_aptitude": "-"}
    reliever = {"starter_aptitude": "-", "reliever_aptitude": "◎", "closer_aptitude": "-"}

    assert dict(app.pitch_count_weights("変化球派", "架空球団用", starter, age=28, player_class="スター級", archetype="変化球")) == {2: 28, 3: 66, 4: 7}
    assert dict(app.pitch_count_weights("本格派", "架空球団用", reliever, age=25, archetype="総合")) == {2: 51, 3: 49}
    assert dict(app.pitch_count_weights("変化球派", "助っ人外国人用", starter, age=28, archetype="変化球")) == {2: 18, 3: 70, 4: 12}
    assert dict(app.pitch_count_weights("本格派", "ドラフト候補用", reliever, age=25, archetype="総合")) == {2: 46, 3: 52, 4: 2}


def _legacy_fielder_archetype_values(seed, archetype):
    rng = random.Random(seed)
    values = {key: 48 for key in app.FIELDER_ABILITY_KEYS}
    if archetype == "巧打":
        app.add_mod(values, {"ミート": rng.randint(10, 14), "パワー": -rng.randint(2, 5), "走力": rng.randint(0, 3), "守備力": rng.randint(0, 2)})
    elif archetype == "長打":
        app.add_mod(values, {"パワー": rng.randint(13, 18), "ミート": -rng.randint(2, 5), "走力": -rng.randint(3, 7), "守備力": -rng.randint(1, 4)})
    elif archetype == "俊足":
        app.add_mod(values, {"走力": rng.randint(12, 17), "守備力": rng.randint(2, 5), "パワー": -rng.randint(4, 7)})
    elif archetype == "守備":
        app.add_mod(values, {"守備力": rng.randint(10, 15), "捕球": rng.randint(8, 12), rng.choice(["ミート", "パワー"]): -rng.randint(1, 4)})
    elif archetype == "強肩":
        app.add_mod(values, {"肩力": rng.randint(12, 17), "守備力": rng.randint(1, 4)})
    elif archetype == "バランス":
        avg = sum(values.values()) / len(values)
        for key in values:
            values[key] += rng.randint(0, 2)
            values[key] = round(values[key] + (avg - values[key]) * rng.uniform(0.15, 0.25))
            if values[key] < 30:
                values[key] += rng.randint(2, 5)
    return values


def test_non_fictional_fielder_archetype_mods_use_legacy_balance():
    for category in ["ドラフト候補用", "助っ人外国人用"]:
        for archetype in ["巧打", "長打", "俊足", "守備", "強肩", "バランス"]:
            values = {key: 48 for key in app.FIELDER_ABILITY_KEYS}
            app.apply_fielder_archetype_mods(random.Random(42), values, archetype, category)
            assert values == _legacy_fielder_archetype_values(42, archetype)


def test_fictional_cleanup_does_not_replace_legacy_archetype_tradeoffs():
    legacy = _legacy_fielder_archetype_values(7, "長打")
    fictional = {key: 48 for key in app.FIELDER_ABILITY_KEYS}
    app.apply_fielder_archetype_mods(random.Random(7), fictional, "長打", "架空球団用")
    assert fictional != legacy
    assert fictional["ミート"] < legacy["ミート"]


def test_fictional_cleanup_suppresses_main_class_strikeout_for_adequate_contact():
    row = {"name": "三振", "kind": "red", "power": "normal", "weight": 12, "target_role": "野手"}
    abilities = {"ミート": {"value": 55}, "パワー": {"value": 72}, "走力": {"value": 60}, "肩力": {"value": 62}, "守備力": {"value": 55}, "捕球": {"value": 50}}
    main = app.adjust_special_chance(row, 12, "野手", "長距離砲", "外野手", 28, abilities, category="架空球団用", player_class="一軍主力級", archetype="長打", position_style="強打外野手")
    bench = app.adjust_special_chance(row, 12, "野手", "長距離砲", "外野手", 28, abilities, category="架空球団用", player_class="一軍控え級", archetype="長打", position_style="強打外野手")
    assert main < bench


def test_fictional_cleanup_keeps_low_contact_slugger_strikeout_possible():
    row = {"name": "三振", "kind": "red", "power": "normal", "weight": 12, "target_role": "野手"}
    low = {"ミート": {"value": 32}, "パワー": {"value": 82}, "走力": {"value": 50}, "肩力": {"value": 62}, "守備力": {"value": 45}, "捕球": {"value": 42}}
    high = {"ミート": {"value": 75}, "パワー": {"value": 82}, "走力": {"value": 50}, "肩力": {"value": 62}, "守備力": {"value": 45}, "捕球": {"value": 42}}
    low_chance = app.adjust_special_chance(row, 12, "野手", "長距離砲", "一塁手", 26, low, category="架空球団用", player_class="一軍主力級", archetype="長打", position_style="強打一塁手")
    high_chance = app.adjust_special_chance(row, 12, "野手", "長距離砲", "一塁手", 26, high, category="架空球団用", player_class="一軍主力級", archetype="長打", position_style="強打一塁手")
    assert low_chance > high_chance
    assert low_chance > 0
    assert high_chance <= 1.5


def test_pitcher_strong_blue_kire_tracks_breaking_quality():
    row = {"name": "キレ○", "kind": "blue", "power": "strong", "weight": 10, "target_role": "投手"}
    abilities = {"球速": "150 km/h", "コントロール": {"value": 58}, "スタミナ": {"value": 62}}
    weak_breaking = [{"kind": "breaking", "movement": 2, "is_second_pitch": False}]
    strong_breaking = [
        {"kind": "breaking", "movement": 4, "is_second_pitch": False},
        {"kind": "breaking", "movement": 3, "is_second_pitch": False},
        {"kind": "breaking", "movement": 3, "is_second_pitch": False},
    ]
    weak = app.adjust_special_chance(row, 6, "投手", "本格派", "先発", 28, abilities, weak_breaking, "架空球団用", "一軍控え級", "総合", "総合型先発")
    strong = app.adjust_special_chance(row, 6, "投手", "本格派", "先発", 28, abilities, strong_breaking, "架空球団用", "一軍控え級", "総合", "総合型先発")
    assert strong > weak


def test_strong_special_definition_matches_csv_power():
    master = app.load_master_data()
    by_name = {row["name"]: row for row in master.abilities}
    for name in ["キレ○", "緩急○", "内角攻め", "クロスファイヤー", "対強打者○", "アベレージヒッター", "パワーヒッター", "守備職人", "レーザービーム"]:
        assert by_name[name]["kind"] == "blue"
        assert by_name[name]["power"] == "strong"


def test_first_adjustment_second_base_guards_are_style_and_class_aware():
    defensive = {key: 35 for key in app.FIELDER_ABILITY_KEYS}
    batting = defensive.copy()

    app.apply_fictional_position_profile_guards(defensive, "二塁手", "一軍主力級", "守備", "守備走塁二塁手")
    app.apply_fictional_position_profile_guards(batting, "二塁手", "二軍級", "長打", "打撃型二塁手")

    assert defensive["走力"] >= 68
    assert defensive["守備力"] >= 58
    assert defensive["捕球"] >= 51
    assert batting["守備力"] < 50
    assert batting["守備力"] < defensive["守備力"]


def test_first_adjustment_outfield_guards_link_speed_and_defense_without_touching_slugger():
    allround = {key: 35 for key in app.FIELDER_ABILITY_KEYS}
    slugger = allround.copy()

    app.apply_fictional_position_profile_guards(allround, "外野手", "一軍主力級", "バランス", "走攻守外野手")
    app.apply_fictional_position_profile_guards(slugger, "外野手", "一軍主力級", "長打", "強打外野手")

    assert allround["走力"] >= 69
    assert allround["肩力"] >= 65
    assert allround["守備力"] >= 54
    assert allround["捕球"] >= 48
    assert slugger == {key: 35 for key in app.FIELDER_ABILITY_KEYS}


def test_first_adjustment_trajectory_adds_three_without_inflating_four():
    assert app.determine_trajectory(54, "巧打", "二塁手", "打撃型二塁手", 52, "一軍主力級") == 3
    assert app.determine_trajectory(55, "バランス", "外野手", "走攻守外野手", 50, "一軍主力級") == 3
    assert app.determine_trajectory(60, "長打", "外野手", "強打外野手", 45, "一軍主力級") == 3
    assert app.determine_trajectory(75, "長打", "外野手", "強打外野手", 45, "一軍主力級") == 4
    assert app.determine_trajectory(75, "長打", "外野手", "強打外野手", 45, "一軍控え級") == 3
    assert app.determine_trajectory(60, "長打", "三塁手", "強打三塁手", 45, "一軍控え級") == 4


def test_first_adjustment_closer_stamina_change_is_role_local():
    starter = {"球速": 145, "コントロール": 48, "スタミナ": 48}
    reliever = starter.copy()
    closer = starter.copy()

    app.apply_pitcher_role_mods(starter, "先発", "総合型先発")
    app.apply_pitcher_role_mods(reliever, "中継ぎ", "総合型中継ぎ")
    app.apply_pitcher_role_mods(closer, "抑え", "総合型クローザー")

    assert starter["スタミナ"] == 59
    assert reliever["スタミナ"] == 40
    assert closer["スタミナ"] == 45


def test_first_adjustment_closer_direction_two_weight_is_local():
    closer_rng = random.Random(8128)
    starter_rng = random.Random(8128)
    closer = [app.weighted_direction_sample(closer_rng, list(app.DIRECTION_NAMES), 2, "抑え") for _ in range(5000)]
    starter = [app.weighted_direction_sample(starter_rng, list(app.DIRECTION_NAMES), 2, "先発") for _ in range(5000)]

    closer_rate = sum("2" in values for values in closer) / len(closer)
    starter_rate = sum("2" in values for values in starter) / len(starter)
    assert closer_rate < starter_rate - 0.08


def test_first_adjustment_special_draws_favor_established_classes():
    rng = random.Random(19)
    controls = [app.extra_special_draws(rng, "架空球団用", "一軍控え級", 56) for _ in range(500)]
    farm = [app.extra_special_draws(rng, "架空球団用", "二軍級", 56) for _ in range(500)]
    main = [app.extra_special_draws(rng, "架空球団用", "一軍主力級", 62) for _ in range(500)]

    assert min(controls) >= 1
    assert sum(controls) > sum(farm) * 3
    assert sum(main) > sum(controls)


def test_first_adjustment_bonus_exclusion_does_not_change_strikeout_weights():
    assert "流し打ち" in app.SPECIAL_COUNT_BONUS_EXCLUSIONS
    assert "三振" not in app.SPECIAL_COUNT_BONUS_EXCLUSIONS
    assert "奪三振" not in app.SPECIAL_COUNT_BONUS_EXCLUSIONS


def test_second_adjustment_fielder_distribution_guards_are_local():
    second = {key: 35 for key in app.FIELDER_ABILITY_KEYS}
    third = {key: 68 for key in app.FIELDER_ABILITY_KEYS}
    catcher = {key: 48 for key in app.FIELDER_ABILITY_KEYS}

    app.apply_second_adjustment_fielder_distribution_guards(
        random.Random(1), second, "二塁手", "二軍級", "守備走塁二塁手", "低走力"
    )
    app.apply_second_adjustment_fielder_distribution_guards(
        random.Random(1), third, "三塁手", "一軍主力級", "平均型三塁手", ""
    )
    app.apply_second_adjustment_fielder_distribution_guards(
        random.Random(1), catcher, "捕手", "二軍級", "打撃型捕手", "低捕球"
    )

    assert second["守備力"] >= 60
    assert second["走力"] >= 70
    assert third["肩力"] < 68
    assert 30 <= catcher["捕球"] <= 39


def test_second_adjustment_catcher_tail_does_not_touch_defensive_catcher():
    values = {key: 48 for key in app.FIELDER_ABILITY_KEYS}
    app.apply_second_adjustment_fielder_distribution_guards(
        random.Random(1), values, "捕手", "二軍級", "守備型捕手", "低捕球"
    )
    assert values["捕球"] == 48


def test_second_adjustment_trajectory_moves_only_target_profiles_to_three():
    assert app.determine_trajectory(63, "長打", "捕手", "打撃型捕手", 45, "一軍控え級") == 3
    assert app.determine_trajectory(82, "長打", "捕手", "打撃型捕手", 45, "一軍控え級") == 3
    assert app.determine_trajectory(69, "長打", "遊撃手", "強打遊撃手", 42, "一軍控え級") == 3
    assert app.determine_trajectory(52, "バランス", "遊撃手", "守備走塁遊撃手", 48, "一軍主力級") == 2


def test_second_adjustment_trajectory_preserves_first_adjustment_positions():
    assert app.determine_trajectory(54, "巧打", "二塁手", "打撃型二塁手", 52, "一軍主力級") == 3
    assert app.determine_trajectory(75, "長打", "外野手", "強打外野手", 45, "一軍主力級") == 4


def test_second_adjustment_middle_reliever_stamina_is_role_local():
    assert app.shape_second_adjustment_middle_reliever_stamina(30, "架空球団用", "中継ぎ", "総合型中継ぎ") == 37
    assert app.shape_second_adjustment_middle_reliever_stamina(61, "架空球団用", "中継ぎ", "総合型中継ぎ") == 56
    assert app.shape_second_adjustment_middle_reliever_stamina(61, "架空球団用", "中継ぎ", "ロングリリーフ型") == 57
    assert app.shape_second_adjustment_middle_reliever_stamina(35, "架空球団用", "抑え", "総合型クローザー") == 35
    assert app.shape_second_adjustment_middle_reliever_stamina(70, "架空球団用", "先発", "総合型先発") == 70


def test_second_adjustment_rank_changes_are_group_local():
    recovery = dict(app.ranked_weight_items_for_group("回復", "投手", "中継ぎ", "技巧派", {}, category="架空球団用", player_class="一軍主力級"))
    quick = dict(app.ranked_weight_items_for_group("クイック", "投手", "中継ぎ", "技巧派", {}, category="架空球団用", player_class="一軍主力級"))
    assert recovery["E"] > recovery["D"]
    assert quick["D"] > quick["E"]


def test_second_adjustment_pitcher_rank_shift_is_probabilistic():
    rng = random.Random(23)
    shifts = [
        app.ranked_shift_for_group(rng, "対左打者", "投手", "中継ぎ", "技巧派", {}, "制球")
        for _ in range(1_000)
    ]
    assert 150 <= sum(value > 0 for value in shifts) <= 250


def test_second_adjustment_special_boosts_only_named_targets():
    assert app.PITCHER_REALISTIC_SPECIAL_BOOSTS["球持ち○"] == 2.80
    assert app.PITCHER_REALISTIC_SPECIAL_BOOSTS["リリース○"] == 3.25
    assert app.FIELDER_REALISTIC_SPECIAL_BOOSTS["併殺"] == 3.00
    assert app.FIELDER_REALISTIC_SPECIAL_BOOSTS["内野安打○"] == 1.45
    assert app.FIELDER_REALISTIC_SPECIAL_BOOSTS["三振"] == 3.25
