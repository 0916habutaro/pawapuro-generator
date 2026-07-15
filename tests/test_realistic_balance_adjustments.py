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

    assert values["球速"] <= 149


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


def test_non_fictional_pitch_count_weights_keep_legacy_role_and_archetype_shape():
    starter = {"starter_aptitude": "◎", "reliever_aptitude": "-", "closer_aptitude": "-"}
    reliever = {"starter_aptitude": "-", "reliever_aptitude": "◎", "closer_aptitude": "-"}

    assert dict(app.pitch_count_weights("変化球派", "助っ人外国人用", starter, age=28, archetype="変化球")) == {2: 18, 3: 70, 4: 12}
    assert dict(app.pitch_count_weights("本格派", "ドラフト候補用", reliever, age=25, archetype="総合")) == {2: 46, 3: 52, 4: 2}
