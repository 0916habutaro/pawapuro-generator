"""架空球団用の日本人野手の、対左投手の打席差と捕手のキャッチャー（野手のランク特能_改修指示.md）。

重みは球団生成で合わせており、正式な判定は scripts/check_fielder_batting.py・check_fielder_position.py（球団生成300球団）。
ここでは個別生成で、打席・ポジションごとの重みが使われること、両打とサブポジ捕手は今の重みのままであること、
乱数の流れとほかの区分が変わらないことを確かめる。
"""
from __future__ import annotations

import app

MASTER = app.load_master_data()
SEEDS = range(1, 301)
NEW_KEYS = ("対左投手_左打", "対左投手_右打", "キャッチャー_捕手")


def players(role: str = "野手", category: str = "架空球団用") -> list[dict]:
    return [app.generate_player(role, category, MASTER, seed=seed) for seed in SEEDS]


def domestic_fielders() -> list[dict]:
    return [player for player in players() if player["roster_origin"] == "domestic"]


def bats_of(player: dict) -> str:
    return str(player["batting_throwing"])[-2:-1]


def letter(player: dict, group: str) -> str | None:
    name = player["abilities"]["ranked_specials"].get(group)
    return name[-1] if name else None


def without_ranked(player: dict) -> dict:
    return {**player, "abilities": {k: v for k, v in player["abilities"].items() if k != "ranked_specials"}}


def test_weights_key_splits_left_pitchers_by_batting_side_and_catcher_by_main_position():
    key = app.fictional_fielder_ranked_weights_key
    assert key("対左投手", "外野手", "右投左打") == "対左投手_左打"
    assert key("対左投手", "外野手", "左投左打") == "対左投手_左打"
    assert key("対左投手", "捕手", "右投右打") == "対左投手_右打"
    assert key("対左投手", "遊撃手", "左投右打") == "対左投手_右打"  # 投げ手ではなく打席で分ける
    assert key("対左投手", "遊撃手", "右投両打") == "対左投手"  # 両打は今の重み
    assert key("キャッチャー", "捕手", "右投右打") == "キャッチャー_捕手"
    assert key("キャッチャー", "一塁手", "右投右打") == "キャッチャー"  # サブポジ捕手は今の重み
    assert key("チャンス", "捕手", "右投左打") == "チャンス"
    for name in (*NEW_KEYS, "対左投手", "キャッチャー"):
        assert name in app.FICTIONAL_FIELDER_RANKED_WEIGHTS


def test_new_weights_are_used_and_switch_hitters_and_sub_catchers_keep_the_old_weights(monkeypatch):
    # 選手格の補正で1段動くので、重なりのない文字にする（G は F に、A は B にしか動かない）
    weights = dict(app.FICTIONAL_FIELDER_RANKED_WEIGHTS)
    weights.update({"対左投手_左打": {"G": 1.0}, "対左投手_右打": {"A": 1.0}, "対左投手": {"D": 1.0},
                    "キャッチャー_捕手": {"G": 1.0}, "キャッチャー": {"A": 1.0}})
    monkeypatch.setattr(app, "FICTIONAL_FIELDER_RANKED_WEIGHTS", weights)
    seen = {"左": 0, "右": 0, "両": 0, "捕手": 0}
    for player in domestic_fielders():
        bats, left = bats_of(player), letter(player, "対左投手")
        expected = {"左": "FG", "右": "AB", "両": "CDE"}[bats]
        assert left in expected, (player["seed"], player["batting_throwing"], left)
        seen[bats] += 1
        catcher = letter(player, "キャッチャー")
        if player["position"] == "捕手":
            assert catcher in "FG", (player["seed"], catcher)
            seen["捕手"] += 1
        elif catcher is not None:
            assert catcher in "AB", (player["seed"], player["sub_positions"], catcher)
    assert all(seen.values()), seen


def test_new_weights_do_not_change_the_random_stream(monkeypatch):
    current = domestic_fielders()
    weights = {**app.FICTIONAL_FIELDER_RANKED_WEIGHTS, **{key: {"D": 1.0} for key in NEW_KEYS}}
    monkeypatch.setattr(app, "FICTIONAL_FIELDER_RANKED_WEIGHTS", weights)
    changed = domestic_fielders()
    for a, b in zip(current, changed):
        assert without_ranked(a) == without_ranked(b)
        ra, rb = a["abilities"]["ranked_specials"], b["abilities"]["ranked_specials"]
        assert set(ra) == set(rb)
        for group in ra:
            uses_new = (group == "対左投手" and bats_of(a) in "左右") or (group == "キャッチャー" and a["position"] == "捕手")
            if not uses_new:
                assert ra[group] == rb[group], (a["seed"], group)


def test_other_categories_do_not_use_the_new_weights(monkeypatch):
    cases = [("投手", "架空球団用"), ("投手", "ドラフト候補用"), ("野手", "ドラフト候補用"), ("投手", "助っ人外国人用"), ("野手", "助っ人外国人用")]
    current = {case: players(*case) for case in cases}
    foreign = [p for p in players() if p["roster_origin"] != "domestic"]
    weights = {**app.FICTIONAL_FIELDER_RANKED_WEIGHTS, **{key: {"G": 1.0} for key in NEW_KEYS}}
    monkeypatch.setattr(app, "FICTIONAL_FIELDER_RANKED_WEIGHTS", weights)
    for case in cases:
        assert players(*case) == current[case], case
    assert [p for p in players() if p["roster_origin"] != "domestic"] == foreign
