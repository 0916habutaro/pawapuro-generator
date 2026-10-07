#!/usr/bin/env python3
"""
外国人選手 生成バランス チェッカー

使い方:
    python check_foreign_balance.py <生成CSV> [<生成CSV> ...] [--boot 200] [--update-baselines --reason 理由] [--quick]

- CSV の role 列（投手／野手）を見て、投手・野手それぞれの完了条件を判定する。
- 判定基準は `外国人投手バランス_改修指示.md` §6 と `外国人野手バランス_改修指示.md` §5。
  ドキュメントの目標値を変えたときは、このファイルの CHECKS も合わせて直すこと。
- 「実在」列は、パワプロ実在外国人（2022〜2026、延べ 投手214人／野手151人）の値（参考）。
- 判定の種類・誤差・合否の付け方は checklib.py（判定の整理_改修指示.md）。判定の一覧は reports/checks/check_foreign_balance.csv。
- 終了コード: 不合格が1件でもあれば 1（要注意・受け入れ済みは 0）。
- 正式な判定は 5000人（例: seed 1〜5000）で行う。1000人だとサンプルの揺れで
  境界付近の項目がまれに外れるので、1000人の結果は途中確認用として扱う。
  基準に合わせるために分布そのものを歪めないこと。
"""
import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checklib  # noqa: E402
from checklib import Checks, in_range  # noqa: E402

SCRIPT = "check_foreign_balance"
# 実在の外国人の人数（2022〜2026、延べ 投手214人／野手151人）。実在側の誤差を、生成側の誤差の人数比で見積もる
REAL_N = {"投手": 214, "野手": 151}

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


def grade_part(fn, data, boot, real_n=None, quick=False):
    evaluate = lambda d: fn(d).checks  # noqa: E731
    checks = evaluate(data)
    se_gen = checklib.bootstrap_se(evaluate, data, checklib.resample_frame, n=boot) if boot else {}
    se_real = checklib.scale_se(se_gen, len(data), real_n) if real_n else {}
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
    ("ストライク先行", "ボール先行"), ("対ランナー○", "対ランナー×"),
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
    R.pct(s, "最頻値1つへの集中", top, hi=0.15, real="13%前後")
    R.pct(s, "160〜162", sp.between(160, 162).mean(), 0.10, 0.15, "12.6%")
    R.pct(s, "163以上", (sp >= 163).mean(), 0.005, 0.025, "1.4%")
    R.pct(s, "150未満", (sp < 150).mean(), hi=0.05, real="2.8%")

    s = "相関"
    c = sp.corr(ct); R.add(s, "球速×コントロール", num(c), c, -0.45, -0.15, "−0.27")
    c = sp.corr(st); R.add(s, "球速×スタミナ", num(c), c, -0.45, -0.15, "−0.30")
    c = ct.corr(st); R.add(s, "コントロール×スタミナ", num(c), c, 0.2, 0.5, "+0.34")

    s = "コントロール・スタミナ"
    v = (ct < 20).sum(); R.add(s, "コントロール20未満", f"{v}件", v, hi=0, real="0件（最低22）")
    v = st[starter].mean(); R.add(s, "先発スタミナ平均", num(v, 1), v, 57, 62, "59.7")
    v = st[reliever].mean(); R.add(s, "救援スタミナ平均", num(v, 1), v, 46, 50, "47.7")
    R.pct(s, "救援スタミナ38未満", (st[reliever] < 38).mean(), hi=0.01, real="0%")

    s = "体格・フォーム"
    v = df.height_cm.mean(); R.add(s, "身長平均", num(v, 1), v, 188, 192, "191.5")
    v = (df.pitching_form_type == "アンダースロー").sum(); R.add(s, "アンダースロー", f"{v}件", v, hi=0, real="0件")
    R.pct(s, "サイドスロー", (df.pitching_form_type == "サイドスロー").mean(), hi=0.04, real="2.3%")

    s = "変化球"
    R.pct(s, "2球種", (n_bb == 2).mean(), 0.50, 0.60, "53.3%")
    v = (n_bb >= 4).sum(); R.add(s, "4球種以上", f"{v}件", v, hi=0, real="0件")
    R.pct(s, "ツーシームファスト", twoseam.mean(), 0.33, 0.42, "38.3%")
    has_sf = bbs.map(lambda l: any(x.get("kind") == "second_fastball" for x in l))
    R.pct(s, "3球種以上＋第二球種", ((n_bb >= 3) & has_sf).mean(), hi=0.01, real="0%")
    R.pct(s, "2球種で第二球種なし", ((n_bb == 2) & ~has_sf).mean(), 0.10, 0.20, "14.0%")
    R.pct(s, "最大変化量2以下", (mx <= 2).mean(), hi=0.03, real="0.9%")
    v = mx[pos == "抑え"].mean(); R.add(s, "抑えの最大変化量平均", num(v), v, lo=4.0, real="4.30")
    for nm, lo, hi, real in [("フォーク", None, 0.08, "5.1%"), ("カーブ", None, 0.08, "4.7%"),
                             ("ナックルカーブ", 0.15, None, "21.5%"), ("Hシンカー", 0.15, None, "19.2%")]:
        R.pct(s, nm, names.map(lambda l: nm in l).mean(), lo, hi, real)

    s = "特殊能力"
    K = specials.map(lambda l: "奪三振" in l)
    R.pct(s, "奪三振", K.mean(), 0.40, 0.52, "47.2%")
    v = K[sp >= 160].mean() if (sp >= 160).any() else float("nan")
    R.pct(s, "奪三振（球速160以上）", v, lo=0.65, real="73%")
    R.pct(s, "四球（制球40以下）", specials[ct <= 40].map(lambda l: "四球" in l).mean(), lo=0.70, real="84%")
    tot = specials.map(lambda l: sum(x in P_NOT_REAL for x in l)).sum() / n
    R.add(s, "実在にない特能（1人あたり）", num(tot), tot, hi=0.05, real="0")
    R.pct(s, "調子極端", specials.map(lambda l: has(l, "投手調子極端", "調子極端")).mean(), 0.05, 0.09, "7.0%")
    R.pct(s, "投球位置左／右", specials.map(lambda l: has(l, "投球位置左", "投球位置右")).mean(), hi=0.01, real="0%")
    v = specials.map(lambda l: any(_in(l, a) and _in(l, b) for a, b in P_CONFLICTS)).sum()
    R.add(s, "矛盾ペア", f"{v}件", v, hi=0)
    R.pct(s, "クイック悪い(E〜G)", ranked.map(lambda d: rank_letter(d, "クイック") in "EFG").mean(), lo=0.50, real="56%（2026は67%）")

    s = "ラベル"
    v = (starter & (df.acquisition_role == "ロングリリーフ")).sum()
    R.add(s, "先発のロングリリーフ", f"{v}件", v, hi=0)
    return R


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

    s = "パワー"
    v = pw.std(); R.add(s, "標準偏差", num(v, 1), v, 8, 10, "8.7")
    R.pct(s, "85以上", (pw >= 85).mean(), 0.005, 0.03, "1.3%")
    v = (pw >= 90).sum(); R.add(s, "90以上", f"{v}件", v, hi=0, real="0件（最高87）")
    R.pct(s, "55未満", (pw < 55).mean(), 0.04, 0.07, "5.3%")

    s = "その他の能力"
    R.pct(s, "ミート65以上", (mt >= 65).mean(), hi=0.05, real="4.0%")
    R.pct(s, "守備力60以上", (fd >= 60).mean(), hi=0.03, real="2.0%")
    v = fd.max(); R.add(s, "守備力の最高", str(v), v, hi=65, real="64")
    v = max(rn.max(), ar.max()); R.add(s, "走力・肩力の最高", str(v), v, hi=95, real="95")
    v = max(mt.max(), pw.max(), fd.max(), cc.max()); R.add(s, "ミート・パワー・守備・捕球の最高", str(v), v, hi=88, real="87")

    s = "弾道"
    for t, lo, hi, real in [(2, .25, .32, "28.5%"), (3, .45, .52, "49.0%"), (4, .20, .25, "22.5%")]:
        R.pct(s, f"弾道{t}", (tj == t).mean(), lo, hi, real)
    c = tj.corr(pw); R.add(s, "弾道×パワー相関", num(c), c, 0.40, 0.55, "0.42")
    R.pct(s, "弾道2でパワー75以上", ((tj == 2) & (pw >= 75)).mean(), lo=0.02, real="4.0%")

    s = "相関"
    c = mt.corr(pw); R.add(s, "ミート×パワー", num(c), c, lo=0.25, real="+0.37")
    c = pw.corr(fd); R.add(s, "パワー×守備力", num(c), c, -0.45, -0.25, "−0.34")

    s = "ポジション・投打・体格"
    for p, lo, hi, real in [("三塁手", .10, .13, "10.6%"), ("遊撃手", .08, .11, "9.9%"), ("捕手", .02, .04, "3.3%")]:
        R.pct(s, p, (df.position == p).mean(), lo, hi, real)
    R.pct(s, "右投右打", (df.batting_throwing == "右投右打").mean(), 0.65, 0.75, "72.2%")
    R.pct(s, "左投右打", (df.batting_throwing == "左投右打").mean(), hi=0.02, real="1.3%")
    v = df.height_cm.mean(); R.add(s, "身長平均", num(v, 1), v, 185, 190, "187.7")
    k = subs.map(len)
    R.pct(s, "サブポジ2つ", (k == 2).mean(), 0.33, 0.43, "39.1%")
    v = (k >= 3).sum(); R.add(s, "サブポジ3つ以上", f"{v}件", v, hi=0, real="0件")

    s = "特殊能力"
    for nm, lo, real in [("三振", .65, "71.5%"), ("積極打法", .38, "46.4%"), ("満塁男", .28, "36.4%")]:
        R.pct(s, nm, specials.map(lambda l: nm in l).mean(), lo=lo, real=real)
    R.pct(s, "パワーヒッター", specials.map(lambda l: "パワーヒッター" in l).mean(), hi=0.06, real="3.3%")
    tot = specials.map(lambda l: sum(x in F_NOT_REAL for x in l)).sum() / n
    R.add(s, "実在にない特能（1人あたり）", num(tot), tot, hi=0.05, real="0")
    R.pct(s, "調子安定", specials.map(lambda l: has(l, "野手調子安定", "調子安定")).mean(), hi=0.01, real="0%")
    R.pct(s, "走塁悪い(E〜G)", ranked.map(lambda d: rank_letter(d, "走塁") in "EFG").mean(), hi=0.10, real="5%")
    R.pct(s, "送球良い(A〜C)", ranked.map(lambda d: rank_letter(d, "送球") in "ABC").mean(), hi=0.12, real="9%")
    return R


# ---------------------------------------------------------------- main


def main(argv):
    parser = argparse.ArgumentParser(description="助っ人外国人用の個別生成CSVを判定します。")
    parser.add_argument("paths", nargs="+", help="生成CSV（scripts/generate_foreign_balance_sample.py で作る）")
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
    print("\n" + checklib.summary_line(graded))
    sys.exit(checklib.finish(SCRIPT, graded, args))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1:])
