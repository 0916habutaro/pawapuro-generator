#!/usr/bin/env python3
"""
架空球団 生成バランス チェッカー

使い方:
    python check_fictional_balance.py <生成CSV> [<生成CSV> ...] [--team] [--boot 200] [--update-baselines --reason 理由] [--quick]

- `category=架空球団用` の行だけを対象にし、そのうち日本人（`roster_origin=domestic`）を判定する。
  外国人（foreign_import）は `check_foreign_balance.py` の担当なので、ここでは人数だけ表示する。
- 判定基準は `架空球団バランス_改修指示.md` §9。
  ドキュメントの目標値を変えたときは、このファイルも合わせて直すこと。
- 「実在」列は、パワプロ 2022〜2026 実在12球団の日本人（延べ 投手1878人／野手1867人）の値（参考）。
  2026で新しく入った特能・球種は2026の値。
- 成長タイプ（実在はマスクデータ）と起用法（選手作成に関係しない）は判定しない。
- 球種数は外国人と同じ数え方（kind=breaking のみ。ストレートとストレート系第二球種は数えない）。
- `--team` を付けると、チーム単位で生成したCSV向けに「捕手・一塁手の比率」も合否に含める。
  付けない場合は参考表示だけ（投手／野手を別々に抽出したCSVでは比率に意味がないため）。
- 判定の種類・誤差・合否の付け方は checklib.py（判定の整理_改修指示.md）。判定の一覧は reports/checks/check_fictional_balance.csv。
- 終了コード: 不合格が1件でもあれば 1（要注意・受け入れ済みは 0）。
- 正式な判定は投手・野手それぞれ 5000人（例: seed 1〜5000）で行う。1000人の結果は途中確認用。
  基準に合わせるために分布そのものを歪めないこと。
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checklib  # noqa: E402
from checklib import Checks, in_range as ok_range  # noqa: E402,F401

SCRIPT = "check_fictional_balance"
# 実在の日本人の人数（2022〜2026年版の延べ。投手1878人／野手1867人）。実在側の誤差を、生成側の誤差の人数比で見積もる
REAL_N = {"投手": 1878, "野手": 1867}

# ---------------------------------------------------------------- 共通


def J(x):
    try:
        return json.loads(x) if isinstance(x, str) else (x or [])
    except Exception:
        return []


def pct(x):
    return "—" if pd.isna(x) else f"{x * 100:.1f}%"


def num(x, nd=2):
    return "—" if pd.isna(x) else f"{x:.{nd}f}"


def rate(mask, cond):
    """mask に当てはまる選手のうち cond を満たす割合（該当者なしは NaN）"""
    return cond[mask].mean() if mask.any() else float("nan")


def has_sp(sp, name):
    return sp.map(lambda l: name in l)


def any_rank(ranked, letter):
    return ranked.map(lambda d: any(v == letter for v in d.values()))


# 判定の id の節の部分。表示名を直しても id は変えないため、節の表示名（先頭一致）から決まった短い名前に対応させる
SECTION_KEYS = {
    "投打": "batting", "能力": "ability", "球速の左右・役割": "speed_hand", "コントロールの役割・左右": "control_hand",
    "救援のスタミナ": "reliever_stamina", "抑え・起用適性": "closer", "フォーム": "form", "変化球": "breaking",
    "特殊能力": "special", "ランク特能": "ranked", "サブポジ": "subpos", "ポジション（チーム単位）": "position",
    "プロ入り年齢": "entry", "相関（参考": "corr_info", "球団ごとの救援の平均": "team_mean",
}


def section_key(section):
    for head, key in SECTION_KEYS.items():
        if section.startswith(head):
            return key
    return re.sub(r"\W+", "_", section)


class Result:
    """判定の集まり。`add` は従来どおり（ok に `ok_range(...)` の結果を渡すと、値と範囲を判定に使う）。
    id は「<prefix>.<節のキー>.<項目名>」。項目名を直すときは id= で元の id を渡す。"""

    def __init__(self, prefix=SCRIPT):
        self.prefix = prefix
        self.checks = Checks(prefix)

    def _id(self, section, item, id):
        return id or f"{self.prefix}.{section_key(section)}.{item}"

    def add(self, section, item, value, ok, target, real="", info=False, kind=None, id=None):
        key = self._id(section, item, id)
        if kind is None:
            kind = "参考" if info else ("設計" if ("仕様" in target or item.startswith(("実在にない特能", "矛盾ペア"))) else "実在")
        if info:
            kind = "参考"
        if isinstance(ok, checklib.Verdict):
            self.checks.add(key, kind, item, ok.value, ok.low, ok.high, section=section, shown=str(value), target=target, real=str(real))
        else:  # 値と範囲が無い（True/False だけ）。条件を満たせば 1、満たさなければ 0
            self.checks.add(key, kind, item, 1.0 if ok else 0.0, 1.0, None, section=section, shown=str(value), target=target, real=str(real))

    def fixed(self, section, item, value, shown, target_real="", default_width=0.3, id=None):
        self.checks.fixed(self._id(section, item, id), item, value, default_width, section=section, shown=shown, real=target_real)

    def extend(self, other):
        self.checks.extend(other.checks)


def grade_part(fn, data, boot, real_n=None, quick=False):
    """fn(data) -> Result|Checks を評価し、データの行を再抽出した誤差で合否を付ける。"""
    evaluate = lambda d: (lambda r: r.checks if isinstance(r, Result) else r)(fn(d))  # noqa: E731
    checks = evaluate(data)
    se_gen = checklib.bootstrap_se(evaluate, data, checklib.resample_frame, n=boot) if boot else {}
    se_real = checklib.scale_se(se_gen, len(data), real_n) if real_n else {}
    return checklib.grade(checks, se_gen=se_gen, se_real=se_real, all_info=quick)


# ---------------------------------------------------------------- 生成CSV → 共通の形

COND_MAP = {"投手調子安定": "調子安定", "投手調子極端": "調子極端", "野手調子安定": "調子安定", "野手調子極端": "調子極端"}


def normalize(df):
    """生成CSVを判定用の列にそろえる。
    sp: 特殊能力（通常＋緑。調子系は「調子安定」「調子極端」に名前をそろえて含める）
    ranked: {項目: ランク1文字}
    bb: 変化球のリスト（kind=breaking / second_fastball）
    main_apt: 起用適性が◎のもの（先・中・抑）"""
    out = pd.DataFrame(index=df.index)
    A = df.abilities_json.map(J)
    out["role"] = df.role
    out["throws_bats"] = df.batting_throwing.fillna("")
    out["position"] = df.position
    out["sp"] = df.special_abilities_json.map(J).map(lambda l: [COND_MAP.get(x, x) for x in l])
    out["ranked"] = df.ranked_special_abilities_json.map(J).map(
        lambda d: {k: str(v)[-1] for k, v in d.items()} if isinstance(d, dict) else {})
    out["bb"] = df.breaking_balls_json.map(J)
    out["subs"] = df.sub_positions_json.map(J).map(lambda l: [x.get("position") for x in l])
    out["sub_apts"] = df.sub_positions_json.map(J).map(lambda l: [x.get("aptitude") for x in l])
    val = lambda k: A.map(lambda a: a[k]["value"] if isinstance(a.get(k), dict) else np.nan)
    out["speed"] = A.map(lambda a: int(re.findall(r"\d+", str(a["球速"]))[0]) if "球速" in a else np.nan)
    out["control"] = val("コントロール")
    out["stamina"] = val("スタミナ")
    for k, c in [("ミート", "contact"), ("パワー", "power"), ("走力", "run_speed"), ("肩力", "arm_strength"),
                 ("守備力", "fielding"), ("捕球", "catching")]:
        out[c] = val(k)
    out["trajectory"] = A.map(lambda a: a.get("弾道", np.nan))
    apt = {"starter_aptitude": "先", "reliever_aptitude": "中", "closer_aptitude": "抑"}
    out["main_apt"] = df.apply(lambda r: "".join(v for k, v in apt.items() if r.get(k) == "◎"), axis=1)
    out["form"] = df.get("pitching_form_type")
    out["entry_route"] = df.get("entry_route")
    out["entry_gap"] = df.age - df.pro_years if {"age", "pro_years"} <= set(df.columns) else np.nan
    return out


# ---------------------------------------------------------------- 投手

# 実在の日本人投手（2022〜2026）に1人もいない特能（§6-3）
P_NOT_REAL = ["安全圏○", "重い球", "立ち上がり○", "闘志", "対強打者○", "ボール先行",
              "人気者", "対ランナー×", "短気", "根性"]
# 右投手専用・左投手専用の球種（ゲーム仕様、§4-2）
LEFT_ONLY = {"スクリュー"}
RIGHT_ONLY = {"シンカー", "Hシンカー"}
# チェンジアップ系（§4-3）。実在は左投手に多く、右投手に少ない
CHANGEUP = {"サークルチェンジ", "チェンジアップ"}


# 球速の左右・役割（`投手球速左右差_改修指示.md`）。実在は2024〜2026年版の日本人投手1,126人。
# 役割の区分: 生成は position が「先発」なら先発、「中継ぎ」「抑え」は救援（球団分析と同じ）。
SPEED_HAND_REAL = {
    # (区分, 投げ手): (平均, 標準偏差)
    ("先発", "右"): (151.39, 4.31), ("先発", "左"): (148.69, 3.61),
    ("救援", "右"): (153.23, 3.55), ("救援", "左"): (149.74, 3.54),
}
SPEED_HAND_QUANTILES_REAL = {"右": (148, 152, 157), "左": (145, 149, 153)}
SPEED_JAPANESE_MEAN_REAL = 151.37
# 改修前（seed 1〜5000）の先発のスタミナの平均は data/config/check_baselines.json（「固定」）。左右の球速・救援のコントロール・
# 救援のスタミナの調整で変わっていないことの確認用。（コントロールは「コントロールの役割・左右」の節で実在と比べる。
# 救援のスタミナは `救援スタミナ相関_改修指示.md` で直したので、「救援のスタミナ」の節で実在と比べる）
SPEED_HAND_STAMINA_KEYS = (("先発", "右"), ("先発", "左"))

# 救援のスタミナ（`救援スタミナ相関_改修指示.md`）。実在は2024〜2026年版の日本人の救援投手553人（右416／左137）。
# 正式な判定は球団生成300球団（scripts/check_pitcher_control.py）。個別生成は参考表示にし、救援の相関だけ 0.10〜0.35 を判定する。
RELIEVER_STAMINA_CORR_REAL = {"全体": 0.216, "右": 0.184, "左": 0.297}  # コントロール×スタミナ
RELIEVER_STAMINA_MEAN_REAL = {"全体": 46.96, "右": 47.10, "左": 46.53}
RELIEVER_STAMINA_SD_REAL = 5.84
RELIEVER_STAMINA_QUANTILES_REAL = (39, 47, 54)  # 10%・中央・90%
RELIEVER_STAMINA_RATING_CORR_REAL = 0.424  # スタミナ×査定
PITCHER_CONTROL_STAMINA_CORR_REAL = 0.491  # 日本人投手全体のコントロール×スタミナ
RELIEVER_STAMINA_INDIVIDUAL_CORR = (0.10, 0.35)

# コントロールの役割・左右（`救援投手コントロール_改修指示.md`）。実在は2024〜2026年版の日本人投手1,126人。
# 正式な判定は球団生成300球団（scripts/check_pitcher_control.py）。個別生成は二軍級が多く、どの区分も球団生成より
# 1〜2低くなるので、このスクリプト（個別生成）では下限だけを判定し、ほかは参考表示にする。
CONTROL_HAND_REAL = {
    # (区分, 投げ手): (平均, 標準偏差, 10%, 中央, 90%)
    ("先発", "右"): (54.47, 12.7, 40, 53, 71), ("先発", "左"): (56.67, 14.2, 39, 55, 74),
    ("救援", "右"): (48.54, 10.0, 36, 48, 62), ("救援", "左"): (47.01, 11.4, 34, 46, 63),
}
CONTROL_HAND_GAP_REAL = {"先発": (2.2, 1.0), "救援": (-1.5, 1.0)}  # 左−右（実在, 許容幅）
CONTROL_RELIEF_GAP_REAL = {"右": (-5.9, 1.0), "左": (-9.7, 1.5)}  # 救援−先発（実在, 許容幅）
CONTROL_JAPANESE_MEAN_REAL = 51.78
CONTROL_RELIEVER_60_REAL, CONTROL_RELIEVER_70_REAL = 0.156, 0.025
# 個別生成の下限: 4区分の平均が実在より2.5以上低くならない、救援で60以上が9%以上
CONTROL_INDIVIDUAL_MAX_DROP = 2.5
CONTROL_INDIVIDUAL_RELIEVER_60_MIN = 0.09


def control_hand_rows(R, s, group, hand, ct, formal):
    """コントロールの役割・左右の表。formal=True（球団生成）なら指示書3-1の範囲で判定し、
    False（個別生成）なら下限だけ判定して、ほかは参考表示にする。"""
    group, hand, ct = np.asarray(group), np.asarray(hand), pd.Series(np.asarray(ct, dtype=float))
    mean = {}
    for (g, h), (real, real_sd, *real_qs) in CONTROL_HAND_REAL.items():
        x = ct[(group == g) & (hand == h)]
        mean[(g, h)] = v = x.mean()
        if formal:
            R.add(s, f"{g}・{h} 平均", num(v), ok_range(v, real - 0.8, real + 0.8), f"{real - 0.8:.2f}〜{real + 0.8:.2f}", num(real))
        else:
            low = real - CONTROL_INDIVIDUAL_MAX_DROP
            R.add(s, f"{g}・{h} 平均", num(v), ok_range(v, low), f"{low:.2f}以上（下限）", num(real))
        if g == "救援":
            v = x.std()
            R.add(s, f"{g}・{h} 標準偏差", num(v), ok_range(v, real_sd - 1.0, real_sd + 1.0),
                  f"{real_sd - 1.0:.1f}〜{real_sd + 1.0:.1f}", num(real_sd, 1), info=not formal)
            for label, q, rq in zip(("10%", "中央", "90%"), x.quantile([0.1, 0.5, 0.9]).tolist(), real_qs):
                R.add(s, f"{g}・{h} {label}", num(q, 0), ok_range(q, rq - 2, rq + 2), f"{rq - 2}〜{rq + 2}", str(rq), info=not formal)
    for g, (real, tol) in CONTROL_HAND_GAP_REAL.items():
        v = mean[(g, "左")] - mean[(g, "右")]
        R.add(s, f"左右差（左−右） {g}", num(v), ok_range(v, real - tol, real + tol), f"{real - tol:+.1f}〜{real + tol:+.1f}", f"{real:+.1f}", info=not formal)
    for h, (real, tol) in CONTROL_RELIEF_GAP_REAL.items():
        v = mean[("救援", h)] - mean[("先発", h)]
        R.add(s, f"救援−先発 {h}", num(v), ok_range(v, real - tol, real + tol), f"{real - tol:+.1f}〜{real + tol:+.1f}", f"{real:+.1f}", info=not formal)
    rel = ct[group == "救援"]
    v = (rel >= 60).mean()
    if formal:
        R.add(s, "救援で60以上", pct(v), ok_range(v, 0.12, 0.19), "12〜19%", pct(CONTROL_RELIEVER_60_REAL))
    else:
        low = CONTROL_INDIVIDUAL_RELIEVER_60_MIN
        R.add(s, "救援で60以上", pct(v), ok_range(v, low), f"{low * 100:.0f}%以上（下限）", pct(CONTROL_RELIEVER_60_REAL))
    v = (rel >= 70).mean()
    R.add(s, "救援で70以上", pct(v), ok_range(v, 0.015, 0.04), "1.5〜4%", pct(CONTROL_RELIEVER_70_REAL), info=not formal)
    v = ct.mean()
    R.add(s, "日本人全体の平均", num(v), ok_range(v, CONTROL_JAPANESE_MEAN_REAL - 0.5, CONTROL_JAPANESE_MEAN_REAL + 0.5),
          f"{CONTROL_JAPANESE_MEAN_REAL - 0.5:.2f}〜{CONTROL_JAPANESE_MEAN_REAL + 0.5:.2f}", num(CONTROL_JAPANESE_MEAN_REAL), info=not formal)


def reliever_stamina_rows(R, s, group, hand, ct, st, rating, formal):
    """救援のスタミナの表。formal=True（球団生成）なら指示書3-1の範囲で判定し、
    False（個別生成）なら救援の相関（0.10〜0.35）だけ判定して、ほかは参考表示にする。rating が None なら査定との相関は出さない。"""
    group, hand = np.asarray(group), np.asarray(hand)
    ct, st = pd.Series(np.asarray(ct, dtype=float)), pd.Series(np.asarray(st, dtype=float))
    rel = group == "救援"
    for h in ("全体", "右", "左"):
        mask = rel if h == "全体" else rel & (hand == h)
        real = RELIEVER_STAMINA_CORR_REAL[h]
        tol = 0.08 if h == "全体" else 0.12
        label = "救援" if h == "全体" else f"救援・{h}"
        v = ct[mask].corr(st[mask])
        if h == "全体" and not formal:
            lo, hi = RELIEVER_STAMINA_INDIVIDUAL_CORR
            R.add(s, f"コントロール×スタミナ相関 {label}", num(v, 3), ok_range(v, lo, hi), f"{lo:.2f}〜{hi:.2f}（個別生成）", num(real, 3))
        else:
            R.add(s, f"コントロール×スタミナ相関 {label}", num(v, 3), ok_range(v, real - tol, real + tol),
                  f"{real - tol:.3f}〜{real + tol:.3f}", num(real, 3), info=not formal)
    v = ct.corr(st)
    real = PITCHER_CONTROL_STAMINA_CORR_REAL
    R.add(s, "コントロール×スタミナ相関 全体", num(v, 3), ok_range(v, real - 0.05, real + 0.05),
          f"{real - 0.05:.3f}〜{real + 0.05:.3f}", num(real, 3), info=not formal)
    for h in ("全体", "右", "左"):
        mask = rel if h == "全体" else rel & (hand == h)
        real = RELIEVER_STAMINA_MEAN_REAL[h]
        tol = 0.5 if h == "全体" else 0.8
        v = st[mask].mean()
        R.add(s, f"{'救援' if h == '全体' else '救援・' + h} 平均", num(v), ok_range(v, real - tol, real + tol),
              f"{real - tol:.2f}〜{real + tol:.2f}", num(real), info=not formal)
    x = st[rel]
    v = x.std()
    real = RELIEVER_STAMINA_SD_REAL
    R.add(s, "救援 標準偏差", num(v), ok_range(v, real - 0.6, real + 0.6), f"{real - 0.6:.2f}〜{real + 0.6:.2f}", num(real), info=not formal)
    for label, q, rq in zip(("10%", "中央", "90%"), x.quantile([0.1, 0.5, 0.9]).tolist(), RELIEVER_STAMINA_QUANTILES_REAL):
        R.add(s, f"救援 {label}", num(q, 0), ok_range(q, rq - 2, rq + 2), f"{rq - 2}〜{rq + 2}", str(rq), info=not formal)
    if rating is not None:
        v = st[rel].corr(pd.Series(np.asarray(rating, dtype=float))[rel])
        real = RELIEVER_STAMINA_RATING_CORR_REAL
        R.add(s, "スタミナ×査定の相関 救援", num(v, 3), ok_range(v, real - 0.10, real + 0.10),
              f"{real - 0.10:.3f}〜{real + 0.10:.3f}", num(real, 3), info=not formal)


def check_pitcher_control_by_hand(R, d):
    s = "コントロールの役割・左右（個別生成は下限だけ判定。正式な判定は check_pitcher_control.py）"
    group = np.where(d.position == "先発", "先発", "救援")
    hand = np.where(d.throws_bats.str.startswith("左"), "左", "右")
    control_hand_rows(R, s, group, hand, d.control, formal=False)


def check_pitcher_speed_by_hand(R, d):
    s = "球速の左右・役割（実在は2024〜2026年版）"
    group = np.where(d.position == "先発", "先発", "救援")
    hand = np.where(d.throws_bats.str.startswith("左"), "左", "右")
    sp = d.speed
    mean = {}
    for (g, h), (real, real_sd) in SPEED_HAND_REAL.items():
        x = sp[(group == g) & (hand == h)]
        mean[(g, h)] = v = x.mean()
        R.add(s, f"{g}・{h} 平均", num(v), ok_range(v, real - 0.5, real + 0.5), f"{real - 0.5:.2f}〜{real + 0.5:.2f}", num(real))
        v = x.std()
        R.add(s, f"{g}・{h} 標準偏差", num(v), ok_range(v, real_sd - 0.6, real_sd + 0.6), f"{real_sd - 0.6:.2f}〜{real_sd + 0.6:.2f}", num(real_sd))
    for g, real in [("先発", -2.7), ("救援", -3.5)]:
        v = mean[(g, "左")] - mean[(g, "右")]
        R.add(s, f"左右差（左−右） {g}", num(v), ok_range(v, real - 0.6, real + 0.6), f"{real - 0.6:+.1f}〜{real + 0.6:+.1f}", f"{real:+.1f}")
    for h, real in [("右", 1.8), ("左", 1.0)]:
        v = mean[("救援", h)] - mean[("先発", h)]
        R.add(s, f"救援−先発 {h}", num(v), ok_range(v, real - 0.6, real + 0.6), f"{real - 0.6:+.1f}〜{real + 0.6:+.1f}", f"{real:+.1f}")
    v = sp.mean()
    R.add(s, "日本人全体の平均", num(v), ok_range(v, SPEED_JAPANESE_MEAN_REAL - 0.3, SPEED_JAPANESE_MEAN_REAL + 0.3),
          f"{SPEED_JAPANESE_MEAN_REAL - 0.3:.2f}〜{SPEED_JAPANESE_MEAN_REAL + 0.3:.2f}", num(SPEED_JAPANESE_MEAN_REAL))
    for h, reals in SPEED_HAND_QUANTILES_REAL.items():
        qs = sp[hand == h].quantile([0.1, 0.5, 0.9]).tolist()
        for label, q, real in zip(("10%", "中央", "90%"), qs, reals):
            R.add(s, f"{h}投手の{label}", num(q, 0), ok_range(q, real - 1, real + 1), f"{real - 1}〜{real + 1}", str(real))
    v = (sp[hand == "左"] >= 155).mean()
    R.add(s, "左投手で155以上", pct(v), ok_range(v, hi=0.06), "6%以下", "3.2%")
    for g, h in SPEED_HAND_STAMINA_KEYS:
        v = d.stamina[(group == g) & (hand == h)].mean()
        R.fixed(s, f"{g}・{h} スタミナ平均", v, num(v), id=f"{SCRIPT}.pitcher.speed_hand.stamina_mean.{g}_{h}")


def check_pitchers(d):
    R = Result(f"{SCRIPT}.pitcher")
    sp, ct, st = d.speed, d.control, d.stamina
    specials, ranked, bt = d.sp, d.ranked, d.throws_bats
    brk = d.bb.map(lambda l: [x for x in l if x.get("kind") == "breaking"])
    names = brk.map(lambda l: {x.get("name") for x in l})
    mx = brk.map(lambda l: max([int(x.get("movement") or 0) for x in l] or [0]))
    closer = d.position == "抑え"
    right, left = bt.str.startswith("右投"), bt.str.startswith("左投")

    s = "投打"
    v = (bt == "左投右打").mean(); R.add(s, "左投右打", pct(v), ok_range(v, hi=0.02), "2%以下", "0.7%")
    v = rate(left, bt.str.endswith("左打")); R.add(s, "左投げのうち左打ち", pct(v), ok_range(v, 0.90), "90%以上", "97.8%")
    v = bt.str.endswith("両打").mean(); R.add(s, "両打", pct(v), ok_range(v, hi=0.02), "2%以下", "0.7%")

    s = "能力"
    v = (sp <= 145).mean(); R.add(s, "球速145以下", pct(v), ok_range(v, hi=0.09), "9%以下", "6.9%（2026は5.6%）")
    v = (sp >= 162).mean(); R.add(s, "球速162以上", pct(v), ok_range(v, hi=0.005), "0.5%以下", "0.2%")
    v = (ct < 20).mean(); R.add(s, "コントロール20未満", pct(v), ok_range(v, hi=0.01), "1%以下", "0.5%")
    c = sp.corr(ct); R.add(s, "球速×コントロール相関", num(c), ok_range(c, -0.40, -0.15), "−0.40〜−0.15", "−0.26")
    c = ct.corr(st); R.add(s, "コントロール×スタミナ相関", num(c), ok_range(c, 0.38, 0.58), "+0.38〜+0.58", "+0.46")

    check_pitcher_speed_by_hand(R, d)
    check_pitcher_control_by_hand(R, d)
    group = np.where(d.position == "先発", "先発", "救援")
    hand = np.where(bt.str.startswith("左"), "左", "右")
    reliever_stamina_rows(R, "救援のスタミナ（個別生成は救援の相関だけ判定。正式な判定は check_pitcher_control.py）",
                          group, hand, ct, st, None, formal=False)

    s = "抑え・起用適性"
    v = sp[closer].mean() if closer.any() else np.nan
    R.add(s, "抑えの球速平均", num(v, 1), ok_range(v, 153), "153以上", "153.6（守護神）")
    v = mx[closer].mean() if closer.any() else np.nan
    R.add(s, "抑えの最大変化量平均", num(v), ok_range(v, 4.2), "4.2以上", "4.45（守護神）")
    v = closer.mean(); R.add(s, "抑えの割合", pct(v), ok_range(v), "3〜4%（目安）", "2.7%（守護神）", info=True)
    apt = d.main_apt.fillna("")
    v = (apt.str.contains("先") & apt.str.contains("中")).mean()
    R.add(s, "先発・中継ぎの両方が◎", pct(v), ok_range(v, 0.20, 0.35), "20〜35%", "28.8%")
    v = (apt == "先").mean(); R.add(s, "先発だけ◎", pct(v), ok_range(v, hi=0.30), "30%以下", "22.8%")

    s = "フォーム"
    fm = d.form.fillna("")
    v = (fm == "スリークォーター").mean(); R.add(s, "スリークォーター", pct(v), ok_range(v, 0.40, 0.55), "40〜55%", "49.2%")
    v = (fm == "オーバースロー").mean(); R.add(s, "オーバースロー", pct(v), ok_range(v, 0.35, 0.50), "35〜50%", "43.6%")

    s = "変化球"
    v = (right & names.map(lambda x: bool(x & LEFT_ONLY))).sum()
    R.add(s, "右投手のスクリュー", f"{v}件", ok_range(v, hi=0), "0件（仕様）", "0件")
    v = (left & names.map(lambda x: bool(x & RIGHT_ONLY))).sum()
    R.add(s, "左投手のシンカー・Hシンカー", f"{v}件", ok_range(v, hi=0), "0件（仕様）", "0件")
    has_chg = names.map(lambda x: bool(x & CHANGEUP))
    v = rate(right, has_chg); R.add(s, "チェンジアップ系（右投手）", pct(v), ok_range(v, hi=0.18), "18%以下", "13.6%")
    v = rate(left, has_chg); R.add(s, "チェンジアップ系（左投手）", pct(v), ok_range(v, 0.42), "42%以上", "51.3%")

    s = "特殊能力"
    v = rate(sp <= 147, has_sp(specials, "奪三振")); R.add(s, "奪三振（球速147以下）", pct(v), ok_range(v, hi=0.20), "20%以下", "9%")
    v = rate(ct <= 40, has_sp(specials, "四球")); R.add(s, "四球（制球40以下）", pct(v), ok_range(v, 0.50), "50%以上", "60%")
    v = rate(ct >= 61, has_sp(specials, "四球")); R.add(s, "四球（制球61以上）", pct(v), ok_range(v, hi=0.20), "20%以下", "12%")
    v = rate(ct <= 40, has_sp(specials, "荒れ球")); R.add(s, "荒れ球（制球40以下）", pct(v), ok_range(v, 0.15), "15%以上", "25%")
    tot = specials.map(lambda l: sum(x in P_NOT_REAL for x in l)).mean()
    R.add(s, "実在にない特能（1人あたり）", num(tot), ok_range(tot, hi=0.05), "0.05以下", "0")
    v = has_sp(specials, "火消し").mean(); R.add(s, "火消し", pct(v), ok_range(v, hi=0.01), "1%以下", "0.3%（2026）")
    v = has_sp(specials, "調子極端").mean(); R.add(s, "調子極端", pct(v), ok_range(v, 0.07, 0.11), "7〜11%", "10.0%（2026は8.4%）")

    s = "ランク特能"
    thr = ranked.map(lambda x: x.get("送球", "D"))
    v = thr.isin(list("EFG")).mean(); R.add(s, "送球悪い(E〜G)", pct(v), ok_range(v, 0.33), "33%以上", "44%（2022〜25）")
    v = thr.isin(list("ABC")).mean(); R.add(s, "送球良い(A〜C)", pct(v), ok_range(v, hi=0.12), "12%以下", "8%（2022〜25）")
    v = any_rank(ranked, "A").mean(); R.add(s, "ランクAを1つ以上", pct(v), ok_range(v, hi=0.04), "4%以下", "2.3%")
    v = any_rank(ranked, "G").mean(); R.add(s, "ランクGを1つ以上", pct(v), ok_range(v, hi=0.03), "3%以下", "1.2%")
    return R


# ---------------------------------------------------------------- 野手

# 実在の日本人野手（2022〜2026）に1人もいない特能（§6-3）
F_NOT_REAL = ["人気者", "窮地○", "チームプレイ×", "ムード○", "帳尻合わせ", "リベンジ", "ささやき破り"]


def check_fielders(d, team=False):
    R = Result(f"{SCRIPT}.fielder")
    mt, pw, rn, ar, fd, tj = d.contact, d.power, d.run_speed, d.arm_strength, d.fielding, d.trajectory
    specials, ranked, bt, pos, subs = d.sp, d.ranked, d.throws_bats, d.position, d.subs
    rank_of = lambda key: ranked.map(lambda x: x.get(key, "D"))

    s = "投打"
    v = (bt == "右投左打").mean(); R.add(s, "右投左打", pct(v), ok_range(v, 0.35, 0.45), "35〜45%", "40.9%")
    v = (bt == "左投右打").sum(); R.add(s, "左投右打", f"{v}件", ok_range(v, hi=0), "0件", "0件", kind="設計")
    v = bt.str.endswith("両打").mean(); R.add(s, "両打", pct(v), ok_range(v, hi=0.03), "3%以下", "1.6%")
    v = rate(pos.isin(["二塁手", "遊撃手"]), bt.str.endswith("左打"))
    R.add(s, "二塁手・遊撃手の左打ち", pct(v), ok_range(v, 0.45), "45%以上", "54%")

    s = "能力"
    v = (tj == 1).mean(); R.add(s, "弾道1", pct(v), ok_range(v, hi=0.04), "4%以下", "2.3%")
    c = tj.corr(pw); R.add(s, "弾道×パワー相関", num(c), ok_range(c, 0.65, 0.78), "0.65〜0.78", "0.72")
    c = mt.corr(pw); R.add(s, "ミート×パワー相関", num(c), ok_range(c, 0.28), "+0.28以上", "+0.35")
    v = (pw >= 70).mean(); R.add(s, "パワー70以上", pct(v), ok_range(v, 0.04, 0.10), "4〜10%", "6.5%")
    v = (rn >= 80).mean(); R.add(s, "走力80以上", pct(v), ok_range(v, 0.12, 0.20), "12〜20%", "16.9%")
    v = (ar >= 80).mean(); R.add(s, "肩力80以上", pct(v), ok_range(v, 0.08, 0.15), "8〜15%", "11.4%")
    v = (fd >= 70).mean(); R.add(s, "守備力70以上", pct(v), ok_range(v, 0.05, 0.11), "5〜11%", "8.1%")

    s = "サブポジ（実在は2022〜25の守備力表から）"
    k = subs.map(len)
    v = (k >= 3).mean(); R.add(s, "サブポジ3つ以上", pct(v), ok_range(v, 0.20, 0.35), "20〜35%", "28.5%")
    v = k[pos.isin(["二塁手", "三塁手", "遊撃手"])].mean()
    R.add(s, "内野手（二・三・遊）の平均", num(v), ok_range(v, 2.2), "2.2以上", "2.60")
    v = rate(pos == "遊撃手", subs.map(lambda l: "二塁手" in l))
    R.add(s, "遊撃手のサブポジ二塁手", pct(v), ok_range(v, 0.80), "80%以上", "91%")
    apts = pd.Series([a for l in d.sub_apts for a in l]) if "sub_apts" in d else pd.Series(dtype=object)
    if len(apts):
        v = (apts == "◎").mean(); R.add(s, "サブポジ適性 ◎", pct(v), ok_range(v, 0.25, 0.45), "25〜45%", "35%（守備力比0.9以上）")
        v = (apts == "○").mean(); R.add(s, "サブポジ適性 ○", pct(v), ok_range(v, hi=0.40), "40%以下", "19%")

    s = "ポジション（チーム単位）"
    v = (pos == "捕手").mean(); R.add(s, "捕手", pct(v), ok_range(v, 0.18, 0.25), "18〜25%", "21.7%", info=not team)
    v = (pos == "一塁手").mean(); R.add(s, "一塁手", pct(v), ok_range(v, 0.03, 0.08), "3〜8%", "5.4%", info=not team)

    s = "特殊能力"
    K = has_sp(specials, "三振")
    v = rate(mt >= 51, K); R.add(s, "三振（ミート51以上）", pct(v), ok_range(v, hi=0.25), "25%以下", "16%")
    v = rate(mt <= 30, K); R.add(s, "三振（ミート30以下）", pct(v), ok_range(v, 0.28), "28%以上", "32%")
    v = rate(rn >= 81, has_sp(specials, "積極盗塁")); R.add(s, "積極盗塁（走力81以上）", pct(v), ok_range(v, 0.30), "30%以上", "41%")
    v = has_sp(specials, "死球集中").mean(); R.add(s, "死球集中", pct(v), ok_range(v, 0.05, 0.11), "5〜11%", "8.0%（2026）")
    tot = specials.map(lambda l: sum(x in F_NOT_REAL for x in l)).mean()
    R.add(s, "実在にない特能（1人あたり）", num(tot), ok_range(tot, hi=0.05), "0.05以下", "0")
    v = has_sp(specials, "フル出場").mean(); R.add(s, "フル出場", pct(v), ok_range(v, hi=0.01), "1%以下", "0%（起用法のみ）")
    v = has_sp(specials, "調子安定").mean(); R.add(s, "調子安定", pct(v), ok_range(v, hi=0.01), "1%以下", "0.3%")

    s = "ランク特能"
    v = rank_of("走塁").isin(list("EFG")).mean(); R.add(s, "走塁悪い(E〜G)", pct(v), ok_range(v, hi=0.08), "8%以下", "3%")
    v = rank_of("盗塁").isin(list("ABC")).mean(); R.add(s, "盗塁良い(A〜C)", pct(v), ok_range(v, hi=0.25), "25%以下", "15%")
    v = any_rank(ranked, "A").mean(); R.add(s, "ランクAを1つ以上", pct(v), ok_range(v, hi=0.05), "5%以下", "4.0%")
    v = any_rank(ranked, "G").mean(); R.add(s, "ランクGを1つ以上", pct(v), ok_range(v, hi=0.03), "3%以下", "1.4%")
    return R


# ---------------------------------------------------------------- main


def check_common(d):
    R = Result(f"{SCRIPT}.common")
    s = "プロ入り年齢（2026）"
    if d.entry_route.notna().any():
        v = (d.entry_route == "その他").mean(); R.add(s, "入団経路「その他」", pct(v), ok_range(v, hi=0.02), "2%以下", "1.3%")
    gap = pd.to_numeric(d.entry_gap, errors="coerce")
    if gap.notna().any():
        v = (gap >= 25).mean(); R.add(s, "年齢−プロ年数が25以上", pct(v), ok_range(v, hi=0.05), "5%以下", "2.4%")
    return R


def run(d, title, team=False, boot=checklib.DEFAULT_BOOTSTRAP, quick=False, suffix=""):
    """共通・投手・野手の判定を評価して表示し、合否を付けた Check のリストを返す。suffix は同じ役割の CSV が複数あるときの id の区別。"""
    graded = []
    parts = [("共通", "共通", lambda x: check_common(x), None)]
    parts += [(role, f"日本人{role}", fn, REAL_N[role]) for role, fn in
              (("投手", check_pitchers), ("野手", lambda x: check_fielders(x, team)))]
    for role, label, fn, real_n in parts:
        x = d if role == "共通" else d[d.role == role]
        if not len(x):
            continue
        x = x.reset_index(drop=True)
        checks = grade_part(fn, x, boot, real_n, quick)
        if suffix:
            for check in checks:
                check.id += suffix
        checklib.print_checks(checks, f"{title}  {label} {len(x)}人")
        graded += checks
    return graded


def main(argv):
    parser = argparse.ArgumentParser(description="架空球団用の個別生成CSVを判定します。")
    parser.add_argument("paths", nargs="+", help="生成CSV（scripts/generate_fictional_balance_sample.py で作る）")
    parser.add_argument("--team", action="store_true", help="チーム単位で生成したCSV向けに「捕手・一塁手の比率」も合否に含める")
    checklib.add_common_args(parser)
    args = parser.parse_args(argv)
    graded = []
    for index, p in enumerate(args.paths):
        df = pd.read_csv(p, encoding="utf-8-sig")
        if "category" in df.columns:
            df = df[df.category == "架空球団用"]
        dom = df[df.roster_origin == "domestic"] if "roster_origin" in df.columns else df
        print(f"\n{p}: 架空球団用 {len(df)}人（日本人 {len(dom)}人 / 外国人 {len(df) - len(dom)}人は check_foreign_balance.py の担当）")
        graded += run(normalize(dom), p, args.team, args.boot, args.quick, suffix="" if index == 0 else f"#{index + 1}")
    print("\n" + checklib.summary_line(graded))
    sys.exit(checklib.finish(SCRIPT, graded, args))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1:])
