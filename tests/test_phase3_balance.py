import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


def make_master():
    abilities = [
        {"name":"フレーミング○","target_role":"野手","group":"catcher_skill","kind":"blue","power":"normal","weight":100},
        {"name":"ささやき破り","target_role":"野手","group":"whisper_break","kind":"blue","power":"normal","weight":100},
        {"name":"レーザービーム","target_role":"野手","group":"laser","kind":"blue","power":"normal","weight":100},
        {"name":"高速チャージ","target_role":"野手","group":"charge","kind":"blue","power":"normal","weight":100},
        {"name":"広角打法","target_role":"野手","group":"slug","kind":"blue","power":"strong","weight":100},
        {"name":"三振","target_role":"野手","group":"strikeout","kind":"red","power":"normal","weight":100},
        {"name":"速球中心","target_role":"投手","group":"pitch_policy","kind":"green","power":"normal","weight":100},
        {"name":"変化球中心","target_role":"投手","group":"pitch_policy","kind":"green","power":"normal","weight":100},
        *[{"name":name,"target_role":"投手","group":name,"kind":"blue","power":"normal","weight":100} for name in app.RELIEF_REQUIRED_SPECIALS],
        *[{"name":f"キャッチャー{r}","target_role":"野手","group":"キャッチャー","kind":"rank","power":"normal","weight":1} for r in app.RANKED_SPECIAL_RANKS],
        *[{"name":f"ノビ{r}","target_role":"投手","group":"ノビ","kind":"rank","power":"normal","weight":1} for r in app.RANKED_SPECIAL_RANKS],
    ]
    app._CURRENT_ABILITIES_FOR_RANK_CHECK = abilities
    return app.MasterData(names={}, places={}, abilities=abilities)


def test_position_constraint_helpers():
    assert app.is_special_allowed_for_player("レーザービーム", "野手", "外野手")
    assert app.is_special_allowed_for_player("レーザービーム", "野手", "遊撃手", [{"position":"外野手","aptitude":"△"}])
    assert not app.is_special_allowed_for_player("レーザービーム", "野手", "遊撃手")
    assert app.is_special_allowed_for_player("高速チャージ", "野手", "一塁手")
    assert app.is_special_allowed_for_player("高速チャージ", "野手", "三塁手")
    assert app.is_special_allowed_for_player("高速チャージ", "野手", "二塁手", "一塁手△")
    assert not app.is_special_allowed_for_player("高速チャージ", "野手", "二塁手")


def test_catcher_constraint_helpers_include_sub_catcher_and_exclude_sasayaki_yaburi():
    assert app.is_special_allowed_for_player("フレーミング○", "野手", "捕手")
    assert app.is_special_allowed_for_player("フレーミング○", "野手", "一塁手", [{"position":"捕手","aptitude":"△"}])
    assert not app.is_special_allowed_for_player("フレーミング○", "野手", "一塁手")
    assert app.is_special_allowed_for_player("ささやき破り", "野手", "遊撃手")


def test_pitcher_relief_constraint_helpers():
    starter_only = {"starter_aptitude":"◎", "reliever_aptitude":"-", "closer_aptitude":"-"}
    reliever = {"starter_aptitude":"-", "reliever_aptitude":"○", "closer_aptitude":"-"}
    closer = {"starter_aptitude":"-", "reliever_aptitude":"-", "closer_aptitude":"◎"}
    for name in ["火消し", "緊急登板○", "投手存在感", "回またぎ○"]:
        assert not app.is_special_allowed_for_player(name, "投手", "先発", pitcher_aptitudes=starter_only)
        assert app.is_special_allowed_for_player(name, "投手", "中継ぎ", pitcher_aptitudes=reliever)
    assert app.is_special_allowed_for_player("緊急登板○", "投手", "抑え", pitcher_aptitudes=closer)
    assert app.is_special_allowed_for_player("投手存在感", "投手", "抑え", pitcher_aptitudes=closer)


def test_catcher_only_normal_special_is_blocked_for_non_catcher_but_allowed_for_sub_catcher():
    master = make_master()
    specials = app.generate_specials(random.Random(1), master, "野手", "守備職人", position="外野手", age=28,
                                    abilities={"守備力":{"value":90}, "捕球":{"value":90}}, category="架空球団用",
                                    player_class="スター級", archetype="守備", position_style="守備外野手")
    assert "フレーミング○" not in specials
    chance = app.adjust_special_chance(master.abilities[0], 100, "野手", "守備職人", position="一塁手", age=28,
                                       abilities={"守備力":{"value":90}, "捕球":{"value":90}}, sub_positions=[{"position":"捕手","aptitude":"△"}])
    assert chance > 0


def test_conflicting_policy_specials_are_mutually_exclusive():
    specials = app.generate_specials(random.Random(2), make_master(), "投手", "変化球派", position="先発", age=28,
                                    abilities={"球速":{"value":150}, "コントロール":{"value":70}, "スタミナ":{"value":70}},
                                    breaking_balls=[{"movement":3},{"movement":3},{"movement":3}], category="架空球団用",
                                    player_class="一軍主力級", archetype="変化球", position_style="変化球型先発")
    assert not ({"速球中心", "変化球中心"} <= set(specials))


def test_catcher_rank_generation_respects_main_and_sub_catcher():
    master = make_master()
    no_catcher = app.generate_ranked_specials(random.Random(3), master, "野手", "一塁手", "守備職人", {"守備力":{"value":80}}, 28,
                                             category="架空球団用", player_class="一軍主力級", archetype="守備", position_style="守備型一塁手")
    assert "キャッチャー" not in no_catcher
    main_catcher = app.generate_ranked_specials(random.Random(3), master, "野手", "捕手", "守備職人", {"守備力":{"value":80}}, 28)
    assert "キャッチャー" in main_catcher
    sub_catcher = app.generate_ranked_specials(random.Random(3), master, "野手", "一塁手", "守備職人", {"守備力":{"value":80}}, 28, sub_positions=[{"position":"捕手","aptitude":"△"}])
    assert "キャッチャー" in sub_catcher


def test_utility_condition_limits_three_subpositions():
    subs = app.generate_sub_positions(random.Random(5), "野手", "一塁手", "長距離砲", "助っ人外国人用", 30, "右投右打",
                                      {"走力":{"value":70}, "肩力":{"value":70}, "守備力":{"value":70}, "捕球":{"value":70}, "パワー":{"value":85}},
                                      player_class="主力期待級", archetype="長打", position_style="強打一塁手", acquisition_role="主砲候補")
    assert len(subs) <= 2


def test_seed_reproducibility_phase3():
    master = app.load_master_data()
    p1 = app.generate_player("野手", "架空球団用", master, seed=333)
    p2 = app.generate_player("野手", "架空球団用", master, seed=333)
    assert p1 == p2
