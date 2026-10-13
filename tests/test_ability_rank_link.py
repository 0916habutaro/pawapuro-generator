"""架空球団用の日本人の、能力とランク特能の結びつき（`能力とランク特能の結びつき_改修指示.md`）。

κ・重みは球団生成で合わせており、正式な判定は scripts/check_pitcher_rank_pitches.py・check_fielder_position.py
（球団生成300球団。共通部分は scripts/rank_ability.py）。ここでは個別生成で、能力の高い選手ほど良いランクになること、
A・G を増やさないこと、乱数を引く回数が変わらないこと、ほかの区分が変わらないことを確かめる。
"""
from __future__ import annotations

import statistics

import app

MASTER = app.load_master_data()
SEEDS = range(1, 401)
TILTED = {"投手": ("回復", "打たれ強さ"), "野手": ("回復", "送球", "キャッチャー")}


def players(role: str = "野手", category: str = "架空球団用") -> list[dict]:
    return [app.generate_player(role, category, MASTER, seed=seed) for seed in SEEDS]


def domestic(role: str) -> list[dict]:
    return [player for player in players(role) if player["roster_origin"] == "domestic"]


def score(player: dict, group: str) -> int:
    name = player["abilities"]["ranked_specials"].get(group)
    return app.FICTIONAL_ABILITY_RANK_SCORES[name[-1]] if name else 0


def value(player: dict, key: str) -> float:
    return float(app.ability_numeric_value(player["abilities"], key))


def without_ranked(player: dict) -> dict:
    return {**player, "abilities": {k: v for k, v in player["abilities"].items() if k != "ranked_specials"}}


def no_tilt(monkeypatch) -> None:
    monkeypatch.setattr(app, "fictional_ability_rank_tilt", lambda role, position, values: (lambda group: 0.0))


def test_tilt_follows_the_table():
    pitcher = {"コントロール": 70, "スタミナ": 70}
    starter = app.fictional_ability_rank_tilt("投手", "先発", pitcher)
    reliever = app.fictional_ability_rank_tilt("投手", "中継ぎ", pitcher)
    z = ((70 - 55.27) / 13.27 + (70 - 56.55) / 11.04) / 2
    assert abs(starter("回復") - 1.3 * z) < 1e-9
    assert abs(starter("打たれ強さ") - 0.5 * z) < 1e-9
    assert reliever("回復") > 0 and reliever("打たれ強さ") > 0
    assert starter("ノビ") == 0.0 and starter("対ピンチ") == 0.0  # 表に無いランク特能は傾けない
    assert app.fictional_ability_rank_tilt("投手", "先発", {"コントロール": 40, "スタミナ": 40})("回復") < 0

    fielder = {"ミート": 60, "パワー": 50, "走力": 50, "肩力": 90, "守備力": 65, "捕球": 65}
    catcher = app.fictional_ability_rank_tilt("野手", "捕手", fielder)
    other = app.fictional_ability_rank_tilt("野手", "遊撃手", fielder)
    assert catcher("キャッチャー") > 0
    assert other("キャッチャー") == 0.0  # サブポジが捕手の野手のキャッチャーには傾きをかけない
    assert catcher("回復") == other("回復") > 0  # 回復・送球は野手全体の平均・SDで傾ける
    assert catcher("送球") == other("送球") > 0
    assert other("走塁") == 0.0
    # 送球は捕球・守備力だけで決まる（肩力は使わない）
    assert other("送球") == app.fictional_ability_rank_tilt("野手", "遊撃手", {**fielder, "肩力": 30})("送球")


def test_ability_tilt_never_increases_a_and_g_and_favours_good_ranks():
    for weights in (*app.FICTIONAL_PITCHER_RANKED_WEIGHTS.values(), *app.FICTIONAL_FIELDER_RANKED_WEIGHTS.values()):
        for tilt in (-2.0, -0.5, 0.5, 2.0):
            tilted = app.fictional_ability_rank_weights(weights, tilt)
            assert tilted["A"] <= weights["A"] + 1e-12
            assert tilted["G"] <= weights["G"] + 1e-12
    weights = app.FICTIONAL_FIELDER_RANKED_WEIGHTS["回復"]
    share = lambda w, letters: sum(w[x] for x in letters) / sum(w.values())  # noqa: E731
    high, low = app.fictional_ability_rank_weights(weights, 1.0), app.fictional_ability_rank_weights(weights, -1.0)
    assert share(high, "BC") > share(weights, "BC") > share(low, "BC")
    assert share(high, "EF") < share(weights, "EF") < share(low, "EF")


def test_better_players_get_better_ranks():
    # 個別生成でも、能力の合成値の上位半分は下位半分よりランクの点が高い（球団生成の相関は 0.4〜0.7）
    def gap(group: list[dict], name: str, keys: tuple[str, ...]) -> float:
        z = [statistics.fmean(value(p, k) for k in keys) for p in group]
        middle = statistics.median(z)
        top = [score(p, name) for p, x in zip(group, z) if x > middle]
        bottom = [score(p, name) for p, x in zip(group, z) if x <= middle]
        return statistics.fmean(top) - statistics.fmean(bottom)

    pitchers = domestic("投手")
    starters = [p for p in pitchers if p["position"] == "先発"]
    assert gap(starters, "回復", ("コントロール", "スタミナ")) > 0.4
    assert gap(pitchers, "打たれ強さ", ("コントロール", "スタミナ")) > 0.1
    fielders = domestic("野手")
    assert gap(fielders, "回復", ("ミート", "守備力", "捕球")) > 0.4
    assert gap(fielders, "送球", ("捕球", "守備力")) > 0.3
    catchers = [p for p in fielders if p["position"] == "捕手"]
    assert gap(catchers, "キャッチャー", ("捕球", "守備力")) > 0.4


def test_tilt_does_not_change_the_random_stream(monkeypatch):
    # 傾きは重みを変えるだけで、乱数を引く回数は変わらない。ランク特能以外と、傾けない項目のランクは同じ
    current = {role: domestic(role) for role in ("投手", "野手")}
    no_tilt(monkeypatch)
    for role in ("投手", "野手"):
        changed = 0
        for a, b in zip(current[role], domestic(role)):
            assert without_ranked(a) == without_ranked(b), (role, a["seed"])
            ra, rb = a["abilities"]["ranked_specials"], b["abilities"]["ranked_specials"]
            for group in set(ra) | set(rb):
                if group not in TILTED[role]:
                    assert ra.get(group) == rb.get(group), (role, a["seed"], group)
            changed += ra != rb
        assert changed > 0, role


def test_other_categories_do_not_use_the_tilt(monkeypatch):
    cases = [("投手", "ドラフト候補用"), ("野手", "ドラフト候補用"), ("投手", "助っ人外国人用"), ("野手", "助っ人外国人用")]
    current = {case: players(*case) for case in cases}
    foreign = {role: [p for p in players(role) if p["roster_origin"] != "domestic"] for role in ("投手", "野手")}
    no_tilt(monkeypatch)
    for case in cases:
        assert players(*case) == current[case], case
    for role in ("投手", "野手"):
        assert [p for p in players(role) if p["roster_origin"] != "domestic"] == foreign[role], role
