"""検出力のテスト（判定の整理_改修指示.md 6-2）: わざと生成を悪くしたとき、前回の正式な結果（スナップショット）との比較で「悪化」になる。

- 正式な規模（check_pitcher_control 300球団・散らばり300球団・構成500球団。seed も同じ）で、スナップショットを作ったときと同じ条件
  （PYTHONHASHSEED=0）で生成する。悪くしていない生成は、スナップショットと同じ値になる（悪化なし）。
- 悪くする処理は、生成のワーカープロセスの中（`_init`）だけで行い、本体のコードには残さない。
- 比較は checklib.compare_snapshot（生成側の誤差の3倍を超えて、範囲の中心から遠ざかったら「悪化」）。
- data/config/check_snapshot.csv が正式な結果で作られていることが前提。意図した変更でスナップショットを更新したら、そのまま通る。
- 時間は数分かかる（並列で生成する）。
"""
from __future__ import annotations

import logging
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd
import pytest

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "scripts"))

import check_pitcher_control  # noqa: E402
import checklib  # noqa: E402
import validate_team_mode  # noqa: E402

BOOT = 50
WORKERS = max(1, min(12, (os.cpu_count() or 2) - 2))
PITCHER_TEAMS, SPREAD_TEAMS, UNIFORM_TEAMS = 300, 300, 500
# 戦力レベルの倍率の効き（STRENGTH_REFERENCE_INDEX。今は 1.1）。0.55 で、球団ごとの査定の標準偏差が今の約1.3倍（実在との比 1.05→1.39 など）
STRENGTH_REFERENCE = 0.55


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PYTHONHASHSEED", "0")  # ワーカーに引き継ぐ（スナップショットと同じ条件）
    yield
    logging.disable(logging.NOTSET)


def _init(kind: str) -> None:
    """生成のワーカーの初期化。kind に応じて、このワーカーの中だけ生成を悪くする。"""
    import app
    from generator import team as team_lib

    if kind in ("pitcher", "pitcher_worse"):
        check_pitcher_control._init_worker()
    else:
        validate_team_mode._init_worker()
    if kind == "pitcher_worse":  # 救援投手のコントロールを +3 する
        original = app.generate_team

        def worse(*args, **kwargs):
            team = original(*args, **kwargs)
            for player in team["players"]:
                if player.get("role") == "投手" and player.get("position") != "先発":
                    player["abilities"]["コントロール"]["value"] += 3
            return team

        app.generate_team = worse
    elif kind == "spread_worse":  # 戦力レベルの倍率を強くして、球団ごとの散らばりを大きくする
        team_lib.STRENGTH_REFERENCE_INDEX = STRENGTH_REFERENCE
    elif kind == "uniform_worse":  # 42番の外国人の倍率を極端にする
        team_lib.UNIFORM_FOREIGN_NUMBER_MULTIPLIERS["42"] = 1000.0


def _generate(kind: str, job, items) -> list:
    with ProcessPoolExecutor(max_workers=WORKERS, initializer=_init, initargs=(kind,)) as pool:
        return list(pool.map(job, items, chunksize=4))


def _compare(graded: list[checklib.Check]) -> tuple[pd.DataFrame, pd.DataFrame]:
    snapshot = checklib.load_snapshot()
    assert snapshot is not None, "data/config/check_snapshot.csv がない（run_checks.py --update-snapshot で作る）"
    comparison = checklib.compare_snapshot(checklib.checks_frame(graded), snapshot)
    return comparison[comparison["変化"] == checklib.WORSE], comparison[comparison["変化"] == checklib.BETTER]


def _pitcher_graded(kind: str) -> list[checklib.Check]:
    frame = pd.concat(_generate(kind, check_pitcher_control._team, range(1, PITCHER_TEAMS + 1)), ignore_index=True)
    return check_pitcher_control.grade_all(frame, BOOT)


def test_unmodified_generation_has_no_worse_items():
    worse, _better = _compare(_pitcher_graded("pitcher"))
    assert worse.empty, worse.to_string()


def test_reliever_control_plus_three_is_worse():
    worse, _better = _compare(_pitcher_graded("pitcher_worse"))
    ids = set(worse["id"])
    assert any("control_hand.救援・右 平均" in i for i in ids) and any("control_hand.救援・左 平均" in i for i in ids), sorted(ids)
    print("\n[救援のコントロール+3] 悪化:", len(worse), "件。例:", worse.head(6)[["id", "前回", "今回", "動き"]].to_dict("records"))


def test_strength_multipliers_1_3x_spread_is_worse():
    spread = _generate("spread_worse", validate_team_mode._generate_spread, [validate_team_mode.SPREAD_BASE_SEED + i for i in range(SPREAD_TEAMS)])
    graded = validate_team_mode.grade_spread_only(spread, BOOT, False)
    ratios = {c.id.split(".")[2]: c.shown for c in graded if c.id.endswith(".sd_ratio") and c.kind == "実在"}
    worse, _better = _compare(graded)
    print(f"\n[戦力の倍率を強く（約1.3倍）] STRENGTH_REFERENCE_INDEX={STRENGTH_REFERENCE}、SD比 {ratios}")
    print("悪化:", len(worse), "件", worse[["id", "前回", "今回", "動き"]].to_dict("records"))
    sd_ratio = [i for i in worse["id"] if i.endswith(".sd_ratio")]
    assert len(sd_ratio) >= 3, f"散らばりが約1.3倍になっても、SD比の悪化が {len(sd_ratio)} 件しかない"


def test_extreme_foreign_42_multiplier_is_worse():
    main = _generate("uniform_worse", validate_team_mode._generate, [(validate_team_mode.BASE_SEED + i, None) for i in range(UNIFORM_TEAMS)])
    graded, _tables = validate_team_mode.grade_data({"main": main}, BOOT, 1)
    worse, _better = _compare(graded)
    assert "validate_team_mode.uniform.foreign_rate.42" in set(worse["id"]), sorted(worse["id"])
    print("\n[42番の外国人の倍率を極端に] 悪化:", len(worse), "件")
