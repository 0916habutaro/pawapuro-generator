"""架空球団用の日本人の、能力による特能の付け替え（`能力と特能の結びつき_改修指示.md`）。

b・gain は球団生成で合わせており、正式な判定は scripts/check_special_profile.py（球団生成300球団。共通部分は
scripts/special_ability_link.py）。ここでは、倍率が表の式どおりであること、能力に合った選手が特能を持ちやすいこと、
特能数の上下限を守ること、乱数を引く回数が変わらないこと、ほかの区分が変わらないことを確かめる。
"""
from __future__ import annotations

import math
import statistics

import app

MASTER = app.load_master_data()
SEEDS = range(1, 401)
PART = app.FICTIONAL_ABILITY_SPECIAL_LINK_PART


def table() -> dict:
    return app.load_fictional_ability_special_link()[PART]


def players(role: str = "野手", category: str = "架空球団用") -> list[dict]:
    return [app.generate_player(role, category, MASTER, seed=seed) for seed in SEEDS]


def domestic(role: str) -> list[dict]:
    return [player for player in players(role) if player["roster_origin"] == "domestic"]


def without_specials(player: dict) -> dict:
    return {key: value for key, value in player.items() if key != "special_abilities"}


def no_link(monkeypatch) -> None:
    monkeypatch.setattr(app, "FICTIONAL_ABILITY_SPECIAL_LINK_OVERRIDE", {})


def z_of(player: dict, role: str, name: str) -> float:
    """標準化した能力の合成値 z（全体の強さを除く前）。"""
    t = table()
    segment = ("先発" if player["position"] == "先発" else "救援") if role == "投手" else player["position"]
    values = app.fictional_ability_link_values(role, player["abilities"], player.get("breaking_balls") or [])
    stats = t["平均・SD"][role][segment]
    weights = t["特能"][role][name]["w"]
    return sum(w * (values[k] - stats[k][0]) / stats[k][1] for k, w in weights.items()) / math.sqrt(sum(w * w for w in weights.values()))


def test_rates_follow_the_formula():
    t = table()
    values = {"弾道": 2, "ミート": 50, "パワー": 55, "走力": 80, "肩力": 85, "守備力": 60, "捕球": 50}
    rates = app.fictional_ability_link_rates(t, "野手", "外野手", values)
    stats = t["平均・SD"]["野手"]["外野手"]
    std = {k: (values[k] - m) / s for k, (m, s) in stats.items()}
    entry, part = t["特能"]["野手"]["レーザービーム"], t["特能"]["野手"]["レーザービーム"]["区分"]["外野手"]
    z = (0.63 * std["走力"] + 1.54 * std["肩力"]) / math.sqrt(0.63 ** 2 + 1.54 ** 2)
    q = statistics.fmean(std[k] for k in t["総合"]["野手"])
    c = t["除く割合"]["野手"] * part["rho"]
    expected = math.exp(entry["b"] * (z - c * q * part["zsd"] / part["qsd"]) / math.sqrt(1 - c * c)) / part["M"]
    assert abs(rates["レーザービーム"] - expected) < 1e-12
    assert rates["レーザービーム"] > 1  # 肩の強い外野手は持ちやすい
    weak = app.fictional_ability_link_rates(t, "野手", "外野手", {**values, "肩力": 50, "走力": 60})
    assert weak["レーザービーム"] < 1
    # 強振多用はパワー・弾道の高い選手、ミート多用は非力な選手
    slugger = app.fictional_ability_link_rates(t, "野手", "一塁手", {**values, "弾道": 4, "パワー": 80})
    assert slugger["強振多用"] > rates["強振多用"] and slugger["ミート多用"] < rates["ミート多用"]
    # 区分の表がないとき（メインのポジションが分からない）は付け替えない
    assert app.fictional_ability_link_rates(t, "野手", "指名打者", values) == {}
    pitcher = {"球速": 145, "コントロール": 70, "スタミナ": 60, "変化球数": 3, "総変化量": 9}
    rates = app.fictional_ability_link_rates(t, "投手", "先発", pitcher)
    assert rates["変化球中心"] > 1 and rates["速球中心"] < 1
    assert set(rates) == set(t["特能"]["投手"])


def test_table_matches_the_real_standardization():
    # 標準化の平均・SD は実在から作った値（scripts/special_ability_link.py --build-real）と同じ
    import json

    real = json.loads((app.DATA_DIR / "config" / "special_ability_link_real.json").read_text(encoding="utf-8"))["平均・SD"]
    for role, segments in table()["平均・SD"].items():
        for segment, items in segments.items():
            for name, (mean, sd) in items.items():
                assert abs(real[role][segment][name][0] - mean) < 1e-3, (role, segment, name)
                assert abs(real[role][segment][name][1] - sd) < 1e-3, (role, segment, name)


def test_players_matching_the_abilities_hold_the_specials():
    # 個別生成でも、持つ選手の合成値 z は持たない選手より高い（球団生成の判定は実在±0.4）
    def gap(group: list[dict], role: str, name: str) -> float:
        held = [z_of(p, role, name) for p in group if name in p["special_abilities"]]
        other = [z_of(p, role, name) for p in group if name not in p["special_abilities"]]
        return statistics.fmean(held) - statistics.fmean(other)

    pitchers = domestic("投手")
    for name in ("キレ○", "変化球中心", "速球中心"):
        assert gap(pitchers, "投手", name) > 0.6, name
    fielders = domestic("野手")
    for name in ("強振多用", "ミート多用", "三振", "決勝打"):
        assert gap(fielders, "野手", name) > 0.4, name


def test_count_bounds_are_kept(monkeypatch):
    names = list(table()["特能"]["野手"])
    player = {"role": "野手", "position": "外野手", "player_class": "スター級", "breaking_balls": []}
    abilities = {key: app.ability(50) for key in app.FICTIONAL_FIELDER_ABILITY_KEYS}
    abilities["弾道"] = 2
    allowed = lambda name: True  # noqa: E731
    countable = lambda names: sum(app.is_countable_special(name) for name in names)  # noqa: E731  緑特（起用法扱い）は数えない
    low, high = app.special_count_bounds("架空球団用", "スター級")
    # すべての特能を外す倍率（r → 0）でも、下限より少なくしない
    forced = {PART: {**table(), "特能": {"野手": {n: {**e, "b": 0.0, "区分": {s: {**v, "M": 1e9} for s, v in e["区分"].items()}}
                                                for n, e in table()["特能"]["野手"].items()}}}}
    monkeypatch.setattr(app, "FICTIONAL_ABILITY_SPECIAL_LINK_OVERRIDE", forced)
    held = [name for name in names if app.is_countable_special(name)][: low + 2]
    result = app.fictional_ability_special_link(1, MASTER, player, list(held), allowed, abilities)
    assert countable(result) == low
    # すべての特能を付ける倍率（r → ∞）でも、上限より多くしない
    forced = {PART: {**table(), "特能": {"野手": {n: {**e, "b": 0.0, "区分": {s: {**v, "M": 1e-9, "p": 0.5} for s, v in e["区分"].items()}}
                                                for n, e in table()["特能"]["野手"].items()}}}}
    monkeypatch.setattr(app, "FICTIONAL_ABILITY_SPECIAL_LINK_OVERRIDE", forced)
    result = app.fictional_ability_special_link(1, MASTER, player, [], allowed, abilities)
    assert countable(result) == high


def test_random_draws_do_not_depend_on_the_player(monkeypatch):
    # 表の特能ごとに必ず1回ずつ引く（倍率・持っているかによらない）
    counts = []

    class Counting:
        def __init__(self):
            self.n = 0

        def random(self):
            self.n += 1
            return 0.5

    def fake(seed, namespace):
        rng = Counting()
        counts.append((namespace, rng))
        return rng

    monkeypatch.setattr(app, "make_sub_rng", fake)
    abilities = {key: app.ability(value) for key, value in zip(app.FICTIONAL_FIELDER_ABILITY_KEYS, (90, 90, 30, 30, 90, 90))}
    abilities["弾道"] = 4
    for position, specials in (("外野手", []), ("捕手", ["レーザービーム", "三振"]), ("指名打者", [])):
        player = {"role": "野手", "position": position, "player_class": "一軍控え級", "breaking_balls": []}
        app.fictional_ability_special_link(1, MASTER, player, specials, lambda name: True, abilities)
    assert [ns for ns, _ in counts] == [app.FICTIONAL_ABILITY_SPECIAL_LINK_NAMESPACE] * 3
    assert {rng.n for _, rng in counts} == {len(table()["特能"]["野手"])}


def test_link_does_not_change_the_random_stream(monkeypatch):
    # 付け替えは自分の副乱数だけを使うので、特能以外（能力・ランク特能・変化球・身長・体重など）は同じ
    current = {role: domestic(role) for role in ("投手", "野手")}
    no_link(monkeypatch)
    for role in ("投手", "野手"):
        changed = 0
        for a, b in zip(current[role], domestic(role)):
            assert without_specials(a) == without_specials(b), (role, a["seed"])
            changed += a["special_abilities"] != b["special_abilities"]
        assert changed > 0, role


def test_other_categories_do_not_use_the_link(monkeypatch):
    # ドラフト候補用・助っ人外国人用は自分の区分（ドラフト候補用・助っ人外国人用）だけを使い、日本人の区分を外しても同じ
    # （外国人の付け替えは tests/test_foreign_ability_link.py、ドラフト候補は tests/test_draft_ability_link.py）
    cases = [("投手", "ドラフト候補用"), ("野手", "ドラフト候補用"), ("投手", "助っ人外国人用"), ("野手", "助っ人外国人用")]
    current = {case: players(*case) for case in cases}
    foreign = {role: [p for p in players(role) if p["roster_origin"] != "domestic"] for role in ("投手", "野手")}
    tables = app.load_fictional_ability_special_link()
    monkeypatch.setattr(app, "FICTIONAL_ABILITY_SPECIAL_LINK_OVERRIDE", {k: v for k, v in tables.items() if k != PART})
    for case in cases:
        assert players(*case) == current[case], case
    for role in ("投手", "野手"):
        assert [p for p in players(role) if p["roster_origin"] != "domestic"] == foreign[role], role
