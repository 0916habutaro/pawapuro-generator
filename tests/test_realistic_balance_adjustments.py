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
