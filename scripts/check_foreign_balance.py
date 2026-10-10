#!/usr/bin/env python3
"""
外国人選手 生成バランス チェッカー

使い方:
    python check_foreign_balance.py <生成CSV> [<生成CSV> ...] [--teams 300] [--boot 200] [--update-baselines --reason 理由] [--quick]

- CSV の role 列（投手／野手）を見て、投手・野手それぞれの完了条件を判定する。
- 判定基準は `外国人投手バランス_改修指示.md` §6 と `外国人野手バランス_改修指示.md` §5、`外国人の残り_改修指示.md` 2-1。
  ドキュメントの目標値を変えたときは、このファイルの CHECKS も合わせて直すこと。
- 「実在」列は、パワプロ実在外国人（2024〜2026年版、投手122人／野手102人。日本人の判定と同じ年版）の値。年齢は2026年版だけ（野手32人）。
  変化球の数は、生成側と同じく同じ方向の第二球種（slot 2）も数える。身長・フォーム・抑えの変化量は元データに無いので、以前の
  データ（2022〜2026年版、延べ 投手214人／野手151人）の値のまま。範囲は、2024〜2026年版の実在が以前の範囲の外に出た項目だけ、
  以前の「実在から範囲までの幅」を保ったまま実在に合わせてずらした。パワーの85以上・55未満とミート×パワーは、今回パワーの幅を
  広げたので2024〜2026年版から引き直した（外国人の残り_改修指示.md 2-1）。
- 「実在（2024〜2026年版）」の節（外国人の残り_改修指示.md 2-1）は、個別生成のCSVと、球団生成（--teams、既定300球団）の外国人の両方で判定する。
  球団生成の判定の id は `check_foreign_balance.team.pitcher.…`／`check_foreign_balance.team.fielder.…`。
- 判定の種類・誤差・合否の付け方は checklib.py（判定の整理_改修指示.md）。判定の一覧は reports/checks/check_foreign_balance.csv。
- 終了コード: 不合格が1件でもあれば 1（要注意・受け入れ済みは 0）。
- 正式な判定は 5000人（例: seed 1〜5000）で行う。1000人だとサンプルの揺れで
  境界付近の項目がまれに外れるので、1000人の結果は途中確認用として扱う。
  基準に合わせるために分布そのものを歪めないこと。
"""
import argparse
import json
import logging
import math
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import checklib  # noqa: E402
from checklib import Checks, in_range  # noqa: E402

SCRIPT = "check_foreign_balance"
# 実在の外国人の人数（2024〜2026年版、投手122人／野手102人）。実在側の誤差を、生成側の誤差の人数比で見積もる
REAL_N = {"投手": 122, "野手": 102}
# 実在の人数が上と違う項目（id の末尾 → 人数）。走力の外野手・遊撃手は2022〜2026年版（野手172人）、年齢は2026年版（野手32人）と比べる
REAL_N_BY_ITEM = {"走力（外野手）": 172, "走力（遊撃手）": 172, "年齢の平均": 32}
REAL_SECTION = "実在（2024〜2026年版）"
# 「実在（2024〜2026年版）」の節の実在の値（外国人の残り_改修指示.md 0章・2-1）
REAL_PITCHER = {
    "赤特の数": 1.074, "ランク点": -1.221, "対ランナー×": 0.139, "対ランナー": 0.049,
    "抜け球": 0.262, "回またぎ○": 0.164, "逃げ球": 0.361, "ナチュラルシュート": 0.098,
}
REAL_FIELDER = {
    "走力": 59.49, "走力_2022": 57.61, "走力（外野手）": 63.93, "走力（遊撃手）": 72.85,  # 外野手・遊撃手の判定は2022〜2026年版
    "走力（外野手）_2024": 65.86, "走力（遊撃手）_2024": 76.56, "年齢": 29.13, "ミートSD": 12.16, "パワーSD": 11.52,
}

# ---------------------------------------------------------------- 共通


def J(x):
    try:
        return json.loads(x) if isinstance(x, str) else (x or [])
    except Exception:
        return []


def has(lst, *names):
    return any(n in lst for n in names)


def rank_letter(d, key):
    v = d.get(key, "D") if isinstance(d, dict) else "D"
    return str(v)[-1]


def pct(x):
    return f"{x * 100:.1f}%"


def num(x, nd=2):
    return f"{x:.{nd}f}"


class Result:
    """判定の集まり。id は「<prefix>.<節>.<項目名>」（節は表示名の空白を _ にしたもの。項目名を直すときは id= で元の id を渡す）。
    `add` は範囲（lo, hi）を渡す。「0件」「（仕様）」「実在にない特能」「矛盾ペア」は設計の判定、ほかは実在に合わせる判定。"""

    def __init__(self, prefix=SCRIPT):
        self.prefix = prefix
        self.checks = Checks(prefix)

    def add(self, section, item, value, v, lo=None, hi=None, real="", target=None, kind=None, id=None):
        if target is None:
            target = f"{lo}〜{hi}" if lo is not None and hi is not None else (f"{lo}以上" if lo is not None else f"{hi}以下")
        if kind is None:
            kind = "設計" if (hi == 0 and lo is None) or item.startswith(("実在にない特能", "矛盾ペア")) else "実在"
        key = id or f"{self.prefix}.{section.replace(' ', '_')}.{item}"
        verdict = in_range(v, lo, hi)
        self.checks.add(key, kind, item, verdict.value, lo, hi, section=section, shown=str(value), target=target, real=str(real))

    def pct(self, section, item, v, lo=None, hi=None, real="", **kw):
        f = lambda x: f"{x * 100:g}%"  # noqa: E731
        target = f"{f(lo)}〜{f(hi)}" if lo is not None and hi is not None else (f"{f(lo)}以上" if lo is not None else f"{f(hi)}以下")
        self.add(section, item, pct(v), v, lo, hi, real, target, **kw)


def grade_part(fn, data, boot, real_n=None, quick=False, cluster=None):
    """cluster（列名）を渡すと、生成側の誤差をそのまとまり（球団）を単位に再抽出して求める。"""
    evaluate = lambda d: fn(d).checks  # noqa: E731
    checks = evaluate(data)
    resample = (lambda f, rng: checklib.resample_frame(f, rng, cluster)) if cluster else checklib.resample_frame
    se_gen = checklib.bootstrap_se(evaluate, data, resample, n=boot) if boot else {}
    se_real = checklib.scale_se(se_gen, len(data), real_n) if real_n else {}
    for key in se_real:
        item_n = next((n for suffix, n in REAL_N_BY_ITEM.items() if key.endswith(f".{suffix}")), None)
        if item_n:
            se_real[key] = se_gen[key] * math.sqrt(len(data) / item_n)
    return checklib.grade(checks, se_gen=se_gen, se_real=se_real, all_info=quick)


# ---------------------------------------------------------------- 投手

# 実在の外国人投手に1人もいない特能（§4-2）
P_NOT_REAL = [
    "安全圏○", "立ち上がり○", "重い球", "国際大会○", "闘志", "根性", "勝ち運",
    "ボール先行", "短気", "尻上がり", "ジャイロボール", "国際大会×", "対強打者○", "軽い球",
    "ムード○", "全開", "人気者", "ポーカーフェイス", "投打躍動", "投手存在感", "ムード×",
]
# 矛盾ペア（§4-3）。調子安定は「投手調子安定」「調子安定」のどちらの表記でも拾う
P_CONFLICTS = [
    ("安全圏○", "寸前"), ("根性", "短気"), ("要所○", "寸前"), ("球持ち○", "抜け球"),
    ("乱調", ("投手調子安定", "調子安定")), ("尻上がり", "寸前"), ("逃げ球", "寸前"),
    ("荒れ球", "ストライク先行"), ("キレ○", "抜け球"), ("勝ち運", "負け運"),
    ("ストライク先行", "ボール先行"), ("対ランナー", "対ランナー×"),
    (("投手調子安定", "調子安定"), ("投手調子極端", "調子極端")),
]


def _in(lst, x):
    return has(lst, *x) if isinstance(x, tuple) else x in lst


def check_pitchers(df):
    R = Result(f"{SCRIPT}.pitcher")
    A = df.abilities_json.map(J)
    sp = A.map(lambda a: int(re.findall(r"\d+", str(a.get("球速", "0")))[0]))
    ct = A.map(lambda a: a["コントロール"]["value"])
    st = A.map(lambda a: a["スタミナ"]["value"])
    pos = df.position
    starter = pos == "先発"
    reliever = ~starter
    specials = df.special_abilities_json.map(J)
    ranked = df.ranked_special_abilities_json.map(J)
    bbs = df.breaking_balls_json.map(J)
    brk = bbs.map(lambda l: [x for x in l if x.get("kind") == "breaking"])
    n_bb = brk.map(len)
    mx = brk.map(lambda l: max([x.get("movement", 0) for x in l] or [0]))
    names = brk.map(lambda l: [x.get("name") for x in l])
    twoseam = bbs.map(lambda l: any(x.get("name") == "ツーシームファスト" for x in l))
    n = len(df)

    s = "球速"
    top = sp.value_counts(normalize=True).max()
    R.pct(s, "最頻値1つへの集中", top, hi=0.176, real="15.6%")
    R.pct(s, "160〜162", sp.between(160, 162).mean(), 0.10, 0.15, "11.5%")
    R.pct(s, "163以上", (sp >= 163).mean(), 0.005, 0.025, "0.8%")
    R.pct(s, "150未満", (sp < 150).mean(), hi=0.05, real="3.3%")

    s = "相関"
    c = sp.corr(ct); R.add(s, "球速×コントロール", num(c), c, -0.45, -0.15, "−0.40")
    c = sp.corr(st); R.add(s, "球速×スタミナ", num(c), c, -0.45, -0.15, "−0.36")
    c = ct.corr(st); R.add(s, "コントロール×スタミナ", num(c), c, 0.39, 0.69, "+0.53")

    s = "コントロール・スタミナ"
    v = (ct < 20).sum(); R.add(s, "コントロール20未満", f"{v}件", v, hi=0, real="0件（最低22）")
    v = st[starter].mean(); R.add(s, "先発スタミナ平均", num(v, 1), v, 57, 62, "59.8")
    v = st[reliever].mean(); R.add(s, "救援スタミナ平均", num(v, 1), v, 46, 50, "46.2")
    R.pct(s, "救援スタミナ38未満", (st[reliever] < 38).mean(), hi=0.01, real="0%")

    s = "体格・フォーム"
    v = df.height_cm.mean(); R.add(s, "身長平均", num(v, 1), v, 188, 192, "191.5（2022〜26）")
    v = (df.pitching_form_type == "アンダースロー").sum(); R.add(s, "アンダースロー", f"{v}件", v, hi=0, real="0件")
    R.pct(s, "サイドスロー", (df.pitching_form_type == "サイドスロー").mean(), hi=0.04, real="2.3%（2022〜26）")

    s = "変化球"
    R.pct(s, "2球種", (n_bb == 2).mean(), 0.50, 0.60, "59.8%")
    v = (n_bb >= 4).sum(); R.add(s, "4球種以上", f"{v}件", v, hi=0, real="0件")
    R.pct(s, "ツーシームファスト", twoseam.mean(), 0.33, 0.42, "41.0%")
    has_sf = bbs.map(lambda l: any(x.get("kind") == "second_fastball" for x in l))
    R.pct(s, "3球種以上＋第二球種", ((n_bb >= 3) & has_sf).mean(), hi=0.01, real="0%")
    R.pct(s, "2球種で第二球種なし", ((n_bb == 2) & ~has_sf).mean(), 0.10, 0.20, "15.6%")
    R.pct(s, "最大変化量2以下", (mx <= 2).mean(), hi=0.03, real="1.6%")
    v = mx[pos == "抑え"].mean(); R.add(s, "抑えの最大変化量平均", num(v), v, lo=4.0, real="4.30（2022〜26）")
    for nm, lo, hi, real in [("フォーク", None, 0.08, "0.8%"), ("カーブ", None, 0.08, "0.8%"),
                             ("ナックルカーブ", 0.15, None, "22.1%"), ("Hシンカー", 0.15, None, "22.1%")]:
        R.pct(s, nm, names.map(lambda l: nm in l).mean(), lo, hi, real)

    s = "特殊能力"
    K = specials.map(lambda l: "奪三振" in l)
    R.pct(s, "奪三振", K.mean(), 0.40, 0.52, "44.3%")
    v = K[sp >= 160].mean() if (sp >= 160).any() else float("nan")
    R.pct(s, "奪三振（球速160以上）", v, lo=0.52, real="60%")
    R.pct(s, "四球（制球40以下）", specials[ct <= 40].map(lambda l: "四球" in l).mean(), lo=0.54, real="68%")
    tot = specials.map(lambda l: sum(x in P_NOT_REAL for x in l)).sum() / n
    R.add(s, "実在にない特能（1人あたり）", num(tot), tot, hi=0.05, real="0")
    R.pct(s, "調子極端", specials.map(lambda l: has(l, "投手調子極端", "調子極端")).mean(), 0.05, 0.09, "9.0%")
    R.pct(s, "投球位置左／右", specials.map(lambda l: has(l, "投球位置左", "投球位置右")).mean(), hi=0.01, real="0%")
    v = specials.map(lambda l: any(_in(l, a) and _in(l, b) for a, b in P_CONFLICTS)).sum()
    R.add(s, "矛盾ペア", f"{v}件", v, hi=0)
    R.pct(s, "クイック悪い(E〜G)", ranked.map(lambda d: rank_letter(d, "クイック") in "EFG").mean(), lo=0.50, real="60.7%")

    s = "ラベル"
    v = (starter & (df.acquisition_role == "ロングリリーフ")).sum()
    R.add(s, "先発のロングリリーフ", f"{v}件", v, hi=0)
    real_pitcher_rows(R, df)
    return R


def real_pitcher_rows(R, df):
    """実在（2024〜2026年版）に合わせる項目（外国人の残り_改修指示.md 2-1）。個別生成と球団生成の両方で使う。"""
    from generator.rating import ranked_points
    from generator.team_analysis import special_counts

    specials = df.special_abilities_json.map(J)
    ranked = df.ranked_special_abilities_json.map(J)
    s, real = REAL_SECTION, REAL_PITCHER
    v = specials.map(lambda l: special_counts(l)["n_red"]).mean()
    R.add(s, "赤特の数", num(v), v, round(real["赤特の数"] - 0.15, 3), round(real["赤特の数"] + 0.15, 3), num(real["赤特の数"]))
    v = ranked.map(lambda d: ranked_points(d, "投手")).mean()
    R.add(s, "ランク点", num(v), v, round(real["ランク点"] - 1.0, 3), round(real["ランク点"] + 1.0, 3), num(real["ランク点"]))
    for name, tol in [("対ランナー×", 0.05), ("対ランナー", 0.05), ("抜け球", 0.07), ("回またぎ○", 0.07), ("逃げ球", 0.07), ("ナチュラルシュート", 0.07)]:
        r = real[name]
        R.pct(s, name, specials.map(lambda l: name in l).mean(), round(max(0.0, r - tol), 3), round(r + tol, 3), pct(r))


# ---------------------------------------------------------------- 野手

F_NOT_REAL = [
    "国際大会×", "ミート多用", "窮地○", "フル出場", "代打○", "帳尻合わせ", "ささやき破り",
    "チャンスメーカー", "かく乱", "リベンジ", "ホーム突入", "プレッシャーラン", "いぶし銀", "人気者",
    "チームプレイ×", "ムード○", "野手存在感", "ムード×", "対エース○", "バント職人",
]


def check_fielders(df):
    R = Result(f"{SCRIPT}.fielder")
    A = df.abilities_json.map(J)
    g = lambda k: A.map(lambda a: a[k]["value"])
    mt, pw, rn, ar, fd, cc = (g(k) for k in ["ミート", "パワー", "走力", "肩力", "守備力", "捕球"])
    tj = A.map(lambda a: a["弾道"])
    specials = df.special_abilities_json.map(J)
    ranked = df.ranked_special_abilities_json.map(J)
    subs = df.sub_positions_json.map(J)
    n = len(df)

    # パワーの標準偏差は「実在（2024〜2026年版）」の節に移した（ミートの標準偏差と並べ、球団生成でも判定する）
    s = "パワー"
    R.pct(s, "85以上", (pw >= 85).mean(), 0.01, 0.04, "2.0%")
    v = (pw >= 90).sum(); R.add(s, "90以上", f"{v}件", v, hi=0, real="0件（最高87）")
    R.pct(s, "55未満", (pw < 55).mean(), 0.07, 0.14, "10.8%（2022〜26 8.1%）")

    s = "その他の能力"
    R.pct(s, "ミート65以上", (mt >= 65).mean(), hi=0.069, real="5.9%")
    R.pct(s, "守備力60以上", (fd >= 60).mean(), hi=0.059, real="4.9%")
    v = fd.max(); R.add(s, "守備力の最高", str(v), v, hi=65, real="64")
    v = max(rn.max(), ar.max()); R.add(s, "走力・肩力の最高", str(v), v, hi=95, real="95")
    v = max(mt.max(), pw.max(), fd.max(), cc.max()); R.add(s, "ミート・パワー・守備・捕球の最高", str(v), v, hi=88, real="87")

    s = "弾道"
    for t, lo, hi, real in [(2, .25, .32, "31.4%"), (3, .45, .52, "46.1%"), (4, .20, .25, "22.5%")]:
        R.pct(s, f"弾道{t}", (tj == t).mean(), lo, hi, real)
    c = tj.corr(pw); R.add(s, "弾道×パワー相関", num(c), c, 0.40, 0.55, "0.46")
    R.pct(s, "弾道2でパワー75以上", ((tj == 2) & (pw >= 75)).mean(), lo=0.02, real="3.9%")

    s = "相関"
    c = mt.corr(pw); R.add(s, "ミート×パワー", num(c), c, lo=0.35, real="+0.56（2022〜26 +0.46）")
    c = pw.corr(fd); R.add(s, "パワー×守備力", num(c), c, -0.26, -0.06, "−0.15")

    s = "ポジション・投打・体格"
    for p, lo, hi, real in [("三塁手", .082, .112, "8.8%"), ("遊撃手", .138, .168, "15.7%"), ("捕手", .02, .04, "3.9%")]:
        R.pct(s, p, (df.position == p).mean(), lo, hi, real)
    R.pct(s, "右投右打", (df.batting_throwing == "右投右打").mean(), 0.712, 0.812, "78.4%")
    R.pct(s, "左投右打", (df.batting_throwing == "左投右打").mean(), hi=0.02, real="0%")
    v = df.height_cm.mean(); R.add(s, "身長平均", num(v, 1), v, 185, 190, "187.7（2022〜26）")
    k = subs.map(len)
    R.pct(s, "サブポジ2つ", (k == 2).mean(), 0.253, 0.353, "31.4%")
    v = (k >= 3).sum(); R.add(s, "サブポジ3つ以上", f"{v}件", v, hi=0, real="0件")

    s = "特殊能力"
    for nm, lo, real in [("三振", .65, "70.6%"), ("積極打法", .38, "48.0%"), ("満塁男", .28, "29.4%")]:
        R.pct(s, nm, specials.map(lambda l: nm in l).mean(), lo=lo, real=real)
    R.pct(s, "パワーヒッター", specials.map(lambda l: "パワーヒッター" in l).mean(), hi=0.06, real="4.9%")
    tot = specials.map(lambda l: sum(x in F_NOT_REAL for x in l)).sum() / n
    R.add(s, "実在にない特能（1人あたり）", num(tot), tot, hi=0.05, real="0")
    R.pct(s, "調子安定", specials.map(lambda l: has(l, "野手調子安定", "調子安定")).mean(), hi=0.01, real="0%")
    R.pct(s, "走塁悪い(E〜G)", ranked.map(lambda d: rank_letter(d, "走塁") in "EFG").mean(), hi=0.10, real="5.9%")
    R.pct(s, "送球良い(A〜C)", ranked.map(lambda d: rank_letter(d, "送球") in "ABC").mean(), hi=0.12, real="6.9%")
    real_fielder_rows(R, df)
    return R


def real_fielder_rows(R, df):
    """実在（2024〜2026年版）に合わせる項目（外国人の残り_改修指示.md 2-1）。個別生成と球団生成の両方で使う。"""
    A = df.abilities_json.map(J)
    g = lambda k: A.map(lambda a: a[k]["value"])  # noqa: E731
    mt, pw, rn = g("ミート"), g("パワー"), g("走力")
    s, real = REAL_SECTION, REAL_FIELDER
    v = rn.mean(); R.add(s, "走力の平均", num(v, 1), v, 57, 61, f"{real['走力']:.1f}（2022〜26 {real['走力_2022']:.1f}）")
    for position, key in [("外野手", "走力（外野手）"), ("遊撃手", "走力（遊撃手）")]:
        v, r = rn[df.position == position].mean(), real[key]
        R.add(s, key, num(v, 1), v, round(r - 4, 2), round(r + 4, 2), f"{r:.1f}（2022〜26。2024〜26 {real[key + '_2024']:.1f}）")
    v = pd.to_numeric(df.age, errors="coerce").mean()
    R.add(s, "年齢の平均", num(v, 1), v, round(real["年齢"] - 0.8, 2), round(real["年齢"] + 0.8, 2), f"{real['年齢']:.1f}（2026年版）")
    for name, x, key in [("ミートの標準偏差", mt, "ミートSD"), ("パワーの標準偏差", pw, "パワーSD")]:
        v, r = x.std(), real[key]
        R.add(s, name, num(v, 1), v, round(r * 0.80, 2), round(r * 1.15, 2), f"{r:.1f}（範囲は実在の0.80〜1.15倍）")


# ---------------------------------------------------------------- 球団生成の外国人

_MASTER = None


def _init_worker():
    logging.disable(logging.WARNING)
    global _MASTER
    import app

    _MASTER = app.load_master_data()


def _team_foreigners(team_seed):
    import app
    from generate_foreign_balance_sample import player_row

    team = app.generate_team(team_seed, master=_MASTER)
    return [{**player_row(p), "team_key": team_seed} for p in team["players"] if p.get("roster_origin") == "foreign_import"]


def collect_team_foreigners(teams, start=1, workers=1):
    """球団生成（seed start〜start+teams-1）の外国人を、個別生成のCSVと同じ形の表にする。"""
    with ProcessPoolExecutor(max_workers=max(1, workers), initializer=_init_worker) as pool:
        rows = [row for part in pool.map(_team_foreigners, range(start, start + teams), chunksize=4) for row in part]
    return pd.DataFrame(rows)


def check_team_pitchers(df):
    R = Result(f"{SCRIPT}.team.pitcher")
    real_pitcher_rows(R, df)
    return R


def check_team_fielders(df):
    R = Result(f"{SCRIPT}.team.fielder")
    real_fielder_rows(R, df)
    return R


# ---------------------------------------------------------------- main


def main(argv):
    parser = argparse.ArgumentParser(description="助っ人外国人用の個別生成CSVを判定します。")
    parser.add_argument("paths", nargs="+", help="生成CSV（scripts/generate_foreign_balance_sample.py で作る）")
    parser.add_argument("--teams", type=int, default=300, help="「実在（2024〜2026年版）」の節を判定する球団生成の球団数（正式は300。0で省く）")
    parser.add_argument("--start", type=int, default=1, help="最初の球団seed")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    checklib.add_common_args(parser)
    args = parser.parse_args(argv)
    graded = []
    seen = {}
    for p in args.paths:
        df = pd.read_csv(p, encoding="utf-8-sig")
        if "category" in df.columns:
            df = df[df.category == "助っ人外国人用"]
        for role, fn in [("投手", check_pitchers), ("野手", check_fielders)]:
            d = df[df.role == role]
            if len(d):
                seen[role] = seen.get(role, 0) + 1
                checks = grade_part(fn, d.reset_index(drop=True), args.boot, REAL_N[role], args.quick)
                if seen[role] > 1:  # 同じ役割のCSVが複数あるときの id の区別
                    for check in checks:
                        check.id += f"#{seen[role]}"
                checklib.print_checks(checks, f"{p}  {role} {len(d)}人")
                graded += checks
    if args.teams > 0:
        teams = collect_team_foreigners(args.teams, args.start, args.workers)
        for role, fn in [("投手", check_team_pitchers), ("野手", check_team_fielders)]:
            d = teams[teams.role == role].reset_index(drop=True)
            checks = grade_part(fn, d, args.boot, REAL_N[role], args.quick, cluster="team_key")
            checklib.print_checks(checks, f"球団生成 {args.teams}球団（seed {args.start}〜{args.start + args.teams - 1}）の外国人 {role} {len(d)}人")
            graded += checks
    print("\n" + checklib.summary_line(graded))
    sys.exit(checklib.finish(SCRIPT, graded, args))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1:])
