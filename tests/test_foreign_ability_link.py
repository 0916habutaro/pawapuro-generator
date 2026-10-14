"""助っ人外国人用の、能力とランク特能・特能の結びつきと、日本人の奪三振の付け替え（`能力との結びつき_外国人_改修指示.md`）。

重み・κ・b・gain は球団生成で合わせており、正式な判定は scripts/check_foreign_balance.py（球団生成300球団の外国人。共通部分は
scripts/rank_ability.py・scripts/special_ability_link.py）と check_special_profile.py（日本人の奪三振）。ここでは、能力に合った選手が
良いランク・特能を持ちやすいこと、A・G が少ないこと、奪三振の帯の保有率を p に使うこと、矛盾の付け替え、乱数を引く回数、
ほかの区分・ほかの項目が変わらないことを確かめる。
"""
from __future__ import annotations

import math
import statistics

import app

MASTER = app.load_master_data()
SEEDS = range(1, 401)
PART = app.FOREIGN_ABILITY_SPECIAL_LINK_PART


def table() -> dict:
    return app.load_fictional_ability_special_link()[PART]


def foreign(role: str) -> list[dict]:
    return [app.generate_player(role, "助っ人外国人用", MASTER, seed=seed) for seed in SEEDS]


def rank_score(player: dict, group: str) -> int:
    letter = str((player["abilities"].get("ranked_specials") or {}).get(group, "D"))[-1]
    return app.FICTIONAL_ABILITY_RANK_SCORES.get(letter, 0)


def correlation(xs: list[float], ys: list[float]) -> float:
    return statistics.correlation(xs, ys)


def test_foreign_tilts_use_the_foreign_real_statistics():
    # 傾きは外国人の実在（rank_ability_real.json の「外国人」）の平均・SDで標準化する
    import json

    real = json.loads((app.DATA_DIR / "config" / "rank_ability_real.json").read_text(encoding="utf-8"))["外国人"]["平均・SD"]
    for key, items in real.items():
        for name, (mean, sd) in items.items():
            assert abs(app.FICTIONAL_ABILITY_RANK_STATS[key][name][0] - mean) < 0.01, (key, name)
            assert abs(app.FICTIONAL_ABILITY_RANK_STATS[key][name][1] - sd) < 0.01, (key, name)
    tilt = app.fictional_ability_rank_tilt("投手", "先発", {"コントロール": 55.05 + 8.54, "スタミナ": 59.81 + 6.51}, app.FOREIGN_ABILITY_RANK_TILTS)
    assert abs(tilt("回復") - 1.656) < 0.01 and abs(tilt("打たれ強さ") - 1.029) < 0.01
    assert tilt("ノビ") == 0.0
    tilt = app.fictional_ability_rank_tilt("投手", "抑え", {"コントロール": 45.02, "スタミナ": 46.23}, app.FOREIGN_ABILITY_RANK_TILTS)
    assert abs(tilt("回復")) < 0.01  # 救援の平均の投手は傾かない
    # 日本人の表は変わらない（既定は FICTIONAL_ABILITY_RANK_TILTS）
    jp = app.fictional_ability_rank_tilt("野手", "捕手", {"ミート": 40, "守備力": 60, "捕球": 60})
    assert jp("キャッチャー") > 0
    fr = app.fictional_ability_rank_tilt("野手", "捕手", {"ミート": 40, "守備力": 60, "捕球": 60}, app.FOREIGN_ABILITY_RANK_TILTS)
    assert fr("キャッチャー") == 0.0 and fr("送球") > 0


def test_able_foreigners_get_better_ranks():
    # 回復・打たれ強さ（投手）、回復・送球（野手）は、能力の高い選手ほど良いランク（球団生成の判定は目標±0.15）
    pitchers = [p for p in foreign("投手") if p["position"] == "先発"]
    quality = [app.ability_numeric_value(p["abilities"], "コントロール") / 8.54 + app.ability_numeric_value(p["abilities"], "スタミナ") / 6.51 for p in pitchers]
    assert correlation(quality, [rank_score(p, "回復") for p in pitchers]) > 0.3
    fielders = foreign("野手")
    quality = [(app.ability_numeric_value(p["abilities"], "捕球") or 0) / 8.79 + (app.ability_numeric_value(p["abilities"], "守備力") or 0) / 9.17 for p in fielders]
    assert correlation(quality, [rank_score(p, "送球") for p in fielders]) > 0.3


def test_a_and_g_are_rare():
    # 実在の外国人に A・G はほとんどいない（判定は各1.5%以下。個別生成400人ずつでは2.5%まで見る）
    for role in ("投手", "野手"):
        players = foreign(role)
        groups = {group for p in players for group in p["abilities"].get("ranked_specials") or {}}
        for group in groups:
            letters = [str((p["abilities"].get("ranked_specials") or {}).get(group, "D"))[-1] for p in players]
            for letter in ("A", "G"):
                assert letters.count(letter) / len(letters) <= 0.025, (role, group, letter)


def test_players_matching_the_abilities_hold_the_specials():
    # 個別生成でも、持つ選手の合成値 z は持たない選手より高い（球団生成の判定は目標±0.4）
    t = table()

    def z_of(player: dict, role: str, name: str) -> float:
        segment = ("先発" if player["position"] == "先発" else "救援") if role == "投手" else player["position"]
        values = app.fictional_ability_link_values(role, player["abilities"], player.get("breaking_balls") or [])
        stats = t["平均・SD"][role][segment]
        weights = t["特能"][role][name]["w"]
        return sum(w * (values[k] - stats[k][0]) / stats[k][1] for k, w in weights.items()) / math.sqrt(sum(w * w for w in weights.values()))

    def gap(players: list[dict], role: str, name: str) -> float:
        held = [z_of(p, role, name) for p in players if name in p["special_abilities"]]
        other = [z_of(p, role, name) for p in players if name not in p["special_abilities"]]
        return statistics.fmean(held) - statistics.fmean(other)

    pitchers = foreign("投手")
    for name in ("キレ○", "逃げ球", "ゴロピッチャー"):
        assert gap(pitchers, "投手", name) > 0.4, name
    fielders = foreign("野手")
    for name in ("強振多用", "決勝打", "併殺", "プルヒッター"):
        assert gap(fielders, "野手", name) > 0.6, name


def test_strikeout_uses_the_band_rate():
    # 奪三振は、付けるときの p に球速の帯ごとの保有率を使い、全体の強さを除かない（指示書 1-5）
    for part, limits in ((app.FICTIONAL_ABILITY_SPECIAL_LINK_PART, [147, 151, 155]), (PART, [151, 155, 159])):
        entry = app.load_fictional_ability_special_link()[part]["特能"]["投手"]["奪三振"]
        assert entry["w"] == {"総変化量": 1.0}
        assert all(seg["rho"] == 0.0 for seg in entry["区分"].values())
        band = entry["p帯"]
        assert band["能力"] == "球速" and band["上限"] == limits
        for segment in ("先発", "救援"):
            rates = band["p"][segment]
            assert rates[-1] > rates[0]  # 速い帯ほど持ちやすい
            for index, speed in enumerate((limits[0], limits[1], limits[2], limits[2] + 1)):
                assert app.fictional_ability_link_p(entry, segment, {"球速": speed}) == rates[index]
    # p帯 のない特能は区分の p
    entry = table()["特能"]["投手"]["キレ○"]
    assert app.fictional_ability_link_p(entry, "先発", {"球速": 160}) == entry["区分"]["先発"]["p"]


def test_conflicting_special_is_swapped_only_when_it_fits_less(monkeypatch):
    # 付けたい特能と矛盾する特能は、その特能も表にあって r が付けたい特能の r より小さければ外して付け替える
    # （指示書 1-4 で r が1未満のときだけだったのを、`能力との結びつき_ドラフト_改修指示.md` 1-4 で広げた。助っ人外国人用だけ）
    abilities = {key: app.ability(value) for key, value in zip(app.FICTIONAL_FIELDER_ABILITY_KEYS, (60, 75, 40, 60, 45, 45))}
    abilities["弾道"] = 4
    player = {"role": "野手", "position": "一塁手", "player_class": "レギュラー競争級", "breaking_balls": []}
    allowed = lambda name: True  # noqa: E731
    base = table()
    entries = dict(base["特能"]["野手"])

    def forced(pull_b: float, wide_b: float = 50.0, with_pull: bool = True) -> dict:
        # 広角打法は必ず付けたい（r>1・gain 100・p 0.5）、プルヒッターは b で r を決める（M 1）
        wide = {**entries["広角打法"], "b": wide_b, "gain": 100.0, "区分": {s: {**v, "M": 1.0, "p": 0.5, "rho": 0.0} for s, v in entries["広角打法"]["区分"].items()}}
        pull = {**entries["プルヒッター"], "b": pull_b, "区分": {s: {**v, "M": 1.0, "rho": 0.0} for s, v in entries["プルヒッター"]["区分"].items()}}
        return {PART: {**base, "特能": {"野手": {"広角打法": wide, **({"プルヒッター": pull} if with_pull else {})}}}}

    def run() -> list[str]:
        return app.fictional_ability_special_link(
            1, MASTER, player, ["プルヒッター"], allowed, abilities, part=PART, category="助っ人外国人用",
            namespace=app.FOREIGN_ABILITY_SPECIAL_LINK_NAMESPACE, conflicts=app.FOREIGN_FIELDER_SPECIAL_CONFLICTS)

    class Low:
        def random(self):
            return 0.999999  # プルヒッターは外さない（1 − r より大きい）が、広角打法は付ける（chance は1）

    monkeypatch.setattr(app, "make_sub_rng", lambda seed, namespace: Low())
    monkeypatch.setattr(app, "FICTIONAL_ABILITY_SPECIAL_LINK_OVERRIDE", forced(-5.0))  # プルヒッターは能力に合っていない（r<1）
    assert sorted(run()) == ["広角打法"]
    monkeypatch.setattr(app, "FICTIONAL_ABILITY_SPECIAL_LINK_OVERRIDE", forced(5.0))  # 合っている（r>1）が、広角打法の r のほうが大きい
    assert sorted(run()) == ["広角打法"]
    monkeypatch.setattr(app, "FICTIONAL_ABILITY_SPECIAL_LINK_OVERRIDE", forced(50.0, wide_b=2.0))  # プルヒッターの r のほうが大きい
    assert run() == ["プルヒッター"]
    monkeypatch.setattr(app, "FICTIONAL_ABILITY_SPECIAL_LINK_OVERRIDE", forced(0.0, with_pull=False))  # 相手が表にないなら付け替えない
    assert run() == ["プルヒッター"]
    # 「矛盾の付け替え」は助っ人外国人用だけ（架空球団用の日本人・ドラフト候補用は false）
    tables = app.load_fictional_ability_special_link()
    assert {part: table_.get("矛盾の付け替え") for part, table_ in tables.items()} == {
        app.FICTIONAL_ABILITY_SPECIAL_LINK_PART: False, PART: True, app.DRAFT_ABILITY_SPECIAL_LINK_PART: False}


def test_foreign_link_draws_once_per_special(monkeypatch):
    # 新しい名前空間の副乱数から、表の特能ごとに必ず1回ずつ引く
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
    for position, specials in (("外野手", []), ("捕手", ["三振", "広角打法"]), ("指名打者", [])):
        player = {"role": "野手", "position": position, "player_class": "大物実績者", "breaking_balls": []}
        app.fictional_ability_special_link(1, MASTER, player, specials, lambda name: True, abilities, part=PART, category="助っ人外国人用",
                                           namespace=app.FOREIGN_ABILITY_SPECIAL_LINK_NAMESPACE, conflicts=app.FOREIGN_FIELDER_SPECIAL_CONFLICTS)
    assert app.FOREIGN_ABILITY_SPECIAL_LINK_NAMESPACE == "foreign_ability_special_link_v1"
    assert [ns for ns, _ in counts] == [app.FOREIGN_ABILITY_SPECIAL_LINK_NAMESPACE] * 3
    assert {rng.n for _, rng in counts} == {len(table()["特能"]["野手"])}


def test_foreign_count_bounds_use_the_foreign_category(monkeypatch):
    # 特能数の上下限は助っ人外国人用（大物実績者 2〜11、ほか 0〜7）
    names = [name for name in table()["特能"]["野手"] if app.is_countable_special(name)]
    player = {"role": "野手", "position": "外野手", "player_class": "レギュラー競争級", "breaking_balls": []}
    abilities = {key: app.ability(50) for key in app.FICTIONAL_FIELDER_ABILITY_KEYS}
    abilities["弾道"] = 2
    forced = {PART: {**table(), "特能": {"野手": {n: {**e, "b": 0.0, "区分": {s: {**v, "M": 1e-9, "p": 0.5} for s, v in e["区分"].items()}}
                                                for n, e in table()["特能"]["野手"].items()}}}}
    monkeypatch.setattr(app, "FICTIONAL_ABILITY_SPECIAL_LINK_OVERRIDE", forced)
    result = app.fictional_ability_special_link(1, MASTER, player, [], lambda name: True, abilities, part=PART, category="助っ人外国人用",
                                                namespace=app.FOREIGN_ABILITY_SPECIAL_LINK_NAMESPACE, conflicts=app.FOREIGN_FIELDER_SPECIAL_CONFLICTS)
    assert sum(app.is_countable_special(name) for name in result) == app.special_count_bounds("助っ人外国人用", "レギュラー競争級")[1] == 7
    assert len(names) > 7


def without(player: dict, keys: tuple[str, ...]) -> dict:
    out = {key: value for key, value in player.items() if key not in keys}
    out["abilities"] = {key: value for key, value in player["abilities"].items() if key != "ranked_specials"}
    return out


def test_only_specials_and_ranks_change_for_foreigners(monkeypatch):
    # 外国人の付け替え・傾きは特能とランク特能だけを変える（名前・年齢・ポジション・投打・能力・弾道・変化球・身長・体重は同じ）
    current = {role: foreign(role) for role in ("投手", "野手")}
    tables = app.load_fictional_ability_special_link()
    monkeypatch.setattr(app, "FICTIONAL_ABILITY_SPECIAL_LINK_OVERRIDE", {k: v for k, v in tables.items() if k != PART})
    monkeypatch.setattr(app, "FOREIGN_ABILITY_RANK_TILTS", {})
    for role in ("投手", "野手"):
        changed = 0
        for a, b in zip(current[role], foreign(role)):
            assert without(a, ("special_abilities",)) == without(b, ("special_abilities",)), (role, a["seed"])
            changed += a["special_abilities"] != b["special_abilities"]
        assert changed > 0, role


def test_japanese_and_draft_do_not_use_the_foreign_table(monkeypatch):
    # 区分「助っ人外国人用」と外国人の傾きを外しても、日本人（国内）とドラフト候補は同じ
    def domestic_and_draft() -> dict:
        out = {}
        for role in ("投手", "野手"):
            out[(role, "架空球団用")] = [p for p in (app.generate_player(role, "架空球団用", MASTER, seed=s) for s in range(1, 151))
                                       if p["roster_origin"] == "domestic"]
            out[(role, "ドラフト候補用")] = [app.generate_player(role, "ドラフト候補用", MASTER, seed=s) for s in range(1, 151)]
        return out

    current = domestic_and_draft()
    tables = app.load_fictional_ability_special_link()
    monkeypatch.setattr(app, "FICTIONAL_ABILITY_SPECIAL_LINK_OVERRIDE", {k: v for k, v in tables.items() if k != PART})
    monkeypatch.setattr(app, "FOREIGN_ABILITY_RANK_TILTS", {})
    assert domestic_and_draft() == current
