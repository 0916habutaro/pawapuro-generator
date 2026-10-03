#!/usr/bin/env python3
"""
架空球団 生成バランス チェッカー

使い方:
    python check_fictional_balance.py <生成CSV> [<生成CSV> ...] [--team]

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
- 終了コード: 全項目合格なら 0、不合格があれば 1。
- 正式な判定は投手・野手それぞれ 5000人（例: seed 1〜5000）で行う。1000人の結果は途中確認用。
  基準に合わせるために分布そのものを歪めないこと。
"""
import json
import re
import sys

import numpy as np
import pandas as pd

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


def ok_range(v, lo=None, hi=None):
    if pd.isna(v):
        return False
    return (lo is None or v >= lo) and (hi is None or v <= hi)


def has_sp(sp, name):
    return sp.map(lambda l: name in l)


def any_rank(ranked, letter):
    return ranked.map(lambda d: any(v == letter for v in d.values()))


class Result:
    def __init__(self):
        self.rows = []

    def add(self, section, item, value, ok, target, real="", info=False):
        st = "参考" if info else ("OK" if ok else "NG")
        self.rows.append((section, item, value, st, target, real))

    def show(self, title):
        print(f"\n===== {title} =====")
        if not self.rows:
            print("（対象なし）")
            return 0
        w = max(len(r[1]) for r in self.rows)
        cur = None
        for sec, item, val, st, tgt, real in self.rows:
            if sec != cur:
                print(f"\n[{sec}]")
                cur = sec
            mark = "✗ " if st == "NG" else "  "
            print(f"{mark}{st:<4}{item.ljust(w)}  値={val:<10} 目標={tgt:<16} 実在={real}")
        ng = sum(r[3] == "NG" for r in self.rows)
        judged = sum(r[3] != "参考" for r in self.rows)
        print(f"\n合計 {judged} 項目 / 不合格 {ng}")
        return ng


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
# 改修前（seed 1〜5000）のコントロール・スタミナの平均。左右の球速の調整で変わっていないことの確認用。
SPEED_HAND_CONTROL_STAMINA_BEFORE = {
    ("先発", "右"): (53.93, 57.33), ("先発", "左"): (53.47, 57.54),
    ("救援", "右"): (49.01, 46.97), ("救援", "左"): (49.56, 47.06),
}


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
    for (g, h), (ct_before, st_before) in SPEED_HAND_CONTROL_STAMINA_BEFORE.items():
        x = d[(group == g) & (hand == h)]
        for label, col, before in (("コントロール", "control", ct_before), ("スタミナ", "stamina", st_before)):
            v = x[col].mean()
            R.add(s, f"{g}・{h} {label}平均", num(v), ok_range(v, before - 0.5, before + 0.5),
                  f"改修前{before:.2f}±0.5", "")


def check_pitchers(d):
    R = Result()
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

    s = "抑え・起用適性"
    v = sp[closer].mean() if closer.any() else np.nan
    R.add(s, "抑えの球速平均", num(v, 1), ok_range(v, 153), "153以上", "153.6（守護神）")
    v = mx[closer].mean() if closer.any() else np.nan
    R.add(s, "抑えの最大変化量平均", num(v), ok_range(v, 4.2), "4.2以上", "4.45（守護神）")
    v = closer.mean(); R.add(s, "抑えの割合", pct(v), True, "3〜4%（目安）", "2.7%（守護神）", info=True)
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
    R.add(s, "右投手のスクリュー", f"{v}件", v == 0, "0件（仕様）", "0件")
    v = (left & names.map(lambda x: bool(x & RIGHT_ONLY))).sum()
    R.add(s, "左投手のシンカー・Hシンカー", f"{v}件", v == 0, "0件（仕様）", "0件")
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
    R = Result()
    mt, pw, rn, ar, fd, tj = d.contact, d.power, d.run_speed, d.arm_strength, d.fielding, d.trajectory
    specials, ranked, bt, pos, subs = d.sp, d.ranked, d.throws_bats, d.position, d.subs
    rank_of = lambda key: ranked.map(lambda x: x.get(key, "D"))

    s = "投打"
    v = (bt == "右投左打").mean(); R.add(s, "右投左打", pct(v), ok_range(v, 0.35, 0.45), "35〜45%", "40.9%")
    v = (bt == "左投右打").sum(); R.add(s, "左投右打", f"{v}件", v == 0, "0件", "0件")
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
    R = Result()
    s = "プロ入り年齢（2026）"
    if d.entry_route.notna().any():
        v = (d.entry_route == "その他").mean(); R.add(s, "入団経路「その他」", pct(v), ok_range(v, hi=0.02), "2%以下", "1.3%")
    gap = pd.to_numeric(d.entry_gap, errors="coerce")
    if gap.notna().any():
        v = (gap >= 25).mean(); R.add(s, "年齢−プロ年数が25以上", pct(v), ok_range(v, hi=0.05), "5%以下", "2.4%")
    return R


def run(d, title, team=False):
    ng = check_common(d).show(f"{title}  日本人 共通 {len(d)}人")
    for role, fn in [("投手", check_pitchers), ("野手", lambda x: check_fielders(x, team))]:
        x = d[d.role == role]
        if len(x):
            ng += fn(x.reset_index(drop=True)).show(f"{title}  日本人{role} {len(x)}人")
    return ng


def main(argv):
    team = "--team" in argv
    paths = [a for a in argv if a != "--team"]
    ng = 0
    for p in paths:
        df = pd.read_csv(p, encoding="utf-8-sig")
        if "category" in df.columns:
            df = df[df.category == "架空球団用"]
        dom = df[df.roster_origin == "domestic"] if "roster_origin" in df.columns else df
        print(f"\n{p}: 架空球団用 {len(df)}人（日本人 {len(dom)}人 / 外国人 {len(df) - len(dom)}人は check_foreign_balance.py の担当）")
        ng += run(normalize(dom), p, team)
    sys.exit(1 if ng else 0)


if __name__ == "__main__":
    if not [a for a in sys.argv[1:] if a != "--team"]:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1:])
