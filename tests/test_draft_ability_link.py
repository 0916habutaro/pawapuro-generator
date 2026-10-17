"""ドラフト候補用の、ランク特能の引き直し・能力とランク特能・特能の結びつきと、日本人の奪三振の左投（`能力との結びつき_ドラフト_改修指示.md`）。

重み・κ・b・gain はドラフト候補の個別生成で合わせており、正式な判定は scripts/check_draft_balance.py（投手・野手 各5000人。共通部分は
scripts/rank_ability.py・scripts/special_ability_link.py の draft_checks）。ここでは、A・G が出ないこと、能力に合った選手が良いランク・
特能を持ちやすいこと、表と平均・SD の対応、乱数を引く回数、ほかの項目・ほかの区分が変わらないことを確かめる。
"""
from __future__ import annotations

import math
import statistics

import app

MASTER = app.load_master_data()
SEEDS = range(1, 401)
PART = app.DRAFT_ABILITY_SPECIAL_LINK_PART


def table() -> dict:
    return app.load_fictional_ability_special_link()[PART]


def draft(role: str, seeds=SEEDS) -> list[dict]:
    return [app.generate_player(role, "ドラフト候補用", MASTER, seed=seed) for seed in seeds]


def letter(player: dict, group: str) -> str:
    return str((player["abilities"].get("ranked_specials") or {}).get(group, "D"))[-1]


def rank_score(player: dict, group: str) -> int:
    return app.FICTIONAL_ABILITY_RANK_SCORES.get(letter(player, group), 0)


def value(player: dict, name: str) -> float:
    return float(app.ability_numeric_value(player["abilities"], name) or 0)


def test_weights_have_no_a_or_g_and_draft_players_never_get_them():
    # 実在のプロ1年目に A・G はいないので重みは 0（傾きは A・G を増やさない）
    for role, groups in app.DRAFT_RANKED_WEIGHTS.items():
        for group, weights in groups.items():
            assert list(weights) == list(app.RANKED_SPECIAL_RANKS), (role, group)
            assert weights["A"] == 0 and weights["G"] == 0, (role, group)
            assert weights["D"] > 0
    for role in ("投手", "野手"):
        for player in draft(role):
            for group in app.DRAFT_RANKED_WEIGHTS[role]:
                if group in player["abilities"]["ranked_specials"]:
                    assert letter(player, group) not in ("A", "G"), (role, player["seed"], group)


def test_tilt_uses_the_draft_statistics_of_the_table():
    # 傾きの平均・SD は、付け替えの表（区分「ドラフト候補用」）の平均・SD（ドラフト候補の生成の値）と同じ
    stats = table()["平均・SD"]
    for role, segments in app.DRAFT_ABILITY_RANK_STATS.items():
        for segment, items in segments.items():
            for name, (mean, sd) in items.items():
                assert abs(stats[role][segment][name][0] - mean) < 0.006, (role, segment, name)
                assert abs(stats[role][segment][name][1] - sd) < 0.006, (role, segment, name)
    assert set(app.DRAFT_ABILITY_RANK_STATS["野手"]) == set(stats["野手"])
    s = app.DRAFT_ABILITY_RANK_STATS["投手"]["先発"]
    tilt = app.draft_ability_rank_tilt("投手", "先発", {"コントロール": s["コントロール"][0] + s["コントロール"][1], "スタミナ": s["スタミナ"][0] + s["スタミナ"][1]})
    assert abs(tilt("回復") - 1.453) < 1e-9 and abs(tilt("打たれ強さ") - 0.776) < 1e-9
    assert tilt("ノビ") == 0.0
    s = app.DRAFT_ABILITY_RANK_STATS["投手"]["救援"]
    assert abs(app.draft_ability_rank_tilt("投手", "抑え", {"コントロール": s["コントロール"][0], "スタミナ": s["スタミナ"][0]})("回復")) < 1e-9
    # 野手はポジションごとの平均・SD。キャッチャーはメインが捕手の選手だけ傾く
    for position in ("捕手", "遊撃手"):
        s = app.DRAFT_ABILITY_RANK_STATS["野手"][position]
        mean = {name: s[name][0] for name in ("ミート", "守備力", "捕球")}
        assert abs(app.draft_ability_rank_tilt("野手", position, mean)("回復")) < 1e-9
        high = {name: s[name][0] + s[name][1] for name in ("ミート", "守備力", "捕球")}
        tilt = app.draft_ability_rank_tilt("野手", position, high)
        assert abs(tilt("回復") - 1.372) < 1e-9 and abs(tilt("送球") - 0.768) < 1e-9
        assert (tilt("キャッチャー") > 0) == (position == "捕手")


def test_able_draft_players_get_better_ranks():
    # 回復・打たれ強さ（投手）、回復・送球・キャッチャー（野手）は能力の高い選手ほど良いランク（判定は日本人の実在±0.15）
    stats = app.DRAFT_ABILITY_RANK_STATS
    for position_group, group, threshold in ((("先発",), "回復", 0.45), (("先発",), "打たれ強さ", 0.2), (("中継ぎ", "抑え"), "回復", 0.25)):
        pitchers = [p for p in draft("投手") if p["position"] in position_group]
        segment = "先発" if position_group == ("先発",) else "救援"
        quality = [sum((value(p, n) - stats["投手"][segment][n][0]) / stats["投手"][segment][n][1] for n in ("コントロール", "スタミナ")) for p in pitchers]
        assert statistics.correlation(quality, [rank_score(p, group) for p in pitchers]) > threshold, (position_group, group)
    fielders = draft("野手", range(1, 801))

    def quality(p: dict, names: tuple[str, ...]) -> float:
        s = stats["野手"][p["position"]]
        return sum((value(p, n) - s[n][0]) / s[n][1] for n in names)

    for group, names, threshold in (("回復", ("ミート", "守備力", "捕球"), 0.35), ("送球", ("捕球", "守備力"), 0.35)):
        assert statistics.correlation([quality(p, names) for p in fielders], [rank_score(p, group) for p in fielders]) > threshold, group
    catchers = [p for p in fielders if p["position"] == "捕手"]
    assert statistics.correlation([quality(p, ("捕球", "守備力")) for p in catchers], [rank_score(p, "キャッチャー") for p in catchers]) > 0.5


def test_catcher_rank_only_for_players_who_can_catch():
    for player in draft("野手"):
        can_catch = app.has_position_aptitude(player["position"], player["sub_positions"], {"捕手"})
        assert ("キャッチャー" in player["abilities"]["ranked_specials"]) == can_catch, player["seed"]
    # 投手の送球（表にないランク特能）は共通の処理のまま残る
    assert all("送球" in p["abilities"]["ranked_specials"] for p in draft("投手", range(1, 51)))


def test_players_matching_the_abilities_hold_the_specials():
    # 持つ選手の合成値 z は持たない選手より高い（判定は日本人の実在±0.4）
    t = table()

    def z_of(player: dict, role: str, name: str) -> float:
        segment = ("先発" if player["position"] == "先発" else "救援") if role == "投手" else player["position"]
        values = app.fictional_ability_link_values(role, player["abilities"], player.get("breaking_balls") or [])
        s = t["平均・SD"][role][segment]
        weights = t["特能"][role][name]["w"]
        return sum(w * (values[k] - s[k][0]) / s[k][1] for k, w in weights.items()) / math.sqrt(sum(w * w for w in weights.values()))

    def gap(players: list[dict], role: str, name: str) -> float:
        held = [z_of(p, role, name) for p in players if name in p["special_abilities"]]
        other = [z_of(p, role, name) for p in players if name not in p["special_abilities"]]
        return statistics.fmean(held) - statistics.fmean(other)

    pitchers = draft("投手", range(1, 1201))
    for name in ("緩急○", "テンポ○", "変化球中心", "奪三振"):
        assert gap(pitchers, "投手", name) > 0.4, name
    fielders = draft("野手", range(1, 1201))
    for name in ("三振", "ミート多用", "強振多用", "積極守備"):
        assert gap(fielders, "野手", name) > 0.5, name


def test_table_covers_the_common_draft_specials():
    # 対象は保有率3%以上の特能（投手12・野手9）。重みは日本人の表と同じ。矛盾の付け替えは使わない
    # （投手の特能と球速_改修指示.md で日本人の投手の6特能の重みに球速を足したが、ドラフト候補用は変えていない。
    # その6特能のうちドラフト候補用にあるキレ○・逃げ球・負け運は改修前の日本人の重みのまま）
    t, jp = table(), app.load_fictional_ability_special_link()[app.FICTIONAL_ABILITY_SPECIAL_LINK_PART]
    assert len(t["特能"]["投手"]) == 12 and len(t["特能"]["野手"]) == 9
    kept = {"キレ○": {"コントロール": 0.46, "スタミナ": 0.64, "総変化量": 1.19}, "逃げ球": {"コントロール": 0.52, "スタミナ": 0.59, "総変化量": 0.82},
            "負け運": {"コントロール": 0.97, "スタミナ": 0.85, "総変化量": 0.77}}
    for role in ("投手", "野手"):
        for name, entry in t["特能"][role].items():
            expected = kept[name] if role == "投手" and name in kept else jp["特能"][role][name]["w"]
            assert entry["w"] == expected, (role, name)
    assert t["除く割合"] == jp["除く割合"] and t["矛盾の付け替え"] is False
    strikeout = t["特能"]["投手"]["奪三振"]
    assert strikeout["w"] == {"総変化量": 1.0} and all(seg["rho"] == 0.0 for seg in strikeout["区分"].values())
    assert strikeout["p帯"]["上限"] == [147, 151, 155]


def test_random_draws_once_per_group_and_special(monkeypatch):
    # ランク特能は draft_rank_v1 からランク特能ごとに必ず1回、特能は draft_ability_special_link_v1 から表の特能ごとに必ず1回
    original = app.make_sub_rng
    counts: dict[str, list[int]] = {}

    class Counting:
        def __init__(self, rng):
            self.rng, self.n = rng, 0

        def random(self):
            self.n += 1
            return self.rng.random()

        def choices(self, *args, **kwargs):
            self.n += 1
            return self.rng.choices(*args, **kwargs)

    def fake(seed, namespace):
        rng = original(seed, namespace)
        if namespace in (app.DRAFT_RANK_NAMESPACE, app.DRAFT_ABILITY_SPECIAL_LINK_NAMESPACE):
            wrapped = Counting(rng)
            counts.setdefault(namespace, []).append(wrapped)
            return wrapped
        return rng

    monkeypatch.setattr(app, "make_sub_rng", fake)
    assert app.DRAFT_RANK_NAMESPACE == "draft_rank_v1" and app.DRAFT_ABILITY_SPECIAL_LINK_NAMESPACE == "draft_ability_special_link_v1"
    for role in ("投手", "野手"):
        counts.clear()
        draft(role, range(1, 41))
        assert {rng.n for rng in counts[app.DRAFT_RANK_NAMESPACE]} == {len(app.DRAFT_RANKED_WEIGHTS[role])}, role
        assert {rng.n for rng in counts[app.DRAFT_ABILITY_SPECIAL_LINK_NAMESPACE]} == {len(table()["特能"][role])}, role


def without(player: dict, keys: tuple[str, ...]) -> dict:
    out = {key: v for key, v in player.items() if key not in keys}
    out["abilities"] = {key: v for key, v in player["abilities"].items() if key != "ranked_specials"}
    return out


def test_only_specials_and_ranks_change_for_draft_players(monkeypatch):
    # 引き直し・付け替えは特能とランク特能だけを変える（名前・年齢・ポジション・投打・能力・弾道・変化球・身長・体重は同じ）
    current = {role: draft(role, range(1, 201)) for role in ("投手", "野手")}
    tables = app.load_fictional_ability_special_link()
    monkeypatch.setattr(app, "FICTIONAL_ABILITY_SPECIAL_LINK_OVERRIDE", {k: v for k, v in tables.items() if k != PART})
    monkeypatch.setattr(app, "DRAFT_RANK_REDRAW", False)
    for role in ("投手", "野手"):
        changed_specials = changed_ranks = 0
        for a, b in zip(current[role], draft(role, range(1, 201))):
            assert without(a, ("special_abilities",)) == without(b, ("special_abilities",)), (role, a["seed"])
            changed_specials += a["special_abilities"] != b["special_abilities"]
            changed_ranks += a["abilities"]["ranked_specials"] != b["abilities"]["ranked_specials"]
        assert changed_specials > 20 and changed_ranks > 150, role


def test_other_categories_do_not_use_the_draft_steps(monkeypatch):
    # 区分「ドラフト候補用」を外し、引き直しを止めても、架空球団用・助っ人外国人用は同じ
    def others() -> dict:
        return {(role, category): [app.generate_player(role, category, MASTER, seed=s) for s in range(1, 121)]
                for role in ("投手", "野手") for category in ("架空球団用", "助っ人外国人用")}

    current = others()
    tables = app.load_fictional_ability_special_link()
    monkeypatch.setattr(app, "FICTIONAL_ABILITY_SPECIAL_LINK_OVERRIDE", {k: v for k, v in tables.items() if k != PART})
    monkeypatch.setattr(app, "DRAFT_RANK_REDRAW", False)
    assert others() == current


def test_japanese_strikeout_left_bands():
    # 日本人の奪三振の左投の帯（〜147／〜151／〜155／156〜）は、球速152以上を上げた。右投・ほかの帯は変えない
    rates = app.FICTIONAL_LINKED_HAND_RATES["投手"]["奪三振"]
    assert rates["左|先発"] == [0.09, 0.15, 0.60, 0.75]
    assert rates["左|救援"] == [0.20, 0.40, 0.76, 0.85]
    assert rates["右|先発"] == [0.045, 0.07, 0.15, 0.62] and rates["右|救援"] == [0.07, 0.21, 0.28, 0.61]
    # 付け替えの p帯 は、左投を上げた後の付け替え前の帯の保有率（球速152〜155 が上がった）
    band = app.load_fictional_ability_special_link()[app.FICTIONAL_ABILITY_SPECIAL_LINK_PART]["特能"]["投手"]["奪三振"]["p帯"]["p"]
    assert band["先発"] == [0.0616, 0.1052, 0.2177, 0.5653]
    assert band["救援"] == [0.1459, 0.276, 0.3664, 0.586]
