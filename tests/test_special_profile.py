"""青特の型（投手の左右×役割・野手の打席とポジション）の補正（`青特の型_改修指示.md`・`投手の役割と特能_改修指示.md`）。

- 左右・ポジションの差が入っている（左投手・左打者のほうが青特が多い、捕手は少ない）
- 右投手のクロスファイヤーは0人
- 投手の区分は「投げ手|役割」（先発・救援）。投手は赤特も表に入る。連動特能（奪三振・球速安定）の保有率も役割で分ける
- 補正の段階は特能（special_abilities）だけを変える（能力・ランク特能・乱数の並びは変わらない）
- マスターに足した4つ（お祭り男・春男・夏男・秋男）は、架空球団用の野手の補正でだけ付く。外国人・ドラフト候補用では出ない
"""
from __future__ import annotations

import dataclasses
import json
import logging
import random
from statistics import mean

import pytest

import app
from generator import team_analysis as ta

MASTER = app.load_master_data()
NEW_SPECIALS = ("お祭り男", "春男", "夏男", "秋男")


@pytest.fixture(autouse=True)
def _quiet_and_restore():
    logging.disable(logging.WARNING)
    saved = app.FICTIONAL_SPECIAL_PROFILE_OVERRIDE
    yield
    app.FICTIONAL_SPECIAL_PROFILE_OVERRIDE = saved
    logging.disable(logging.NOTSET)


def players(role: str, category: str, seeds: range, master=MASTER) -> list[dict]:
    return [app.generate_player(role, category, master, seed=seed) for seed in seeds]


def blue(player: dict) -> int:
    return ta.special_counts(player["special_abilities"])["n_blue"]


def test_hand_and_segment() -> None:
    assert app.fictional_special_hand("投手", "左投左打") == "左"
    assert app.fictional_special_hand("投手", "右投左打") == "右"
    assert app.fictional_special_hand("野手", "右投左打") == "左"
    assert app.fictional_special_hand("野手", "右投両打") == "右"  # 両打は右打と同じ
    assert app.fictional_special_hand("野手", "左投右打") == "右"
    assert app.fictional_special_segment("投手", "左投右打", "先発") == "左|先発"
    assert app.fictional_special_segment("投手", "右投左打", "中継ぎ") == "右|救援"  # 中継ぎ・抑えは救援
    assert app.fictional_special_segment("投手", "右投右打", "抑え") == "右|救援"
    assert app.fictional_special_segment("野手", "右投左打", "捕手") == "捕手|左"
    # 連動特能の区分は、投手は「投げ手|役割」、野手は打席だけ
    assert app.fictional_linked_hand("投手", "左投左打", "先発") == "左|先発"
    assert app.fictional_linked_hand("投手", "右投右打", "抑え") == "右|救援"
    assert app.fictional_linked_hand("野手", "右投左打", "捕手") == "左"


def test_linked_hand_rates_have_the_same_bands_as_linked_specials() -> None:
    for role, table in app.FICTIONAL_LINKED_HAND_RATES.items():
        base = {name: rates for name, _key, _limits, rates in app.FICTIONAL_LINKED_SPECIALS[role]}
        for name, hands in table.items():
            # 区分は 左・右 か「投げ手|役割」。どちらの投げ手も、投げ手だけの指定か、先発・救援の両方の指定がある
            assert set(hands) <= {"右", "左"} | {f"{h}|{r}" for h in ("右", "左") for r in ("先発", "救援")}, name
            assert all(h in hands or {f"{h}|先発", f"{h}|救援"} <= set(hands) for h in ("右", "左")), name
            assert all(len(rates) == len(base[name]) for rates in hands.values()), name
            assert all(0.0 <= rate <= 1.0 for rates in hands.values() for rate in rates)
    # 奪三振・内野安打○は左のほうが多い。広角打法は右打に多い
    assert all(left > right for left, right in zip(*(app.FICTIONAL_LINKED_HAND_RATES["投手"]["奪三振"][h] for h in ("左", "右"))))
    assert all(left > right for left, right in zip(*(app.FICTIONAL_LINKED_HAND_RATES["野手"]["内野安打○"][h] for h in ("左", "右"))))
    assert sum(app.FICTIONAL_LINKED_HAND_RATES["野手"]["広角打法"]["右"]) > sum(app.FICTIONAL_LINKED_HAND_RATES["野手"]["広角打法"]["左"])
    # 保有率の上書きを返す。指定がなければ元の保有率
    assert app.fictional_linked_rates("投手", "奪三振", [0.1], "左") == app.FICTIONAL_LINKED_HAND_RATES["投手"]["奪三振"]["左"]
    assert app.fictional_linked_rates("投手", "四球", [0.1, 0.2], "左") == [0.1, 0.2]


def test_linked_rates_by_pitcher_role() -> None:
    """奪三振・球速安定は、同じ球速の帯でも救援のほうが多い（`投手の役割と特能_改修指示.md` 1-2）。"""
    rates = app.FICTIONAL_LINKED_HAND_RATES["投手"]
    for hand in ("右", "左"):
        # 奪三振は球速156以上では役割の差がない（実在 先発・救援とも 0.62）ので、155以下の帯で比べる
        assert all(r > s for r, s in zip(rates["奪三振"][f"{hand}|救援"][:3], rates["奪三振"][f"{hand}|先発"][:3]))
        assert all(r > s for r, s in zip(rates["球速安定"][f"{hand}|救援"], rates["球速安定"][f"{hand}|先発"]))
    # 「投げ手|役割」の指定があればそれを、なければ投げ手だけの指定を、それもなければ元の保有率を使う
    assert app.fictional_linked_rates("投手", "奪三振", [0.1], "左|救援") == rates["奪三振"]["左|救援"]
    assert app.fictional_linked_rates("野手", "内野安打○", [0.1], "左|救援") == app.FICTIONAL_LINKED_HAND_RATES["野手"]["内野安打○"]["左"]
    assert app.fictional_linked_rates("投手", "四球", [0.1, 0.2], "右|先発") == [0.1, 0.2]
    # 共有の乱数の空回し（hand=None）は、改修前と同じく投打・役割の差なし
    base = next(r for name, _key, _limits, r in app.FICTIONAL_LINKED_SPECIALS["投手"] if name == "球速安定")
    assert app.fictional_linked_rates("投手", "球速安定", base, None) == base


def domestic_pitchers(seeds: range) -> list[dict]:
    return [p for p in players("投手", "架空球団用", seeds) if p.get("roster_origin", "domestic") == "domestic"]


def test_relievers_have_more_linked_specials_than_starters() -> None:
    """個別生成でも、同じ球速の帯（148〜151）で救援のほうが球速安定・奪三振を多く持つ。"""
    band = [p for p in domestic_pitchers(range(1, 1501)) if 148 <= app.pitcher_speed_value(p["abilities"]) <= 151]
    starters = [p for p in band if p["position"] == "先発"]
    relievers = [p for p in band if p["position"] != "先発"]
    assert len(starters) > 80 and len(relievers) > 80
    rate = lambda group, name: sum(name in p["special_abilities"] for p in group) / len(group)  # noqa: E731
    assert rate(relievers, "球速安定") - rate(starters, "球速安定") > 0.08  # 実在は 0.32 − 0.13
    assert rate(relievers, "奪三振") - rate(starters, "奪三振") > 0.06  # 実在は 0.28 − 0.10


def test_profile_segment_uses_pitcher_role() -> None:
    """青特の型の補正は、投手を「投げ手|役割」で分ける。救援だけの目標は先発には効かない。"""
    allow = lambda name: True  # noqa: E731
    app.FICTIONAL_SPECIAL_PROFILE_OVERRIDE = {"投手": {"緊急登板○": {"右|救援": [0.0, 1.0], "右|先発": [0.0, 0.0]}}}
    pitcher = {"role": "投手", "position": "中継ぎ", "age": 36, "player_class": "一軍主力級", "batting_throwing": "右投右打"}
    assert "緊急登板○" in app.fictional_special_profile_adjust(1, MASTER, pitcher, ["球持ち○"], allow)
    assert "緊急登板○" in app.fictional_special_profile_adjust(1, MASTER, {**pitcher, "position": "抑え"}, ["球持ち○"], allow)
    assert "緊急登板○" not in app.fictional_special_profile_adjust(1, MASTER, {**pitcher, "position": "先発"}, ["球持ち○"], allow)
    assert "緊急登板○" not in app.fictional_special_profile_adjust(1, MASTER, {**pitcher, "batting_throwing": "左投左打"}, ["球持ち○"], allow)
    # 赤特も外せる（先発の負け運の目標を0にすると、20歳なら必ず外れる）
    app.FICTIONAL_SPECIAL_PROFILE_OVERRIDE = {"投手": {"負け運": {"右|先発": [0.5, 0.0]}}}
    young = {**pitcher, "position": "先発", "age": 20, "player_class": "一軍控え級"}
    assert app.fictional_special_profile_adjust(1, MASTER, young, ["負け運", "球持ち○"], allow) == ["球持ち○"]


def test_role_differences_of_specials() -> None:
    """役割で差の大きい特能が、実在と同じ向きに分かれる（指示書 0-2）。"""
    pitchers = domestic_pitchers(range(1, 2001))
    starters = [p for p in pitchers if p["position"] == "先発"]
    relievers = [p for p in pitchers if p["position"] != "先発"]
    rate = lambda group, name: sum(name in p["special_abilities"] for p in group) / len(group)  # noqa: E731
    assert rate(relievers, "緊急登板○") - rate(starters, "緊急登板○") > 0.06
    for name in ("スロースターター", "負け運", "牽制○", "内角攻め", "緩急○"):
        assert rate(starters, name) - rate(relievers, name) > 0.03, name


def test_right_pitchers_never_have_crossfire() -> None:
    pitchers = players("投手", "架空球団用", range(1, 701))
    right = [p for p in pitchers if p["batting_throwing"].startswith("右投")]
    left = [p for p in pitchers if p["batting_throwing"].startswith("左投")]
    assert len(right) > 300 and len(left) > 100
    assert not [p["seed"] for p in right if "クロスファイヤー" in p["special_abilities"]]
    assert any("クロスファイヤー" in p["special_abilities"] for p in left)  # 左投手には残る（実在は18.6%）


def test_left_pitchers_and_left_batters_have_more_blue_specials() -> None:
    pitchers = players("投手", "架空球団用", range(1, 1501))
    left = mean(blue(p) for p in pitchers if p["batting_throwing"].startswith("左投"))
    right = mean(blue(p) for p in pitchers if p["batting_throwing"].startswith("右投"))
    assert left - right > 0.4  # 実在は +0.76
    fielders = players("野手", "架空球団用", range(1, 1501))
    left = mean(blue(p) for p in fielders if p["batting_throwing"][2:3] == "左")
    right = mean(blue(p) for p in fielders if p["batting_throwing"][2:3] != "左")
    assert left - right > 0.25  # 実在は +0.62


def test_catchers_have_fewer_blue_specials_than_other_positions() -> None:
    fielders = players("野手", "架空球団用", range(1, 1501))
    catchers = [blue(p) for p in fielders if p["position"] == "捕手"]
    others = [blue(p) for p in fielders if p["position"] != "捕手"]
    assert len(catchers) > 100
    assert mean(others) - mean(catchers) > 0.3  # 実在は 2.45 − 1.72


def test_not_real_specials_are_removed() -> None:
    pitcher_banned = {"ムード○", "投打躍動", "全開"}
    fielder_banned = {"対エース○", "ブロッキング", "フレーミング○", "フレーミング◎"}
    assert pitcher_banned <= app.FICTIONAL_NOT_REAL_SPECIALS["投手"] and fielder_banned <= app.FICTIONAL_NOT_REAL_SPECIALS["野手"]
    assert not [p["seed"] for p in players("投手", "架空球団用", range(1, 501)) if pitcher_banned & set(p["special_abilities"])]
    assert not [p["seed"] for p in players("野手", "架空球団用", range(1, 501)) if fielder_banned & set(p["special_abilities"])]


def test_pitcher_runner_special_is_blue_for_pitchers_and_red_is_added_by_profile() -> None:
    assert "対ランナー×" in app.FICTIONAL_AGE_NEGATIVE_SPECIALS and "対ランナー" not in app.FICTIONAL_AGE_NEGATIVE_SPECIALS
    assert "対ランナー×" in app.FICTIONAL_NOT_REAL_SPECIALS["投手"]  # 最初の抽選では出さない
    pitchers = players("投手", "架空球団用", range(1, 1501))
    red = [p for p in pitchers if "対ランナー×" in p["special_abilities"]]
    assert 0.04 < len(red) / len(pitchers) < 0.14  # 実在は約8.6%
    assert not [p["seed"] for p in red if "対ランナー" in p["special_abilities"]]  # 同じグループは同時に持たない


def test_new_specials_only_for_fictional_fielders() -> None:
    fictional = players("野手", "架空球団用", range(1, 1001))
    held = {name: sum(name in p["special_abilities"] for p in fictional) for name in NEW_SPECIALS}
    assert held["お祭り男"] > 10 and held["春男"] > 3  # 実在は 4.1%・1.9%
    for category in ("助っ人外国人用", "ドラフト候補用"):
        for role in ("投手", "野手"):
            assert not [p["seed"] for p in players(role, category, range(1, 301)) if set(NEW_SPECIALS) & set(p["special_abilities"])], (category, role)
    assert not [p["seed"] for p in players("投手", "架空球団用", range(1, 301)) if set(NEW_SPECIALS) & set(p["special_abilities"])]
    rows = {row["name"]: row for row in MASTER.abilities}
    for name in NEW_SPECIALS:
        assert rows[name]["kind"] == "blue" and rows[name]["weight"] == 0 and rows[name]["target_role"] == "野手"
    assert len({rows[name]["group"] for name in NEW_SPECIALS}) == 4  # それぞれ別のグループ
    assert all(name in app.SPECIAL_ABILITY_DISPLAY_INDEX for name in NEW_SPECIALS)


@pytest.mark.parametrize("role", ["投手", "野手"])
def test_profile_stage_changes_only_special_abilities(role: str) -> None:
    """補正の段階は専用の乱数を使い、特能（special_abilities）しか変えない。能力・ランク特能・名前などは補正なしと同じ。"""
    changed = 0
    for seed in range(1, 81):
        app.FICTIONAL_SPECIAL_PROFILE_OVERRIDE = {}
        before = app.generate_player(role, "架空球団用", MASTER, seed=seed)
        app.FICTIONAL_SPECIAL_PROFILE_OVERRIDE = None
        after = app.generate_player(role, "架空球団用", MASTER, seed=seed)
        assert {k: v for k, v in before.items() if k != "special_abilities"} == {k: v for k, v in after.items() if k != "special_abilities"}, seed
        changed += before["special_abilities"] != after["special_abilities"]
    assert changed > 10  # 表を入れると特能は動く


@pytest.mark.parametrize("category", ["助っ人外国人用", "ドラフト候補用", "架空球団用"])
def test_new_master_rows_do_not_shift_the_random_stream(category: str) -> None:
    """マスターに足した4行（weight=0）は抽選に入れない。行を足しても、ほかの特能の抽選（乱数の並び）が変わらない。"""
    app.FICTIONAL_SPECIAL_PROFILE_OVERRIDE = {}
    old_master = dataclasses.replace(MASTER, abilities=[row for row in MASTER.abilities if row["name"] not in NEW_SPECIALS])
    for seed in range(1, 41):
        assert app.generate_player("野手", category, old_master, seed=seed) == app.generate_player("野手", category, MASTER, seed=seed), seed


def fielder(position: str = "捕手", age: int = 36, player_class: str = "一軍主力級", bats: str = "右投右打") -> dict:
    return {"role": "野手", "position": position, "age": age, "player_class": player_class, "batting_throwing": bats}


def test_profile_adjust_adds_with_age_weight_and_removes_with_age_weight() -> None:
    allow = lambda name: True  # noqa: E731
    # 目標が 1.0 なら、年齢の重み（36歳の野手は 1.78/1.054 ≈ 1.69）をかけても必ず足す
    app.FICTIONAL_SPECIAL_PROFILE_OVERRIDE = {"野手": {"お祭り男": {"捕手|右": [0.0, 1.0]}}}
    assert "お祭り男" in app.fictional_special_profile_adjust(1, MASTER, fielder(), ["サヨナラ男"], allow)
    # 区分が違えば何もしない
    assert "お祭り男" not in app.fictional_special_profile_adjust(1, MASTER, fielder("外野手"), ["サヨナラ男"], allow)
    # 目標が 0 なら（20歳の外す重み 1.44 をかけると確率は 1 を超えるので）必ず外す
    app.FICTIONAL_SPECIAL_PROFILE_OVERRIDE = {"野手": {"サヨナラ男": {"捕手|右": [0.2, 0.0]}}}
    assert app.fictional_special_profile_adjust(1, MASTER, fielder(age=20, player_class="一軍控え級"), ["サヨナラ男", "満塁男"], allow) == ["満塁男"]
    # 持っていて目標のほうが高い、持っていなくて目標のほうが低い、のときは動かさない
    app.FICTIONAL_SPECIAL_PROFILE_OVERRIDE = {"野手": {"サヨナラ男": {"捕手|右": [0.5, 0.9]}, "満塁男": {"捕手|右": [0.5, 0.1]}}}
    assert app.fictional_special_profile_adjust(1, MASTER, fielder(), ["サヨナラ男"], allow) == ["サヨナラ男"]


def test_profile_adjust_respects_count_bounds_and_groups_and_position() -> None:
    allow = lambda name: True  # noqa: E731
    app.FICTIONAL_SPECIAL_PROFILE_OVERRIDE = {"野手": {"お祭り男": {"捕手|右": [0.0, 1.0]}}}
    low, high = app.special_count_bounds("架空球団用", "二軍級")
    full = ["サヨナラ男", "満塁男", "流し打ち", "初球○", "決勝打"][:high]
    assert len(app.fictional_special_profile_adjust(1, MASTER, fielder(player_class="二軍級"), full, allow)) == high  # 上限を超えて足さない
    # 下限までは外さない
    app.FICTIONAL_SPECIAL_PROFILE_OVERRIDE = {"野手": {"サヨナラ男": {"捕手|右": [0.5, 0.0]}}}
    star_low = app.special_count_bounds("架空球団用", "スター級")[0]
    held = ["サヨナラ男", "満塁男", "流し打ち", "初球○"][:star_low]
    assert "サヨナラ男" in app.fictional_special_profile_adjust(1, MASTER, fielder(player_class="スター級"), held, allow)
    # 位置などの条件を満たさない特能は足さない
    app.FICTIONAL_SPECIAL_PROFILE_OVERRIDE = {"野手": {"お祭り男": {"捕手|右": [0.0, 1.0]}}}
    assert "お祭り男" not in app.fictional_special_profile_adjust(1, MASTER, fielder(), [], lambda name: name != "お祭り男")
    # 同じグループの特能を持っているときは足さない（force=False）
    app.FICTIONAL_SPECIAL_PROFILE_OVERRIDE = {"投手": {"対ランナー×": {"右|先発": [0.0, 1.0]}}}
    pitcher = {"role": "投手", "position": "先発", "age": 36, "player_class": "一軍主力級", "batting_throwing": "右投右打"}
    assert "対ランナー×" not in app.fictional_special_profile_adjust(1, MASTER, pitcher, ["対ランナー"], allow)
    assert "対ランナー×" in app.fictional_special_profile_adjust(1, MASTER, pitcher, ["球持ち○"], allow)


def test_right_pitcher_crossfire_is_removed_even_below_the_lower_bound() -> None:
    allow = lambda name: True  # noqa: E731
    app.FICTIONAL_SPECIAL_PROFILE_OVERRIDE = {"投手": {"緩急○": {"右|先発": [0.2, 0.2]}}}  # 表に入っていなくても外す
    pitcher = {"role": "投手", "position": "先発", "age": 30, "player_class": "スター級", "batting_throwing": "右投右打"}
    low = app.special_count_bounds("架空球団用", "スター級")[0]
    held = ["クロスファイヤー", "リリース○", "球持ち○", "内角攻め"][:low]
    assert "クロスファイヤー" not in app.fictional_special_profile_adjust(1, MASTER, pitcher, held, allow)
    assert "クロスファイヤー" in app.fictional_special_profile_adjust(1, MASTER, {**pitcher, "batting_throwing": "左投左打"}, held, allow)


def test_no_table_means_no_adjustment() -> None:
    app.FICTIONAL_SPECIAL_PROFILE_OVERRIDE = {}
    specials = ["クロスファイヤー", "緩急○"]
    pitcher = {"role": "投手", "position": "先発", "age": 30, "player_class": "一軍主力級", "batting_throwing": "右投右打"}
    assert app.fictional_special_profile_adjust(1, MASTER, pitcher, specials, lambda name: True) == specials


def test_profile_table_file_is_consistent() -> None:
    data = json.loads(app.FICTIONAL_SPECIAL_PROFILE_PATH.read_text(encoding="utf-8"))
    table = data["表"]
    positions = {"捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手"}
    master_names = {row["name"]: row for row in MASTER.abilities}
    for role, specials in table.items():
        linked = {name for name, *_ in app.FICTIONAL_LINKED_SPECIALS[role]}
        for name, segments in specials.items():
            assert name in master_names and master_names[name]["kind"] != "green", name
            # 赤特は投手だけ（対ランナー×のほかは `投手の役割と特能_改修指示.md` 1-1 で足した）。野手の表は青特だけ
            assert role == "投手" or master_names[name]["kind"] != "red" or name == "対ランナー×", name
            assert name not in linked and (name not in app.FICTIONAL_NOT_REAL_SPECIALS[role] or name == "対ランナー×"), name
            if role == "投手":
                expected = {f"{h}|{r}" for h in ("左", "右") for r in ("先発", "救援")}
            else:
                expected = {f"{p}|{h}" for p in positions for h in ("左", "右")}
            assert set(segments) == expected, name
            assert all(0.0 <= c <= 1.0 and 0.0 <= t <= 1.0 for c, t in segments.values()), name
    assert table["投手"]["クロスファイヤー"]["右|先発"][1] == 0.0 and table["投手"]["クロスファイヤー"]["右|救援"][1] == 0.0
    # 投手の赤特（能力と連動させる四球・荒れ球は入れない）
    assert {"スロースターター", "負け運", "一発", "乱調", "寸前", "軽い球", "抜け球"} <= set(table["投手"])
    assert not {"四球", "荒れ球"} & set(table["投手"])
    assert set(NEW_SPECIALS) <= set(table["野手"])
    # 保有率が0の特能（お祭り男など）は、この段階の前には誰も持っていない
    assert all(c == 0.0 for name in NEW_SPECIALS for c, _t in table["野手"][name].values())


def test_profile_rng_is_a_separate_namespace() -> None:
    assert app.FICTIONAL_SPECIAL_PROFILE_NAMESPACE not in {app.FICTIONAL_AGE_SPECIAL_NAMESPACE, app.FICTIONAL_MOVEMENT_QUALITY_NAMESPACE}
    a = app.make_sub_rng(5, app.FICTIONAL_SPECIAL_PROFILE_NAMESPACE)
    b = app.make_sub_rng(5, app.FICTIONAL_SPECIAL_PROFILE_NAMESPACE)
    assert [a.random() for _ in range(3)] == [b.random() for _ in range(3)] != [random.Random(5).random() for _ in range(3)]
