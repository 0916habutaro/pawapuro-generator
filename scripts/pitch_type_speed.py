"""
変化球の種類と球速の、表づくりと判定の共通部分（`変化球の種類と球速_改修指示.md`）。

- 実在は2024〜2026年版の日本人投手（外国人を除く）。変化球の表（build_real_team_reference.parse_directory の breaking）を、
  年版・球団・名前で投手と結合する。方向は第一球種（slot 1）で数える。スクリューは取り込みの時点でシンカーにまとめられているので、
  表を作るときは左投手のシンカーをスクリューとして扱う。判定ではシンカーとスクリューを合わせて「シンカー」と数える。
- 同じ選手が複数の年版に入っているので、誤差は異なる選手の数（名前で数える）で出す。
- `python scripts/pitch_type_speed.py --build-real` で、実在から
    data/config/pitch_type_speed_real.json（判定に使う実在の値）と
    reports/pitch_type_speed/fictional_pitch_type_speed_rebuilt.json（生成に使う表を作り直したもの。試作表との差も出す）
  を書き出す。生成に使う表は data/config/fictional_pitch_type_speed.json（試作表。--write-table を付けたときだけ作り直した表で上書きする）。
- 表の作り方（指示書1-2）:
    方向の組の重み … 投げ手 × 第一球種の数 k（2・3）ごとの条件つきロジット。組の重み W と方向ごとの傾き β（スライダー方向は0、
                      k=2・3 で共通）を同時に最尤推定し、x=0 の組の割合（%）を出す。実在にない組が0にならないよう、
                      組の重みの対数に弱い L2 の罰則をかける。k=1 は右投手の1球種の方向の件数に疑似カウント1を足した割合を両投げ手で使う。
    球種の重み     … 投げ手 × 方向ごとの多項ロジット。傾き γ は両投げ手で共通（標準偏差1の事前分布）。x=0 の割合（%）を出す。
    変化量の起こりやすさ … 球種ごとの変化量1〜6の件数に、同じ方向の割合を3件分の重みで足して均した割合。
    x = (球速 − 中心) / 4 を −2.5〜2.5 に収める。中心は 右投 152、左投 149。
- check_pitcher_rank_pitches.py が、この module の type_checks で「変化球の種類と球速」の節を足す（指示書2-1）。
- 先発の球種の数と総変化量（`変化球の数と変化量_改修指示.md` 2-1）も同じ実在から作り、実在の値は pitch_type_speed_real.json の
  「先発の球種の数と総変化量」に入れる。count_checks がその節を足す。実在の年齢は2026年版は記載の値、2024・2025年版は生年からの
  逆算（age_backcalc）。変化球数・総変化量は第一球種だけで数える。誤差は 標準偏差/√異なる選手の数。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import checklib  # noqa: E402
from checklib import Checks  # noqa: E402

REAL_PATH = APP_DIR / "data" / "config" / "pitch_type_speed_real.json"
TABLE_PATH = APP_DIR / "data" / "config" / "fictional_pitch_type_speed.json"
REBUILT_PATH = APP_DIR / "reports" / "pitch_type_speed" / "fictional_pitch_type_speed_rebuilt.json"
REAL_SEASONS = (2024, 2025, 2026)
HANDS = ("右投", "左投")
CODES = ("1", "2", "3", "4", "5")
DIRECTION_LABELS = {"1": "スライダー方向", "2": "カーブ方向", "3": "フォーク方向", "4": "シンカー方向", "5": "シュート方向"}
CENTER = {"右投": 152.0, "左投": 149.0}
WIDTH, X_LIMIT = 4.0, 2.5
# 組の重みの対数にかける L2 の罰則（実在にない組を0にしないため）と、球種の傾きの事前分布の標準偏差
SET_RIDGE, NAME_RIDGE, SLOPE_PRIOR_SD = 0.03, 0.03, 1.0
MOVEMENT_PSEUDO = 3.0
# 表に入れない球種（実在の日本人は0人）
EXCLUDED_NAMES = ("ナックル",)

# 判定（指示書2-1）
SPEED_BANDS = {
    "右投": (("〜148", 0, 148), ("149〜151", 149, 151), ("152〜154", 152, 154), ("155〜", 155, 999)),
    "左投": (("〜145", 0, 145), ("146〜148", 146, 148), ("149〜151", 149, 151), ("152〜", 152, 999)),
}
BAND_CODES = {"右投": ("3", "4", "1"), "左投": ("3",)}
TYPE_BANDS = (("〜148", 0, 148), ("149〜152", 149, 152), ("153〜", 153, 999))
FAST_NAMES = ("Vスライダー", "SFF", "パワーカーブ", "ナックルカーブ", "ドロップカーブ")
SLOW_NAMES = ("シンカー", "Hシュート", "Hシンカー", "チェンジアップ", "スローカーブ", "シンキングツーシーム")
SPEED_DIFF_NAMES = ("Vスライダー", "SFF", "チェンジアップ", "スローカーブ")
# 参考に出す、持つ先発の球速と全体の差（指示書1-3）
SPEED_DIFF_REFERENCE = ("パワーカーブ", "Vスライダー", "SFF", "ドロップカーブ", "チェンジアップ", "スローカーブ", "Hシュート", "シンカー")
TOL_BAND_MIN, TOL_OVERALL, TOL_NAME_MIN, TOL_SPEED_DIFF, TOL_COMBO = 6.0, 3.0, 2.5, 1.5, 3.0
NAME_MIN_SHARE, COMBO_MIN_SHARE = 2.0, 3.0
SPLIT_MAX = 6.0
SECTION = "変化球の種類と球速（方向は第一球種。実在は2024〜2026年版の日本人投手。誤差は異なる選手の数）"
# 改修前（球団生成 seed 1〜300、main 4f25a3b）の値（指示書0-2・1-3）。表示用
BEFORE = {
    "overall": {"1": 74.5, "2": 59.1, "3": 65.8, "4": 42.0, "5": 11.8},
    "fast": {"〜148": 49.4, "149〜152": 51.0, "153〜": 53.6},
    "slow": {"〜148": 39.2, "149〜152": 40.7, "153〜": 36.2},
}


# 先発の球種の数と総変化量（`変化球の数と変化量_改修指示.md` 2-1）
AGE_BANDS = (("〜23", 0, 23), ("24〜29", 24, 29), ("30〜33", 30, 33), ("34〜", 34, 999))
CONTROL_BANDS = (("〜44", 0, 44), ("45〜54", 45, 54), ("55〜64", 55, 64), ("65〜", 65, 999))
TOL_COUNT_MIN, TOL_MOVEMENT_BY_COUNT = 0.10, 0.3
FOUR_YOUNG_MAX_AGE, FOUR_LOW_CONTROL = 23, 50
FOUR_LIMIT, FOUR_STARTER_RANGE = 0.5, (1.0, 4.0)  # %
STARTER_SPEED_CORR, STARTER_COUNT_CORR, RELIEVER_SPEED_CORR = (0.05, 0.25), (0.33, 0.53), (-0.05, 0.12)
FAST_STARTER, SLOW_STARTER = 154, 148
COUNT_SECTION = "先発の球種の数と総変化量（第一球種。実在は2024〜2026年版の日本人投手。誤差は異なる選手の数）"


def canonical(name: str) -> str:
    """判定で数える球種名（スクリューはシンカーに合わせる）。"""
    return "シンカー" if name == "スクリュー" else name


def speed_x(speed: float, hand: str) -> float:
    return max(-X_LIMIT, min(X_LIMIT, (float(speed) - CENTER[hand]) / WIDTH))


def band_of(speed: float, bands: tuple[tuple[str, int, int], ...]) -> str | None:
    if speed is None or (isinstance(speed, float) and math.isnan(speed)):
        return None
    return next((label for label, low, high in bands if low <= speed <= high), None)


# ---------------------------------------------------------------------------
# 1人分の列（実在・生成で共通）
# ---------------------------------------------------------------------------
def type_columns(balls: list[Any], *, real: bool) -> dict[str, Any]:
    """方向の組（第一球種の方向コードを並べた文字列）と、持つ球種（第一球種・第二球種。| 区切り、スクリューはシンカー）。"""
    primary, names = [], set()
    for ball in balls or []:
        if not isinstance(ball, dict) or ball.get("kind", "breaking") != "breaking":
            continue
        name = canonical(str(ball.get("name") or ""))
        if name:
            names.add(name)
        is_second = int(ball.get("slot") or 1) > 1 if real else bool(ball.get("is_second_pitch"))
        if not is_second and ball.get("direction_code"):
            primary.append(str(ball.get("direction_code")))
    return {"pt_dirs": "".join(sorted(set(primary))), "pt_names": "|".join(sorted(names))}


# ---------------------------------------------------------------------------
# 実在
# ---------------------------------------------------------------------------
def load_real_rows() -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """実在（2024〜2026年版）の日本人投手の行と、第一球種の球の並び（表づくりに使う）。"""
    import build_real_team_reference as ref
    from generator import real_data
    from generator import team_analysis as ta

    foreign_keys = ref.foreign_list_keys(ref.DEFAULT_FOREIGN_LIST)
    entry = ref.load_entry_route(ref.DEFAULT_ENTRY_ROUTE)
    rows, balls_out = [], []
    with tempfile.TemporaryDirectory() as temp:
        folders = ref.extract_seasons(ref.DEFAULT_ZIP, Path(temp))
        folders[real_data.AGE_SEASON] = ref.DEFAULT_RAW_2026
        for season, folder in sorted(folders.items()):
            if season not in REAL_SEASONS:
                continue
            tables, _ = ref.parse_directory(folder)
            players = ref.decorate_season(tables["players"], season, foreign_keys, entry)
            breaking = real_data.usable_breaking_rows(tables["breaking"])
            breaking = breaking[breaking["kind"].fillna("breaking").astype(str) == "breaking"]
            ball_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
            for item in breaking.itertuples():
                movement = pd.to_numeric(item.movement, errors="coerce")
                slot = pd.to_numeric(item.slot, errors="coerce")
                ball_map.setdefault((item.team, item.name), []).append({
                    "kind": "breaking", "name": str(item.canonical_pitch_type or item.pitch_type or ""),
                    "direction_code": str(item.direction_code or ""), "movement": 0 if pd.isna(movement) else int(movement),
                    "slot": 1 if pd.isna(slot) else int(slot),
                })
            for row in players.to_dict("records"):
                if row.get("is_foreign") or row.get("role") != "投手":
                    continue
                throws, _bats = ta._hand_parts(row.get("throws_bats"))
                hand = "左投" if throws == "左" else "右投"
                speed = pd.to_numeric(row.get("top_speed"), errors="coerce")
                if pd.isna(speed):
                    continue
                balls = ball_map.get((row["team"], row["name"]), [])
                name = "".join(str(row.get("name") or "").split())
                role = "先発" if str(row.get("pitcher_roles") or "")[:1] == "先" else "救援"
                primary = [ball for ball in balls if ball["slot"] <= 1]
                rows.append({"season": season, "name": name, "hand": hand, "prole": role, "球速": float(speed),
                             "age": pd.to_numeric(row.get("age_backcalc"), errors="coerce"),
                             "コントロール": pd.to_numeric(row.get("control"), errors="coerce"),
                             "スタミナ": pd.to_numeric(row.get("stamina"), errors="coerce"),
                             "変化球数": float(len(primary)), "総変化量": float(sum(ball["movement"] for ball in primary)),
                             **type_columns(balls, real=True)})
                balls_out.append({"name": name, "hand": hand, "x": speed_x(float(speed), hand), "balls": primary})
    return pd.DataFrame(rows), balls_out


def _minimize(fun, theta: np.ndarray, iters: int = 4000, tol: float = 1e-9) -> np.ndarray:
    """L-BFGS（バックトラッキングの直線探索つき）。fun(theta) は (値, 勾配) を返す。scipy に頼らないための小さな実装。"""
    value, grad = fun(theta)
    s_hist: list[np.ndarray] = []
    y_hist: list[np.ndarray] = []
    for _ in range(iters):
        q = grad.copy()
        alphas = []
        for s, y in reversed(list(zip(s_hist, y_hist))):
            a = s @ q / (y @ s)
            alphas.append(a)
            q -= a * y
        if s_hist:
            q *= (s_hist[-1] @ y_hist[-1]) / (y_hist[-1] @ y_hist[-1])
        for (s, y), a in zip(zip(s_hist, y_hist), reversed(alphas)):
            b = y @ q / (y @ s)
            q += s * (a - b)
        direction = -q
        if direction @ grad >= 0:
            direction, s_hist, y_hist = -grad, [], []
        step = 1.0
        while True:
            new_theta = theta + step * direction
            new_value, new_grad = fun(new_theta)
            if new_value <= value + 1e-4 * step * (direction @ grad) or step < 1e-12:
                break
            step *= 0.5
        s, y = new_theta - theta, new_grad - grad
        if y @ s > 1e-12:
            s_hist.append(s)
            y_hist.append(y)
            s_hist, y_hist = s_hist[-10:], y_hist[-10:]
        converged = abs(value - new_value) < tol * max(1.0, abs(value))
        theta, value, grad = new_theta, new_value, new_grad
        if converged and np.max(np.abs(grad)) < 1e-5:
            break
    return theta


def _softmax_rows(scores: np.ndarray) -> np.ndarray:
    scores = scores - scores.max(axis=1, keepdims=True)
    e = np.exp(scores)
    return e / e.sum(axis=1, keepdims=True)


def fit_direction_sets(samples: list[dict[str, Any]], hand: str) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """方向の組の重み（k=2・3、x=0 の%）と方向の傾き（スライダー方向は0）。"""
    import itertools

    combos = {k: ["".join(c) for c in itertools.combinations(CODES, k)] for k in (2, 3)}
    data = {k: ([], []) for k in (2, 3)}
    for sample in samples:
        if sample["hand"] != hand:
            continue
        dirs = "".join(sorted({ball["direction_code"] for ball in sample["balls"] if ball["direction_code"] in CODES}))
        if len(dirs) in data and len(dirs) == len(sample["balls"]):
            data[len(dirs)][0].append(combos[len(dirs)].index(dirs))
            data[len(dirs)][1].append(sample["x"])
    members = {k: np.array([[1.0 if code in combo else 0.0 for code in CODES] for combo in combos[k]]) for k in (2, 3)}
    n2, n3 = len(combos[2]), len(combos[3])

    def fun(theta: np.ndarray) -> tuple[float, np.ndarray]:
        beta = np.concatenate([[0.0], theta[n2 + n3:]])
        value, grad = 0.0, np.zeros_like(theta)
        for k, offset, n in ((2, 0, n2), (3, n2, n3)):
            chosen, xs = np.array(data[k][0], dtype=int), np.array(data[k][1])
            a = theta[offset:offset + n]
            if len(chosen):
                scores = a[None, :] + xs[:, None] * (members[k] @ beta)[None, :]
                p = _softmax_rows(scores)
                log_norm = np.log(np.exp(scores - scores.max(axis=1, keepdims=True)).sum(axis=1)) + scores.max(axis=1)
                value -= float((scores[np.arange(len(chosen)), chosen] - log_norm).sum())
                onehot = np.zeros_like(p)
                onehot[np.arange(len(chosen)), chosen] = 1.0
                diff = onehot - p
                grad[offset:offset + n] -= diff.sum(axis=0)
                grad[n2 + n3:] -= ((diff @ members[k]) * xs[:, None]).sum(axis=0)[1:]
            centered = a - a.mean()
            value += 0.5 * SET_RIDGE * float(centered @ centered)
            grad[offset:offset + n] += SET_RIDGE * centered
        return value, grad

    theta = _minimize(fun, np.zeros(n2 + n3 + 4))
    weights = {}
    for k, offset, n in ((2, 0, n2), (3, n2, n3)):
        a = theta[offset:offset + n]
        share = np.exp(a - a.max())
        share = share / share.sum() * 100
        weights[str(k)] = {combo: round(float(v), 2) for combo, v in zip(combos[k], share)}
    slopes = {"1": 0.0, **{code: round(float(v), 3) for code, v in zip(CODES[1:], theta[n2 + n3:])}}
    return weights, slopes


def single_direction_weights(samples: list[dict[str, Any]]) -> dict[str, float]:
    """1球種の方向の割合（右投手の件数＋疑似カウント1。両投げ手で使う。合計100に丸める）。"""
    counts = {code: 1.0 for code in CODES}
    for sample in samples:
        if sample["hand"] == "右投" and len(sample["balls"]) == 1 and sample["balls"][0]["direction_code"] in CODES:
            counts[sample["balls"][0]["direction_code"]] += 1
    total = sum(counts.values())
    shares = {code: counts[code] / total * 100 for code in CODES}
    rounded = {code: int(round(v)) for code, v in shares.items()}
    top = max(rounded, key=rounded.get)
    rounded[top] += 100 - sum(rounded.values())
    return {code: rounded[code] for code in sorted(CODES, key=lambda c: (-rounded[c], c))}


def allowed_names(hand: str, code: str) -> list[str]:
    import app

    return sorted(name for name in app.allowed_pitch_names_for_generation(code, f"{hand}右打") if name not in EXCLUDED_NAMES)


def table_name(name: str, hand: str, code: str) -> str:
    """実在の球種名を表の球種名にする（左投手のシンカー方向のシンカーはスクリュー）。"""
    return "スクリュー" if hand == "左投" and code == "4" and name == "シンカー" else name


def fit_pitch_types(samples: list[dict[str, Any]]) -> tuple[dict[str, dict[str, dict[str, float]]], dict[str, float]]:
    """球種の重み（投げ手 × 方向、x=0 の%）と球種の傾き（両投げ手で共通。スクリューはシンカーと同じ）。"""
    groups = [(hand, code, allowed_names(hand, code)) for hand in HANDS for code in CODES]
    slope_names = sorted({canonical(name) for _h, _c, names in groups for name in names})
    obs: dict[tuple[str, str], tuple[list[int], list[float]]] = {(h, c): ([], []) for h, c, _n in groups}
    for sample in samples:
        for ball in sample["balls"]:
            hand, code = sample["hand"], ball["direction_code"]
            if code not in CODES:
                continue
            names = next(n for h, c, n in groups if h == hand and c == code)
            name = table_name(ball["name"], hand, code)
            if name in names:
                obs[(hand, code)][0].append(names.index(name))
                obs[(hand, code)][1].append(sample["x"])
    offsets, total = [], 0
    for _h, _c, names in groups:
        offsets.append(total)
        total += len(names)
    slope_index = {name: total + i for i, name in enumerate(slope_names)}

    def fun(theta: np.ndarray) -> tuple[float, np.ndarray]:
        value, grad = 0.0, np.zeros_like(theta)
        for (hand, code, names), offset in zip(groups, offsets):
            n = len(names)
            a = theta[offset:offset + n]
            g_index = np.array([slope_index[canonical(name)] for name in names])
            gamma = theta[g_index]
            chosen, xs = np.array(obs[(hand, code)][0], dtype=int), np.array(obs[(hand, code)][1])
            if len(chosen):
                scores = a[None, :] + xs[:, None] * gamma[None, :]
                p = _softmax_rows(scores)
                log_norm = np.log(np.exp(scores - scores.max(axis=1, keepdims=True)).sum(axis=1)) + scores.max(axis=1)
                value -= float((scores[np.arange(len(chosen)), chosen] - log_norm).sum())
                onehot = np.zeros_like(p)
                onehot[np.arange(len(chosen)), chosen] = 1.0
                diff = onehot - p
                grad[offset:offset + n] -= diff.sum(axis=0)
                np.add.at(grad, g_index, -(diff * xs[:, None]).sum(axis=0))
            centered = a - a.mean()
            value += 0.5 * NAME_RIDGE * float(centered @ centered)
            grad[offset:offset + n] += NAME_RIDGE * centered
        gamma_all = theta[total:]
        value += 0.5 * float(gamma_all @ gamma_all) / SLOPE_PRIOR_SD ** 2
        grad[total:] += gamma_all / SLOPE_PRIOR_SD ** 2
        return value, grad

    theta = _minimize(fun, np.zeros(total + len(slope_names)))
    weights: dict[str, dict[str, dict[str, float]]] = {hand: {} for hand in HANDS}
    for (hand, code, names), offset in zip(groups, offsets):
        a = theta[offset:offset + len(names)]
        share = np.exp(a - a.max())
        share = share / share.sum() * 100
        weights[hand][code] = {name: round(float(v), 2) for name, v in zip(names, share)}
    slopes = {}
    for _h, _c, names in groups:
        for name in names:
            slopes.setdefault(name, round(float(theta[slope_index[canonical(name)]]), 3))
    return weights, slopes


def movement_likelihood(samples: list[dict[str, Any]]) -> dict[str, list[float]]:
    """球種ごとの変化量1〜6の割合（件数 + 同じ方向の割合 × 3件、を均した値）。スクリューはシンカーと同じ。"""
    import app

    by_name: dict[str, np.ndarray] = {}
    by_code: dict[str, np.ndarray] = {code: np.zeros(6) for code in CODES}
    for sample in samples:
        for ball in sample["balls"]:
            code, movement = ball["direction_code"], int(ball["movement"])
            if code not in CODES or not 1 <= movement:
                continue
            index = min(movement, 6) - 1
            by_code[code][index] += 1
            by_name.setdefault(canonical(ball["name"]), np.zeros(6))[index] += 1
    out = {}
    for ball in app.BREAKING_BALL_MASTER:
        name, code = ball["name"], ball["direction_code"]
        share = by_code[code] / by_code[code].sum()
        counts = by_name.get(canonical(name), np.zeros(6))
        smoothed = (counts + MOVEMENT_PSEUDO * share) / (counts.sum() + MOVEMENT_PSEUDO)
        out[name] = [round(float(v), 3) for v in smoothed]
    return out


def build_table(samples: list[dict[str, Any]]) -> dict[str, Any]:
    set_weights, set_slopes = {}, {}
    single = single_direction_weights(samples)
    for hand in HANDS:
        weights, slopes = fit_direction_sets(samples, hand)
        set_weights[hand] = {**weights, "1": single}
        set_slopes[hand] = slopes
    name_weights, name_slopes = fit_pitch_types(samples)
    return {
        "説明": "架空球団用の日本人投手の変化球の方向と球種を、球速と投げ手で実在（2024〜2026年版の日本人投手）の表から引き直す。"
                "x=(球速−中心)/4 を −2.5〜2.5 に収める。",
        "中心": dict(CENTER), "幅": WIDTH, "x上限": X_LIMIT,
        "方向の組の重み": set_weights, "方向の傾き": set_slopes,
        "球種の重み": name_weights, "球種の傾き": name_slopes,
        "変化量の起こりやすさ": movement_likelihood(samples),
    }


def compare_tables(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """試作表と作り直した表の差（傾きは0.1以上、割合は5ポイント以上を「大きい差」として印を付ける）。"""
    lines = []

    def line(label: str, a: float, b: float, big: float) -> None:
        mark = " ★大きい差" if abs(b - a) >= big else ""
        lines.append(f"  {label}: 試作 {a:+.3f} → 作り直し {b:+.3f}（差 {b - a:+.3f}）{mark}")

    lines.append("[方向の傾き]")
    for hand in HANDS:
        for code in CODES:
            line(f"{hand} {DIRECTION_LABELS[code]}", old["方向の傾き"][hand][code], new["方向の傾き"][hand][code], 0.1)
    # 同じ方向の球種の傾きを一律にずらしても割合は変わらない（ずれは事前分布の置き方だけで決まる）ので、
    # 方向ごとに平均の差をそろえてから比べる。
    lines.append("[球種の傾き（方向ごとの一律のずれを除いた差）]")
    for code in CODES:
        names = sorted({name for hand in HANDS for name in old["球種の重み"][hand].get(code, {})})
        diffs = {name: new["球種の傾き"].get(name, math.nan) - old["球種の傾き"][name] for name in names}
        shift = sum(diffs.values()) / len(diffs)
        lines.append(f"  ({DIRECTION_LABELS[code]} 一律のずれ {shift:+.3f})")
        for name in names:
            line(name, old["球種の傾き"][name], old["球種の傾き"][name] + diffs[name] - shift, 0.1)
    lines.append("[方向の組の重み（%）]")
    for hand in HANDS:
        for k in ("1", "2", "3"):
            for combo, value in old["方向の組の重み"][hand][k].items():
                line(f"{hand} k={k} {combo}", value, new["方向の組の重み"][hand][k].get(combo, math.nan), 5.0)
    lines.append("[球種の重み（%）]")
    for hand in HANDS:
        for code, items in old["球種の重み"][hand].items():
            for name, value in items.items():
                line(f"{hand} {DIRECTION_LABELS[code]} {name}", value, new["球種の重み"][hand][code].get(name, math.nan), 5.0)
    lines.append("[変化量の起こりやすさ（最大の差）]")
    for name, values in old["変化量の起こりやすさ"].items():
        other = new["変化量の起こりやすさ"].get(name, [math.nan] * 6)
        diff = max(abs(a - b) for a, b in zip(values, other))
        lines.append(f"  {name}: 最大の差 {diff:.3f}{' ★大きい差' if diff >= 0.05 else ''}")
    return lines


# ---------------------------------------------------------------------------
# 集計（実在・生成で共通。frame は hand・prole・球速・pt_dirs・pt_names の列を持つ）
# ---------------------------------------------------------------------------
def _has_dir(frame: pd.DataFrame, code: str) -> pd.Series:
    return frame["pt_dirs"].astype(str).str.contains(code, regex=False)


def _pct(mask: pd.Series) -> float:
    return float(mask.mean() * 100) if len(mask) else math.nan


def _distinct(frame: pd.DataFrame) -> int:
    return int(frame["name"].nunique()) if "name" in frame.columns else int(len(frame))


def _mean_stat(frame: pd.DataFrame, column: str) -> list[float]:
    """[平均, 標準偏差, 異なる選手の数]。"""
    x = pd.to_numeric(frame[column], errors="coerce").dropna()
    return [round(float(x.mean()), 4) if len(x) else math.nan, round(float(x.std()), 4) if len(x) > 1 else math.nan, _distinct(frame.loc[x.index])]


def _corr(frame: pd.DataFrame, a: str, b: str) -> float:
    x = frame[[a, b]].apply(pd.to_numeric, errors="coerce").dropna()
    return round(float(x[a].corr(x[b])), 4) if len(x) > 2 else math.nan


def count_statistics(frame: pd.DataFrame) -> dict[str, Any]:
    """先発の球種の数と総変化量（指示書2-1）。frame は prole・age・コントロール・スタミナ・球速・変化球数・総変化量の列を持つ。"""
    starter = frame[frame["prole"] == "先発"]
    relief = frame[frame["prole"] == "救援"]
    out: dict[str, Any] = {"年齢帯": {}, "コントロール帯": {}}
    for key, column, bands in (("年齢帯", "age", AGE_BANDS), ("コントロール帯", "コントロール", CONTROL_BANDS)):
        values = pd.to_numeric(starter[column], errors="coerce")
        for band, low, high in bands:
            part = starter[(values >= low) & (values <= high)]
            out[key][band] = {"球種数": _mean_stat(part, "変化球数"), "2球種": round(_pct(part["変化球数"] == 2), 2),
                              "4球種": round(_pct(part["変化球数"] >= 4), 2)}
    age = pd.to_numeric(starter["age"], errors="coerce")
    control = pd.to_numeric(starter["コントロール"], errors="coerce")
    out["4球種"] = {
        "〜23歳": round(_pct(starter.loc[age <= FOUR_YOUNG_MAX_AGE, "変化球数"] >= 4), 2),
        "コントロール50未満": round(_pct(starter.loc[control < FOUR_LOW_CONTROL, "変化球数"] >= 4), 2),
        "先発全体": round(_pct(starter["変化球数"] >= 4), 2),
    }
    out["総変化量"] = {}
    for role, part in (("先発", starter), ("救援", relief)):
        out["総変化量"][role] = {"平均と標準偏差": _mean_stat(part, "総変化量"), **{
            f"×{column}": _corr(part, "総変化量", column) for column in ("コントロール", "スタミナ", "球速", "変化球数")}}
    out["球種数ごとの総変化量"] = {str(k): _mean_stat(starter[starter["変化球数"] == k], "総変化量") for k in (2, 3)}
    speed = pd.to_numeric(starter["球速"], errors="coerce")
    out["球速ごとの総変化量"] = {f"{FAST_STARTER}以上": _mean_stat(starter[speed >= FAST_STARTER], "総変化量"),
                         f"{SLOW_STARTER}以下": _mean_stat(starter[speed <= SLOW_STARTER], "総変化量")}
    return out


def statistics(frame: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"方向の保有率": {}, "全体の方向の保有率": {}, "速い・遅い球種": {}, "球種の保有率": {}, "球速の差": {}, "方向の組": {}}
    sets = frame["pt_names"].fillna("").astype(str).str.split("|").map(set)
    names = sorted({name for items in sets for name in items if name})
    has = {name: sets.map(lambda items, n=name: n in items) for name in names}
    fast = sets.map(lambda items: not items.isdisjoint(FAST_NAMES))
    slow = sets.map(lambda items: not items.isdisjoint(SLOW_NAMES))
    for hand in HANDS:
        part = frame[frame["hand"] == hand]
        bands = part["球速"].map(lambda v: band_of(v, SPEED_BANDS[hand]))
        out["方向の保有率"][hand] = {}
        for band, _low, _high in SPEED_BANDS[hand]:
            b = part[bands == band]
            out["方向の保有率"][hand][band] = {**{code: round(_pct(_has_dir(b, code)), 2) for code in CODES}, "異なる選手の数": _distinct(b)}
    out["全体の方向の保有率"] = {**{code: round(_pct(_has_dir(frame, code)), 2) for code in CODES}, "異なる選手の数": _distinct(frame)}
    bands = frame["球速"].map(lambda v: band_of(v, TYPE_BANDS))
    for band, _low, _high in TYPE_BANDS:
        mask = bands == band
        out["速い・遅い球種"][band] = {"速い": round(_pct(fast[mask]), 2), "遅い": round(_pct(slow[mask]), 2), "異なる選手の数": _distinct(frame[mask])}
    out["球種の保有率"] = {name: round(_pct(has[name]), 2) for name in names}
    starter = frame["prole"] == "先発"
    mean_speed = float(frame.loc[starter, "球速"].mean()) if starter.any() else math.nan
    for name in names:
        holders = frame[starter & has[name]]
        out["球速の差"][name] = [round(float(holders["球速"].mean()) - mean_speed, 3) if len(holders) else math.nan, _distinct(holders)]
    combos = frame["pt_dirs"].astype(str)
    out["方向の組"] = {combo: round(float((combos == combo).mean() * 100), 2) for combo in sorted(combos.unique()) if combo}
    return out


def build_real(write_table: bool = False) -> None:
    rows, samples = load_real_rows()
    stats = statistics(rows)
    data = {
        "作り方": "python scripts/pitch_type_speed.py --build-real。実在（2024〜2026年版）の日本人投手（外国人を除く）。方向は第一球種（slot 1）、"
                 "球種は第一球種・第二球種（シンカーとスクリューは「シンカー」）。割合は%で、年版ごとの行で数える。"
                 "異なる選手の数は名前で数えた（誤差に使う）。球速の差は、その球種を持つ先発の球速の平均と先発全体の平均の差 [差, 異なる選手の数]。"
                 "先発の球種の数と総変化量は第一球種で数え、平均は [平均, 標準偏差, 異なる選手の数]（年齢は2024・2025年版は逆算）。",
        "人数": int(len(rows)), "異なる選手の数": _distinct(rows),
        **stats,
        "先発の球種の数と総変化量": count_statistics(rows),
    }
    REAL_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"書き出しました: {REAL_PATH}（{len(rows)}人、異なる選手 {_distinct(rows)}人）")
    table = build_table(samples)
    REBUILT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REBUILT_PATH.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"書き出しました: {REBUILT_PATH}")
    if TABLE_PATH.exists():
        print("\n[試作表（data/config/fictional_pitch_type_speed.json）と作り直した表の差]")
        print("\n".join(compare_tables(json.loads(TABLE_PATH.read_text(encoding="utf-8")), table)))
    if write_table:
        TABLE_PATH.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"書き出しました: {TABLE_PATH}")


def real_reference() -> dict[str, Any]:
    return json.loads(REAL_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------
def share_se(share: float, n: int) -> float:
    p = share / 100
    return math.sqrt(p * (1 - p) / n) * 100 if n > 1 else math.nan


def _band_tol(share: float, n: int, minimum: float) -> float:
    se = share_se(share, n)
    return max(minimum, 2 * se) if not math.isnan(se) else minimum


def checked_names(real: dict[str, Any]) -> list[str]:
    return [name for name, value in real["球種の保有率"].items() if value >= NAME_MIN_SHARE]


def checked_combos(real: dict[str, Any]) -> list[str]:
    return [combo for combo, value in real["方向の組"].items() if value >= COMBO_MIN_SHARE]


def type_checks(checks: Checks, frame: pd.DataFrame, prefix: str, kind: str) -> None:
    """指示書2-1 の判定。frame は hand・prole・球速・pt_dirs・pt_names の列を持つ（生成）。"""
    real, now = real_reference(), statistics(frame)
    design = checklib.KIND_INFO if kind == checklib.KIND_INFO else checklib.KIND_DESIGN

    def add(key: str, label: str, value: float, low: float, high: float, real_text: str, fmt: str = "{:.1f}", item_kind: str = kind) -> None:
        checks.add(f"{prefix}.pitch_type.{key}", item_kind, label, value, low, high, section=SECTION,
                   shown="nan" if math.isnan(value) else fmt.format(value), target=f"{fmt.format(low)}〜{fmt.format(high)}", real=real_text)

    for hand in HANDS:
        for band, _low, _high in SPEED_BANDS[hand]:
            r = real["方向の保有率"][hand][band]
            for code in BAND_CODES[hand]:
                tol = _band_tol(r[code], r["異なる選手の数"], TOL_BAND_MIN)
                add(f"band.{hand}.{band}.{code}", f"{hand} 球速{band} {DIRECTION_LABELS[code]}の保有率", now["方向の保有率"][hand][band][code],
                    r[code] - tol, r[code] + tol, f"{r[code]:.1f}（{r['異なる選手の数']}人）")
    r = real["全体の方向の保有率"]
    for code in CODES:
        add(f"overall.{code}", f"全体 {DIRECTION_LABELS[code]}の保有率", now["全体の方向の保有率"][code], r[code] - TOL_OVERALL, r[code] + TOL_OVERALL, f"{r[code]:.1f}")
    for band, _low, _high in TYPE_BANDS:
        r = real["速い・遅い球種"][band]
        for key, label in (("速い", "fast"), ("遅い", "slow")):
            tol = _band_tol(r[key], r["異なる選手の数"], TOL_BAND_MIN)
            add(f"{label}.{band}", f"球速{band} {key}投手の球種を持つ割合", now["速い・遅い球種"][band][key], r[key] - tol, r[key] + tol,
                f"{r[key]:.1f}（{r['異なる選手の数']}人）")
    n_all = real["異なる選手の数"]
    for name in checked_names(real):
        rv = real["球種の保有率"][name]
        tol = _band_tol(rv, n_all, TOL_NAME_MIN)
        add(f"name.{name}", f"{name}の保有率", now["球種の保有率"].get(name, 0.0), rv - tol, rv + tol, f"{rv:.1f}")
    split = now["球種の保有率"].get("シンキングスプリット", 0.0)
    add("split", "シンキングスプリットの保有率", split, 0.0, SPLIT_MAX, f"{real['球種の保有率'].get('シンキングスプリット', 0.0):.1f}", item_kind=design)
    for name in SPEED_DIFF_NAMES:
        rv = real["球速の差"][name][0]
        low, high = (max(rv - TOL_SPEED_DIFF, 0.0), rv + TOL_SPEED_DIFF) if rv > 0 else (rv - TOL_SPEED_DIFF, min(rv + TOL_SPEED_DIFF, 0.0))
        add(f"speed_diff.{name}", f"先発 {name}を持つ投手の球速−全体の平均", now["球速の差"].get(name, [math.nan])[0], low, high,
            f"{rv:+.2f}（{real['球速の差'][name][1]}人）", fmt="{:+.2f}")
    for combo in checked_combos(real):
        rv = real["方向の組"][combo]
        label = "＋".join(DIRECTION_LABELS[code][:-2] for code in combo)
        add(f"combo.{combo}", f"方向の組 {label}", now["方向の組"].get(combo, 0.0), rv - TOL_COMBO, rv + TOL_COMBO, f"{rv:.1f}")
    # 参考: 右投手のシュート方向（帯ごと）
    for band, _low, _high in SPEED_BANDS["右投"]:
        r = real["方向の保有率"]["右投"][band]
        value = now["方向の保有率"]["右投"][band]["5"]
        checks.info(f"{prefix}.pitch_type.reference.右投.{band}.5", f"右投 球速{band} シュート方向の保有率", value, section=SECTION,
                    shown=f"{value:.1f}", real=f"{r['5']:.1f}（{r['異なる選手の数']}人）")


def real_errors(prefix: str) -> dict[str, float]:
    """実在側の誤差（割合は √(p(1−p)/異なる選手の数)）。球速の差は持つ先発の異なる選手の数で、球速の標準偏差を4として見積もる。"""
    real = real_reference()
    se: dict[str, float] = {}
    for hand in HANDS:
        for band, _low, _high in SPEED_BANDS[hand]:
            r = real["方向の保有率"][hand][band]
            for code in BAND_CODES[hand]:
                se[f"{prefix}.pitch_type.band.{hand}.{band}.{code}"] = share_se(r[code], r["異なる選手の数"])
    n_all = real["異なる選手の数"]
    for code in CODES:
        se[f"{prefix}.pitch_type.overall.{code}"] = share_se(real["全体の方向の保有率"][code], n_all)
    for band, _low, _high in TYPE_BANDS:
        r = real["速い・遅い球種"][band]
        se[f"{prefix}.pitch_type.fast.{band}"] = share_se(r["速い"], r["異なる選手の数"])
        se[f"{prefix}.pitch_type.slow.{band}"] = share_se(r["遅い"], r["異なる選手の数"])
    for name in checked_names(real):
        se[f"{prefix}.pitch_type.name.{name}"] = share_se(real["球種の保有率"][name], n_all)
    for name in SPEED_DIFF_NAMES:
        n = real["球速の差"][name][1]
        se[f"{prefix}.pitch_type.speed_diff.{name}"] = 4.0 / math.sqrt(n) if n > 1 else math.nan
    for combo in checked_combos(real):
        se[f"{prefix}.pitch_type.combo.{combo}"] = share_se(real["方向の組"][combo], n_all)
    return se


def _mean_se(stat: list[float]) -> float:
    return stat[1] / math.sqrt(stat[2]) if stat[2] > 1 and not math.isnan(stat[1]) else math.nan


def count_checks(checks: Checks, frame: pd.DataFrame, prefix: str, kind: str) -> None:
    """先発の球種の数と総変化量の判定（`変化球の数と変化量_改修指示.md` 2-1）。frame は count_statistics の列を持つ（生成）。"""
    real, now = real_reference()["先発の球種の数と総変化量"], count_statistics(frame)
    design = checklib.KIND_INFO if kind == checklib.KIND_INFO else checklib.KIND_DESIGN

    def add(key: str, label: str, value: float, low: float, high: float, real_text: str, fmt: str = "{:.2f}", item_kind: str = kind) -> None:
        checks.add(f"{prefix}.pitch_count.{key}", item_kind, label, value, low, high, section=COUNT_SECTION,
                   shown="nan" if math.isnan(value) else fmt.format(value), target=f"{fmt.format(low)}〜{fmt.format(high)}", real=real_text)

    for key, short, bands in (("年齢帯", "age", AGE_BANDS), ("コントロール帯", "control", CONTROL_BANDS)):
        prefix_label = "年齢" if short == "age" else "コントロール"
        for band, _low, _high in bands:
            r = real[key][band]["球種数"]
            se = _mean_se(r)
            tol = max(TOL_COUNT_MIN, 2 * se) if not math.isnan(se) else TOL_COUNT_MIN
            add(f"{short}.{band}", f"先発 {prefix_label}{band}の球種数の平均", now[key][band]["球種数"][0], r[0] - tol, r[0] + tol,
                f"{r[0]:.2f}（{r[2]}人）")
    for key, label in (("〜23歳", "23歳以下の先発の4球種"), ("コントロール50未満", "コントロール50未満の先発の4球種")):
        add(f"four.{key}", label, now["4球種"][key], 0.0, FOUR_LIMIT, f"{real['4球種'][key]:.1f}", fmt="{:.1f}", item_kind=design)
    add("four.先発全体", "先発全体の4球種（%）", now["4球種"]["先発全体"], *FOUR_STARTER_RANGE, f"{real['4球種']['先発全体']:.1f}", fmt="{:.1f}",
        item_kind=design)
    for role, column, key, (low, high) in (("先発", "球速", "starter_speed", STARTER_SPEED_CORR), ("先発", "変化球数", "starter_count", STARTER_COUNT_CORR),
                                           ("救援", "球速", "reliever_speed", RELIEVER_SPEED_CORR)):
        r = real["総変化量"][role][f"×{column}"]
        add(f"corr.{key}", f"{role}の総変化量×{column}相関", now["総変化量"][role][f"×{column}"], low, high, f"{r:.3f}", fmt="{:.3f}")
    for k in ("2", "3"):
        r = real["球種数ごとの総変化量"][k]
        add(f"movement.{k}", f"先発 {k}球種の総変化量の平均", now["球種数ごとの総変化量"][k][0], r[0] - TOL_MOVEMENT_BY_COUNT, r[0] + TOL_MOVEMENT_BY_COUNT,
            f"{r[0]:.2f}（{r[2]}人）")
    r = real["球速ごとの総変化量"][f"{FAST_STARTER}以上"]
    tol = 2 * _mean_se(r)
    add("movement.fast", f"{FAST_STARTER}km以上の先発の総変化量の平均", now["球速ごとの総変化量"][f"{FAST_STARTER}以上"][0], r[0] - tol, r[0] + tol,
        f"{r[0]:.2f}（{r[2]}人）")


def count_real_errors(prefix: str) -> dict[str, float]:
    """実在側の誤差（平均は 標準偏差/√異なる選手の数）。4球種・相関は範囲を固定で決めたので、生成側の誤差だけ。"""
    real = real_reference()["先発の球種の数と総変化量"]
    se: dict[str, float] = {}
    for key, short, bands in (("年齢帯", "age", AGE_BANDS), ("コントロール帯", "control", CONTROL_BANDS)):
        for band, _low, _high in bands:
            se[f"{prefix}.pitch_count.{short}.{band}"] = _mean_se(real[key][band]["球種数"])
    for k in ("2", "3"):
        se[f"{prefix}.pitch_count.movement.{k}"] = _mean_se(real["球種数ごとの総変化量"][k])
    se[f"{prefix}.pitch_count.movement.fast"] = _mean_se(real["球速ごとの総変化量"][f"{FAST_STARTER}以上"])
    return se


def print_count_reference(frame: pd.DataFrame) -> None:
    """先発の球種の数（年齢帯・コントロール帯）と総変化量の表（今回／実在。参考）。"""
    real, now = real_reference()["先発の球種の数と総変化量"], count_statistics(frame)
    for key, bands in (("年齢帯", AGE_BANDS), ("コントロール帯", CONTROL_BANDS)):
        rows = [{key: band, "平均": f"{now[key][band]['球種数'][0]:.2f}／{real[key][band]['球種数'][0]:.2f}",
                 "2球種": f"{now[key][band]['2球種']:.1f}／{real[key][band]['2球種']:.1f}",
                 "4球種": f"{now[key][band]['4球種']:.1f}／{real[key][band]['4球種']:.1f}",
                 "実在の異なる選手": real[key][band]["球種数"][2]} for band, _l, _h in bands]
        print(f"\n[先発の球種の数（{key}。今回／実在、%）。参考]")
        print(pd.DataFrame(rows).to_string(index=False))
    rows = []
    for label, path in (("平均", ("平均と標準偏差", 0)), ("標準偏差", ("平均と標準偏差", 1)), ("×コントロール相関", ("×コントロール", None)),
                        ("×スタミナ相関", ("×スタミナ", None)), ("×球速相関", ("×球速", None)), ("×球種数相関", ("×変化球数", None))):
        cells = {}
        for role in ("先発", "救援"):
            n, r = now["総変化量"][role][path[0]], real["総変化量"][role][path[0]]
            n, r = (n[path[1]], r[path[1]]) if path[1] is not None else (n, r)
            cells[role] = f"{n:.3f}／{r:.3f}"
        rows.append({"総変化量": label, **cells})
    print("\n[総変化量（今回／実在）。参考]")
    print(pd.DataFrame(rows).to_string(index=False))
    print("[先発の球種数ごと・球速ごとの総変化量（今回／実在）] " + "、".join(
        [f"{k}球種 {now['球種数ごとの総変化量'][k][0]:.2f}／{real['球種数ごとの総変化量'][k][0]:.2f}" for k in ("2", "3")]
        + [f"{key} {now['球速ごとの総変化量'][key][0]:.2f}／{real['球速ごとの総変化量'][key][0]:.2f}" for key in real["球速ごとの総変化量"]]))
    print("[先発の4球種（%、今回／実在）] " + "、".join(f"{k} {now['4球種'][k]:.1f}／{real['4球種'][k]:.1f}" for k in real["4球種"]))


def watch_notes(frame: pd.DataFrame) -> list[str]:
    """右投手148以下のシュート方向・スライダー方向が範囲（実在±誤差の2倍、最低±6ポイント）の外なら要注意として返す（指示書2-1）。"""
    real, now = real_reference(), statistics(frame)
    notes = []
    r = real["方向の保有率"]["右投"]["〜148"]
    for code in ("5", "1"):
        tol = _band_tol(r[code], r["異なる選手の数"], TOL_BAND_MIN)
        value = now["方向の保有率"]["右投"]["〜148"][code]
        if not r[code] - tol <= value <= r[code] + tol:
            notes.append(f"要注意: 右投 球速〜148 {DIRECTION_LABELS[code]} {value:.1f}（実在 {r[code]:.1f}、範囲 {r[code] - tol:.1f}〜{r[code] + tol:.1f}）")
    return notes


def print_type_reference(frame: pd.DataFrame, before: bool = True) -> None:
    """方向の保有率・速い/遅い球種・球種の保有率・球速の差（今回・実在。参考）。"""
    real, now = real_reference(), statistics(frame)
    print("\n[変化球の種類と球速: 方向の保有率（%、今回／実在）。参考]")
    for hand in HANDS:
        rows = []
        for code in CODES:
            rows.append({"方向": DIRECTION_LABELS[code], **{band: f"{now['方向の保有率'][hand][band][code]:.1f}／{real['方向の保有率'][hand][band][code]:.1f}"
                                                         for band, _l, _h in SPEED_BANDS[hand]}})
        rows.append({"方向": "実在の異なる選手", **{band: str(real["方向の保有率"][hand][band]["異なる選手の数"]) for band, _l, _h in SPEED_BANDS[hand]}})
        print(f"({hand})")
        print(pd.DataFrame(rows).to_string(index=False))
    print("[全体の方向の保有率（%）] " + "、".join(
        f"{DIRECTION_LABELS[c]} {now['全体の方向の保有率'][c]:.1f}／{real['全体の方向の保有率'][c]:.1f}"
        + (f"（改修前 {BEFORE['overall'][c]:.1f}）" if before else "") for c in CODES))
    print("[速い投手の球種・遅い投手の球種を1つ以上持つ割合（%、今回／実在）] " + "、".join(
        f"{band} 速い {now['速い・遅い球種'][band]['速い']:.1f}／{real['速い・遅い球種'][band]['速い']:.1f}"
        f" 遅い {now['速い・遅い球種'][band]['遅い']:.1f}／{real['速い・遅い球種'][band]['遅い']:.1f}" for band, _l, _h in TYPE_BANDS))
    names = sorted(set(now["球種の保有率"]) | set(real["球種の保有率"]), key=lambda n: -real["球種の保有率"].get(n, 0.0))
    print("[球種の保有率（%、今回／実在）] " + "、".join(f"{n} {now['球種の保有率'].get(n, 0.0):.1f}／{real['球種の保有率'].get(n, 0.0):.1f}" for n in names))
    print("[持つ先発の球速−先発全体の平均（今回／実在）] " + "、".join(
        f"{n} {now['球速の差'].get(n, [math.nan])[0]:+.2f}／{real['球速の差'].get(n, [math.nan])[0]:+.2f}" for n in SPEED_DIFF_REFERENCE))
    combos = sorted(real["方向の組"], key=lambda c: -real["方向の組"][c])[:10]
    print("[方向の組（%、今回／実在。実在の上位10）] " + "、".join(f"{c} {now['方向の組'].get(c, 0.0):.1f}／{real['方向の組'][c]:.1f}" for c in combos))
    for note in watch_notes(frame):
        print(note)


def main() -> None:
    parser = argparse.ArgumentParser(description="変化球の種類と球速の表を実在から作り直します。")
    parser.add_argument("--build-real", action="store_true", help="実在の値（data/config/pitch_type_speed_real.json）と作り直した表を書き出す")
    parser.add_argument("--write-table", action="store_true", help="作り直した表で data/config/fictional_pitch_type_speed.json を上書きする")
    args = parser.parse_args()
    if args.build_real:
        build_real(write_table=args.write_table)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
