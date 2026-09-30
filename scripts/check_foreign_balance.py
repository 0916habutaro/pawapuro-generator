#!/usr/bin/env python3
"""
外国人選手 生成バランス チェッカー

使い方:
    python check_foreign_balance.py <生成CSV> [<生成CSV> ...]

- CSV の role 列（投手／野手）を見て、投手・野手それぞれの完了条件を判定する。
- 判定基準は `外国人投手バランス_改修指示.md` §6 と `外国人野手バランス_改修指示.md` §5。
  ドキュメントの目標値を変えたときは、このファイルの CHECKS も合わせて直すこと。
- 「実在」列は、パワプロ実在外国人（2022〜2026、延べ 投手214人／野手151人）の値（参考）。
- 終了コード: 全項目合格なら 0、不合格があれば 1。
- 正式な判定は 5000人（例: seed 1〜5000）で行う。1000人だとサンプルの揺れで
  境界付近の項目がまれに外れるので、1000人の結果は途中確認用として扱う。
  基準に合わせるために分布そのものを歪めないこと。
"""
import json
import re
import sys

import pandas as pd

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
    def __init__(self):
        self.rows = []

    def add(self, section, item, value, ok, target, real=""):
        self.rows.append((section, item, value, "OK" if ok else "NG", target, real))

    def show(self, title):
        print(f"\n===== {title} =====")
        w = max(len(r[1]) for r in self.rows)
        cur = None
        for sec, item, val, st, tgt, real in self.rows:
            if sec != cur:
                print(f"\n[{sec}]")
                cur = sec
            mark = "  " if st == "OK" else "✗ "
            print(f"{mark}{st}  {item.ljust(w)}  値={val:<10} 目標={tgt:<16} 実在={real}")
        ng = sum(r[3] == "NG" for r in self.rows)
        print(f"\n合計 {len(self.rows)} 項目 / 不合格 {ng}")
        return ng


# ---------------------------------------------------------------- 投手

# 実在の外国人投手に1人もいない特能（§4-2）
P_NOT_REAL = [
    "安全圏○", "立ち上がり○", "重い球", "国際大会○", "闘志", "根性", "勝ち運", "対ランナー×",
    "ボール先行", "短気", "尻上がり", "ジャイロボール", "国際大会×", "対強打者○", "軽い球",
    "ムード○", "全開", "人気者", "ポーカーフェイス", "投打躍動", "投手存在感", "ムード×",
]
# 矛盾ペア（§4-3）。調子安定は「投手調子安定」「調子安定」のどちらの表記でも拾う
P_CONFLICTS = [
    ("安全圏○", "寸前"), ("根性", "短気"), ("要所○", "寸前"), ("球持ち○", "抜け球"),
    ("乱調", ("投手調子安定", "調子安定")), ("尻上がり", "寸前"), ("逃げ球", "寸前"),
    ("荒れ球", "ストライク先行"), ("キレ○", "抜け球"), ("勝ち運", "負け運"),
    ("ストライク先行", "ボール先行"), ("対ランナー○", "対ランナー×"),
    (("投手調子安定", "調子安定"), ("投手調子極端", "調子極端")),
]


def _in(lst, x):
    return has(lst, *x) if isinstance(x, tuple) else x in lst


def check_pitchers(df):
    R = Result()
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
    R.add(s, "最頻値1つへの集中", pct(top), top < 0.15, "15%未満", "13%前後")
    v = sp.between(160, 162).mean(); R.add(s, "160〜162", pct(v), 0.10 <= v <= 0.15, "10〜15%", "12.6%")
    v = (sp >= 163).mean(); R.add(s, "163以上", pct(v), 0.005 <= v <= 0.025, "0.5〜2.5%", "1.4%")
    v = (sp < 150).mean(); R.add(s, "150未満", pct(v), v <= 0.05, "5%以下", "2.8%")

    s = "相関"
    c = sp.corr(ct); R.add(s, "球速×コントロール", num(c), -0.45 <= c <= -0.15, "−0.45〜−0.15", "−0.27")
    c = sp.corr(st); R.add(s, "球速×スタミナ", num(c), -0.45 <= c <= -0.15, "−0.45〜−0.15", "−0.30")
    c = ct.corr(st); R.add(s, "コントロール×スタミナ", num(c), 0.2 <= c <= 0.5, "+0.2〜+0.5", "+0.34")

    s = "コントロール・スタミナ"
    v = (ct < 20).sum(); R.add(s, "コントロール20未満", f"{v}件", v == 0, "0件", "0件（最低22）")
    v = st[starter].mean(); R.add(s, "先発スタミナ平均", num(v, 1), 57 <= v <= 62, "57〜62", "59.7")
    v = st[reliever].mean(); R.add(s, "救援スタミナ平均", num(v, 1), 46 <= v <= 50, "46〜50", "47.7")
    v = (st[reliever] < 38).mean(); R.add(s, "救援スタミナ38未満", pct(v), v <= 0.01, "1%以下", "0%")

    s = "体格・フォーム"
    v = df.height_cm.mean(); R.add(s, "身長平均", num(v, 1), 188 <= v <= 192, "188〜192", "191.5")
    v = (df.pitching_form_type == "アンダースロー").sum(); R.add(s, "アンダースロー", f"{v}件", v == 0, "0件", "0件")
    v = (df.pitching_form_type == "サイドスロー").mean(); R.add(s, "サイドスロー", pct(v), v <= 0.04, "4%以下", "2.3%")

    s = "変化球"
    v = (n_bb == 2).mean(); R.add(s, "2球種", pct(v), 0.50 <= v <= 0.60, "50〜60%", "53.3%")
    v = (n_bb >= 4).sum(); R.add(s, "4球種以上", f"{v}件", v == 0, "0件", "0件")
    v = twoseam.mean(); R.add(s, "ツーシームファスト", pct(v), 0.33 <= v <= 0.42, "33〜42%", "38.3%")
    v = (mx <= 2).mean(); R.add(s, "最大変化量2以下", pct(v), v <= 0.03, "3%以下", "0.9%")
    v = mx[pos == "抑え"].mean(); R.add(s, "抑えの最大変化量平均", num(v), v >= 4.0, "4.0以上", "4.30")
    for nm, lo, hi, real in [("フォーク", None, 0.08, "5.1%"), ("カーブ", None, 0.08, "4.7%"),
                             ("ナックルカーブ", 0.15, None, "21.5%"), ("Hシンカー", 0.15, None, "19.2%")]:
        v = names.map(lambda l: nm in l).mean()
        ok = (lo is None or v >= lo) and (hi is None or v <= hi)
        R.add(s, nm, pct(v), ok, f"{'≧'+pct(lo) if lo else '≦'+pct(hi)}", real)

    s = "特殊能力"
    K = specials.map(lambda l: "奪三振" in l)
    v = K.mean(); R.add(s, "奪三振", pct(v), 0.40 <= v <= 0.52, "40〜52%", "47.2%")
    v = K[sp >= 160].mean() if (sp >= 160).any() else float("nan")
    R.add(s, "奪三振（球速160以上）", pct(v), v >= 0.65, "65%以上", "73%")
    v = specials[ct <= 40].map(lambda l: "四球" in l).mean()
    R.add(s, "四球（制球40以下）", pct(v), v >= 0.70, "70%以上", "84%")
    tot = specials.map(lambda l: sum(x in P_NOT_REAL for x in l)).sum() / n
    R.add(s, "実在にない特能（1人あたり）", num(tot), tot <= 0.05, "0.05以下", "0")
    v = specials.map(lambda l: has(l, "投手調子極端", "調子極端")).mean()
    R.add(s, "調子極端", pct(v), 0.05 <= v <= 0.09, "5〜9%", "7.0%")
    v = specials.map(lambda l: has(l, "投球位置左", "投球位置右")).mean()
    R.add(s, "投球位置左／右", pct(v), v <= 0.01, "1%以下", "0%")
    v = specials.map(lambda l: any(_in(l, a) and _in(l, b) for a, b in P_CONFLICTS)).sum()
    R.add(s, "矛盾ペア", f"{v}件", v == 0, "0件")
    v = ranked.map(lambda d: rank_letter(d, "クイック") in "EFG").mean()
    R.add(s, "クイック悪い(E〜G)", pct(v), v >= 0.50, "50%以上", "56%（2026は67%）")

    s = "ラベル"
    v = (starter & (df.acquisition_role == "ロングリリーフ")).sum()
    R.add(s, "先発のロングリリーフ", f"{v}件", v == 0, "0件")
    return R


# ---------------------------------------------------------------- 野手

F_NOT_REAL = [
    "国際大会×", "ミート多用", "窮地○", "フル出場", "代打○", "帳尻合わせ", "ささやき破り",
    "チャンスメーカー", "かく乱", "リベンジ", "ホーム突入", "プレッシャーラン", "いぶし銀", "人気者",
    "チームプレイ×", "ムード○", "野手存在感", "ムード×", "対エース○", "バント職人",
]


def check_fielders(df):
    R = Result()
    A = df.abilities_json.map(J)
    g = lambda k: A.map(lambda a: a[k]["value"])
    mt, pw, rn, ar, fd, cc = (g(k) for k in ["ミート", "パワー", "走力", "肩力", "守備力", "捕球"])
    tj = A.map(lambda a: a["弾道"])
    specials = df.special_abilities_json.map(J)
    ranked = df.ranked_special_abilities_json.map(J)
    subs = df.sub_positions_json.map(J)
    n = len(df)

    s = "パワー"
    v = pw.std(); R.add(s, "標準偏差", num(v, 1), 8 <= v <= 10, "8〜10", "8.7")
    v = (pw >= 85).mean(); R.add(s, "85以上", pct(v), 0.005 <= v <= 0.03, "0.5〜3%", "1.3%")
    v = (pw >= 90).sum(); R.add(s, "90以上", f"{v}件", v == 0, "0件", "0件（最高87）")
    v = (pw < 55).mean(); R.add(s, "55未満", pct(v), 0.04 <= v <= 0.07, "4〜7%", "5.3%")

    s = "その他の能力"
    v = (mt >= 65).mean(); R.add(s, "ミート65以上", pct(v), v <= 0.05, "5%以下", "4.0%")
    v = (fd >= 60).mean(); R.add(s, "守備力60以上", pct(v), v <= 0.03, "3%以下", "2.0%")
    v = fd.max(); R.add(s, "守備力の最高", str(v), v <= 65, "65以下", "64")
    v = max(rn.max(), ar.max()); R.add(s, "走力・肩力の最高", str(v), v <= 95, "95以下", "95")
    v = max(mt.max(), pw.max(), fd.max(), cc.max()); R.add(s, "ミート・パワー・守備・捕球の最高", str(v), v <= 88, "88以下", "87")

    s = "弾道"
    for t, lo, hi, real in [(2, .25, .32, "28.5%"), (3, .45, .52, "49.0%"), (4, .20, .25, "22.5%")]:
        v = (tj == t).mean(); R.add(s, f"弾道{t}", pct(v), lo <= v <= hi, f"{pct(lo)}〜{pct(hi)}", real)
    c = tj.corr(pw); R.add(s, "弾道×パワー相関", num(c), 0.40 <= c <= 0.55, "0.40〜0.55", "0.42")
    v = ((tj == 2) & (pw >= 75)).mean(); R.add(s, "弾道2でパワー75以上", pct(v), v >= 0.02, "2%以上", "4.0%")

    s = "相関"
    c = mt.corr(pw); R.add(s, "ミート×パワー", num(c), c >= 0.25, "+0.25以上", "+0.37")
    c = pw.corr(fd); R.add(s, "パワー×守備力", num(c), -0.45 <= c <= -0.25, "−0.45〜−0.25", "−0.34")

    s = "ポジション・投打・体格"
    for p, lo, hi, real in [("三塁手", .10, .13, "10.6%"), ("遊撃手", .08, .11, "9.9%"), ("捕手", .02, .04, "3.3%")]:
        v = (df.position == p).mean(); R.add(s, p, pct(v), lo <= v <= hi, f"{pct(lo)}〜{pct(hi)}", real)
    v = (df.batting_throwing == "右投右打").mean(); R.add(s, "右投右打", pct(v), 0.65 <= v <= 0.75, "65〜75%", "72.2%")
    v = (df.batting_throwing == "左投右打").mean(); R.add(s, "左投右打", pct(v), v <= 0.02, "2%以下", "1.3%")
    v = df.height_cm.mean(); R.add(s, "身長平均", num(v, 1), 185 <= v <= 190, "185〜190", "187.7")
    k = subs.map(len)
    v = (k == 2).mean(); R.add(s, "サブポジ2つ", pct(v), 0.33 <= v <= 0.43, "33〜43%", "39.1%")
    v = (k >= 3).sum(); R.add(s, "サブポジ3つ以上", f"{v}件", v == 0, "0件", "0件")

    s = "特殊能力"
    for nm, lo, real in [("三振", .65, "71.5%"), ("積極打法", .38, "46.4%"), ("満塁男", .28, "36.4%")]:
        v = specials.map(lambda l: nm in l).mean(); R.add(s, nm, pct(v), v >= lo, f"{pct(lo)}以上", real)
    tot = specials.map(lambda l: sum(x in F_NOT_REAL for x in l)).sum() / n
    R.add(s, "実在にない特能（1人あたり）", num(tot), tot <= 0.05, "0.05以下", "0")
    v = specials.map(lambda l: has(l, "野手調子安定", "調子安定")).mean()
    R.add(s, "調子安定", pct(v), v <= 0.01, "1%以下", "0%")
    v = ranked.map(lambda d: rank_letter(d, "走塁") in "EFG").mean()
    R.add(s, "走塁悪い(E〜G)", pct(v), v <= 0.10, "10%以下", "5%")
    v = ranked.map(lambda d: rank_letter(d, "送球") in "ABC").mean()
    R.add(s, "送球良い(A〜C)", pct(v), v <= 0.12, "12%以下", "9%")
    return R


# ---------------------------------------------------------------- main


def main(paths):
    ng = 0
    for p in paths:
        df = pd.read_csv(p, encoding="utf-8-sig")
        if "category" in df.columns:
            df = df[df.category == "助っ人外国人用"]
        for role, fn in [("投手", check_pitchers), ("野手", check_fielders)]:
            d = df[df.role == role]
            if len(d):
                ng += fn(d.reset_index(drop=True)).show(f"{p}  {role} {len(d)}人")
    sys.exit(1 if ng else 0)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1:])
