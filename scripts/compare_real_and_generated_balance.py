from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STANDARD_REAL_DIR = Path("reports/real_powerpro_players_12teams")

FIELDER_ABILITIES = ["ミート", "パワー", "走力", "肩力", "守備力", "捕球", "弾道"]
PITCHER_ABILITIES = ["球速", "コントロール", "スタミナ", "球種数", "総変化量", "第二球種数"]
POSITIONS = ["捕手", "一塁手", "二塁手", "三塁手", "遊撃手", "外野手"]
PERCENTILES = [0.10, 0.25, 0.75, 0.90]
CATEGORY_PRIORITY = ["架空球団用", "ドラフト候補用", "助っ人外国人用"]
SPECIAL_CATEGORY_ORDER = ["青特", "赤特", "金特", "緑特", "ランク系", "usage", "不明"]
RANK_SUFFIX_RE = re.compile(r"(?:[A-GＡ-ＧＳ])$")
RED_SPECIAL_NAMES = {"三振", "四球", "一発", "乱調", "スロースターター", "エラー", "併殺", "負け運", "寸前", "抜け球", "軽い球", "シュート回転", "リリース×", "キレ×", "ノビF", "ノビG", "対左打者F", "対左打者G", "対ピンチF", "対ピンチG", "打たれ強さF", "打たれ強さG"}
GREEN_SPECIAL_NAMES = {"積極打法", "慎重打法", "積極走塁", "慎重走塁", "慎重盗塁", "積極盗塁", "選球眼", "積極守備", "チームプレイ○", "チームプレイ×", "テンポ○", "速球中心", "変化球中心", "投球位置左", "投球位置右", "強振多用", "ミート多用"}
USAGE_SPECIAL_NAMES = {"勝利投手", "調子次第", "代打要員", "守備要員", "代走要員", "途中交代", "スタミナ限界", "接戦時", "ビハインドでも", "リード時", "中継ぎエース", "守護神", "セーブ狙い", "おまかせ", "完投", "完封"}
GOLD_SPECIAL_KEYWORDS = ("怪童", "怪物", "精密機械", "鉄腕", "走者釘付", "驚異", "変幻自在", "強心臓", "終盤力", "勝利の星", "アーチスト", "安打製造機", "電光石火", "魔術師", "球界の頭脳", "左キラー", "広角砲", "勝負師", "高速レーザー", "ストライク送球")

REAL_PLAYER_COLS = {
    "role": "role", "main_position": "position", "pitcher_roles": "pitcher_role",
    "top_speed": "球速", "control": "コントロール", "stamina": "スタミナ",
    "trajectory": "弾道", "contact": "ミート", "power": "パワー", "run_speed": "走力",
    "arm_strength": "肩力", "fielding": "守備力", "catching": "捕球",
}
GENERATED_PLAYER_COLS = {"role": "role", "category": "category", "position": "position", "trajectory": "弾道"}

GENERATED_OPTIONAL_FILES = [
    "position_balance_summary.csv", "position_balance_warnings.csv", "position_high_ability_rates.csv",
    "position_distribution_diagnostics.csv", "position_extreme_examples.csv", "warnings.csv",
    "pitcher_aptitude_summary.csv", "second_pitch_summary.csv", "breaking_pitch_summary.csv",
    "breaking_direction_summary.csv", "pitch_count_distribution.csv", "total_movement_distribution.csv",
    "sub_position_summary.csv",
]
REAL_OPTIONAL_FILES = [
    "position_ability_average.csv", "team_fielder_ability_average.csv", "team_pitcher_ability_average.csv",
    "pitcher_role_ability_average.csv", "pitcher_role_summary.csv", "breaking_ball_count_distribution.csv",
    "total_movement_distribution.csv", "second_pitch_summary.csv", "fielder_sub_position_summary.csv",
    "special_kind_summary.csv", "normal_special_summary.csv", "ranked_special_summary.csv",
]
POSITION_RATE_RULES = {
    "捕手": [("ミート", 50), ("ミート", 60), ("守備力", 55), ("守備力", 65)],
    "一塁手": [("パワー", 65), ("パワー", 70), ("パワー", 80)],
    "二塁手": [("走力", 60), ("走力", 70), ("走力", 80), ("守備力", 60), ("守備力", 70)],
    "三塁手": [("パワー", 65), ("パワー", 70), ("パワー", 80), ("肩力", 60), ("肩力", 70)],
    "遊撃手": [("走力", 60), ("走力", 70), ("走力", 80), ("守備力", 60), ("守備力", 70), ("パワー", 60), ("パワー", 65)],
    "外野手": [("パワー", 65), ("走力", 70), ("肩力", 70)],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="実在パワプロ選手データと生成選手データの能力分布差分レポートを作成します。")
    parser.add_argument("--real-dir", type=Path, default=STANDARD_REAL_DIR, help="実在データ取り込み結果ディレクトリ")
    parser.add_argument("--generated-dir", type=Path, help="生成データ検証結果ディレクトリ")
    parser.add_argument("--real-players", type=Path, help="実在 players CSV/Excel")
    parser.add_argument("--real-breaking", type=Path, help="実在 breaking_balls CSV/Excel")
    parser.add_argument("--real-specials", type=Path, help="実在 special_abilities CSV/Excel")
    parser.add_argument("--generated-players", type=Path, help="生成 generated_players CSV/Excel")
    parser.add_argument("--generated-special-kind", type=Path, help="生成 special_kind_stats CSV/Excel")
    parser.add_argument("--generated-special-name", type=Path, help="生成 special_name_stats CSV/Excel")
    parser.add_argument("--generated-ranked-special", type=Path, help="生成 ranked_special_stats CSV/Excel")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/real_vs_generated_balance"), help="CSV/Markdown出力先")
    parser.add_argument("--excel", action="store_true", help="Excelも出力します")
    return parser.parse_args()


def read_table(path: Path | None, sheet: str | int | None = 0) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, sheet_name=sheet)
    return pd.read_csv(path, low_memory=False)


def load_optional_dir_tables(base_dir: Path | None, filenames: list[str]) -> tuple[dict[str, pd.DataFrame], list[str], list[str]]:
    tables: dict[str, pd.DataFrame] = {}
    loaded: list[str] = []
    missing: list[str] = []
    if base_dir is None:
        return tables, loaded, filenames[:]
    for filename in filenames:
        path = base_dir / filename
        if not path.exists():
            missing.append(filename)
            continue
        df = read_table(path)
        tables[Path(filename).stem] = df
        loaded.append(filename)
    return tables, loaded, missing


def first_existing(*paths: Path | None) -> Path | None:
    for path in paths:
        if path and path.exists():
            return path
    return None


def resolve_inputs(args: argparse.Namespace) -> dict[str, pd.DataFrame]:
    real_dir = args.real_dir
    gen_dir = args.generated_dir
    real_book = first_existing(real_dir / "real_powerpro_players.xlsx" if real_dir else None)
    gen_book = first_existing(gen_dir / "ability_balance_report.xlsx" if gen_dir else None)
    real_players = read_table(args.real_players or first_existing(real_dir / "players.csv" if real_dir else None, real_book), "players" if real_book and not args.real_players else 0)
    real_breaking = read_table(args.real_breaking or first_existing(real_dir / "breaking_balls.csv" if real_dir else None, real_book), "breaking_balls" if real_book and not args.real_breaking else 0)
    real_specials = read_table(args.real_specials or first_existing(real_dir / "special_abilities.csv" if real_dir else None, real_book), "special_abilities" if real_book and not args.real_specials else 0)
    gen_players = read_table(args.generated_players or first_existing(gen_dir / "generated_players.csv" if gen_dir else None, gen_book), "players" if gen_book and not args.generated_players else 0)
    real_optional, real_loaded, real_missing = load_optional_dir_tables(real_dir, REAL_OPTIONAL_FILES)
    gen_optional, gen_loaded, gen_missing = load_optional_dir_tables(gen_dir, GENERATED_OPTIONAL_FILES)
    return {"real_players": real_players, "real_breaking": real_breaking, "real_specials": real_specials, "generated_players": gen_players, "_real_optional": real_optional, "_generated_optional": gen_optional, "_real_loaded_files": real_loaded, "_generated_loaded_files": gen_loaded, "_real_missing_files": real_missing, "_generated_missing_files": gen_missing}


def normalize_position(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"左翼手", "中堅手", "右翼手"}:
        return "外野手"
    return text


def normalize_real_players(df: pd.DataFrame, breaking: pd.DataFrame) -> pd.DataFrame:
    out = df.rename(columns={k: v for k, v in REAL_PLAYER_COLS.items() if k in df.columns}).copy()
    if "position" in out:
        out["position"] = out["position"].map(normalize_position)
    for col in [*FIELDER_ABILITIES, "球速", "コントロール", "スタミナ"]:
        if col in out:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if not breaking.empty and {"source", "team", "name"}.issubset(breaking.columns):
        b = breaking.copy()
        b["movement"] = pd.to_numeric(b.get("movement"), errors="coerce").fillna(0)
        per = b.groupby(["source", "team", "name"], dropna=False).agg(球種数=("pitch_type", "count"), 総変化量=("movement", "sum"), 第二球種数=("slot", lambda s: int((pd.to_numeric(s, errors="coerce") >= 2).sum()))).reset_index()
        out = out.merge(per, on=["source", "team", "name"], how="left")
    for col in ["球種数", "総変化量", "第二球種数"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0) if col in out else 0
    out["category"] = "実在12球団"
    return out


def normalize_generated_players(df: pd.DataFrame) -> pd.DataFrame:
    out = df.rename(columns=GENERATED_PLAYER_COLS).copy()
    for col in [*FIELDER_ABILITIES, "球速", "コントロール", "スタミナ", "変化球数", "総変化量"]:
        if col in out:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "pitch_type_count_including_second" in out:
        out["球種数"] = pd.to_numeric(out["pitch_type_count_including_second"], errors="coerce")
    elif "変化球数" in out and "球種数" not in out:
        out["球種数"] = out["変化球数"]
    if "total_movement_including_second" in out:
        out["総変化量"] = pd.to_numeric(out["total_movement_including_second"], errors="coerce")
    if "second_pitch_count" in out:
        out["第二球種数"] = pd.to_numeric(out["second_pitch_count"], errors="coerce").fillna(0)
    elif "第二球種数" not in out:
        out["第二球種数"] = 0
    if "position" in out:
        out["position"] = out["position"].map(normalize_position)
    if "breaking_ball_names" not in out and "変化球方向" in out:
        out["breaking_ball_names"] = out["変化球方向"].fillna("").astype(str).map(lambda text: ",".join(part.split(":", 1)[1].replace("(第2)", "") for part in text.split(",") if ":" in part))
    if "breaking_ball_directions" not in out and "変化球方向" in out:
        out["breaking_ball_directions"] = out["変化球方向"].fillna("").astype(str).map(lambda text: ",".join(part.split(":", 1)[0] for part in text.split(",") if ":" in part))
    if "first_pitch_directions" not in out and "変化球方向" in out:
        out["first_pitch_directions"] = out["変化球方向"].fillna("").astype(str).map(lambda text: ",".join(part.split(":", 1)[0] for part in text.split(",") if ":" in part and "(第2)" not in part))
    if "second_pitch_directions" not in out and "変化球方向" in out:
        out["second_pitch_directions"] = out["変化球方向"].fillna("").astype(str).map(lambda text: ",".join(part.split(":", 1)[0] for part in text.split(",") if ":" in part and "(第2)" in part))
    if "category" not in out:
        out["category"] = "生成"
    return out


def describe(values: pd.Series) -> dict[str, Any]:
    v = pd.to_numeric(values, errors="coerce").dropna()
    return {"人数": int(v.count()), "平均": round(v.mean(), 3) if len(v) else None, "標準偏差": round(v.std(), 3) if len(v) > 1 else 0, "中央値": round(v.median(), 3) if len(v) else None, "最小": v.min() if len(v) else None, "最大": v.max() if len(v) else None, "10%": v.quantile(.10) if len(v) else None, "25%": v.quantile(.25) if len(v) else None, "75%": v.quantile(.75) if len(v) else None, "90%": v.quantile(.90) if len(v) else None}


def ability_compare(real: pd.DataFrame, gen: pd.DataFrame, role: str, abilities: list[str], category: str | None = None) -> pd.DataFrame:
    rows = []
    gbase = gen[gen["role"].eq(role)]
    categories = [category] if category else [c for c in CATEGORY_PRIORITY if c in set(gbase.get("category", []))] or sorted(gbase.get("category", pd.Series(dtype=str)).dropna().unique())
    rbase = real[real["role"].eq(role)]
    for cat in categories:
        g = gbase[gbase["category"].eq(cat)] if "category" in gbase else gbase
        for ability in abilities:
            if ability not in real.columns and ability not in gen.columns:
                continue
            rstat = describe(rbase.get(ability, pd.Series(dtype=float)))
            gstat = describe(g.get(ability, pd.Series(dtype=float)))
            rows.append({"カテゴリ": cat, "対象": role, "能力": ability, **{f"実在_{k}": v for k, v in rstat.items()}, **{f"生成_{k}": v for k, v in gstat.items()}, "平均差分": None if rstat["平均"] is None or gstat["平均"] is None else round(gstat["平均"] - rstat["平均"], 3)})
    return pd.DataFrame(rows)


def position_compare(real: pd.DataFrame, gen: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cat in [c for c in CATEGORY_PRIORITY if c in set(gen.get("category", []))]:
        for pos in POSITIONS:
            r = real[(real["role"].eq("野手")) & (real["position"].eq(pos))]
            g = gen[(gen["role"].eq("野手")) & (gen["category"].eq(cat)) & (gen["position"].eq(pos))]
            for ability in FIELDER_ABILITIES:
                rs, gs = describe(r.get(ability, pd.Series(dtype=float))), describe(g.get(ability, pd.Series(dtype=float)))
                rows.append({"カテゴリ": cat, "ポジション": pos, "能力": ability, "実在人数": rs["人数"], "生成人数": gs["人数"], "実在平均": rs["平均"], "生成平均": gs["平均"], "平均差分": None if rs["平均"] is None or gs["平均"] is None else round(gs["平均"] - rs["平均"], 3), "実在中央値": rs["中央値"], "生成中央値": gs["中央値"], "実在標準偏差": rs["標準偏差"], "生成標準偏差": gs["標準偏差"]})
    return pd.DataFrame(rows)


def role_label(text: Any) -> str | None:
    if pd.isna(text):
        return None
    t = str(text).strip()
    if not t or t in {"nan", "None", "野手", "投手"}:
        return None
    if "先" in t or "先発" in t:
        return "先発"
    if "抑" in t or "抑え" in t:
        return "抑え"
    if "中" in t or "中継" in t:
        return "中継ぎ"
    return t


def aptitude_usage(row: pd.Series) -> str | None:
    if not {"starter_aptitude", "reliever_aptitude", "closer_aptitude"}.issubset(row.index):
        return None
    starter = row.get("starter_aptitude")
    reliever = row.get("reliever_aptitude")
    closer = row.get("closer_aptitude")
    if pd.isna(starter) and pd.isna(reliever) and pd.isna(closer):
        return None
    if closer == "◎":
        return "抑え"
    if starter == "◎":
        return "先発"
    if reliever == "◎":
        return "中継ぎ"
    if starter == "○":
        return "先発"
    if reliever == "○":
        return "中継ぎ"
    if closer == "○":
        return "抑え"
    return "比較対象外"


def assign_pitcher_usage(df: pd.DataFrame, source_columns: list[str], prefer_aptitudes: bool = False) -> pd.Series:
    usage = pd.Series([None] * len(df), index=df.index, dtype="object")
    if prefer_aptitudes:
        usage = df.apply(aptitude_usage, axis=1)
    for column in source_columns:
        if column in df.columns:
            normalized = df[column].map(role_label)
            usage = usage.where(usage.notna(), normalized)
    return usage.fillna("比較対象外")


def pitcher_role_compare(real: pd.DataFrame, gen: pd.DataFrame) -> pd.DataFrame:
    real_pitchers = real[real["role"].eq("投手")].copy()
    gen_pitchers = gen[gen["role"].eq("投手")].copy()
    real_pitchers["起用"] = assign_pitcher_usage(real_pitchers, ["pitcher_role", "起用", "usage", "position"])
    gen_pitchers["起用"] = assign_pitcher_usage(gen_pitchers, ["pitcher_role", "起用", "usage", "position"], prefer_aptitudes=True)
    real_pitchers = real_pitchers[real_pitchers["起用"].isin(["先発", "中継ぎ", "抑え", "比較対象外"])]
    gen_pitchers = gen_pitchers[gen_pitchers["起用"].isin(["先発", "中継ぎ", "抑え", "比較対象外"])]
    rows = []
    for cat in [c for c in CATEGORY_PRIORITY if c in set(gen_pitchers.get("category", []))]:
        cat_gen = gen_pitchers[gen_pitchers["category"].eq(cat)]
        for usage in ["先発", "中継ぎ", "抑え", "比較対象外"]:
            real_usage = real_pitchers[real_pitchers["起用"].eq(usage)]
            gen_usage = cat_gen[cat_gen["起用"].eq(usage)]
            for ability in ["球速", "コントロール", "スタミナ", "球種数", "総変化量"]:
                rs = describe(real_usage.get(ability, pd.Series(dtype=float))) if not real_usage.empty else {"人数": 0, "平均": None}
                gs = describe(gen_usage.get(ability, pd.Series(dtype=float))) if not gen_usage.empty else {"人数": 0, "平均": None}
                diff = None if rs["平均"] is None or gs["平均"] is None else round(gs["平均"] - rs["平均"], 3)
                rows.append({"カテゴリ": cat, "起用": usage, "能力": ability, "実在平均": rs["平均"], "生成平均": gs["平均"], "平均差分": diff, "実在人数": rs["人数"], "生成人数": gs["人数"]})
    return pd.DataFrame(rows)


def _explode_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df:
        return pd.Series(dtype=str)
    values = df[column].fillna("").astype(str).str.split(",").explode().str.strip()
    return values[values.ne("")]


def breaking_compare(real: pd.DataFrame, gen: pd.DataFrame, real_breaking: pd.DataFrame) -> pd.DataFrame:
    rows = []
    real_pitchers = real[real["role"].eq("投手")]
    metrics = [("球種数分布", "球種数"), ("総変化量分布", "総変化量")]
    for label, col in metrics:
        for val, cnt in real_pitchers[col].value_counts(dropna=False).items():
            rows.append({"カテゴリ": "実在12球団", "比較軸": label, "値": val, "件数": int(cnt), "割合%": round(cnt / max(1, len(real_pitchers)) * 100, 2)})
        for cat in [c for c in CATEGORY_PRIORITY if c in set(gen.get("category", []))]:
            gp = gen[(gen["role"].eq("投手")) & (gen["category"].eq(cat))]
            for val, cnt in gp[col].value_counts(dropna=False).items():
                rows.append({"カテゴリ": cat, "比較軸": label, "値": val, "件数": int(cnt), "割合%": round(cnt / max(1, len(gp)) * 100, 2)})
    real_second = int((real_pitchers["第二球種数"] > 0).sum())
    rows.append({"カテゴリ": "実在12球団", "比較軸": "第二球種あり", "値": "あり", "件数": real_second, "割合%": round(real_second / max(1, len(real_pitchers)) * 100, 2)})
    for cat in [c for c in CATEGORY_PRIORITY if c in set(gen.get("category", []))]:
        gp = gen[(gen["role"].eq("投手")) & (gen["category"].eq(cat))]
        gen_second = int((pd.to_numeric(gp.get("第二球種数", pd.Series(dtype=float)), errors="coerce").fillna(0) > 0).sum())
        rows.append({"カテゴリ": cat, "比較軸": "第二球種あり", "値": "あり", "件数": gen_second, "割合%": round(gen_second / max(1, len(gp)) * 100, 2)})
    if not real_breaking.empty:
        if "pitch_type" in real_breaking:
            total = max(1, int(real_breaking["pitch_type"].notna().sum()))
            for name, cnt in real_breaking["pitch_type"].fillna("unknown").astype(str).value_counts().items():
                rows.append({"カテゴリ": "実在12球団", "比較軸": "球種名別出現率", "値": name, "件数": int(cnt), "割合%": round(cnt / total * 100, 2)})
        for axis, col in [("方向別出現率", "direction"), ("変化量別出現数", "movement")]:
            total = max(1, int(real_breaking[col].notna().sum())) if col in real_breaking else 1
            for val, cnt in real_breaking[col].value_counts(dropna=False).items() if col in real_breaking else []:
                rows.append({"カテゴリ": "実在12球団", "比較軸": axis, "値": val, "件数": int(cnt), "割合%": round(cnt / total * 100, 2) if axis.endswith("率") else None})
        for slot_label, mask in [("第一球種", pd.to_numeric(real_breaking.get("slot", pd.Series(dtype=float)), errors="coerce").fillna(1) < 2), ("第二球種", pd.to_numeric(real_breaking.get("slot", pd.Series(dtype=float)), errors="coerce").fillna(1) >= 2)]:
            rb = real_breaking[mask]
            total = max(1, len(rb))
            if "direction" in rb:
                for val, cnt in rb["direction"].value_counts(dropna=False).items():
                    rows.append({"カテゴリ": "実在12球団", "比較軸": f"{slot_label}方向分布", "値": val, "件数": int(cnt), "割合%": round(cnt / total * 100, 2)})
    for cat in [c for c in CATEGORY_PRIORITY if c in set(gen.get("category", []))]:
        gp = gen[(gen["role"].eq("投手")) & (gen["category"].eq(cat))]
        total_pitches = max(1, len(_explode_series(gp, "breaking_ball_names")))
        for name, cnt in _explode_series(gp, "breaking_ball_names").value_counts().items():
            rows.append({"カテゴリ": cat, "比較軸": "球種名別出現率", "値": name, "件数": int(cnt), "割合%": round(cnt / total_pitches * 100, 2)})
        for axis, col in [("方向別出現率", "breaking_ball_directions"), ("第一球種方向分布", "first_pitch_directions"), ("第二球種方向分布", "second_pitch_directions")]:
            values = _explode_series(gp, col)
            total = max(1, len(values))
            for val, cnt in values.value_counts().items():
                rows.append({"カテゴリ": cat, "比較軸": axis, "値": val, "件数": int(cnt), "割合%": round(cnt / total * 100, 2)})
    if not real_breaking.empty and "pitch_type" in real_breaking:
        real_names = set(real_breaking["pitch_type"].dropna().astype(str))
        gen_names = set(_explode_series(gen[gen["role"].eq("投手")], "breaking_ball_names"))
        for name in sorted(real_names - gen_names):
            rows.append({"カテゴリ": "差分", "比較軸": "実在に存在するが生成に出ない球種", "値": name, "件数": 0, "割合%": None})
        for name in sorted(gen_names - real_names):
            rows.append({"カテゴリ": "差分", "比較軸": "生成に存在するが実在にない球種", "値": name, "件数": 0, "割合%": None})
    return pd.DataFrame(rows)

def load_special_kind_map() -> dict[str, str]:
    path = ROOT / "data" / "special_abilities.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    if not {"name", "kind"}.issubset(df.columns):
        return {}
    return {str(row["name"]): normalize_special_category(row.get("kind"), row.get("name")) for _, row in df.iterrows()}


def normalize_special_category(kind: Any, name: Any = "") -> str:
    t = "" if pd.isna(kind) else str(kind).strip()
    n = "" if pd.isna(name) else str(name).strip()
    if t in {"rank", "ランク系"} or RANK_SUFFIX_RE.search(n):
        return "ランク系"
    if t in {"red", "赤特"} or n in RED_SPECIAL_NAMES:
        return "赤特"
    if t in {"green", "緑特"} or n in GREEN_SPECIAL_NAMES:
        return "緑特"
    if t in {"usage"} or n in USAGE_SPECIAL_NAMES:
        return "usage"
    if t in {"gold", "金特"} or any(keyword in n for keyword in GOLD_SPECIAL_KEYWORDS):
        return "金特"
    if t in {"blue", "normal", "neutral", "mixed", "青特"}:
        return "青特"
    return t if t else "不明"


def special_tables(real_specials: pd.DataFrame, gen: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    special_kind_by_name = load_special_kind_map()
    real_total = max(1, int(real_specials[["team", "name"]].drop_duplicates().shape[0])) if {"team", "name"}.issubset(real_specials.columns) else 1
    rs = real_specials.copy()
    if not rs.empty:
        rs["カテゴリ正規化"] = rs.apply(lambda r: special_kind_by_name.get(str(r.get("special", "")), normalize_special_category(r.get("special_kind"), r.get("special"))), axis=1)
    cat_rows = []
    for cat, cnt in (rs["カテゴリ正規化"].value_counts() if "カテゴリ正規化" in rs else pd.Series(dtype=int)).items():
        cat_rows.append({"データ": "実在12球団", "カテゴリ": cat, "出現数": int(cnt), "出現率%": round(cnt / real_total * 100, 2)})
    name_rows = []
    rank_rows = []
    if "special" in rs and "カテゴリ正規化" in rs:
        normal_rs = rs[rs["カテゴリ正規化"].ne("ランク系")].copy()
        for (category, name), cnt in normal_rs.groupby(["カテゴリ正規化", "special"], dropna=False).size().items():
            name_rows.append({"データ": "実在12球団", "特殊能力": name, "カテゴリ": category if pd.notna(category) else "不明", "出現数": int(cnt), "出現率%": round(cnt / real_total * 100, 2)})
        rank_rs = rs[rs["カテゴリ正規化"].eq("ランク系")].copy()
        for name, cnt in rank_rs["special"].value_counts(dropna=False).items():
            rank_rows.append({"データ": "実在12球団", "ランク系特殊能力": name, "カテゴリ": "ランク系", "出現数": int(cnt), "出現率%": round(cnt / real_total * 100, 2)})
    for cat in [c for c in CATEGORY_PRIORITY if c in set(gen.get("category", []))]:
        sub = gen[gen["category"].eq(cat)]
        total = max(1, len(sub))
        generated_category_counts: dict[str, int] = {}
        if "特殊能力" in sub:
            exploded = sub["特殊能力"].fillna("").astype(str).str.split(",").explode().str.strip()
            exploded = exploded[exploded.ne("")]
            for name, cnt in exploded.value_counts().items():
                category = special_kind_by_name.get(str(name), normalize_special_category("", name)) or "不明"
                generated_category_counts[category] = generated_category_counts.get(category, 0) + int(cnt)
                name_rows.append({"データ": cat, "特殊能力": name, "カテゴリ": category, "出現数": int(cnt), "出現率%": round(cnt / total * 100, 2)})
        if "ランク系特殊能力" in sub:
            exploded = sub["ランク系特殊能力"].fillna("").astype(str).str.split(",").explode().str.strip()
            exploded = exploded[exploded.ne("")]
            for name, cnt in exploded.value_counts().items():
                generated_category_counts["ランク系"] = generated_category_counts.get("ランク系", 0) + int(cnt)
                rank_rows.append({"データ": cat, "ランク系特殊能力": name, "カテゴリ": "ランク系", "出現数": int(cnt), "出現率%": round(cnt / total * 100, 2)})
        for category in SPECIAL_CATEGORY_ORDER:
            cnt = generated_category_counts.get(category, 0)
            if cnt or category in {"赤特", "金特", "緑特", "ランク系"}:
                cat_rows.append({"データ": cat, "カテゴリ": category, "出現数": cnt, "出現率%": round(cnt / total * 100, 2)})
    return pd.DataFrame(cat_rows), pd.DataFrame(name_rows), pd.DataFrame(rank_rows)


def category_rate(special_cat: pd.DataFrame, dataset: str, category: str) -> float:
    match = special_cat[(special_cat["データ"].eq(dataset)) & (special_cat["カテゴリ"].eq(category))]
    return float(match["出現率%"].sum()) if not match.empty else 0.0


def build_warnings(fielder: pd.DataFrame, pitcher: pd.DataFrame, pos: pd.DataFrame, breaking: pd.DataFrame, special_cat: pd.DataFrame) -> pd.DataFrame:
    rows = []
    base_f = fielder[fielder["カテゴリ"].eq("架空球団用")]
    trajectory = base_f[base_f["能力"].eq("弾道")]
    if trajectory.empty or trajectory["生成_平均"].isna().all():
        rows.append({"警告": "弾道比較が未比較", "詳細": "生成側の弾道列を確認してください"})
    for _, r in base_f[base_f["平均差分"].abs() >= 8].iterrows():
        rows.append({"警告": "実在平均より生成平均が±8以上ズレている野手能力", "詳細": f"{r['能力']}: {r['平均差分']}"})
    for _, r in pitcher[(pitcher["カテゴリ"].eq("架空球団用")) & (pitcher["能力"].eq("球速")) & (pitcher["平均差分"].abs() >= 4)].iterrows():
        rows.append({"警告": "実在平均より生成平均が±4km/h以上ズレている球速", "詳細": f"球速: {r['平均差分']}"})
    for _, r in pos[(pos["カテゴリ"].eq("架空球団用")) & (pos["平均差分"].abs() >= 8)].iterrows():
        rows.append({"警告": "野手ポジション別の能力差が±8以上", "詳細": f"{r['ポジション']} {r['能力']}: {r['平均差分']}"})
    def ratio(cat: str, axis: str, val: Any) -> float:
        m = breaking[(breaking["カテゴリ"].eq(cat)) & (breaking["比較軸"].eq(axis)) & (breaking["値"].astype(str).eq(str(val)))]
        return float(m["割合%"].iloc[0]) if not m.empty and pd.notna(m["割合%"].iloc[0]) else 0.0
    if ratio("架空球団用", "球種数分布", 1) - ratio("実在12球団", "球種数分布", 1) >= 10:
        rows.append({"警告": "1球種投手率が実在より10ポイント以上高い", "詳細": "架空球団用を確認"})
    low_real = breaking[(breaking["カテゴリ"].eq("実在12球団")) & (breaking["比較軸"].eq("総変化量分布")) & (pd.to_numeric(breaking["値"], errors="coerce") <= 3)]["割合%"].sum()
    low_gen = breaking[(breaking["カテゴリ"].eq("架空球団用")) & (breaking["比較軸"].eq("総変化量分布")) & (pd.to_numeric(breaking["値"], errors="coerce") <= 3)]["割合%"].sum()
    if low_gen - low_real >= 10:
        rows.append({"警告": "総変化量3以下率が実在より10ポイント以上高い", "詳細": f"実在={low_real:.2f}% 生成={low_gen:.2f}%"})
    real_gold = special_cat[(special_cat["データ"].eq("実在12球団")) & (special_cat["カテゴリ"].eq("金特"))]["出現数"].sum()
    gen_gold = special_cat[(special_cat["データ"].eq("架空球団用")) & (special_cat["カテゴリ"].eq("金特"))]["出現数"].sum()
    if real_gold > 0 and gen_gold == 0:
        rows.append({"警告": "金特が実在にはあるが生成で0件", "詳細": "架空球団用"})
    for category in ["赤特", "金特", "緑特"]:
        real_rate = category_rate(special_cat, "実在12球団", category)
        gen_rate = category_rate(special_cat, "架空球団用", category)
        if abs(gen_rate - real_rate) >= 10:
            rows.append({"警告": f"{category}出現率が実在より大幅に高い/低い", "詳細": f"実在={real_rate:.2f}% 生成={gen_rate:.2f}%"})
    unknown = special_cat[special_cat["カテゴリ"].eq("不明")].copy() if "カテゴリ" in special_cat else pd.DataFrame()
    unknown_count = int(pd.to_numeric(unknown.get("出現数", pd.Series(dtype=int)), errors="coerce").fillna(0).sum()) if not unknown.empty else 0
    if unknown_count:
        rows.append({"警告": "カテゴリ不明の特殊能力があります", "詳細": f"不明={unknown_count}件"})
    return pd.DataFrame(rows or [{"警告": "警告なし", "詳細": "主要しきい値内です"}])


def percentile_compare(fielder: pd.DataFrame, pitcher: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for df in [fielder, pitcher]:
        for _, r in df.iterrows():
            for p in ["10%", "25%", "75%", "90%"]:
                rows.append({"カテゴリ": r["カテゴリ"], "対象": r["対象"], "能力": r["能力"], "分位点": p, "実在": r.get(f"実在_{p}"), "生成": r.get(f"生成_{p}"), "差分": None if pd.isna(r.get(f"実在_{p}")) or pd.isna(r.get(f"生成_{p}")) else round(r.get(f"生成_{p}") - r.get(f"実在_{p}"), 3)})
    return pd.DataFrame(rows)


def _available_categories(gen: pd.DataFrame) -> list[str]:
    return [c for c in CATEGORY_PRIORITY if c in set(gen.get("category", []))]


def trajectory_distribution_compare(real: pd.DataFrame, gen: pd.DataFrame) -> pd.DataFrame:
    rows = []
    datasets = [("実在12球団", real[real["role"].eq("野手")])]
    datasets += [(cat, gen[(gen["role"].eq("野手")) & (gen["category"].eq(cat))]) for cat in _available_categories(gen)]
    for label, df in datasets:
        for pos in POSITIONS:
            sub = df[df["position"].eq(pos)]
            values = pd.to_numeric(sub.get("弾道", pd.Series(dtype=float)), errors="coerce")
            total = max(1, int(values.notna().sum()))
            for trajectory in [1, 2, 3, 4]:
                cnt = int(values.eq(trajectory).sum())
                rows.append({"データ": label, "ポジション": pos, "弾道": trajectory, "人数": cnt, "割合%": round(cnt / total * 100, 2)})
            high = int(values.ge(3).sum())
            rows.append({"データ": label, "ポジション": pos, "弾道": "3以上", "人数": high, "割合%": round(high / total * 100, 2)})
    return pd.DataFrame(rows)


def position_rate_compare(real: pd.DataFrame, gen: pd.DataFrame) -> pd.DataFrame:
    rows = []
    datasets = [("実在12球団", real[real["role"].eq("野手")])]
    datasets += [(cat, gen[(gen["role"].eq("野手")) & (gen["category"].eq(cat))]) for cat in _available_categories(gen)]
    for label, df in datasets:
        for pos, rules in POSITION_RATE_RULES.items():
            sub = df[df["position"].eq(pos)]
            total = max(1, len(sub))
            for ability, threshold in rules:
                values = pd.to_numeric(sub.get(ability, pd.Series(dtype=float)), errors="coerce")
                cnt = int(values.ge(threshold).sum())
                rows.append({"データ": label, "ポジション": pos, "指標": f"{ability}{threshold}以上", "能力": ability, "しきい値": threshold, "人数": cnt, "母数": len(sub), "割合%": round(cnt / total * 100, 2)})
    return pd.DataFrame(rows)


def generated_warning_tables(optional: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames = []
    for key in ["warnings", "position_balance_warnings"]:
        df = optional.get(key, pd.DataFrame())
        if not df.empty:
            tmp = df.copy()
            tmp["source_file"] = f"{key}.csv"
            if "severity" not in tmp:
                tmp["severity"] = "unknown"
            frames.append(tmp)
    all_warnings = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame(columns=["severity", "source_file"])
    summary = all_warnings["severity"].fillna("unknown").astype(str).value_counts().rename_axis("severity").reset_index(name="件数")
    high = all_warnings[all_warnings["severity"].fillna("").astype(str).str.lower().eq("high")].copy()
    return summary, high


def sub_position_compare(real_optional: dict[str, pd.DataFrame], gen_optional: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    mapping = [("実在12球団", real_optional.get("fielder_sub_position_summary", pd.DataFrame())), ("生成", gen_optional.get("sub_position_summary", pd.DataFrame()))]
    for label, df in mapping:
        if df.empty:
            continue
        for _, r in df.iterrows():
            axis = r.get("集計軸", r.get("metric", ""))
            value = r.get("値", r.get("value", ""))
            rows.append({"データ": label, "集計軸": axis, "値": value, "人数": r.get("人数", r.get("count")), "割合%": r.get("割合%", r.get("rate%"))})
    return pd.DataFrame(rows)


def pitcher_aptitude_compare(real_optional: dict[str, pd.DataFrame], gen_optional: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for label, df in [("実在12球団", real_optional.get("pitcher_role_summary", real_optional.get("pitcher_role_ability_average", pd.DataFrame()))), ("生成", gen_optional.get("pitcher_aptitude_summary", pd.DataFrame()))]:
        if df.empty:
            continue
        for _, r in df.iterrows():
            rows.append({"データ": label, "集計軸": r.get("集計軸", r.get("pitcher_roles", r.get("role", ""))), "値": r.get("値", r.get("pitcher_roles", "")), "人数": r.get("人数", r.get("count")), "割合%": r.get("割合%", r.get("rate%")), "平均球速": r.get("平均球速", r.get("top_speed"))})
    return pd.DataFrame(rows)


def distribution_compare_from_optional(real_optional: dict[str, pd.DataFrame], gen_optional: dict[str, pd.DataFrame], real_key: str, gen_key: str, label: str) -> pd.DataFrame:
    rows = []
    for data_label, df in [("実在12球団", real_optional.get(real_key, pd.DataFrame())), ("生成", gen_optional.get(gen_key, pd.DataFrame()))]:
        if df.empty:
            continue
        for _, r in df.iterrows():
            rows.append({"データ": data_label, "分布": r.get("分布", label), "集計軸": r.get("集計軸", "全体"), "値": r.get("値", r.get("value")), "人数": r.get("人数", r.get("count")), "割合%": r.get("割合%", r.get("rate%"))})
    return pd.DataFrame(rows)


def second_pitch_compare(real_optional: dict[str, pd.DataFrame], gen_optional: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for data_label, df in [("実在12球団", real_optional.get("second_pitch_summary", pd.DataFrame())), ("生成", gen_optional.get("second_pitch_summary", pd.DataFrame()))]:
        if df.empty:
            continue
        for _, r in df.iterrows():
            rows.append({"データ": data_label, "集計軸": r.get("集計軸", r.get("metric", "")), "値": r.get("値", r.get("value", "")), "人数": r.get("人数", r.get("count")), "割合%": r.get("割合%", r.get("rate%"))})
    return pd.DataFrame(rows)


def _rate_lookup(df: pd.DataFrame, data: str, pos: str, key: Any, key_col: str) -> float | None:
    if df.empty:
        return None
    m = df[(df["データ"].eq(data)) & (df["ポジション"].eq(pos)) & (df[key_col].astype(str).eq(str(key)))]
    return None if m.empty else float(m["割合%"].iloc[0])


def write_summary(tables: dict[str, pd.DataFrame], output_dir: Path, meta: dict[str, list[str]]) -> None:
    lines = ["# 実在12球団 vs 生成選手 バランス比較サマリー", "", "## 重視カテゴリ", "- 架空球団用を実在12球団との主比較対象として扱います。", "- ドラフト候補用は低め、助っ人外国人用は尖りを許容して警告を解釈してください。", ""]
    lines.extend(["## 使用データ", f"- 実在データ: `{meta.get('real_dir', [''])[0]}`", f"- 生成データ: `{meta.get('generated_dir', [''])[0]}`", ""])
    lines.extend(["## 読み込み状況", "", "### 実在側で読み込んだ任意ファイル"])
    lines.extend([f"- `{x}`" for x in meta.get("real_loaded", [])] or ["- なし"])
    lines.append("### 生成側で読み込んだ任意ファイル")
    lines.extend([f"- `{x}`" for x in meta.get("generated_loaded", [])] or ["- なし"])
    lines.append("### 読み込めなかった任意ファイル")
    missing = [f"実在: `{x}`" for x in meta.get("real_missing", [])] + [f"生成: `{x}`" for x in meta.get("generated_missing", [])]
    lines.extend([f"- {x}" for x in missing] or ["- なし"])
    lines.extend(["", "## 架空球団用と実在12球団の主要差分", ""])
    for _, r in tables.get("fielder_ability_compare", pd.DataFrame()).query("カテゴリ == '架空球団用'").head(12).iterrows():
        lines.append(f"- 野手 {r['能力']}: 実在平均 {r.get('実在_平均')} / 生成平均 {r.get('生成_平均')} / 差分 {r.get('平均差分')}")
    for _, r in tables.get("pitcher_ability_compare", pd.DataFrame()).query("カテゴリ == '架空球団用'").head(8).iterrows():
        lines.append(f"- 投手 {r['能力']}: 実在平均 {r.get('実在_平均')} / 生成平均 {r.get('生成_平均')} / 差分 {r.get('平均差分')}")
    lines.extend(["", "## 弾道分布の要約", ""])
    traj = tables.get("trajectory_distribution_compare", pd.DataFrame())
    for pos in ["一塁手", "三塁手", "外野手", "捕手", "二塁手", "遊撃手"]:
        real3, gen3 = _rate_lookup(traj, "実在12球団", pos, "3以上", "弾道"), _rate_lookup(traj, "架空球団用", pos, "3以上", "弾道")
        real4, gen4 = _rate_lookup(traj, "実在12球団", pos, 4, "弾道"), _rate_lookup(traj, "架空球団用", pos, 4, "弾道")
        lines.append(f"- {pos}: 弾道3以上 実在 {real3}% / 架空 {gen3}%、弾道4 実在 {real4}% / 架空 {gen4}%")
    lines.extend(["", "## ポジション別上位割合の要約", ""])
    pr = tables.get("position_rate_compare", pd.DataFrame())
    for metric in ["ミート60以上", "パワー70以上", "走力70以上", "守備力70以上", "肩力70以上"]:
        sub = pr[(pr["データ"].eq("架空球団用")) & (pr["指標"].eq(metric))].head(6) if not pr.empty else pd.DataFrame()
        if not sub.empty:
            lines.append("- " + " / ".join(f"{r['ポジション']} {r['割合%']}%" for _, r in sub.iterrows()))
    lines.extend(["", "## severity 別 warning 件数", ""])
    sev = tables.get("generated_warning_severity_summary", pd.DataFrame())
    lines.extend([f"- {r['severity']}: {r['件数']}件" for _, r in sev.iterrows()] or ["- severity付き生成警告なし"])
    high = tables.get("generated_high_warnings", pd.DataFrame())
    if not high.empty:
        lines.append("- high警告タイプ: " + ", ".join(sorted(set(high.get("警告タイプ", high.get("警告", pd.Series(dtype=str))).dropna().astype(str)))))
        lines.append(f"- high代表例: {high.iloc[0].to_dict()}")
    lines.extend(["", "## 第二球種・変化球分布の要約", ""])
    sp = tables.get("second_pitch_compare", pd.DataFrame())
    lines.extend([f"- {r['データ']} {r['集計軸']} {r['値']}: {r.get('割合%')}%" for _, r in sp.head(8).iterrows()] or ["- 任意サマリーなし（既存の breaking_ball_compare を参照）。"])
    lines.extend(["", "## サブポジ比較の要約", ""])
    subpos = tables.get("sub_position_compare", pd.DataFrame())
    lines.extend([f"- {r['データ']} {r['集計軸']} {r['値']}: {r.get('割合%')}%" for _, r in subpos.head(12).iterrows()] or ["- サブポジ任意サマリーなし。"])
    left_bad = subpos[subpos["値"].astype(str).str.contains("左投げ野手の二三遊サブ", na=False)] if not subpos.empty else pd.DataFrame()
    if not left_bad.empty:
        lines.append("- 左投げ野手の二三遊サブ警告あり: " + "; ".join(f"{r['データ']} {r.get('人数')}人" for _, r in left_bad.iterrows()))
    lines.extend(["", "## 警告", ""])
    for _, row in tables["warnings"].iterrows():
        lines.append(f"- {row['警告']}: {row['詳細']}")
    lines.extend(["", "## 残課題", "- 任意CSVが欠けている項目は従来の players / breaking_balls / special_abilities 由来の比較、またはスキップで後方互換運用しています。", "- 実在側に生成側と同じ粒度の詳細診断がない項目は参考比較として扱ってください。"])
    lines.extend(["", "## 出力CSV", ""])
    for name in tables:
        lines.append(f"- `{name}.csv`")
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    data = resolve_inputs(args)
    real = normalize_real_players(data["real_players"], data["real_breaking"])
    gen = normalize_generated_players(data["generated_players"])
    if real.empty or gen.empty:
        raise SystemExit("実在/生成の players データを読み込めませんでした。--real-dir/--generated-dir または個別ファイルを確認してください。")
    overall = pd.DataFrame([{"データ": "実在12球団", "投手人数": int(real["role"].eq("投手").sum()), "野手人数": int(real["role"].eq("野手").sum())}, *[{"データ": c, "投手人数": int(gen[(gen["category"].eq(c)) & (gen["role"].eq("投手"))].shape[0]), "野手人数": int(gen[(gen["category"].eq(c)) & (gen["role"].eq("野手"))].shape[0])} for c in CATEGORY_PRIORITY if c in set(gen.get("category", []))]])
    fielder = ability_compare(real, gen, "野手", FIELDER_ABILITIES)
    pitcher = ability_compare(real, gen, "投手", PITCHER_ABILITIES)
    position = position_compare(real, gen)
    pitch_role = pitcher_role_compare(real, gen)
    breaking = breaking_compare(real, gen, data["real_breaking"])
    special_cat, special_name, rank_name = special_tables(data["real_specials"], gen)
    real_optional = data["_real_optional"]
    generated_optional = data["_generated_optional"]
    severity_summary, high_warnings = generated_warning_tables(generated_optional)
    tables = {"overall_compare": overall, "fielder_ability_compare": fielder, "pitcher_ability_compare": pitcher, "position_compare": position, "pitcher_role_compare": pitch_role, "breaking_ball_compare": breaking, "special_ability_category_compare": special_cat, "special_ability_name_compare": special_name, "rank_ability_compare": rank_name, "percentile_compare": percentile_compare(fielder, pitcher)}
    tables.update({
        "trajectory_distribution_compare": trajectory_distribution_compare(real, gen),
        "position_rate_compare": position_rate_compare(real, gen),
        "generated_warning_severity_summary": severity_summary,
        "generated_high_warnings": high_warnings,
        "sub_position_compare": sub_position_compare(real_optional, generated_optional),
        "pitcher_aptitude_compare": pitcher_aptitude_compare(real_optional, generated_optional),
        "second_pitch_compare": second_pitch_compare(real_optional, generated_optional),
        "pitch_count_distribution_compare": distribution_compare_from_optional(real_optional, generated_optional, "breaking_ball_count_distribution", "pitch_count_distribution", "球種数分布"),
        "total_movement_distribution_compare": distribution_compare_from_optional(real_optional, generated_optional, "total_movement_distribution", "total_movement_distribution", "総変化量分布"),
    })
    for key, axis in [("breaking_pitch_summary", "生成_球種名別詳細"), ("breaking_direction_summary", "生成_方向別詳細")]:
        df = generated_optional.get(key, pd.DataFrame())
        if not df.empty:
            extra = df.copy()
            extra.insert(0, "カテゴリ", "生成詳細")
            extra.insert(1, "比較軸", axis)
            tables["breaking_ball_compare"] = pd.concat([tables["breaking_ball_compare"], extra], ignore_index=True, sort=False)
    tables["warnings"] = build_warnings(fielder, pitcher, position, breaking, special_cat)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(args.output_dir / f"{name}.csv", index=False, encoding="utf-8-sig")
    if args.excel:
        with pd.ExcelWriter(args.output_dir / "real_vs_generated_balance.xlsx") as writer:
            for name, df in tables.items():
                df.to_excel(writer, sheet_name=name[:31], index=False)
    write_summary(tables, args.output_dir, {"real_dir": [str(args.real_dir)], "generated_dir": [str(args.generated_dir)], "real_loaded": data["_real_loaded_files"], "generated_loaded": data["_generated_loaded_files"], "real_missing": data["_real_missing_files"], "generated_missing": data["_generated_missing_files"]})
    print(f"比較レポートを出力しました: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
