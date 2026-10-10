"""外国人の要注意6件（投手のコントロール×スタミナ、野手のパワーの形・パワー×守備力・遊撃手・右投右打）の改修
（外国人の要注意_改修指示.md）を確かめる。

分布の合否は scripts/check_foreign_balance.py（個別生成5000人・球団生成300球団）で見る。
ここでは少ない人数で、向きと仕組み（役割の中の相関・両打の割合・パワーの上限・日本人とドラフト候補は変わらない）を確かめる。
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


def value(player: dict, key: str) -> int:
    return app.ability_numeric_value(player["abilities"], key) or 0


def control_stamina_correlation(players: list[dict]) -> float:
    return statistics.correlation([value(p, "コントロール") for p in players], [value(p, "スタミナ") for p in players])


def test_foreign_pitcher_control_and_stamina_go_together_within_each_role():
    # 実在（2024〜2026年版）は 先発 0.37・救援 0.24。改修前は 0.11・0.10
    starters = [p for p in PITCHERS if p["position"] == "先発"]
    relievers = [p for p in PITCHERS if p["position"] != "先発"]
    assert control_stamina_correlation(starters) >= 0.2
    assert control_stamina_correlation(relievers) >= 0.12
    assert control_stamina_correlation(PITCHERS) >= 0.38
    assert app.FOREIGN_PITCHER_STAMINA_CONTROL_WEIGHT["先発"] > app.FOREIGN_PITCHER_STAMINA_CONTROL_WEIGHT["中継ぎ"] > 0.08
    # 先発のスタミナの平均は保つ（実在 59.8）
    assert 57 <= statistics.fmean(value(p, "スタミナ") for p in starters) <= 62


def test_foreign_fielders_switch_hitters_are_rare():
    # 実在（2024〜2026年版）は 右投右打 78.4%・右投両打 2.9%。改修前は 70.1%・9.5%
    right_switch = sum(p["batting_throwing"] == "右投両打" for p in FIELDERS) / len(FIELDERS)
    right_right = sum(p["batting_throwing"] == "右投右打" for p in FIELDERS) / len(FIELDERS)
    assert right_switch <= 0.08
    assert right_right >= 0.71
    assert dict(app.FOREIGN_FIELDER_BAT_SIDE_WEIGHTS["右投"])["両打"] < dict(app.FOREIGN_FIELDER_BAT_SIDE_WEIGHTS["右投"])["左打"]


def test_foreign_fielder_power_has_long_weak_tail_and_low_ceiling():
    # 実在（2024〜2026年版）は 55未満 10.8%・85以上 2.0%・中央 70。弱い側の裾が長く、強い側は頭打ち
    power = [value(p, "パワー") for p in FIELDERS]
    assert max(power) <= app.FOREIGN_FIELDER_POWER_MAX <= 87
    assert sum(v >= 85 for v in power) / len(power) <= 0.03
    assert sum(v < 55 for v in power) / len(power) >= 0.07
    assert 68 <= statistics.median(power) <= 72
    low_spread, high_spread = app.FOREIGN_FIELDER_POWER_SPREAD
    assert low_spread > high_spread


def test_foreign_fielder_power_and_fielding_are_not_too_negative():
    # 実在（2024〜2026年版）は −0.15。改修前は −0.29（守備力をパワーの高さで下げていた）
    assert app.FOREIGN_FIELDER_FIELDING_POWER_DEV == 0.0
    correlation = statistics.correlation([value(p, "パワー") for p in FIELDERS], [value(p, "守備力") for p in FIELDERS])
    assert -0.30 <= correlation <= -0.05


def test_foreign_fielder_shortstops_are_more_common_with_real_sub_positions():
    # 実在（2024〜2026年版）は遊撃手 15.7%。改修前は 9.6%
    shortstop = sum(p["position"] == "遊撃手" for p in FIELDERS) / len(FIELDERS)
    assert shortstop >= 0.11
    # 遊撃手は実在（2024〜2026年版 62.5%・2022〜2026年版 65%）に合わせて「2つ」を84%→64%にした。
    # 三塁手は実在（2022〜2026年版）に合わせて、サブポジ0つをなくした
    assert dict(app.FOREIGN_FIELDER_SUB_POSITION_COUNT_WEIGHTS["遊撃手"])[2] == 64
    shortstops = [p for p in FIELDERS if p["position"] == "遊撃手"]
    assert 0.45 <= sum(len(p["sub_positions"]) == 2 for p in shortstops) / len(shortstops) <= 0.80
    assert dict(app.FOREIGN_FIELDER_SUB_POSITION_COUNT_WEIGHTS["三塁手"])[0] == 0
    assert all(p["sub_positions"] for p in FIELDERS if p["position"] == "三塁手")


def fingerprint(player: dict) -> str:
    return hashlib.sha256(json.dumps(player, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


# 改修前（d61a162）の app.py で作った、架空球団用の日本人・ドラフト候補用の指紋（各25人。架空球団用は外国人枠の seed を除く）。
# 外国人だけを変える改修なので、日本人とドラフト候補は1人も変わらない。
UNCHANGED_PATH = Path(__file__).resolve().parent / "fixtures" / "foreign_caution_unchanged.json"


def test_japanese_and_draft_players_are_unchanged():
    expected = json.loads(UNCHANGED_PATH.read_text(encoding="utf-8"))
    assert sum(len(values) for values in expected.values()) == 100
    for key, values in expected.items():
        category, role = key.split("|")
        for seed, digest in values.items():
            player = app.generate_player(role, category, MASTER, seed=int(seed), used_names=set())
            assert fingerprint(player) == digest, f"{key} seed {seed}"
