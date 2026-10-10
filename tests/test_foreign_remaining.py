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
UNCHANGED_PATH = Path(__file__).resolve().parent / "fixtures" / "foreign_remaining_unchanged.json"


def test_japanese_and_draft_players_are_unchanged():
    expected = json.loads(UNCHANGED_PATH.read_text(encoding="utf-8"))
    assert sum(len(values) for values in expected.values()) == 60
    for key, values in expected.items():
        category, role = key.split("|")
        for seed, digest in values.items():
            player = app.generate_player(role, category, MASTER, seed=int(seed), used_names=set())
            assert fingerprint(player) == digest, f"{key} seed {seed}"
