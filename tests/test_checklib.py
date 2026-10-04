"""検証スクリプト共通の合否の付け方（scripts/checklib.py、判定の整理_改修指示.md）。"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR / "scripts"))

import checklib  # noqa: E402
from checklib import Checks  # noqa: E402


def one(kind: str, value: float, low=None, high=None, se: float | None = None, id: str = "t.x", accepted=None, baselines_path=None) -> checklib.Check:
    checks = Checks("t")
    check = checks.add(id, kind, "項目", value, low, high)
    graded = checklib.grade(checks, se_gen={id: se} if se is not None else {}, accepted=accepted or {})
    return graded[0]


# ---------------------------------------------------------------------------
# 種類ごとの合否
# ---------------------------------------------------------------------------
def test_real_inside_range_passes():
    assert one("実在", 5.0, 4.0, 6.0, se=0.5).status == "合格"


def test_real_just_outside_is_warning_far_outside_is_failure():
    # 誤差 0.5 の2倍 = 1.0 以内の外れは要注意、超えたら不合格
    near = one("実在", 6.9, 4.0, 6.0, se=0.5)
    assert near.status == "要注意" and near.sigmas == pytest.approx(1.8)
    far = one("実在", 7.2, 4.0, 6.0, se=0.5)
    assert far.status == "不合格" and "2倍超" in far.reason


def test_real_without_error_is_strict():
    assert one("実在", 6.01, 4.0, 6.0).status == "不合格"
    assert one("実在", 6.01, 4.0, 6.0, se=0.0).status == "不合格"


def test_error_combines_generation_and_real_side():
    checks = Checks("t")
    checks.add("t.x", "実在", "項目", 6.8, 4.0, 6.0)
    graded = checklib.grade(checks, se_gen={"t.x": 0.3}, se_real={"t.x": 0.4}, accepted={})
    assert graded[0].se == pytest.approx(0.5)  # √(0.3²+0.4²)
    assert graded[0].status == "要注意"  # 外れ 0.8 ≦ 2×0.5


def test_design_is_strict_even_with_error():
    assert one("設計", 6.1, None, 6.0, se=5.0).status == "不合格"
    assert one("設計", 6.0, None, 6.0, se=5.0).status == "合格"


def test_real_side_error_is_ignored_for_non_real_kinds():
    checks = Checks("t")
    checks.add("t.x", "設計", "項目", 6.5, None, 6.0)
    graded = checklib.grade(checks, se_gen={"t.x": 1.0}, se_real={"t.x": 1.0}, accepted={})
    assert graded[0].se_real is None and graded[0].status == "不合格"


def test_info_has_no_verdict_and_nan_fails():
    assert one("参考", 100.0, 1.0, 2.0).status == "参考"
    assert one("実在", math.nan, 1.0, 2.0, se=1.0).status == "不合格"


def test_quick_makes_everything_info():
    checks = Checks("t")
    checks.add("t.x", "実在", "項目", 99.0, 1.0, 2.0)
    graded = checklib.grade(checks, accepted={}, all_info=True)
    assert graded[0].status == "参考" and "簡易版" in graded[0].reason


def test_exit_code_only_fails_on_failure():
    ok = [one("実在", 6.5, 4.0, 6.0, se=0.5), one("実在", 5.0, 4.0, 6.0)]
    assert [c.status for c in ok] == ["要注意", "合格"] and checklib.exit_code(ok) == 0
    assert checklib.exit_code(ok + [one("設計", 9.0, None, 6.0)]) == 1


# ---------------------------------------------------------------------------
# 受け入れ済みの不合格
# ---------------------------------------------------------------------------
RECORD = {"id": "t.x", "accepted_value": 303.1, "limit": 301.45, "direction": "upper", "reason": "理由", "pr": "#1", "date": "2026-10-04"}


def test_accepted_value_not_worse_is_accepted():
    check = one("実在", 303.0, None, 301.45, se=0.4, accepted={"t.x": RECORD})
    assert check.status == "受け入れ済み" and "理由" in check.reason


def test_accepted_value_worse_within_two_errors_is_still_accepted():
    # 受け入れた値 303.1 より 0.7 悪い。誤差 0.4 の2倍 = 0.8 以内
    assert one("実在", 303.8, None, 301.45, se=0.4, accepted={"t.x": RECORD}).status == "受け入れ済み"


def test_accepted_value_worse_beyond_two_errors_fails():
    check = one("実在", 304.2, None, 301.45, se=0.4, accepted={"t.x": RECORD})
    assert check.status == "不合格" and "受け入れた値より悪化" in check.reason


def test_accepted_record_for_value_back_in_range_suggests_removal():
    check = one("実在", 301.0, None, 301.45, se=0.4, accepted={"t.x": RECORD})
    assert check.status == "合格" and "外してよい" in check.reason


def test_accepted_lower_direction():
    record = {**RECORD, "accepted_value": 10.0, "direction": "lower"}
    assert one("実在", 10.1, 12.0, None, se=0.1, accepted={"t.x": record}).status == "受け入れ済み"
    assert one("実在", 9.5, 12.0, None, se=0.1, accepted={"t.x": record}).status == "不合格"


# ---------------------------------------------------------------------------
# 基準値ファイル（固定）
# ---------------------------------------------------------------------------
@pytest.fixture()
def baseline_file(tmp_path, monkeypatch):
    path = tmp_path / "baselines.json"
    path.write_text(json.dumps({"version": 1, "items": {
        "t.stamina": {"value": 58.75, "width": 0.3, "direction": "both", "label": "先発スタミナ", "pr": "#108", "reason": "初期", "date": "2026-10-04"},
        "t.corr": {"value": 0.98, "width": 0.0, "direction": "lower", "label": "相関", "pr": "#102", "reason": "初期", "date": "2026-10-04"},
    }}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(checklib, "BASELINES_PATH", path)
    checklib.reload_config()
    yield path
    checklib.reload_config()


def fixed(id: str, value: float, width: float = 0.3) -> checklib.Check:
    checks = Checks("t")
    checks.fixed(id, "項目", value, width)
    return checklib.grade(checks, accepted={})[0]


def test_fixed_compares_with_baseline_value_and_width(baseline_file):
    assert fixed("t.stamina", 58.9).status == "合格"
    assert fixed("t.stamina", 59.2).status == "不合格"
    assert fixed("t.corr", 0.99).status == "合格"
    assert fixed("t.corr", 0.97).status == "不合格"


def test_fixed_without_baseline_fails(baseline_file):
    check = fixed("t.unknown", 1.0)
    assert check.status == "不合格" and "基準値なし" in check.reason


def test_update_baselines_requires_reason_and_reports_changes(baseline_file):
    checks = Checks("t")
    checks.fixed("t.stamina", "項目", 59.5, 0.3)
    checks.fixed("t.new", "新しい項目", 1.5, 0.2)
    graded = checklib.grade(checks, accepted={})
    with pytest.raises(SystemExit):
        checklib.update_baselines(graded, "  ")
    assert json.loads(baseline_file.read_text(encoding="utf-8"))["items"]["t.stamina"]["value"] == 58.75  # 理由が空なら書き込まない
    changed = checklib.update_baselines(graded, "テストの理由", pr="#999")
    assert ("t.stamina", 58.75, 59.5) in changed and ("t.new", None, 1.5) in changed
    items = json.loads(baseline_file.read_text(encoding="utf-8"))["items"]
    assert items["t.stamina"]["reason"] == "テストの理由" and items["t.stamina"]["width"] == 0.3
    assert items["t.new"]["width"] == 0.2  # 新しい項目は呼び出し側の既定の幅
    assert fixed("t.stamina", 59.6).status == "合格"


def test_update_baselines_ignores_non_fixed_kinds(baseline_file):
    checks = Checks("t")
    checks.add("t.real", "実在", "項目", 5.0, 4.0, 6.0)
    assert checklib.update_baselines(checklib.grade(checks, accepted={}), "理由") == []


# ---------------------------------------------------------------------------
# 誤差（ブートストラップ）
# ---------------------------------------------------------------------------
def _mean_check(frame: pd.DataFrame) -> Checks:
    checks = Checks("t")
    checks.add("t.mean", "実在", "平均", frame["x"].mean())
    return checks


def test_bootstrap_se_matches_standard_error_of_the_mean():
    rng = np.random.default_rng(1)
    frame = pd.DataFrame({"x": rng.normal(50, 10, 400)})
    se = checklib.bootstrap_se(_mean_check, frame, checklib.resample_frame, n=300, seed=3)["t.mean"]
    assert se == pytest.approx(10 / math.sqrt(400), rel=0.2)


def test_bootstrap_is_reproducible_and_cluster_resampling_widens_error():
    rng = np.random.default_rng(2)
    team = np.repeat(np.arange(40), 25)
    frame = pd.DataFrame({"team": team, "x": rng.normal(0, 1, 40)[team] * 5 + rng.normal(0, 1, 1000)})
    a = checklib.bootstrap_se(_mean_check, frame, checklib.resample_frame, n=100, seed=5)["t.mean"]
    b = checklib.bootstrap_se(_mean_check, frame, checklib.resample_frame, n=100, seed=5)["t.mean"]
    clustered = checklib.bootstrap_se(_mean_check, frame, lambda f, r: checklib.resample_frame(f, r, "team"), n=100, seed=5)["t.mean"]
    assert a == b
    assert clustered > a * 2  # 球団ごとの値が似ているとき、球団単位の誤差のほうが大きい


def test_bootstrap_offset_follows_the_boundary():
    # 値は固定で、範囲の境界が実在の再抽出で動く判定: 境界の揺れを誤差として返す
    real = pd.DataFrame({"x": np.random.default_rng(4).normal(10, 2, 36)})

    def evaluate(frame: pd.DataFrame) -> Checks:
        checks = Checks("t")
        center = frame["x"].mean()
        checks.add("t.p", "実在", "境界が動く", 10.0, center - 1, center + 1)
        return checks

    se = checklib.bootstrap_se(evaluate, real, checklib.resample_frame, n=200, seed=1, offset=True)["t.p"]
    assert se == pytest.approx(2 / math.sqrt(36), rel=0.3)


def test_scale_se_converts_by_player_count():
    assert checklib.scale_se({"a": 1.0}, 5000, 1250)["a"] == pytest.approx(2.0)
    assert checklib.scale_se({"a": 1.0}, 5000, 0)["a"] == 0.0


def test_verdict_works_as_bool_and_keeps_range():
    verdict = checklib.in_range(5.0, 4.0, 6.0)
    assert verdict and verdict.low == 4.0 and verdict.high == 6.0
    assert not checklib.in_range(7.0, hi=6.0) and not checklib.in_range(float("nan"), 1.0)
    assert checklib.in_range(3.0, lo=2.0) and checklib.in_range(3.0, low=2.0, high=4.0)


# ---------------------------------------------------------------------------
# 出力・設定ファイル
# ---------------------------------------------------------------------------
def test_csv_has_common_columns(tmp_path):
    checks = Checks("t")
    checks.add("t.x", "実在", "項目", 5.0, 4.0, 6.0, section="節", shown="5.00")
    graded = checklib.grade(checks, se_gen={"t.x": 0.1}, accepted={})
    path = tmp_path / "x.csv"
    checklib.write_csv(graded, path)
    frame = checklib.read_csv(path)
    assert list(frame.columns) == list(checklib.CSV_COLUMNS)
    assert frame.loc[0, "id"] == "t.x" and frame.loc[0, "合否"] == "合格" and frame.loc[0, "種類"] == "実在"


def test_committed_config_files_are_well_formed():
    baselines = checklib.baselines()
    assert baselines, "data/config/check_baselines.json が空"
    for key, item in baselines.items():
        assert {"value", "width", "label", "pr", "reason", "date"} <= set(item), key
        assert item.get("direction", "both") in ("both", "lower", "upper"), key
        assert key.startswith(("check_", "validate_")), key
    accepted = checklib.accepted_deviations()
    for key, item in accepted.items():
        assert {"id", "accepted_value", "limit", "direction", "reason", "pr", "date"} <= set(item), key
        assert item["direction"] in ("upper", "lower"), key


# ---------------------------------------------------------------------------
# 前回の正式な結果（スナップショット）との比較
# ---------------------------------------------------------------------------
def snap(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame([{"id": i, "種類": k, "値(数値)": str(v), "生成側誤差": "0.1"} for i, k, v in rows])


def frame_of(id: str, kind: str, value: float, low=None, high=None, se: float | None = 0.1) -> pd.DataFrame:
    checks = Checks("t")
    check = checks.add(id, kind, "項目", value, low, high)
    check.se_gen = se
    return checklib.checks_frame(checks)


def change_of(frame: pd.DataFrame, previous: float, kind: str = "実在") -> str:
    result = checklib.compare_snapshot(frame, snap([("t.x", kind, previous)]))
    return result["変化"].iloc[0] if len(result) else ""


def test_snapshot_two_sided_range_measures_distance_from_center():
    # 範囲 4〜6（中心5）、誤差 0.1 の3倍 = 0.3
    assert change_of(frame_of("t.x", "実在", 5.5, 4, 6), 5.0) == "悪化"   # 中心から遠ざかる
    assert change_of(frame_of("t.x", "実在", 5.2, 4, 6), 5.0) == ""       # 3倍以内
    assert change_of(frame_of("t.x", "実在", 5.0, 4, 6), 5.5) == "改善"   # 中心へ近づく
    assert change_of(frame_of("t.x", "実在", 4.5, 4, 6), 5.5) == ""       # 反対側へ同じだけ動いても、中心からの距離は同じ
    assert change_of(frame_of("t.x", "実在", 4.2, 4, 6), 5.0) == "悪化"   # 下側へ遠ざかる


def test_snapshot_one_sided_range_uses_direction_toward_violation():
    assert change_of(frame_of("t.x", "実在", 0.9, None, 1.0), 0.5) == "悪化"  # 上限だけ: 増える
    assert change_of(frame_of("t.x", "実在", 0.5, None, 1.0), 0.9) == "改善"
    assert change_of(frame_of("t.x", "設計", 3.0, 5.0, None), 4.0) == "悪化"  # 下限だけ: 減る


def test_snapshot_without_error_flags_any_move_and_ignores_other_kinds():
    assert change_of(frame_of("t.x", "設計", 1.0, None, 0.0, se=None), 0.0) == "悪化"  # 0件が1件になった
    assert change_of(frame_of("t.x", "設計", 0.0, None, 0.0, se=None), 0.0) == ""
    assert change_of(frame_of("t.x", "固定", 9.0, 1.0, 2.0), 1.5, kind="固定") == ""   # 固定・参考は比べない
    new_id = checklib.compare_snapshot(frame_of("t.new", "実在", 9.0, 1, 2), snap([("t.x", "実在", 1.0)]))
    assert new_id.empty  # スナップショットにない id は比べない
    assert checklib.compare_snapshot(frame_of("t.x", "実在", 9.0, 1, 2), None).empty


def test_write_snapshot_requires_reason_and_reports_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(checklib, "SNAPSHOT_META_PATH", tmp_path / "meta.json")
    path = tmp_path / "snap.csv"
    first = pd.DataFrame({"id": ["a.1", "b.1"], "種類": ["実在", "設計"], "値(数値)": ["1.0", "2.0"], "生成側誤差": ["0.1", ""]})
    with pytest.raises(SystemExit):
        checklib.write_snapshot(first, " ", path=path)
    assert not path.exists()
    assert len(checklib.write_snapshot(first, "初回", "abc", path=path)) == 2
    second = pd.DataFrame({"id": ["a.1"], "種類": ["実在"], "値(数値)": ["1.5"], "生成側誤差": ["0.1"]})
    changed = checklib.write_snapshot(second, "a だけ流した", "def", only_scripts_prefix=("a.",), path=path)
    assert changed == [("a.1", 1.0, 1.5)]
    kept = checklib.load_snapshot(path)
    assert set(kept["id"]) == {"a.1", "b.1"} and kept.set_index("id").loc["b.1", "値(数値)"] == "2.0"  # 流さなかった側は残る
    assert json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))["reason"] == "a だけ流した"
