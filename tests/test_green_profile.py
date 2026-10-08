"""緑特の型（投手の役割・野手のポジション）の補正（`緑特の型_改修指示.md` 1-2）。

- 役割・ポジションの差が入っている（救援に速球中心、先発にテンポ○、一塁手に強振多用、二遊間にミート多用 など）
- 補正の段階は対象の緑特だけを変える（能力・ランク特能・青特・赤特・名前などは補正なしと同じ）
- 青特の型の段階の乱数の並びを変えない（新しい名前空間の副乱数）
- 外国人・ドラフト候補用は変わらない
"""
from __future__ import annotations

import json
import logging
from statistics import mean

import pytest

import app

MASTER = app.load_master_data()
TARGETS = {
    "投手": {"変化球中心", "速球中心", "テンポ○"},
    "野手": {"積極打法", "慎重打法", "強振多用", "ミート多用", "チームプレイ○", "積極走塁", "積極守備"},
}


@pytest.fixture(autouse=True)
def _quiet_and_restore():
    logging.disable(logging.WARNING)
    saved = app.FICTIONAL_GREEN_PROFILE_OVERRIDE
    yield
    app.FICTIONAL_GREEN_PROFILE_OVERRIDE = saved
    logging.disable(logging.NOTSET)


def players(role: str, category: str, seeds: range) -> list[dict]:
    return [app.generate_player(role, category, MASTER, seed=seed) for seed in seeds]


def rate(group: list[dict], name: str) -> float:
    return mean(name in p["special_abilities"] for p in group)


def test_segment() -> None:
    assert app.fictional_green_segment("投手", "左投右打", "先発") == "左|先発"
    assert app.fictional_green_segment("投手", "右投右打", "中継ぎ") == "右|救援"
    assert app.fictional_green_segment("投手", "右投左打", "抑え") == "右|救援"
    assert app.fictional_green_segment("野手", "右投左打", "二塁手") == "二塁手|左"
    assert app.fictional_green_segment("野手", "右投両打", "捕手") == "捕手|右"  # 両打は右打と同じ


def test_pitcher_role_differences() -> None:
    pitchers = players("投手", "架空球団用", range(1, 2001))
    starters = [p for p in pitchers if p["position"] == "先発"]
    relievers = [p for p in pitchers if p["position"] != "先発"]
    assert len(starters) > 500 and len(relievers) > 500
    assert rate(relievers, "速球中心") - rate(starters, "速球中心") > 0.05  # 実在は 17.9% − 6.3%
    assert rate(starters, "テンポ○") - rate(relievers, "テンポ○") > 0.05  # 実在は 12.6% − 2.4%


def test_fielder_position_differences() -> None:
    fielders = players("野手", "架空球団用", range(1, 2501))
    by_position = lambda *names: [p for p in fielders if p["position"] in names]  # noqa: E731
    middle, outfield, catchers = by_position("二塁手", "遊撃手"), by_position("外野手"), by_position("捕手")
    assert rate(middle, "ミート多用") - rate(outfield, "ミート多用") > 0.05  # 実在は 二塁 21%・遊撃 18%、外野 5%
    assert rate(outfield, "積極打法") - rate(catchers, "積極打法") > 0.05  # 実在は 外野 24%、捕手 9%
    assert rate(middle, "強振多用") < rate(outfield, "強振多用")  # 実在は 二遊間 4%、外野 12%


@pytest.mark.parametrize("role", ["投手", "野手"])
def test_green_stage_changes_only_target_greens(role: str) -> None:
    """緑特の型の段階は専用の乱数を使い、対象の緑特しか変えない。能力・ランク特能・青特・名前などは補正なしと同じ。"""
    changed = 0
    for seed in range(1, 121):
        app.FICTIONAL_GREEN_PROFILE_OVERRIDE = {}
        before = app.generate_player(role, "架空球団用", MASTER, seed=seed)
        app.FICTIONAL_GREEN_PROFILE_OVERRIDE = None
        after = app.generate_player(role, "架空球団用", MASTER, seed=seed)
        assert {k: v for k, v in before.items() if k != "special_abilities"} == {k: v for k, v in after.items() if k != "special_abilities"}, seed
        assert not (set(before["special_abilities"]) ^ set(after["special_abilities"])) - TARGETS[role], seed
        changed += before["special_abilities"] != after["special_abilities"]
    assert changed > 4  # 表を入れると緑特は動く（架空球団用の投手は約1割、野手は約2.5割が変わる）


@pytest.mark.parametrize("category", ["助っ人外国人用", "ドラフト候補用"])
@pytest.mark.parametrize("role", ["投手", "野手"])
def test_other_categories_are_not_changed(category: str, role: str) -> None:
    for seed in range(1, 41):
        app.FICTIONAL_GREEN_PROFILE_OVERRIDE = {}
        before = app.generate_player(role, category, MASTER, seed=seed)
        app.FICTIONAL_GREEN_PROFILE_OVERRIDE = None
        assert app.generate_player(role, category, MASTER, seed=seed) == before, seed


def pitcher(position: str = "中継ぎ", age: int = 30, bats: str = "右投右打") -> dict:
    return {"role": "投手", "position": position, "age": age, "player_class": "一軍主力級", "batting_throwing": bats}


def test_green_adjust_adds_removes_and_keeps_groups() -> None:
    allow = lambda name: True  # noqa: E731
    app.FICTIONAL_GREEN_PROFILE_OVERRIDE = {"投手": {"速球中心": {"右|救援": [0.0, 1.0]}}}
    assert "速球中心" in app.fictional_green_profile_adjust(1, MASTER, pitcher(), [], allow)
    assert "速球中心" not in app.fictional_green_profile_adjust(1, MASTER, pitcher("先発"), [], allow)  # 区分が違えば何もしない
    # 速球中心と変化球中心は同じグループなので、両方は付かない（force=False）
    assert app.fictional_green_profile_adjust(1, MASTER, pitcher(), ["変化球中心"], allow) == ["変化球中心"]
    # 目標が 0 なら（20歳の外す重みは 1 を超えるので）必ず外す
    app.FICTIONAL_GREEN_PROFILE_OVERRIDE = {"投手": {"テンポ○": {"右|救援": [0.3, 0.0]}}}
    assert app.fictional_green_profile_adjust(1, MASTER, pitcher(age=20), ["テンポ○", "球持ち○"], allow) == ["球持ち○"]
    app.FICTIONAL_GREEN_PROFILE_OVERRIDE = {}
    assert app.fictional_green_profile_adjust(1, MASTER, pitcher(), ["テンポ○"], allow) == ["テンポ○"]  # 表がなければ何もしない


def test_green_stage_does_not_change_blue_stage_random_stream() -> None:
    """緑特の型の乱数は新しい名前空間。青特の型の段階の結果は、緑特の表の有無で変わらない。"""
    assert app.FICTIONAL_GREEN_PROFILE_NAMESPACE not in {
        app.FICTIONAL_SPECIAL_PROFILE_NAMESPACE, app.FICTIONAL_AGE_SPECIAL_NAMESPACE, app.FICTIONAL_MOVEMENT_QUALITY_NAMESPACE,
    }
    p = {**pitcher("先発"), "seed": 7}
    specials = ["テンポ○", "クロスファイヤー", "球持ち○"]
    allow = lambda name: True  # noqa: E731
    blue_only = app.fictional_special_profile_adjust(7, MASTER, p, specials, allow)
    app.FICTIONAL_GREEN_PROFILE_OVERRIDE = {"投手": {"テンポ○": {"右|先発": [0.5, 0.0]}}}
    assert app.fictional_special_profile_adjust(7, MASTER, p, specials, allow) == blue_only


def test_green_table_file_is_consistent() -> None:
    data = json.loads(app.FICTIONAL_GREEN_PROFILE_PATH.read_text(encoding="utf-8"))
    table = data["表"]
    positions = {"捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手"}
    kinds = {row["name"]: row["kind"] for row in MASTER.abilities}
    for role, specials in table.items():
        assert set(specials) == TARGETS[role]
        for name, segments in specials.items():
            assert kinds[name] == "green", name
            expected = {f"{h}|{r}" for h in ("左", "右") for r in ("先発", "救援")} if role == "投手" else {f"{p}|{h}" for p in positions for h in ("左", "右")}
            assert set(segments) == expected, name
            assert all(0.0 <= c <= 1.0 and 0.0 <= t <= 1.0 for c, t in segments.values()), name
    # 実在の差が表に入っている
    assert table["投手"]["速球中心"]["右|救援"][1] > table["投手"]["速球中心"]["右|先発"][1]
    assert table["投手"]["テンポ○"]["右|先発"][1] > table["投手"]["テンポ○"]["右|救援"][1]
    assert data["実在"]["緑特の数"]["投手"]["平均"] < data["実在"]["緑特の数"]["野手"]["平均"]
