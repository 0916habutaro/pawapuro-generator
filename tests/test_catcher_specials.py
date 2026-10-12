"""架空球団用の日本人野手の、ポジションのまとまり（捕手・二遊）ごとの連動特能の保有率と、捕手の下限の特能のテスト（`捕手の特能_改修指示.md`）。

保有率の分布の判定は scripts/check_fielder_position.py（球団生成300球団）で行う。ここでは区分の選び方・捕手の下限の特能・
空回し（共有の乱数）が変わらないこと・ほかの区分が変わらないことを見る。
"""
import logging
import random
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402

MASTER = app.load_master_data()


@pytest.fixture(autouse=True)
def _quiet():
    logging.disable(logging.WARNING)
    yield
    logging.disable(logging.NOTSET)


def test_linked_hand_by_position_group() -> None:
    assert app.fictional_linked_hand("野手", "右投右打", "捕手") == "右|捕手"
    assert app.fictional_linked_hand("野手", "右投左打", "二塁手") == "左|二遊"
    assert app.fictional_linked_hand("野手", "右投右打", "遊撃手") == "右|二遊"
    assert app.fictional_linked_hand("野手", "右投両打", "遊撃手") == "右|二遊"  # 両打は右打と同じ
    for position in ("一塁手", "三塁手", "外野手"):
        assert app.fictional_linked_hand("野手", "右投左打", position) == "左"


def test_linked_rates_pick_the_group_then_the_hand_then_the_overall() -> None:
    table = app.FICTIONAL_LINKED_HAND_RATES["野手"]
    base = {name: rates for name, _key, _limits, rates in app.FICTIONAL_LINKED_SPECIALS["野手"]}
    assert app.fictional_linked_rates("野手", "選球眼", base["選球眼"], "右|捕手") == table["選球眼"]["右|捕手"]
    assert app.fictional_linked_rates("野手", "三振", base["三振"], "左|二遊") == table["三振"]["左|二遊"]
    # 二遊の選球眼は指定が無いので、打席だけの指定も無ければ全体の保有率
    assert app.fictional_linked_rates("野手", "選球眼", base["選球眼"], "左|二遊") == base["選球眼"]
    # 二遊の広角打法は打席だけの指定
    assert app.fictional_linked_rates("野手", "広角打法", base["広角打法"], "右|二遊") == table["広角打法"]["右"]
    # 捕手は同じミートでも選球眼・固め打ち・三振が少ない。三振は二遊が一塁手・三塁手・外野手より少ない
    for name in ("選球眼", "固め打ち"):
        assert all(c <= b for c, b in zip(table[name]["右|捕手"], base[name])), name
    assert sum(table["三振"]["右|捕手"]) < sum(table["三振"]["右"])
    assert all(m <= o for m, o in zip(table["三振"]["右|二遊"], table["三振"]["右"]))
    # 全体の保有率（空回しが使う）は変えていない
    assert base["三振"] == [0.34, 0.38, 0.37, 0.16]
    assert base["選球眼"] == [0.09, 0.13, 0.26, 0.33]


def fillers_only(hand: str | None, player_class: str = "スター級") -> list[str]:
    """連動・出現率の補正を外して、下限まで足す特能だけを見る。"""
    with mock.patch.dict(app.FICTIONAL_LINKED_SPECIALS, {"野手": []}), mock.patch.dict(app.FICTIONAL_SPECIAL_RATE_TARGETS, {"野手": []}):
        return app._fictional_adjust_specials(random.Random(1), MASTER, "野手", player_class, [], {}, lambda name: True, hand, set())


def test_catcher_fillers() -> None:
    assert app.FICTIONAL_SPECIAL_FILLERS["野手|捕手"][0] == "ホーム死守"
    catcher = fillers_only("右|捕手")
    assert catcher[0] == "ホーム死守" and "選球眼" not in catcher
    # 捕手以外・空回し（hand=None）は今のまま選球眼から
    for hand in ("右", "左|二遊", None):
        assert fillers_only(hand)[0] == "選球眼", hand
    # ドラフト候補用の下限の特能は変えない
    assert app.FICTIONAL_SPECIAL_FILLERS["野手"][0] == "選球眼"


@pytest.mark.parametrize("seed", range(1, 31))
def test_shared_random_stream_does_not_depend_on_the_group(seed: int) -> None:
    """空回しは区分によらないので、区分（捕手・二遊・打席だけ）を変えても共有の乱数は同じだけ進む。"""
    states = []
    for hand in ("右", "右|捕手", "右|二遊"):
        rng = random.Random(seed)
        app.fictional_adjust_specials(rng, MASTER, "野手", "スター級", ["選球眼", "三振"], {"ミート": 45, "走力": 60, "パワー": 60, "守備力": 50},
                                      lambda name: True, hand)
        states.append(rng.random())
    assert states[0] == states[1] == states[2]


def without_groups():
    """ポジションのまとまり・捕手の下限の特能を外した状態（区分は打席だけ）。"""
    return (
        mock.patch.object(app, "FICTIONAL_LINKED_FIELDER_GROUPS", {}),
        mock.patch.dict(app.FICTIONAL_SPECIAL_FILLERS, {"野手|捕手": app.FICTIONAL_SPECIAL_FILLERS["野手"]}),
    )


def test_fielders_change_only_special_abilities() -> None:
    """まとまりの区分は特能だけを変える。能力・ランク特能・体重・名前などは、まとまりを外した状態と同じ。"""
    changed = catchers = 0
    for seed in range(1, 81):
        a, b = without_groups()
        with a, b:
            before = app.generate_player("野手", "架空球団用", MASTER, seed=seed)
        after = app.generate_player("野手", "架空球団用", MASTER, seed=seed)
        assert {k: v for k, v in before.items() if k != "special_abilities"} == {k: v for k, v in after.items() if k != "special_abilities"}, seed
        catchers += after["position"] in app.FICTIONAL_LINKED_FIELDER_GROUPS
        changed += before["special_abilities"] != after["special_abilities"]
    assert catchers > 0 and changed > 0


@pytest.mark.parametrize(("role", "category"), [
    ("投手", "架空球団用"), ("投手", "ドラフト候補用"), ("野手", "ドラフト候補用"), ("投手", "助っ人外国人用"), ("野手", "助っ人外国人用"),
])
def test_other_segments_do_not_change(role: str, category: str) -> None:
    for seed in range(1, 21):
        a, b = without_groups()
        with a, b:
            before = app.generate_player(role, category, MASTER, seed=seed)
        assert app.generate_player(role, category, MASTER, seed=seed) == before, seed
