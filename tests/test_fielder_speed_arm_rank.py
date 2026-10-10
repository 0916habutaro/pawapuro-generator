"""架空球団用の日本人野手の、走塁・盗塁・送球のランクと走力・肩力の結びつき（野手の走力肩力ランク_改修指示.md）。

確率・重みは球団生成で合わせており、正式な判定は scripts/check_fielder_speed.py（球団生成300球団）。
ここでは個別生成で、走力・肩力の低い選手のランクが強く下がらないこと、走力70〜79の走塁が上がること、
確率を変えても乱数の引く回数が変わらないこと、ほかの区分が変わらないことを確かめる。
"""
from __future__ import annotations

import app

MASTER = app.load_master_data()
SEEDS = range(1, 301)
GROUPS = ("走塁", "盗塁", "送球")


def players(role: str = "野手", category: str = "架空球団用") -> list[dict]:
    return [app.generate_player(role, category, MASTER, seed=seed) for seed in SEEDS]


def domestic_fielders() -> list[dict]:
    return [player for player in players() if player["roster_origin"] == "domestic"]


def letter(player: dict, group: str) -> str | None:
    name = player["abilities"]["ranked_specials"].get(group)
    return name[-1] if name else None


def ability(player: dict, key: str) -> float:
    return float(player["abilities"][key]["value"])


def without_groups(player: dict, groups: tuple[str, ...] = GROUPS) -> dict:
    abilities = dict(player["abilities"])
    abilities["ranked_specials"] = {k: v for k, v in abilities["ranked_specials"].items() if k not in groups}
    return {**player, "abilities": abilities}


def only_d_weights(monkeypatch) -> None:
    """走塁・盗塁・送球の重みを D だけにして、結びつきで動いた分だけが見えるようにする。"""
    weights = {**app.FICTIONAL_FIELDER_RANKED_WEIGHTS, **{group: {"D": 1.0} for group in GROUPS}}
    monkeypatch.setattr(app, "FICTIONAL_FIELDER_RANKED_WEIGHTS", weights)


def test_link_rates_and_weights():
    assert app.FICTIONAL_FIELDER_RANK_LINK_RATES["盗塁"][1] == 0.0  # 遅い選手の盗塁は下げない
    assert app.FICTIONAL_FIELDER_RANK_LINK_RATES["走塁"][1] < 0.4  # 改修前より弱く下げる
    assert app.FICTIONAL_FIELDER_RANK_LINK_RATES["送球"][1] < 0.4
    assert 0 < app.FICTIONAL_FIELDER_RUNNING_MID_RATE < 1
    assert app.FICTIONAL_FIELDER_RANK_LINK_NAMESPACE != app.FICTIONAL_FIELDER_BALANCE_NAMESPACE


def test_slow_and_weak_arm_players_are_not_pushed_down_strongly(monkeypatch):
    only_d_weights(monkeypatch)
    fielders = domestic_fielders()
    slow = [p for p in fielders if ability(p, "走力") <= 50]
    weak = [p for p in fielders if ability(p, "肩力") <= 55]
    assert len(slow) >= 20 and len(weak) >= 20, (len(slow), len(weak))
    assert all(letter(p, "盗塁") in ("D", None) for p in slow)
    down_run = sum(letter(p, "走塁") == "E" for p in slow) / len(slow)
    down_arm = sum(letter(p, "送球") == "E" for p in weak) / len(weak)
    rates = app.FICTIONAL_FIELDER_RANK_LINK_RATES
    assert down_run <= rates["走塁"][1] + 0.15, down_run
    assert down_arm <= rates["送球"][1] + 0.15, down_arm


def test_running_goes_up_for_speed_70_to_79(monkeypatch):
    only_d_weights(monkeypatch)
    fielders = domestic_fielders()
    middle = [p for p in fielders if 70 <= ability(p, "走力") < 80]
    others = [p for p in fielders if 50 < ability(p, "走力") < 70]
    assert len(middle) >= 30 and len(others) >= 30, (len(middle), len(others))
    up = sum(letter(p, "走塁") == "C" for p in middle) / len(middle)
    assert abs(up - app.FICTIONAL_FIELDER_RUNNING_MID_RATE) < 0.2, up
    assert all(letter(p, "走塁") == "D" for p in others)
    assert all(letter(p, "盗塁") == "D" for p in middle)  # 盗塁は走力70〜79で動かさない


def test_rates_do_not_change_the_random_stream(monkeypatch):
    def run(up: float, down: float, middle: float) -> list[dict]:
        monkeypatch.setattr(app, "FICTIONAL_FIELDER_RANK_LINK_RATES", {group: (up, down) for group in GROUPS})
        monkeypatch.setattr(app, "FICTIONAL_FIELDER_RUNNING_MID_RATE", middle)
        return domestic_fielders()

    low, high = run(0.0, 0.0, 0.0), run(1.0, 1.0, 1.0)
    assert any(letter(a, "走塁") != letter(b, "走塁") for a, b in zip(low, high))
    for a, b in zip(low, high):
        assert without_groups(a) == without_groups(b), a["seed"]


def test_other_categories_do_not_change(monkeypatch):
    cases = [("投手", "架空球団用"), ("投手", "ドラフト候補用"), ("野手", "ドラフト候補用"), ("投手", "助っ人外国人用"), ("野手", "助っ人外国人用")]
    current = {case: players(*case) for case in cases}
    foreign = [p for p in players() if p["roster_origin"] != "domestic"]
    monkeypatch.setattr(app, "FICTIONAL_FIELDER_RANK_LINK_RATES", {group: (1.0, 1.0) for group in GROUPS})
    monkeypatch.setattr(app, "FICTIONAL_FIELDER_RUNNING_MID_RATE", 1.0)
    for case in cases:
        assert players(*case) == current[case], case
    assert [p for p in players() if p["roster_origin"] != "domestic"] == foreign
