"""外国人の残り（投手の特能・ランク特能、野手の走力・年齢・打撃の幅）の改修（外国人の残り_改修指示.md）を確かめる。

分布の合否は scripts/check_foreign_balance.py の「実在（2024〜2026年版）」の節（個別生成5000人・球団生成300球団）で見る。
ここでは少ない人数で、向きと仕組み（対ランナー×が出る・対ランナーと同時に付かない・日本人とドラフト候補は変わらない）を確かめる。
"""
from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path

import app

MASTER = app.load_master_data()
PITCHERS = [app.generate_player("投手", "助っ人外国人用", MASTER, seed=seed) for seed in range(1, 601)]
FIELDERS = [app.generate_player("野手", "助っ人外国人用", MASTER, seed=seed) for seed in range(1, 601)]


def rate(players: list[dict], name: str) -> float:
    return sum(name in p["special_abilities"] for p in players) / len(players)


def value(player: dict, key: str) -> int:
    return app.ability_numeric_value(player["abilities"], key) or 0


def test_foreign_pitchers_get_red_runner_special_but_never_with_blue():
    # 実在（2024〜2026年版）は対ランナー× 13.9%、対ランナー 4.9%
    assert 0.08 <= rate(PITCHERS, "対ランナー×") <= 0.22
    assert rate(PITCHERS, "対ランナー") <= 0.10
    assert ("対ランナー", "対ランナー×") in app.FOREIGN_PITCHER_SPECIAL_CONFLICTS
    for player in PITCHERS:
        assert not {"対ランナー", "対ランナー×"} <= set(player["special_abilities"])


def test_foreign_pitcher_red_specials_follow_real():
    # 実在: 抜け球 26.2%、逃げ球 36.1%、ナチュラルシュート 9.8%
    assert 0.17 <= rate(PITCHERS, "抜け球") <= 0.35
    assert 0.27 <= rate(PITCHERS, "逃げ球") <= 0.45
    assert 0.04 <= rate(PITCHERS, "ナチュラルシュート") <= 0.16
    relievers = [p for p in PITCHERS if app.has_pitcher_aptitude({k: p.get(k) for k in app.PITCHER_APTITUDE_KEYS}, {"reliever_aptitude", "closer_aptitude"})]
    assert rate(relievers, "回またぎ○") >= 0.12


def test_foreign_pitcher_ranked_specials_have_few_a_b():
    # 実在（2024〜2026年版）は 対ピンチ A・B 0%、打たれ強さ A・B 4.1%、対左打者 A・B 2.5%
    def good(group: str) -> float:
        return sum(p["abilities"]["ranked_specials"].get(group, "D")[-1] in "AB" for p in PITCHERS) / len(PITCHERS)

    assert good("対ピンチ") <= 0.05
    assert good("打たれ強さ") <= 0.09
    assert good("対左打者") <= 0.08
    assert good("ノビ") <= 0.22


def test_foreign_fielders_are_faster_and_younger_with_wider_batting():
    outfield = [value(p, "走力") for p in FIELDERS if p["position"] == "外野手"]
    assert statistics.fmean(value(p, "走力") for p in FIELDERS) >= 56
    assert statistics.fmean(outfield) >= 62
    assert 28.3 <= statistics.fmean(p["age"] for p in FIELDERS) <= 30.0
    contact = [value(p, "ミート") for p in FIELDERS]
    power = [value(p, "パワー") for p in FIELDERS]
    assert statistics.stdev(contact) >= 9.3
    assert statistics.stdev(power) >= 8.8
    assert statistics.correlation(contact, power) >= 0.35


def test_foreign_fielder_age_weights_are_one_and_a_half_years_younger():
    weights = dict(app.FOREIGN_AGE_WEIGHTS["野手"])
    old = {19: 2, 20: 3, 21: 5, 22: 8, 23: 12, 24: 17, 25: 30, 26: 44, 27: 55, 28: 90, 29: 105, 30: 123,
           31: 110, 32: 110, 33: 98, 34: 58, 35: 43, 36: 31, 37: 22, 38: 15, 39: 9, 40: 5, 41: 3, 42: 2}
    for age in range(19, 42):
        assert weights[age] == (old.get(age + 1, 0) + old.get(age + 2, 0)) / 2

    def mean(items: dict[int, float]) -> float:
        return sum(age * weight for age, weight in items.items()) / sum(items.values())

    assert 1.3 <= mean(old) - mean(weights) <= 1.7


def fingerprint(player: dict) -> str:
    return hashlib.sha256(json.dumps(player, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


# 改修前（0619a5d）の app.py で作った、架空球団用の日本人・ドラフト候補用の指紋（各15人。架空球団用は外国人枠の seed を除く）。
# 外国人だけを変える改修なので、日本人とドラフト候補は1人も変わらない。
# 架空球団用の日本人野手は、野手のランク特能_改修指示.md（対左投手・キャッチャーの重み）でランク特能だけ変わった分を更新した。
# 野手の走力肩力ランク_改修指示.md（走塁・盗塁・送球と走力・肩力の結びつき）で走塁・盗塁・送球だけ変わった分も更新した。
# 野手のランク年齢傾き_改修指示.md（年齢でランクを傾ける補正）でランク特能だけ変わった分も更新した。
# 捕手の特能_改修指示.md（連動特能の保有率をポジションのまとまりで分けた）で特能だけ変わった分も更新した。
# ランク特能の形_改修指示.md（走塁・盗塁・ケガしにくさ・チャンス・対ピンチの重みをポジション・役割で分けた）で、架空球団用の日本人の
# 投手・野手のランク特能だけ変わった分も更新した。
# ランクの年齢の幅_改修指示.md（年齢でランクを傾ける補正の β・γ）で、架空球団用の日本人の投手・野手のランク特能だけ変わった分も更新した。
# 能力とランク特能の結びつき_改修指示.md（回復・打たれ強さ・送球・キャッチャーを能力で傾けた）で、架空球団用の日本人の投手・野手のランク特能だけ変わった分も更新した。
# 能力と特能の結びつき_改修指示.md（能力による特能の付け替え）で、架空球団用の日本人の投手・野手の特能だけ変わった分も更新した。
# 能力との結びつき_外国人_改修指示.md（日本人の奪三振の付け替えを総変化量だけ・球速の帯の保有率にした）で、架空球団用の日本人の投手の特能だけ変わった分も更新した。
# 能力との結びつき_ドラフト_改修指示.md（ドラフト候補のランク特能の引き直し・能力による特能の付け替え）で、ドラフト候補用の投手・野手の特能・ランク特能だけ変わった分も更新した。
# 変化球の種類と球速_改修指示.md（変化球の方向と球種を球速で引き直した）で、架空球団用の日本人の投手の変化球（と一部の特能）だけ変わった分も更新した
# （表を空にすると元の指紋を再現できることを確かめた）。
# 変化球の数と変化量_改修指示.md（先発の球種の数・総変化量）で、架空球団用の日本人の投手6人の変化球（と一部の特能）だけ変わった分も更新した
# （球種の数の処理を止め、総変化量の式を改修前に戻すと元の指紋を再現できることを確かめた）。
# 日本人の名前_改修指示.md（日本人の名を9,999個にして重みで選び、名を選ぶ乱数を分けた）で、日本人の名前（と名前で決まる肌の色）だけ変わった分も更新した
# （改修前の app.py・names.json で元の指紋を再現でき、名前と肌の色を除いた指紋は改修前と一致することを確かめた）。
UNCHANGED_PATH = Path(__file__).resolve().parent / "fixtures" / "foreign_remaining_unchanged.json"


def test_japanese_and_draft_players_are_unchanged():
    expected = json.loads(UNCHANGED_PATH.read_text(encoding="utf-8"))
    assert sum(len(values) for values in expected.values()) == 60
    for key, values in expected.items():
        category, role = key.split("|")
        for seed, digest in values.items():
            player = app.generate_player(role, category, MASTER, seed=int(seed), used_names=set())
            assert fingerprint(player) == digest, f"{key} seed {seed}"
