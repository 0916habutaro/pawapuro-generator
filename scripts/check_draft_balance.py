#!/usr/bin/env python3
"""
ドラフト候補 生成バランス チェッカー

使い方:
    python check_draft_balance.py <生成CSV> [<生成CSV> ...]

- CSV の category が「ドラフト候補用」の行だけを見る（category 列がなければ全行）。
- 育成候補（player_class=育成候補）は除いて判定する（実在データは支配下指名の選手だけのため）。
- 判定基準は `ドラフト候補バランス_改修指示.md` §6。
  ドキュメントの目標値を変えたときは、このファイルの基準も合わせて直すこと。
- 「実在」列は、パワプロ実在選手のプロ1年目（2022〜2026、投手167人／野手139人）の実測値。
  実在データを同じ形式に変換してこのチェッカーにかけると、全項目合格する（年齢の項目は対象外）。
- 終了コード: 全項目合格なら 0、不合格があれば 1。
- 正式な判定は 5000人（例: seed 1〜5000）で行う。2000人だと経路別の人数が少なく
  境界付近の項目がまれに外れるので、途中確認用として扱う。
  基準に合わせるために分布そのものを歪めないこと。
"""
import json
import re
import sys

import pandas as pd

# ---------------------------------------------------------------- 共通

# 通常特能の数から除くもの（緑特能・起用法系）。実在側のデータにこれらが含まれないため
GREEN_USAGE = {
    "積極打法", "積極走塁", "選球眼", "積極守備", "変化球中心", "慎重打法", "積極盗塁", "速球中心",
    "強振多用", "ミート多用", "チームプレイ○", "テンポ○",
    "おまかせ", "調子次第", "慎重盗塁", "ビハインドでも", "代打要員", "スタミナ限界", "接戦時",
    "リード時", "中継ぎエース", "代走要員", "勝利投手", "守備要員", "守護神", "完投",
    "左のワンポイント", "フル出場", "セーブ狙い",
}

MAIN_ROUTES = ["高卒", "大卒", "社会人"]


def J(x):
    try:
        return json.loads(x) if isinstance(x, str) else (x or [])
    except Exception:
        return []


def pct(x):
    return "nan" if pd.isna(x) else f"{x * 100:.1f}%"


def num(x, nd=1):
    return "nan" if pd.isna(x) else f"{x:.{nd}f}"


def between(v, lo, hi):
    return (not pd.isna(v)) and (lo is None or v >= lo) and (hi is None or v <= hi)


def tgt(lo, hi, f):
    if lo is None:
        return f"{f(hi)}以下"
    if hi is None:
        return f"{f(lo)}以上"
    return f"{f(lo)}〜{f(hi)}"


class Result:
    def __init__(self):
        self.rows = []

    def add(self, section, item, value, ok, target, real=""):
        self.rows.append((section, item, value, "OK" if ok else "NG", target, real))

    def rng(self, section, item, v, lo, hi, real="", kind="num"):
        f = pct if kind == "pct" else (lambda x: num(x, 1))
        self.add(section, item, f(v), between(v, lo, hi), tgt(lo, hi, f), real)

    def show(self, title):
        print(f"\n===== {title} =====")
        w = max(len(r[1]) for r in self.rows)
        cur = None
        for sec, item, val, st, tg, real in self.rows:
            if sec != cur:
                print(f"\n[{sec}]")
                cur = sec
            mark = "  " if st == "OK" else "✗ "
            print(f"{mark}{st}  {item.ljust(w)}  値={val:<9} 目標={tg:<14} 実在={real}")
        ng = sum(r[3] == "NG" for r in self.rows)
        print(f"\n合計 {len(self.rows)} 項目 / 不合格 {ng}")
        return ng


def core_specials(lst):
    return [x for x in lst if x not in GREEN_USAGE]


# ---------------------------------------------------------------- 投手


def check_pitchers(df, R):
    A = df.abilities_json.map(J)
    sp = A.map(lambda a: int(re.findall(r"\d+", str(a.get("球速", "0")))[0]))
    ct = A.map(lambda a: a["コントロール"]["value"])
    st = A.map(lambda a: a["スタミナ"]["value"])
    rt = df.entry_route
    brk = df.breaking_balls_json.map(J).map(lambda l: [x for x in l if x.get("kind", "breaking") == "breaking"])
    nb = brk.map(len)
    mx = brk.map(lambda l: max([x.get("movement", 0) for x in l] or [0]))
    spc = df.special_abilities_json.map(J).map(core_specials).map(len)

    s = "投手 球速"
    for r, lo, hi, real in [("高卒", 149, 151, "150.1"), ("大卒", 151, 153, "152.6"), ("社会人", 150.5, 152.5, "151.6")]:
        R.rng(s, f"{r} 平均", sp[rt == r].mean(), lo, hi, real)
    for r, hi, real in [("高卒", 0.05, "2.2%"), ("大卒", 0.05, "0%"), ("社会人", 0.07, "5.4%")]:
        R.rng(s, f"{r} 144以下", (sp[rt == r] <= 144).mean(), None, hi, real, "pct")
    R.rng(s, "158以上（全体）", (sp >= 158).mean(), None, 0.05, "4.8%", "pct")

    s = "投手 コントロール・スタミナ"
    h = rt == "高卒"
    R.rng(s, "高卒 スタミナ10%タイル", st[h].quantile(0.10), 28, None, "34")
    R.rng(s, "高卒 スタミナ90%タイル", st[h].quantile(0.90), None, 50, "45")
    R.rng(s, "高卒 スタミナ最大", st[h].max(), None, 58, "53")
    R.rng(s, "高卒 コントロール平均", ct[h].mean(), 39, 43, "41.4")
    ds = rt.isin(["大卒", "社会人"])
    R.rng(s, "大卒・社会人 スタミナ最大", st[ds].max(), None, 70, "68")
    R.rng(s, "大卒・社会人 スタミナ65以上", (st[ds] >= 65).mean(), None, 0.05, "2.5%", "pct")
    R.rng(s, "コントロール20未満（全体）", (ct < 20).mean(), None, 0.01, "0.6%", "pct")

    s = "投手 変化球"
    R.rng(s, "2球種（全体）", (nb == 2).mean(), 0.25, 0.35, "28.1%", "pct")
    R.add(s, "4球種以上", f"{(nb >= 4).sum()}件", (nb >= 4).sum() == 0, "0件", "0件")
    R.rng(s, "高卒 3球種", (nb[h] == 3).mean(), 0.50, 0.70, "60.9%", "pct")
    R.rng(s, "高卒 最大変化量4以上", (mx[h] >= 4).mean(), None, 0.02, "0%", "pct")
    R.rng(s, "大卒・社会人 最大変化量4以上", (mx[ds] >= 4).mean(), 0.18, 0.28, "20.3%", "pct")
    R.rng(s, "大卒・社会人 最大変化量5以上", (mx[ds] >= 5).mean(), None, 0.07, "5.1%", "pct")
    R.rng(s, "大卒・社会人 総変化量平均", brk[ds].map(lambda l: sum(x.get("movement", 0) for x in l)).mean(), 5.6, 6.6, "6.1")

    s = "投手 特殊能力"
    R.rng(s, "高卒 通常特能の数", spc[h].mean(), 1.8, 2.4, "2.1")
    R.rng(s, "大卒・社会人 通常特能の数", spc[ds].mean(), 2.6, 3.4, "3.0")


# ---------------------------------------------------------------- 野手


def check_fielders(df, R):
    A = df.abilities_json.map(J)
    g = lambda k: A.map(lambda a: a[k]["value"])
    mt, pw, rn, ar, fd = (g(k) for k in ["ミート", "パワー", "走力", "肩力", "守備力"])
    tj = A.map(lambda a: a["弾道"])
    rt = df.entry_route
    h = rt == "高卒"
    ds = rt.isin(["大卒", "社会人"])
    specials = df.special_abilities_json.map(J)
    spc = specials.map(core_specials).map(len)
    pos = df.position

    s = "野手 基本能力"
    R.rng(s, "高卒 走力平均", rn[h].mean(), 59, 63, "61.0")
    R.rng(s, "大卒・社会人 走力平均", rn[ds].mean(), 64, 69, "68.3")
    R.rng(s, "高卒 肩力平均", ar[h].mean(), 64, 69, "68.1")
    R.rng(s, "大卒・社会人 肩力平均", ar[ds].mean(), 61, 66, "63.9")
    R.rng(s, "高卒 ミート平均", mt[h].mean(), 29, 33, "30.7")
    R.rng(s, "大卒 ミート平均", mt[rt == "大卒"].mean(), 36, 40, "37.3")
    R.rng(s, "社会人 ミート平均", mt[rt == "社会人"].mean(), 38, 42, "39.2")
    R.rng(s, "高卒 守備力平均", fd[h].mean(), 35, 40, "37.1")
    R.rng(s, "パワー80以上（全体）", (pw >= 80).mean(), None, 0.01, "0%（最高72）", "pct")
    R.rng(s, "ミート70以上（全体）", (mt >= 70).mean(), None, 0.01, "0%（最高61）", "pct")
    R.rng(s, "肩力50未満（全体）", (ar < 50).mean(), None, 0.10, "7.2%", "pct")

    s = "野手 弾道"
    R.rng(s, "弾道1", (tj == 1).mean(), None, 0.03, "2.2%", "pct")
    R.rng(s, "弾道3以上", (tj >= 3).mean(), 0.45, 0.55, "50.4%", "pct")
    R.rng(s, "高卒 弾道平均", tj[h].mean(), 2.4, 2.7, "2.56")

    s = "野手 守備位置"
    R.rng(s, "捕手 肩力平均", ar[pos == "捕手"].mean(), 70, None, "74.2")
    R.rng(s, "外野手 走力平均", rn[pos == "外野手"].mean(), 67, None, "70.7")
    R.rng(s, "遊撃手の割合", (pos == "遊撃手").mean(), 0.22, 0.30, "28.8%", "pct")
    R.rng(s, "一塁手の割合", (pos == "一塁手").mean(), 0.05, 0.10, "6.5%", "pct")
    R.rng(s, "サブポジ平均", df.sub_positions_json.map(J).map(len).mean(), 0.95, 1.3, "1.12")

    s = "野手 特殊能力"
    R.rng(s, "高卒 通常特能の数", spc[h].mean(), 0.8, 1.3, "1.02")
    R.rng(s, "大卒・社会人 通常特能の数", spc[ds].mean(), 1.4, 2.0, "1.72")
    for nm, real in [("エラー", "4.3%"), ("併殺", "2.9%")]:
        R.rng(s, nm, specials.map(lambda l: nm in l).mean(), None, 0.06, real, "pct")


# ---------------------------------------------------------------- 共通項目


def check_common(df, R):
    bt = df.batting_throwing.astype(str)
    left = bt.str.startswith("左")
    s = "投打・年齢"
    R.rng(s, "左投右打", (bt == "左投右打").mean(), None, 0.01, "0.3%", "pct")
    R.rng(s, "左投げのうち左打ち", (bt[left] == "左投左打").mean(), 0.95, None, "98.3%", "pct")
    R.rng(s, "両打ち（全体）", bt.str.endswith("両打").mean(), None, 0.03, "1.0%", "pct")
    R.rng(s, "投手の左投げ", left[df.role == "投手"].mean(), 0.25, 0.33, "29.3%", "pct")
    R.rng(s, "野手の左投げ", left[df.role == "野手"].mean(), 0.04, 0.10, "7.2%", "pct")
    if "age" in df.columns:
        for r, lo, hi in [("高卒", 18.0, 18.2), ("大卒", 21.7, 21.9), ("社会人", 23.8, 24.2)]:
            R.rng(s, f"{r} 年齢平均", df.age[df.entry_route == r].mean(), lo, hi, "（1年目は+0.7〜0.9）")


# ---------------------------------------------------------------- main


def main(paths):
    ng = 0
    for p in paths:
        df = pd.read_csv(p, encoding="utf-8-sig")
        if "category" in df.columns:
            df = df[df.category == "ドラフト候補用"]
        n_all = len(df)
        if "player_class" in df.columns:
            df = df[df.player_class != "育成候補"]
        df = df.reset_index(drop=True)
        R = Result()
        P = df[df.role == "投手"].reset_index(drop=True)
        F = df[df.role == "野手"].reset_index(drop=True)
        if len(P):
            check_pitchers(P, R)
        if len(F):
            check_fielders(F, R)
        check_common(df, R)
        cnt = df.groupby(["role", "entry_route"]).size()
        small = [f"{k[0]}{k[1]}={v}" for k, v in cnt.items() if k[1] in MAIN_ROUTES and v < 200]
        ng += R.show(f"{p}  {n_all}人中 育成候補を除く{len(df)}人（投手{len(P)}／野手{len(F)}）")
        if small:
            print("注意: 経路別の人数が200人未満の区分があります（揺れで境界付近が外れやすい）: " + ", ".join(small))
    sys.exit(1 if ng else 0)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1:])
