from __future__ import annotations

import argparse
from functools import lru_cache
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



def load_special_master() -> pd.DataFrame:
    path = ROOT / "data" / "special_abilities.csv"
    if not path.exists():
        return pd.DataFrame(columns=["name", "kind", "group", "target_role"])
    df = pd.read_csv(path)
    for col in ["name", "kind", "group", "target_role"]:
        if col not in df:
            df[col] = ""
    df["カテゴリ"] = df.apply(lambda r: normalize_special_category(r.get("kind"), r.get("name")), axis=1)
    df["対象役割"] = df["target_role"].fillna("").replace({"": "共通"})
    return df


def special_master_maps() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    master = load_special_master()
    return (
        dict(zip(master["name"].astype(str), master["カテゴリ"].astype(str))),
        dict(zip(master["name"].astype(str), master["対象役割"].astype(str))),
        dict(zip(master["name"].astype(str), master["group"].astype(str))),
    )


def _split_specials(value: Any) -> list[str]:
    if pd.isna(value):
        return []
    return [part.strip() for part in str(value).replace("、", ",").split(",") if part.strip()]


def _player_key_cols(df: pd.DataFrame) -> list[str]:
    cols = [c for c in ["source", "team", "name", "seed"] if c in df.columns]
    return cols or ["name"] if "name" in df.columns else []


def build_special_events(real_players: pd.DataFrame, real_specials: pd.DataFrame, gen: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    kind_map, role_map, group_map = special_master_maps()
    real = real_specials.copy()
    if not real.empty and {"team", "name"}.issubset(real.columns):
        merge_cols = [c for c in ["source", "team", "name"] if c in real.columns and c in real_players.columns]
        cols = merge_cols + [c for c in ["role", "category", "position", "pitcher_role", "usage"] if c in real_players.columns]
        real = real.merge(real_players[cols].drop_duplicates(), on=merge_cols, how="left") if merge_cols else real
    real_rows = []
    for _, r in real.iterrows():
        name = str(r.get("special", "")).strip()
        if not name:
            continue
        cat = kind_map.get(name, normalize_special_category(r.get("special_kind"), name))
        real_rows.append({"データ": "実在12球団", "カテゴリ": "実在12球団", "対象": r.get("role", "不明"), "選手キー": "|".join(str(r.get(c, "")) for c in _player_key_cols(real)), "選手名": r.get("name", ""), "特殊能力": name, "特殊能力カテゴリ": cat, "対象役割": role_map.get(name, "不明"), "ランク系統": ranked_special_base(name) if cat == "ランク系" else group_map.get(name, "")})
    gen_rows = []
    for idx, r in gen.iterrows():
        key = str(r.get("seed", idx))
        for name in _split_specials(r.get("特殊能力", "")):
            cat = kind_map.get(name, normalize_special_category("", name))
            gen_rows.append({"データ": "生成", "カテゴリ": r.get("category", "生成"), "対象": r.get("role", "不明"), "選手キー": key, "選手名": r.get("name", ""), "特殊能力": name, "特殊能力カテゴリ": cat, "対象役割": role_map.get(name, "不明"), "ランク系統": group_map.get(name, "")})
        for name in _split_specials(r.get("ランク系特殊能力", "")):
            gen_rows.append({"データ": "生成", "カテゴリ": r.get("category", "生成"), "対象": r.get("role", "不明"), "選手キー": key, "選手名": r.get("name", ""), "特殊能力": name, "特殊能力カテゴリ": "ランク系", "対象役割": role_map.get(name, "不明"), "ランク系統": ranked_special_base(name)})
    return pd.DataFrame(real_rows + gen_rows), load_special_master()


def ranked_special_base(name: Any) -> str:
    text = str(name or "").strip()
    return re.sub(r"[A-GＡ-ＧＳ]$", "", text)


def special_scope_metrics(events: pd.DataFrame, players: pd.DataFrame, data_label: str, category: str, role: str | None, group_cols: list[str]) -> pd.DataFrame:
    base = players.copy()
    if data_label == "実在12球団":
        base = base[base.get("category", pd.Series(index=base.index, dtype=str)).eq("実在12球団")]
    elif category != "全体":
        base = base[base.get("category", pd.Series(index=base.index, dtype=str)).eq(category)]
    if role:
        base = base[base.get("role", pd.Series(index=base.index, dtype=str)).eq(role)]
    ev = events[events["データ"].eq(data_label if data_label == "実在12球団" else "生成")].copy()
    if data_label != "実在12球団" and category != "全体":
        ev = ev[ev["カテゴリ"].eq(category)]
    if role:
        ev = ev[ev["対象"].eq(role)]
    total = len(base)
    rows=[]
    if ev.empty:
        return pd.DataFrame()
    for keys, sub in ev.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple): keys=(keys,)
        holders = sub["選手キー"].nunique()
        rows.append({"データ": data_label if data_label == "実在12球団" else category, "対象": role or "全体", "対象選手数": total, **dict(zip(group_cols, keys)), "総出現数": len(sub), "1人あたり平均個数": round(len(sub)/max(1,total),3), "100人あたり出現数": round(len(sub)/max(1,total)*100,2), "1件以上保有する選手数": holders, "1件以上保有率%": round(holders/max(1,total)*100,2)})
    return pd.DataFrame(rows)


def special_review_tables(real: pd.DataFrame, real_specials: pd.DataFrame, gen: pd.DataFrame) -> dict[str, pd.DataFrame]:
    events, master = build_special_events(real, real_specials, gen)
    players = pd.concat([real.assign(category="実在12球団"), gen], ignore_index=True, sort=False)
    tables={}
    scopes=[("実在12球団","実在12球団",None),("実在12球団","実在12球団","投手"),("実在12球団","実在12球団","野手")]
    for cat in ["全体", *_available_categories(gen)]:
        scopes.append(("生成",cat,None))
        for role in ["投手","野手"]: scopes.append(("生成",cat,role))
    kind_frames=[special_scope_metrics(events, players, d,c,r,["特殊能力カテゴリ"]) for d,c,r in scopes]
    name_frames=[special_scope_metrics(events[events["特殊能力カテゴリ"].ne("ランク系")], players, d,c,r,["特殊能力","特殊能力カテゴリ","対象役割"]) for d,c,r in scopes]
    tables["special_kind_metrics_compare"] = pd.concat([x for x in kind_frames if not x.empty], ignore_index=True, sort=False).rename(columns={"特殊能力カテゴリ":"カテゴリ"})
    nm = pd.concat([x for x in name_frames if not x.empty], ignore_index=True, sort=False)
    # 名称別は、全体CSVとしても実在/生成の差分列を持たせます。
    compare_rows = []
    if not nm.empty:
        real_nm = nm[(nm["データ"].eq("実在12球団")) & (nm["対象"].isin(["全体", "投手", "野手"]))]
        for _, g in nm[~nm["データ"].eq("実在12球団")].iterrows():
            rmatch = real_nm[(real_nm["対象"].eq(g["対象"])) & (real_nm["特殊能力"].eq(g["特殊能力"]))]
            r = rmatch.iloc[0] if not rmatch.empty else pd.Series(dtype=object)
            compare_rows.append({"データ": g["データ"], "対象": g["対象"], "特殊能力": g["特殊能力"], "カテゴリ": g.get("特殊能力カテゴリ"), "対象役割": g.get("対象役割"), "実在出現数": int(r.get("総出現数", 0) or 0), "生成出現数": int(g.get("総出現数", 0) or 0), "実在保有率%": float(r.get("1件以上保有率%", 0) or 0), "生成保有率%": float(g.get("1件以上保有率%", 0) or 0), "保有率差分": round(float(g.get("1件以上保有率%", 0) or 0) - float(r.get("1件以上保有率%", 0) or 0), 2), "実在100人あたり出現数": float(r.get("100人あたり出現数", 0) or 0), "生成100人あたり出現数": float(g.get("100人あたり出現数", 0) or 0)})
    tables["special_name_metrics_compare"] = pd.DataFrame(compare_rows) if compare_rows else nm
    # count distribution normal specials only
    rows=[]
    for d,c,r in scopes:
        base = players if d=="生成" else players[players["category"].eq("実在12球団")]
        if d=="生成" and c!="全体": base=base[base["category"].eq(c)]
        if r: base=base[base["role"].eq(r)]
        ev=events[(events["データ"].eq(d if d=="実在12球団" else "生成")) & (events["特殊能力カテゴリ"].ne("ランク系"))]
        if d=="生成" and c!="全体": ev=ev[ev["カテゴリ"].eq(c)]
        if r: ev=ev[ev["対象"].eq(r)]
        counts=ev.groupby("選手キー").size().to_dict()
        real_key_cols = [col for col in ["source", "team", "name"] if col in base.columns]
        vals=[counts.get(str(row.get("seed", i)) if d=="生成" else "|".join(str(row.get(x,"")) for x in real_key_cols),0) for i,row in base.iterrows()]
        for b in ["0個","1個","2個","3個","4個","5個以上"]:
            if b=="5個以上": n=sum(v>=5 for v in vals)
            else: n=sum(v==int(b[0]) for v in vals)
            rows.append({"データ": d if d=="実在12球団" else c,"対象":r or "全体","特殊能力数":b,"人数":n,"対象選手数":len(vals),"割合%":round(n/max(1,len(vals))*100,2)})
    tables["special_count_distribution_compare"]=pd.DataFrame(rows)
    # ranked A-G distribution, D included only when explicit/generated existing; memo notes no blind fill.
    rank_ev=events[events["特殊能力カテゴリ"].eq("ランク系")].copy(); rank_ev["ランク"]=rank_ev["特殊能力"].astype(str).str[-1]
    rank_rows=[]
    for d,c,r in scopes:
        ev=rank_ev[rank_ev["データ"].eq(d if d=="実在12球団" else "生成")]
        if d=="生成" and c!="全体": ev=ev[ev["カテゴリ"].eq(c)]
        if r: ev=ev[ev["対象"].eq(r)]
        for fam, fdf in ev.groupby("ランク系統", dropna=False):
            total=max(1, fdf["選手キー"].nunique())
            real_rates={}
            for rank,cnt in fdf["ランク"].value_counts().items():
                rate=round(cnt/total*100,2); real_rates[rank]=rate
                rank_rows.append({"データ":d if d=="実在12球団" else c,"カテゴリ":c,"対象":r or "全体","ランク系統":fam,"ランク":rank,"人数":int(cnt),"割合%":rate,"実在との差分":None})
    tables["ranked_ability_family_distribution_compare"]=pd.DataFrame(rank_rows)
    # consistency/conflicts simplified diagnostics
    tables["special_ability_consistency_warnings"] = consistency_warnings(gen, events)
    tables["special_ability_consistency_summary"] = tables["special_ability_consistency_warnings"].groupby(["対象","チェック"], dropna=False).agg(人数=("seed","nunique"), 代表seed=("seed","first")).reset_index() if not tables["special_ability_consistency_warnings"].empty else pd.DataFrame(columns=["対象","チェック","人数","代表seed"])
    tables["special_ability_conflicts"] = conflict_warnings(gen, events, master)
    tables["special_ability_conflict_summary"] = tables["special_ability_conflicts"].groupby("衝突タイプ", dropna=False).agg(件数=("seed","count"), 代表seed=("seed","first")).reset_index() if not tables["special_ability_conflicts"].empty else pd.DataFrame(columns=["衝突タイプ","件数","代表seed"])
    tables["generated_special_context_metrics"] = generated_context_metrics(gen, events)
    return tables


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


def _nonblank(value: Any) -> bool:
    return not pd.isna(value) and str(value).strip() != ""


def _first_nonblank(row: pd.Series, columns: list[str], default: str = "比較不能") -> Any:
    for col in columns:
        if col in row and _nonblank(row[col]):
            return row[col]
    return default


def _warning_display_name(row: pd.Series) -> str:
    warning_type = _first_nonblank(row, ["警告タイプ"], default="")
    if warning_type:
        return str(warning_type)
    warning = _first_nonblank(row, ["警告"], default="")
    # 「警告」のような汎用ラベルだけでは内容を識別できないため、次候補を使います。
    if warning and str(warning).strip() not in {"警告", "warning"}:
        return str(warning)
    position, ability = row.get("ポジション"), row.get("能力")
    if _nonblank(position) and _nonblank(ability):
        return f"{position} {ability}"
    if warning:
        return str(warning)
    return str(_first_nonblank(row, ["source_file"], default="比較不能"))


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
    if not high.empty:
        high["警告表示名"] = high.apply(_warning_display_name, axis=1)
        if "警告タイプ" not in high:
            high["警告タイプ"] = high["警告表示名"]
        else:
            high["警告タイプ"] = high.apply(lambda r: r["警告タイプ"] if _nonblank(r.get("警告タイプ")) else r["警告表示名"], axis=1)
    return summary, high


def sub_position_compare(real_optional: dict[str, pd.DataFrame], gen_optional: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    mapping = [("実在12球団", real_optional.get("fielder_sub_position_summary", pd.DataFrame())), ("生成", gen_optional.get("sub_position_summary", pd.DataFrame()))]
    for label, df in mapping:
        if df.empty:
            continue
        for _, r in df.iterrows():
            axis = _first_nonblank(r, ["集計軸", "metric"], default="")
            value = _first_nonblank(r, ["値", "value", "item"], default="")
            rows.append({"データ": label, "集計軸": axis, "値": value, "人数": _first_nonblank(r, ["人数", "count"], default=None), "割合%": _first_nonblank(r, ["割合%", "rate%", "ratio_percent"], default="比較不能")})
    return pd.DataFrame(rows)


def _normalize_aptitude_pattern(text: Any) -> str:
    value = str(text or "").strip()
    if value in {"先", "中", "先中", "中抑", "先中抑"}:
        return value
    marks = {"先発": "-", "中継ぎ": "-", "抑え": "-"}
    for role, mark in re.findall(r"(先発|中継ぎ|抑え)\s*([◎○-])", value):
        marks[role] = mark
    parts = []
    if marks["先発"] in {"◎", "○"}:
        parts.append("先")
    if marks["中継ぎ"] in {"◎", "○"}:
        parts.append("中")
    if marks["抑え"] in {"◎", "○"}:
        parts.append("抑")
    return "".join(parts) or "比較不能"


def pitcher_aptitude_compare(real_optional: dict[str, pd.DataFrame], gen_optional: dict[str, pd.DataFrame], gen: pd.DataFrame | None = None) -> pd.DataFrame:
    rows = []
    real_df = real_optional.get("pitcher_role_summary", real_optional.get("pitcher_role_ability_average", pd.DataFrame()))
    if not real_df.empty:
        total = pd.to_numeric(real_df.get("人数", real_df.get("count")), errors="coerce").sum()
        for _, r in real_df.iterrows():
            count = _first_nonblank(r, ["人数", "count"], default=None)
            rate = _first_nonblank(r, ["割合%", "rate%", "ratio_percent"], default=None)
            if (rate is None or pd.isna(rate)) and total:
                rate = round(float(count) / total * 100, 2)
            pattern = _first_nonblank(r, ["値", "pitcher_roles", "role", "集計軸"], default="比較不能")
            rows.append({"データ": "実在12球団", "カテゴリ": "実在12球団", "集計軸": "適正パターン別", "比較用適正パターン": pattern, "詳細適正パターン": pattern, "人数": count, "割合%": rate if rate is not None else "比較不能", "平均球速": _first_nonblank(r, ["平均球速", "top_speed"], default="")})
    gen_pitchers = pd.DataFrame() if gen is None else gen[gen.get("role", pd.Series(dtype=str)).eq("投手")].copy()
    if not gen_pitchers.empty and {"category", "starter_aptitude", "reliever_aptitude", "closer_aptitude"}.issubset(gen_pitchers.columns):
        gen_pitchers["詳細適正パターン"] = gen_pitchers.apply(lambda r: f"先発{r.get('starter_aptitude', '-')} / 中継ぎ{r.get('reliever_aptitude', '-')} / 抑え{r.get('closer_aptitude', '-')}", axis=1)
        for category, cdf in gen_pitchers.groupby("category", dropna=False):
            total = len(cdf)
            grouped = cdf.groupby("詳細適正パターン", dropna=False)
            for detail, pdf in grouped:
                rows.append({"データ": "生成", "カテゴリ": category, "集計軸": "適正パターン別", "比較用適正パターン": _normalize_aptitude_pattern(detail), "詳細適正パターン": detail, "人数": len(pdf), "割合%": round(len(pdf) / max(1, total) * 100, 2), "平均球速": round(pd.to_numeric(pdf.get("球速", pd.Series(dtype=float)), errors="coerce").mean(), 3)})
    else:
        gen_df = gen_optional.get("pitcher_aptitude_summary", pd.DataFrame())
        if not gen_df.empty:
            work = gen_df.copy()
            work["カテゴリ"] = work["カテゴリ"] if "カテゴリ" in work else "生成（カテゴリ不明）"
            for category, cdf in work.groupby("カテゴリ", dropna=False):
                pattern_rows = cdf[cdf.get("集計軸", pd.Series(index=cdf.index, dtype=str)).astype(str).eq("適正パターン別")]
                total = pd.to_numeric(pattern_rows.get("人数", pattern_rows.get("count")), errors="coerce").sum()
                for _, r in pattern_rows.iterrows():
                    count = _first_nonblank(r, ["人数", "count"], default=None)
                    rate = _first_nonblank(r, ["割合%", "rate%"], default=None)
                    if (rate is None or pd.isna(rate)) and total:
                        rate = round(float(count) / total * 100, 2)
                    detail = _first_nonblank(r, ["値", "pitcher_roles", "詳細適正パターン"], default="比較不能")
                    rows.append({"データ": "生成", "カテゴリ": category, "集計軸": "適正パターン別", "比較用適正パターン": _normalize_aptitude_pattern(detail), "詳細適正パターン": detail, "人数": count, "割合%": rate if rate is not None else "比較不能", "平均球速": _first_nonblank(r, ["平均球速", "top_speed"], default="")})
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
            rows.append({"データ": data_label, "集計軸": _first_nonblank(r, ["集計軸", "metric"], default=""), "値": _first_nonblank(r, ["値", "value", "item"], default=""), "人数": _first_nonblank(r, ["人数", "count"], default=None), "割合%": _first_nonblank(r, ["割合%", "rate%", "ratio_percent"], default="比較不能")})
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
            lines.append("- " + " / ".join(f"{r['ポジション']} {r['指標']}: {r['割合%']}%" for _, r in sub.iterrows()))
    lines.extend(["", "## severity 別 warning 件数", ""])
    sev = tables.get("generated_warning_severity_summary", pd.DataFrame())
    lines.extend([f"- {r['severity']}: {r['件数']}件" for _, r in sev.iterrows()] or ["- severity付き生成警告なし"])
    high = tables.get("generated_high_warnings", pd.DataFrame())
    if not high.empty:
        type_col = "警告表示名" if "警告表示名" in high else "警告タイプ"
        lines.append("- high警告タイプ: " + ", ".join(sorted(set(high.get(type_col, high.get("警告", pd.Series(dtype=str))).dropna().astype(str)))))
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



def _num(row: pd.Series, col: str, default: float = 0) -> float:
    return float(pd.to_numeric(pd.Series([row.get(col, default)]), errors="coerce").fillna(default).iloc[0])


def consistency_warnings(gen: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    by_seed=events[events["データ"].eq("生成")].groupby("選手キー")["特殊能力"].apply(set).to_dict()
    checks=[("野手","三振と低ミート",lambda r,s: "三振" in s and _num(r,"ミート",99)>=55), ("野手","エラーと低守備力・低捕球",lambda r,s:"エラー" in s and min(_num(r,"守備力",99),_num(r,"捕球",99))>=50), ("野手","併殺と低走力",lambda r,s:"併殺" in s and _num(r,"走力",99)>=55), ("野手","パワーヒッター系とパワー",lambda r,s: bool({"パワーヒッター","アーチスト"}&s) and _num(r,"パワー",0)<65), ("野手","アベレージヒッター系とミート",lambda r,s: bool({"アベレージヒッター","安打製造機"}&s) and _num(r,"ミート",0)<65), ("野手","盗塁・走塁系と走力",lambda r,s: bool({"盗塁A","盗塁B","走塁A","走塁B","電光石火"}&s) and _num(r,"走力",0)<60), ("野手","守備系特殊能力と守備力・捕球・肩力",lambda r,s: bool({"守備職人","魔術師","レーザービーム","高速レーザー"}&s) and max(_num(r,"守備力"),_num(r,"捕球"),_num(r,"肩力"))<60), ("野手","捕手系特殊能力と捕手ポジション",lambda r,s: any("キャッチャー" in x or x=="球界の頭脳" for x in s) and r.get("position")!="捕手"), ("投手","四球・抜け球・乱調と低コントロール",lambda r,s: bool({"四球","抜け球","乱調"}&s) and _num(r,"コントロール",99)>=50), ("投手","一発・軽い球と球速・総変化量",lambda r,s: bool({"一発","軽い球"}&s) and (_num(r,"球速",0)>=150 or _num(r,"総変化量",0)>=9)), ("投手","ノビ系と球速",lambda r,s: any(str(x).startswith("ノビ") for x in s) and _num(r,"球速",0)<140), ("投手","キレ系と変化球",lambda r,s: any("キレ" in str(x) for x in s) and _num(r,"総変化量",0)<5), ("投手","奪三振系と球速・総変化量",lambda r,s: bool({"奪三振","ドクターK"}&s) and _num(r,"球速",0)<145 and _num(r,"総変化量",0)<7), ("投手","先発用特殊能力と先発適正",lambda r,s: bool({"完投","完封","尻上がり"}&s) and r.get("starter_aptitude") not in {"◎","○"}), ("投手","中継ぎ・抑え用特殊能力と適正",lambda r,s: bool({"中継ぎエース","守護神","セーブ狙い"}&s) and r.get("reliever_aptitude") not in {"◎","○"} and r.get("closer_aptitude") not in {"◎","○"})]
    for idx,r in gen.iterrows():
        seed=str(r.get("seed",idx)); specs=by_seed.get(seed,set())
        for role,label,fn in checks:
            if r.get("role")==role and fn(r,specs): rows.append({"seed":seed,"対象":role,"チェック":label,"特殊能力":"、".join(sorted(specs)),"カテゴリ":r.get("category"),"player_type":r.get("player_type")})
    return pd.DataFrame(rows)


def conflict_warnings(gen: pd.DataFrame, events: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    rows=[]; role_map=dict(zip(master["name"].astype(str), master["対象役割"].astype(str))) if not master.empty else {}
    pairs=[("積極打法","慎重打法"),("強振多用","ミート多用"),("速球中心","変化球中心"),("投球位置左","投球位置右"),("チームプレイ○","チームプレイ×"),("パワーヒッター","アーチスト"),("アベレージヒッター","安打製造機")]
    by_seed=events[events["データ"].eq("生成")].groupby("選手キー")["特殊能力"].apply(list).to_dict()
    for idx,r in gen.iterrows():
        seed=str(r.get("seed",idx)); vals=by_seed.get(seed,[]); specs=set(vals)
        for name in set(vals):
            if vals.count(name)>1: rows.append({"seed":seed,"衝突タイプ":"同一特殊能力の重複","詳細":name})
        for a,b in pairs:
            if a in specs and b in specs: rows.append({"seed":seed,"衝突タイプ":"相反特殊能力の同時所持","詳細":f"{a} / {b}"})
        fams={}
        for name in specs:
            if normalize_special_category('',name)=="ランク系": fams.setdefault(ranked_special_base(name),set()).add(name[-1])
            target=role_map.get(name)
            if target in {"投手","野手"} and target != r.get("role"): rows.append({"seed":seed,"衝突タイプ":"専用能力の対象外所持","詳細":name})
        for fam,ranks in fams.items():
            if len(ranks)>1: rows.append({"seed":seed,"衝突タイプ":"同じランク系統を複数ランクで所持","詳細":f"{fam}:{','.join(sorted(ranks))}"})
        usage=[x for x in specs if x in USAGE_SPECIAL_NAMES]
        if len(usage)>=3: rows.append({"seed":seed,"衝突タイプ":"usage能力の不自然な複数所持","詳細":"、".join(sorted(usage))})
    return pd.DataFrame(rows)


def generated_context_metrics(gen: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    ev=events[(events["データ"].eq("生成")) & (events["特殊能力カテゴリ"].ne("ランク系"))]
    counts=ev.groupby("選手キー").size().to_dict(); rows=[]
    work=gen.copy(); work["特殊能力数"]=[counts.get(str(r.get("seed",i)),0) for i,r in work.iterrows()]
    nums=[c for c in ["ミート","パワー","走力","肩力","守備力","捕球","球速","コントロール","スタミナ","総変化量","age"] if c in work.columns]
    work["総合スコア"] = work[nums].apply(pd.to_numeric, errors="coerce").mean(axis=1) if nums else 0
    work["総合スコア帯"] = pd.cut(work["総合スコア"], bins=[-1,45,55,65,999], labels=["45未満","45-55","55-65","65以上"])
    if "age" in work: work["年齢帯"] = pd.cut(pd.to_numeric(work["age"],errors="coerce"), bins=[0,22,26,32,99], labels=["22歳以下","23-26歳","27-32歳","33歳以上"])
    for col,label in [("player_type","player_type"),("総合スコア帯","総合スコア帯"),("年齢帯","年齢帯"),("position","ポジション"),("category","カテゴリ")]:
        if col in work:
            for val,sub in work.groupby(col, dropna=False): rows.append({"集計軸":label,"値":val,"人数":len(sub),"平均特殊能力数":round(sub["特殊能力数"].mean(),3)})
    if {"starter_aptitude","reliever_aptitude","closer_aptitude"}.issubset(work.columns):
        work["投手起用"] = assign_pitcher_usage(work, [], prefer_aptitudes=True)
        for val,sub in work[work["role"].eq("投手")].groupby("投手起用", dropna=False): rows.append({"集計軸":"投手起用","値":val,"人数":len(sub),"平均特殊能力数":round(sub["特殊能力数"].mean(),3)})
    return pd.DataFrame(rows)


def write_special_review_memo(tables: dict[str, pd.DataFrame], output_dir: Path) -> None:
    kind=tables.get("special_kind_metrics_compare",pd.DataFrame()); conf=tables.get("special_ability_conflict_summary",pd.DataFrame()); cons=tables.get("special_ability_consistency_summary",pd.DataFrame())
    gold=kind[kind.get("カテゴリ",pd.Series(dtype=str)).eq("金特")] if not kind.empty else pd.DataFrame()
    lines=["# 特殊能力 最終比較レビュー", "", "## 現在の比較指標にあった問題", "- 旧 `出現率%` は特殊能力の総出現数を選手数で割った値で、複数所持を合算するため100%を超える指標でした。保有率ではありません。", "", "## 修正した集計定義", "- `総出現数`、`対象選手数`、`1人あたり平均個数`、`100人あたり出現数`、`1件以上保有する選手数`、`1件以上保有率%`、個数分布（0/1/2/3/4/5個以上）を分離しました。", "- 投手・野手・投手×カテゴリ・野手×カテゴリを分け、専用能力を全選手分母だけで判定しない形式にしました。", "", "## 通常青特の比較 / 赤特の比較 / 緑特の比較 / 金特0件の原因", f"- カテゴリ別詳細は `special_kind_metrics_compare.csv` と `special_name_metrics_compare.csv` を参照してください。金特行数={len(gold)}、生成金特総出現数={int(pd.to_numeric(gold.get('総出現数',pd.Series(dtype=int)),errors='coerce').fillna(0).sum()) if not gold.empty else 0}。", "- master (`data/special_abilities.csv`) に `kind=gold` が存在しない場合、現仕様では通常生成候補に金特分類がありません。今回の確認では確率変更はしていません。", "", "## ランク系A〜G分布", "- `ranked_ability_family_distribution_compare.csv` に系統・ランク別分布を出力しました。D補完は実在データに未記録=Dと断定できる仕様情報がCSVだけでは不足するため、推測補完していません。", "", "## 特殊能力数分布", "- `special_count_distribution_compare.csv` に0個〜5個以上の人数・割合を出力しました。", "", "## 投手・野手別の差 / カテゴリ別の差", "- 全体、投手、野手、投手×カテゴリ、野手×カテゴリの各スコープで比較CSVを出力しました。", "", "## 能力整合性警告", f"- 警告サマリー件数: {len(cons)}。詳細は `special_ability_consistency_warnings.csv`。", "", "## 衝突・重複", f"- 衝突タイプ件数: {len(conf)}。詳細は `special_ability_conflicts.csv`。", "", "## 修正が必要な特殊能力", "- レビューCSVで実在保有率との差分が大きい能力、整合性警告、衝突検出に出る能力を優先候補とします。", "", "## 現状維持でよい特殊能力", "- 差分が小さく、整合性警告・衝突にほぼ出ない能力は現状維持候補です。", "", "## 生成ロジックを修正すべきか", "- 本ステップはレビューのみです。金特有無、D補完仕様、カテゴリ別過多/過少を確認後に確率変更を判断してください。"]
    (output_dir/"special_ability_review_memo.md").write_text("\n".join(lines)+"\n",encoding="utf-8")



# --- Special ability review v2: usage/gold excluded, rank separated ---
COMPARE_ALIAS_MAP = {
    "投手調子安定": "調子安定", "野手調子安定": "調子安定",
    "投手調子極端": "調子極端", "野手調子極端": "調子極端",
}
RANK_COLUMNS = ["rank", "value", "grade", "ability_rank"]
NORMAL_REVIEW_CATEGORIES = ["青特", "赤特", "緑特"]


def normalize_rank_char(value: Any) -> str:
    text = str(value or "").strip().translate(str.maketrans("ＡＢＣＤＥＦＧ", "ABCDEFG"))
    return text if text in set("ABCDEFG") else ""


def normalize_compare_special_name(name: Any) -> tuple[str, bool]:
    raw = str(name or "").strip().translate(str.maketrans("ＡＢＣＤＥＦＧ", "ABCDEFG"))
    normalized = COMPARE_ALIAS_MAP.get(raw, raw)
    return normalized, normalized != raw


def explicit_rank_from_row(row: pd.Series) -> str:
    for col in RANK_COLUMNS:
        if col in row and _nonblank(row.get(col)):
            rank_value = normalize_rank_char(row.get(col))
            if rank_value:
                return rank_value
    return ""


@lru_cache(maxsize=1)
def master_category_maps() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    master = load_special_master()
    category = dict(zip(master["name"].astype(str), master["カテゴリ"].astype(str))) if not master.empty else {}
    role = dict(zip(master["name"].astype(str), master["対象役割"].astype(str))) if not master.empty else {}
    group = dict(zip(master["name"].astype(str), master["group"].astype(str))) if not master.empty else {}
    return category, role, group


def classify_special_event(name: str, special_kind: Any = "", rank_value: str = "", source_is_rank_column: bool = False) -> dict[str, str]:
    normalized_name, alias_applied = normalize_compare_special_name(name)
    kind_text = "" if pd.isna(special_kind) else str(special_kind).strip()
    master_category, role_map, group_map = master_category_maps()
    explicit_kind = kind_text.lower()
    rank = normalize_rank_char(rank_value)
    if explicit_kind in {"usage", "player_usage"} or normalized_name in USAGE_SPECIAL_NAMES:
        return {"除外": "1", "除外理由": "usage", "生データ名称": str(name), "正規化名称": normalized_name, "alias適用有無": "あり" if alias_applied else "なし"}
    is_rank = explicit_kind in {"rank", "ランク系"} or bool(rank) or re.search(r"[A-G]$", normalized_name)
    if is_rank:
        if not rank:
            rank = normalize_rank_char(str(normalized_name)[-1:])
        family = ranked_special_base(normalized_name) if rank else normalized_name
        normalized = f"{family}{rank}" if rank and not str(normalized_name).endswith(rank) else normalized_name
        return {"除外": "0", "イベント種別": "ランク系", "特殊能力カテゴリ": "ランク系", "ランク系統": family, "ランク": rank, "生データ名称": str(name), "正規化名称": normalized, "対象役割": role_map.get(normalized, role_map.get(family, "不明")), "alias適用有無": "あり" if alias_applied or normalized != str(name).strip() else "なし"}
    if explicit_kind in {"green", "緑特"}:
        category = "緑特"
    elif explicit_kind in {"gold", "金特"}:
        category = "金特"
    elif explicit_kind in {"red", "赤特"}:
        category = "赤特"
    else:
        category = master_category.get(normalized_name, normalize_special_category(kind_text, normalized_name))
        if category == "usage":
            return {"除外": "1", "除外理由": "usage", "生データ名称": str(name), "正規化名称": normalized_name, "alias適用有無": "あり" if alias_applied else "なし"}
        if category == "ランク系":
            rank = normalize_rank_char(str(normalized_name)[-1:])
            family = ranked_special_base(normalized_name)
            return {"除外": "0", "イベント種別": "ランク系", "特殊能力カテゴリ": "ランク系", "ランク系統": family, "ランク": rank, "生データ名称": str(name), "正規化名称": normalized_name, "対象役割": role_map.get(normalized_name, "不明"), "alias適用有無": "あり" if alias_applied else "なし"}
    event_kind = "緑特" if category == "緑特" else "金特" if category == "金特" else "通常"
    return {"除外": "0", "イベント種別": event_kind, "特殊能力カテゴリ": category, "ランク系統": "", "ランク": "", "生データ名称": str(name), "正規化名称": normalized_name, "対象役割": role_map.get(normalized_name, "不明"), "alias適用有無": "あり" if alias_applied else "なし"}


def build_special_events(real_players: pd.DataFrame, real_specials: pd.DataFrame, gen: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    master = load_special_master()
    real = real_specials.copy()
    if not real.empty and {"source", "team", "name"}.issubset(real.columns):
        cols = ["source", "team", "name"] + [c for c in ["role", "category", "position", "sub_positions"] if c in real_players.columns]
        real = real.merge(real_players[cols].drop_duplicates(), on=["source", "team", "name"], how="left")
    for _, r in real.iterrows():
        raw = str(r.get("special", "")).strip()
        if not raw:
            continue
        rank_value = explicit_rank_from_row(r)
        info = classify_special_event(raw, r.get("special_kind", ""), rank_value)
        if info.get("除外") == "1":
            continue
        rows.append({"データ": "実在12球団", "カテゴリ": "実在12球団", "対象": r.get("role", "不明"), "選手キー": "|".join(str(r.get(c, "")) for c in ["source", "team", "name"]), "選手名": r.get("name", ""), "source_column": "special_abilities", **info})
    for idx, r in gen.iterrows():
        key = str(r.get("seed", idx))
        base = {"データ": "生成", "カテゴリ": r.get("category", "生成"), "対象": r.get("role", "不明"), "選手キー": key, "選手名": r.get("name", ""), "seed": key, "player_type": r.get("player_type", ""), "position": r.get("position", ""), "sub_positions": r.get("サブポジ一覧", "")}
        for raw in _split_specials(r.get("特殊能力", "")):
            info = classify_special_event(raw, "")
            if info.get("除外") == "1":
                continue
            rows.append({**base, "source_column": "特殊能力", **info})
        for raw in _split_specials(r.get("ランク系特殊能力", "")):
            info = classify_special_event(raw, "rank")
            if info.get("除外") == "1":
                continue
            rows.append({**base, "source_column": "ランク系特殊能力", **info})
    return pd.DataFrame(rows), master



def generated_seed_key(value: Any, fallback: Any) -> str:
    if pd.isna(value):
        return str(fallback)
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value)


def _available_generated_scopes(gen: pd.DataFrame) -> list[tuple[str, str | None]]:
    scopes = [("架空球団用", None), ("架空球団用", "投手"), ("架空球団用", "野手")]
    for category in [c for c in CATEGORY_PRIORITY if c in set(gen.get("category", []))]:
        if category == "架空球団用":
            continue
        scopes.extend([(category, None), (category, "投手"), (category, "野手")])
    return scopes


def _player_subset(players: pd.DataFrame, data: str, category: str, role: str | None) -> pd.DataFrame:
    if data == "実在12球団":
        base = players[players["category"].eq("実在12球団")].copy()
    else:
        base = players[players["category"].eq(category)].copy()
    return base[base["role"].eq(role)] if role else base


def _event_subset(events: pd.DataFrame, data: str, category: str, role: str | None) -> pd.DataFrame:
    ev = events[events["データ"].eq("実在12球団" if data == "実在12球団" else "生成")].copy()
    if data != "実在12球団":
        ev = ev[ev["カテゴリ"].eq(category)]
    return ev[ev["対象"].eq(role)] if role else ev


def _metrics_from_counts(counts: list[int], total_occurrences: int, holders: int, total_players: int) -> dict[str, Any]:
    return {"総出現数": total_occurrences, "対象選手数": total_players, "1人あたり平均個数": round(total_occurrences / max(1, total_players), 3), "100人あたり出現数": round(total_occurrences / max(1, total_players) * 100, 2), "1件以上保有者数": holders, "1件以上保有率%": round(holders / max(1, total_players) * 100, 2), "0個率%": round(sum(c == 0 for c in counts) / max(1, total_players) * 100, 2), "1個率%": round(sum(c == 1 for c in counts) / max(1, total_players) * 100, 2), "2個率%": round(sum(c == 2 for c in counts) / max(1, total_players) * 100, 2), "3個率%": round(sum(c == 3 for c in counts) / max(1, total_players) * 100, 2), "4個率%": round(sum(c == 4 for c in counts) / max(1, total_players) * 100, 2), "5個以上率%": round(sum(c >= 5 for c in counts) / max(1, total_players) * 100, 2)}


def special_review_tables(real: pd.DataFrame, real_specials: pd.DataFrame, gen: pd.DataFrame) -> dict[str, pd.DataFrame]:
    events, master = build_special_events(real, real_specials, gen)
    players = pd.concat([real.assign(category="実在12球団"), gen], ignore_index=True, sort=False)
    scopes = [("実在12球団", "実在12球団", None), ("実在12球団", "実在12球団", "投手"), ("実在12球団", "実在12球団", "野手")]
    scopes += [("生成", c, r) for c, r in _available_generated_scopes(gen)]
    tables: dict[str, pd.DataFrame] = {}
    kind_rows = []
    name_rows = []
    count_rows = []
    normal_events = events[events["特殊能力カテゴリ"].isin(NORMAL_REVIEW_CATEGORIES)].copy()
    for data_label, category, role in scopes:
        base = _player_subset(players, data_label, category, role)
        ev_scope = _event_subset(normal_events, data_label, category, role)
        player_keys = [generated_seed_key(r.get("seed", i), i) if data_label == "生成" else "|".join(str(r.get(c, "")) for c in ["source", "team", "name"]) for i, r in base.iterrows()]
        total_counts_by_player = ev_scope.groupby("選手キー").size().to_dict()
        total_counts = [int(total_counts_by_player.get(key, 0)) for key in player_keys]
        count_metrics = _metrics_from_counts(total_counts, int(len(ev_scope)), int(ev_scope["選手キー"].nunique()), len(base))
        for bucket, rate_key in [("0個", "0個率%"), ("1個", "1個率%"), ("2個", "2個率%"), ("3個", "3個率%"), ("4個", "4個率%"), ("5個以上", "5個以上率%")]:
            if bucket == "5個以上":
                n = sum(c >= 5 for c in total_counts)
            else:
                n = sum(c == int(bucket[0]) for c in total_counts)
            count_rows.append({"データ": data_label if data_label == "実在12球団" else category, "対象": role or "全体", "特殊能力数": bucket, "人数": n, "対象選手数": len(base), "割合%": count_metrics[rate_key]})
        for special_category in NORMAL_REVIEW_CATEGORIES:
            ev_cat = ev_scope[ev_scope["特殊能力カテゴリ"].eq(special_category)]
            counts_by_player = ev_cat.groupby("選手キー").size().to_dict()
            counts = [int(counts_by_player.get(key, 0)) for key in player_keys]
            kind_rows.append({"データ": data_label if data_label == "実在12球団" else category, "対象": role or "全体", "カテゴリ": special_category, **_metrics_from_counts(counts, int(len(ev_cat)), int(ev_cat["選手キー"].nunique()), len(base))})
        for (special_name, special_category, target_role), sub in ev_scope.groupby(["正規化名称", "特殊能力カテゴリ", "対象役割"], dropna=False):
            name_rows.append({"データ": data_label if data_label == "実在12球団" else category, "対象": role or "全体", "特殊能力": special_name, "カテゴリ": special_category, "対象役割": target_role, "出現数": len(sub), "保有者数": sub["選手キー"].nunique(), "対象選手数": len(base), "保有率%": round(sub["選手キー"].nunique() / max(1, len(base)) * 100, 2), "100人あたり出現数": round(len(sub) / max(1, len(base)) * 100, 2), "生データ名称": "、".join(sorted(set(sub["生データ名称"].astype(str)))[:5]), "alias適用有無": "あり" if (sub["alias適用有無"].eq("あり")).any() else "なし"})
    name_long = pd.DataFrame(name_rows)
    compare_rows = []
    if not name_long.empty:
        real_lookup = name_long[name_long["データ"].eq("実在12球団")]
        generated = name_long[~name_long["データ"].eq("実在12球団")]
        for _, g in generated.iterrows():
            rmatch = real_lookup[(real_lookup["対象"].eq(g["対象"])) & (real_lookup["特殊能力"].eq(g["特殊能力"]))]
            r = rmatch.iloc[0] if not rmatch.empty else pd.Series(dtype=object)
            compare_rows.append({"データ": g["データ"], "対象": g["対象"], "特殊能力": g["特殊能力"], "カテゴリ": g["カテゴリ"], "対象役割": g.get("対象役割"), "実在出現数": int(r.get("出現数", 0) or 0), "生成出現数": int(g.get("出現数", 0) or 0), "実在保有率%": float(r.get("保有率%", 0) or 0), "生成保有率%": float(g.get("保有率%", 0) or 0), "保有率差分": round(float(g.get("保有率%", 0) or 0) - float(r.get("保有率%", 0) or 0), 2), "実在100人あたり出現数": float(r.get("100人あたり出現数", 0) or 0), "生成100人あたり出現数": float(g.get("100人あたり出現数", 0) or 0), "生データ名称": g.get("生データ名称", ""), "正規化名称": g["特殊能力"], "alias適用有無": g.get("alias適用有無", "なし")})
    tables["special_kind_metrics_compare"] = pd.DataFrame(kind_rows)
    tables["special_name_metrics_compare"] = pd.DataFrame(compare_rows)
    tables["special_count_distribution_compare"] = pd.DataFrame(count_rows)
    tables["ranked_ability_family_distribution_compare"] = ranked_family_distribution(events, players, master)
    audit, audit_summary = special_event_classification_audit(events, real_specials, gen)
    tables["special_event_classification_audit"] = audit
    tables["special_event_classification_summary"] = audit_summary
    tables["special_ability_consistency_warnings"] = consistency_warnings(gen, events)
    tables["special_ability_consistency_summary"] = consistency_summary(gen, events, tables["special_ability_consistency_warnings"])
    tables["special_ability_conflicts"] = conflict_warnings(gen, events, master)
    tables["special_ability_conflict_summary"] = tables["special_ability_conflicts"].groupby("衝突タイプ", dropna=False).agg(件数=("seed", "count"), 代表seed=("seed", "first")).reset_index() if not tables["special_ability_conflicts"].empty else pd.DataFrame(columns=["衝突タイプ", "件数", "代表seed"])
    tables["generated_special_context_metrics"] = generated_context_metrics(gen, events)
    return tables


def special_event_classification_audit(events: pd.DataFrame, real_specials: pd.DataFrame, gen: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    real_counts = events[events["データ"].eq("実在12球団")]["特殊能力カテゴリ"].value_counts().to_dict()
    existing = real_specials[~real_specials.get("special_kind", pd.Series(dtype=str)).astype(str).eq("usage")].copy() if not real_specials.empty else pd.DataFrame()
    if "special_kind" in existing:
        expected_rank = int(existing[existing["special_kind"].astype(str).isin(["rank", "ランク系"])].shape[0])
        expected_green = int(existing[existing["special_kind"].astype(str).isin(["green", "緑特"])].shape[0])
        expected_normal = int(existing[existing["special_kind"].astype(str).isin(["normal", "blue", "red", "neutral", "mixed"])].shape[0])
    else:
        expected_rank = expected_green = expected_normal = 0
    for category in ["青特", "赤特", "緑特", "ランク系", "金特"]:
        rows.append({"データ": "実在12球団", "監査項目": f"分類後_{category}", "期待値": "", "実測値": int(real_counts.get(category, 0)), "差分": "", "結果": "参考", "理由": "usage除外後の分類結果"})
    rows.extend([
        {"データ": "実在12球団", "監査項目": "既存rank件数", "期待値": expected_rank, "実測値": int(real_counts.get("ランク系", 0)), "差分": int(real_counts.get("ランク系", 0)) - expected_rank, "結果": "OK" if int(real_counts.get("ランク系", 0)) == expected_rank else "差分あり", "理由": "明示special_kindに加え、ランク列または名称末尾A-Gをランク系として優先分類"},
        {"データ": "実在12球団", "監査項目": "既存green件数", "期待値": expected_green, "実測値": int(real_counts.get("緑特", 0)), "差分": int(real_counts.get("緑特", 0)) - expected_green, "結果": "OK" if int(real_counts.get("緑特", 0)) == expected_green else "差分あり", "理由": "special_kindとマスタ/名前推定を併用して緑特へ正規化"},
        {"データ": "実在12球団", "監査項目": "既存normal件数", "期待値": expected_normal, "実測値": int(real_counts.get("青特", 0) + real_counts.get("赤特", 0)), "差分": int(real_counts.get("青特", 0) + real_counts.get("赤特", 0)) - expected_normal, "結果": "OK" if int(real_counts.get("青特", 0) + real_counts.get("赤特", 0)) == expected_normal else "差分あり", "理由": "通常normalを青特/赤特へ再分類し、名称末尾A-Gや緑特推定は通常から除外"},
    ])
    generated_events = events[events["データ"].eq("生成")]
    expanded_normal = sum(1 for value in gen.get("特殊能力", pd.Series(dtype=str)) for name in _split_specials(value) if classify_special_event(name).get("除外") != "1")
    expanded_rank = sum(1 for value in gen.get("ランク系特殊能力", pd.Series(dtype=str)) for name in _split_specials(value))
    normal_event_count = int(generated_events[generated_events["source_column"].eq("特殊能力")].shape[0])
    rank_event_count = int(generated_events[generated_events["source_column"].eq("ランク系特殊能力") & generated_events["特殊能力カテゴリ"].eq("ランク系")].shape[0])
    overlap = generated_events.groupby(["選手キー", "正規化名称"])["イベント種別"].nunique().reset_index(name="種別数")
    overlap_count = int(overlap[overlap["種別数"].gt(1)].shape[0])
    gold_count = int(generated_events[generated_events["特殊能力カテゴリ"].eq("金特")].shape[0])
    rows.extend([
        {"データ": "生成", "監査項目": "通常イベント件数", "期待値": expanded_normal, "実測値": normal_event_count, "差分": normal_event_count - expanded_normal, "結果": "OK" if normal_event_count == expanded_normal else "差分あり", "理由": "generated_players.csvの特殊能力列をusage除外後に展開"},
        {"データ": "生成", "監査項目": "ランク系イベント件数", "期待値": expanded_rank, "実測値": rank_event_count, "差分": rank_event_count - expanded_rank, "結果": "OK" if rank_event_count == expanded_rank else "差分あり", "理由": "ランク系特殊能力列の展開件数"},
        {"データ": "生成", "監査項目": "通常ランク重複", "期待値": 0, "実測値": overlap_count, "差分": overlap_count, "結果": "OK" if overlap_count == 0 else "要確認", "理由": "同一選手・同一正規化名称が複数イベント種別に入っていないか"},
        {"データ": "生成", "監査項目": "金特イベント", "期待値": 0, "実測値": gold_count, "差分": gold_count, "結果": "OK" if gold_count == 0 else "要確認", "理由": "実在0件に合わせて生成対象外"},
    ])
    audit = pd.DataFrame(rows)
    summary = audit.groupby(["データ", "結果"], dropna=False).size().reset_index(name="件数")
    return audit, summary


def ranked_family_distribution(events: pd.DataFrame, players: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    rank_events = events[events["特殊能力カテゴリ"].eq("ランク系")].copy()
    if rank_events.empty:
        return pd.DataFrame(columns=["データ", "カテゴリ", "対象", "比較区分", "ランク系統", "ランク", "人数", "対象選手数", "割合%", "実在との差分"])
    role_by_group = {}
    if not master.empty:
        m = master.copy()
        m["family"] = m["name"].astype(str).map(ranked_special_base)
        for family, sub in m.groupby("family"):
            roles = set(sub.get("対象役割", sub.get("target_role", pd.Series(dtype=str))).fillna("共通").astype(str))
            role_by_group[family] = "投手" if "投手" in roles and "野手" not in roles else "野手" if "野手" in roles and "投手" not in roles else "共通"
    rows = []
    for data_label, category in [("実在12球団", "実在12球団"), *[("生成", c) for c in CATEGORY_PRIORITY if c in set(players.get("category", []))]]:
        ev_base = rank_events[rank_events["データ"].eq(data_label)] if data_label == "実在12球団" else rank_events[(rank_events["データ"].eq("生成")) & (rank_events["カテゴリ"].eq(category))]
        if ev_base.empty:
            continue
        for family, fdf in ev_base.groupby("ランク系統", dropna=False):
            target_role = role_by_group.get(family, "共通")
            if "キャッチャー" in str(family):
                target = "捕手"
                pbase = players[players["category"].eq(category)] if data_label == "生成" else players[players["category"].eq("実在12球団")]
                pbase = pbase[(pbase.get("position", pd.Series(dtype=str)).astype(str).str.contains("捕手", na=False)) | (pbase.get("sub_positions", pbase.get("サブポジ一覧", pd.Series(dtype=str))).astype(str).str.contains("捕手", na=False))]
            elif target_role in {"投手", "野手"}:
                target = target_role
                pbase = players[players["category"].eq(category)] if data_label == "生成" else players[players["category"].eq("実在12球団")]
                pbase = pbase[pbase["role"].eq(target_role)]
            else:
                target = "全体"
                pbase = players[players["category"].eq(category)] if data_label == "生成" else players[players["category"].eq("実在12球団")]
            denom = len(pbase)
            for rank in list("ABCDEFG"):
                cnt = int(fdf[fdf["ランク"].eq(rank)]["選手キー"].nunique())
                rows.append({"データ": "実在12球団" if data_label == "実在12球団" else category, "カテゴリ": category, "対象": target, "比較区分": "明示ランクのみ比較" if data_label == "実在12球団" else "生成全ランク参考", "ランク系統": family, "ランク": rank, "人数": cnt, "対象選手数": denom, "割合%": round(cnt / max(1, denom) * 100, 2), "実在との差分": None})
    df = pd.DataFrame(rows)
    if not df.empty:
        real_rates = df[df["データ"].eq("実在12球団")].set_index(["対象", "ランク系統", "ランク"])["割合%"].to_dict()
        df["実在との差分"] = df.apply(lambda r: None if r["データ"] == "実在12球団" else round(float(r["割合%"])-float(real_rates.get((r["対象"], r["ランク系統"], r["ランク"]), 0)), 2), axis=1)
    return df


def _consistency_check_specs() -> list[tuple[str, str, set[str], Any]]:
    return [
        ("野手", "三振と低ミート", {"三振"}, lambda r: _num(r, "ミート", 99) >= 55),
        ("野手", "エラーと低守備力・低捕球", {"エラー"}, lambda r: min(_num(r, "守備力", 99), _num(r, "捕球", 99)) >= 50),
        ("野手", "併殺と低走力", {"併殺"}, lambda r: _num(r, "走力", 99) >= 55),
        ("野手", "パワーヒッター系とパワー", {"パワーヒッター", "アーチスト"}, lambda r: _num(r, "パワー", 0) < 65),
        ("野手", "アベレージヒッター系とミート", {"アベレージヒッター", "安打製造機"}, lambda r: _num(r, "ミート", 0) < 65),
        ("野手", "盗塁・走塁系と走力", {"盗塁A", "盗塁B", "走塁A", "走塁B", "電光石火"}, lambda r: _num(r, "走力", 0) < 60),
        ("野手", "守備系特殊能力と守備力・捕球・肩力", {"守備職人", "魔術師", "レーザービーム", "高速レーザー"}, lambda r: max(_num(r, "守備力"), _num(r, "捕球"), _num(r, "肩力")) < 60),
        ("野手", "捕手系特殊能力とメイン/サブ捕手", {"キャッチャーA", "キャッチャーB", "キャッチャーC", "キャッチャーE", "キャッチャーF", "キャッチャーG", "球界の頭脳"}, lambda r: "捕手" not in str(r.get("position", "")) and "捕手" not in str(r.get("サブポジ一覧", ""))),
        ("投手", "四球・抜け球・乱調とコントロール", {"四球", "抜け球", "乱調"}, lambda r: _num(r, "コントロール", 99) >= 50),
        ("投手", "一発・軽い球と球速・総変化量", {"一発", "軽い球"}, lambda r: _num(r, "球速", 0) >= 150 or _num(r, "総変化量", 0) >= 9),
        ("投手", "ノビ系と球速", {"ノビA", "ノビB", "ノビC", "ノビE", "ノビF", "ノビG"}, lambda r: _num(r, "球速", 0) < 140),
        ("投手", "キレ系と総変化量", {"キレ○", "キレ×"}, lambda r: _num(r, "総変化量", 0) < 5),
        ("投手", "奪三振系と球速・総変化量", {"奪三振", "ドクターK"}, lambda r: _num(r, "球速", 0) < 145 and _num(r, "総変化量", 0) < 7),
        ("投手", "起用系と投手適正", {"完投", "完封", "尻上がり", "中継ぎエース", "守護神", "セーブ狙い"}, lambda r: False),
    ]


def consistency_warnings(gen: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    gen_events = events[(events["データ"].eq("生成")) & (~events["特殊能力カテゴリ"].isin(["usage", "金特"]))]
    by_seed = gen_events.groupby("選手キー")["正規化名称"].apply(set).to_dict()
    for idx, r in gen.iterrows():
        seed = str(r.get("seed", idx))
        specs = by_seed.get(seed, set())
        for role, label, names, predicate in _consistency_check_specs():
            if r.get("role") != role or not specs.intersection(names):
                continue
            bad = False
            if label == "起用系と投手適正":
                starter_bad = bool(specs.intersection({"完投", "完封", "尻上がり"})) and r.get("starter_aptitude") not in {"◎", "○"}
                relief_bad = bool(specs.intersection({"中継ぎエース", "守護神", "セーブ狙い"})) and r.get("reliever_aptitude") not in {"◎", "○"} and r.get("closer_aptitude") not in {"◎", "○"}
                bad = starter_bad or relief_bad
            else:
                bad = bool(predicate(r))
            if bad:
                rows.append({"seed": seed, "カテゴリ": r.get("category"), "対象": role, "player_type": r.get("player_type"), "チェック": label, "対象特殊能力": "、".join(sorted(specs.intersection(names))), "特殊能力": "、".join(sorted(specs))})
    return pd.DataFrame(rows)


def consistency_summary(gen: pd.DataFrame, events: pd.DataFrame, warnings: pd.DataFrame) -> pd.DataFrame:
    rows = []
    gen_events = events[events["データ"].eq("生成")]
    by_seed = gen_events.groupby("選手キー")["正規化名称"].apply(set).to_dict()
    for role, label, names, _predicate in _consistency_check_specs():
        category_scopes = ["全生成", *[c for c in CATEGORY_PRIORITY if c in set(gen.get("category", []))]]
        player_type_scopes = ["全体", *sorted(gen.get("player_type", pd.Series(dtype=str)).dropna().astype(str).unique())]
        for category in category_scopes:
            for player_type in player_type_scopes:
                base = gen[gen["role"].eq(role)].copy()
                if category != "全生成":
                    base = base[base["category"].eq(category)]
                if player_type != "全体":
                    base = base[base["player_type"].astype(str).eq(player_type)]
                if base.empty:
                    continue
                seeds = set(base["seed"].astype(str))
                holders = {seed for seed in seeds if by_seed.get(seed, set()).intersection(names)}
                if not holders:
                    continue
                w = warnings[(warnings.get("チェック", pd.Series(dtype=str)).eq(label)) & (warnings.get("seed", pd.Series(dtype=str)).astype(str).isin(seeds))] if not warnings.empty else pd.DataFrame()
                bad_count = int(w["seed"].nunique()) if not w.empty else 0
                usable = player_type == "全体" or len(holders) >= 20 or (bad_count / max(1, len(base)) * 100) >= 1
                rows.append({"カテゴリ": category, "対象": role, "player_type": player_type, "チェック": label, "全対象人数": len(base), "特殊能力保有者数": len(holders), "不整合人数": bad_count, "全対象比%": round(bad_count / max(1, len(base)) * 100, 2), "保有者内不整合率%": round(bad_count / max(1, len(holders)) * 100, 2), "調整根拠採用可": "可" if usable else "参考のみ", "代表seed": int(w["seed"].iloc[0]) if not w.empty else ""})
    return pd.DataFrame(rows)


def conflict_warnings(gen: pd.DataFrame, events: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    rows = []
    role_map = dict(zip(master["name"].astype(str), master["対象役割"].astype(str))) if not master.empty and "対象役割" in master else {}
    pairs = [("積極打法", "慎重打法"), ("強振多用", "ミート多用"), ("速球中心", "変化球中心"), ("投球位置左", "投球位置右"), ("チームプレイ○", "チームプレイ×")]
    ev = events[(events["データ"].eq("生成")) & (~events["特殊能力カテゴリ"].isin(["金特"]))]
    by_seed = ev.groupby("選手キー")["正規化名称"].apply(list).to_dict()
    for idx, r in gen.iterrows():
        seed = str(r.get("seed", idx)); vals = by_seed.get(seed, []); specs = set(vals)
        for name in set(vals):
            if vals.count(name) > 1:
                rows.append({"seed": seed, "衝突タイプ": "同一特殊能力の重複", "詳細": name})
        for a, b in pairs:
            if a in specs and b in specs:
                rows.append({"seed": seed, "衝突タイプ": "相反特殊能力の同時所持", "詳細": f"{a} / {b}"})
        fams: dict[str, set[str]] = {}
        for name in specs:
            if re.search(r"[A-G]$", name):
                fams.setdefault(ranked_special_base(name), set()).add(name[-1])
            target = role_map.get(name)
            if target in {"投手", "野手"} and target != r.get("role"):
                rows.append({"seed": seed, "衝突タイプ": "専用能力の対象外所持", "詳細": name})
        for fam, ranks in fams.items():
            if len(ranks) > 1:
                rows.append({"seed": seed, "衝突タイプ": "同じランク系統を複数ランクで所持", "詳細": f"{fam}:{','.join(sorted(ranks))}"})
    return pd.DataFrame(rows, columns=["seed", "衝突タイプ", "詳細"])


def generated_context_metrics(gen: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    ev = events[(events["データ"].eq("生成")) & (events["特殊能力カテゴリ"].isin(NORMAL_REVIEW_CATEGORIES))]
    counts = ev.groupby("選手キー").size().to_dict()
    red_counts = ev[ev["特殊能力カテゴリ"].eq("赤特")].groupby("選手キー").size().to_dict()
    rows = []
    work = gen.copy()
    work["通常特殊能力数"] = [counts.get(generated_seed_key(r.get("seed", i), i), 0) for i, r in work.iterrows()]
    work["赤特数_比較用"] = [red_counts.get(generated_seed_key(r.get("seed", i), i), 0) for i, r in work.iterrows()]
    work["総合スコア帯"] = pd.cut(pd.to_numeric(work.get("総合スコア", pd.Series(dtype=float)), errors="coerce"), bins=[-1, 180, 220, 260, 999], labels=["180未満", "180-220", "220-260", "260以上"])
    if "age" in work:
        work["年齢帯_比較用"] = pd.cut(pd.to_numeric(work["age"], errors="coerce"), bins=[0, 22, 26, 32, 99], labels=["22歳以下", "23-26歳", "27-32歳", "33歳以上"])
    for col, label in [("player_type", "player_type"), ("総合スコア帯", "総合スコア帯"), ("年齢帯_比較用", "年齢帯"), ("position", "ポジション"), ("category", "カテゴリ")]:
        if col in work:
            for val, sub in work.groupby(col, dropna=False):
                rows.append({"集計軸": label, "値": val, "人数": len(sub), "平均特殊能力数": round(sub["通常特殊能力数"].mean(), 3), "0個率%": round(sub["通常特殊能力数"].eq(0).mean() * 100, 2), "5個以上率%": round(sub["通常特殊能力数"].ge(5).mean() * 100, 2), "赤特平均": round(sub["赤特数_比較用"].mean(), 3)})
    if {"starter_aptitude", "reliever_aptitude", "closer_aptitude"}.issubset(work.columns):
        work["投手起用"] = assign_pitcher_usage(work, [], prefer_aptitudes=True)
        for val, sub in work[work["role"].eq("投手")].groupby("投手起用", dropna=False):
            rows.append({"集計軸": "投手起用", "値": val, "人数": len(sub), "平均特殊能力数": round(sub["通常特殊能力数"].mean(), 3), "0個率%": round(sub["通常特殊能力数"].eq(0).mean() * 100, 2), "5個以上率%": round(sub["通常特殊能力数"].ge(5).mean() * 100, 2), "赤特平均": round(sub["赤特数_比較用"].mean(), 3)})
    return pd.DataFrame(rows)


def write_special_review_memo(tables: dict[str, pd.DataFrame], output_dir: Path) -> None:
    kind = tables.get("special_kind_metrics_compare", pd.DataFrame())
    audit = tables.get("special_event_classification_audit", pd.DataFrame())
    conflict = tables.get("special_ability_conflict_summary", pd.DataFrame())
    consistency = tables.get("special_ability_consistency_summary", pd.DataFrame())
    lines = ["# 特殊能力 最終比較レビュー", "", "## 集計定義の修正", "- usageは選手生成とは別枠のため、特殊能力イベント・不足判定・警告・調整計画から除外しました。", "- 金特は今回の実在12球団データで0件、生成側も0件のため一致扱いです。警告・修正必須・将来候補から除外します。", "- 通常特殊能力は青特・赤特・緑特のみとし、ランク系は完全に別イベントとして扱います。", "", "## 分類監査", f"- 監査行数: {len(audit)}。詳細は `special_event_classification_audit.csv` と `special_event_classification_summary.csv`。", "", "## 通常特殊能力の比較", "- `special_kind_metrics_compare.csv` は青特・赤特・緑特のみを対象に、平均個数・100人あたり出現数・保有率・個数率を出力しています。", "- 架空球団用を実在12球団との主比較対象、ドラフト候補用は低め、助っ人外国人用は尖り許容として解釈します。", "", "## 特殊能力名別の比較", "- `special_name_metrics_compare.csv` は生データ名称・正規化名称・alias適用有無を保持し、表記差を比較時のみ吸収します。", "", "## ランク系A〜G分布", "- 実在側は明示ランクのみ比較し、未記録=Dの補完は行いません。", "- 生成側はDを明示出力しているため、生成全ランク分布は参考表示として出力します。", "- キャッチャー系は捕手（メインまたはサブ）分母、投手系は投手分母、野手系は野手分母、共通系は全選手分母に分離しました。", "", "## 整合性警告", f"- サマリー行数: {len(consistency)}。全対象比%と保有者内不整合率%を分け、調整要否は主に保有者内不整合率%で判断します。", "", "## 衝突・重複", f"- 衝突サマリー行数: {len(conflict)}。usageと金特は衝突確認対象外です。", "", "## 修正判断", "- usageと金特を除外した再集計後の数値に基づき、調整案は `special_ability_adjustment_plan.md` に記載します。"]
    (output_dir / "special_ability_review_memo.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_special_adjustment_plan(tables: dict[str, pd.DataFrame], output_dir: Path) -> None:
    kind = tables.get("special_kind_metrics_compare", pd.DataFrame())
    name = tables.get("special_name_metrics_compare", pd.DataFrame())
    rank = tables.get("ranked_ability_family_distribution_compare", pd.DataFrame())
    consistency = tables.get("special_ability_consistency_summary", pd.DataFrame())
    context = tables.get("generated_special_context_metrics", pd.DataFrame())
    audit = tables.get("special_event_classification_audit", pd.DataFrame())
    conflict = tables.get("special_ability_conflict_summary", pd.DataFrame())
    def md(df: pd.DataFrame, max_rows: int = 40) -> str:
        if df.empty:
            return "該当なし"
        view = df.head(max_rows).fillna("")
        cols = list(view.columns)
        lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
        for _, row in view.iterrows():
            lines.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
        return "\n".join(lines)
    main_kind = kind[(kind["データ"].isin(["実在12球団", "架空球団用"])) & (kind["対象"].isin(["投手", "野手"]))] if not kind.empty else pd.DataFrame()
    too_much = name[(name.get("データ", pd.Series(dtype=str)).eq("架空球団用")) & (pd.to_numeric(name.get("保有率差分", pd.Series(dtype=float)), errors="coerce") >= 10)] if not name.empty else pd.DataFrame()
    too_low = name[(name.get("データ", pd.Series(dtype=str)).eq("架空球団用")) & (pd.to_numeric(name.get("保有率差分", pd.Series(dtype=float)), errors="coerce") <= -10)] if not name.empty else pd.DataFrame()
    generated_only = name[(name.get("データ", pd.Series(dtype=str)).eq("架空球団用")) & (pd.to_numeric(name.get("実在出現数", pd.Series(dtype=float)), errors="coerce").eq(0)) & (pd.to_numeric(name.get("生成出現数", pd.Series(dtype=float)), errors="coerce").gt(0))] if not name.empty else pd.DataFrame()
    real_only = name[(name.get("データ", pd.Series(dtype=str)).eq("架空球団用")) & (pd.to_numeric(name.get("実在出現数", pd.Series(dtype=float)), errors="coerce").gt(0)) & (pd.to_numeric(name.get("生成出現数", pd.Series(dtype=float)), errors="coerce").eq(0))] if not name.empty else pd.DataFrame()
    usable_consistency = consistency[
        (consistency.get("カテゴリ", pd.Series(dtype=str)).eq("架空球団用"))
        & (consistency.get("player_type", pd.Series(dtype=str)).eq("全体"))
    ] if not consistency.empty else pd.DataFrame()
    high_consistency = usable_consistency[pd.to_numeric(usable_consistency.get("保有者内不整合率%", pd.Series(dtype=float)), errors="coerce") >= 20] if not usable_consistency.empty else pd.DataFrame()
    rank_major = pd.DataFrame()
    if not rank.empty:
        tmp = rank[(rank["データ"].eq("架空球団用")) & (rank["ランク"].isin(list("ABCEFG")))].copy()
        tmp["absdiff"] = pd.to_numeric(tmp["実在との差分"], errors="coerce").abs()
        rank_major = tmp.sort_values("absdiff", ascending=False).head(20).drop(columns=["absdiff"], errors="ignore")
    conflict_total = int(pd.to_numeric(conflict.get("件数", pd.Series(dtype=int)), errors="coerce").fillna(0).sum()) if not conflict.empty else 0
    adjustment_rows = []
    if not too_low.empty:
        adjustment_rows.append({"対象能力または能力群": "実在より10pt以上少ない通常特殊能力", "現状値": "special_name_metrics_compare参照", "実在値": "同左", "問題": "実在との差が大きい", "修正方針": "個別能力のweight/条件を軽微調整候補にする", "修正対象の関数・マスタ": "data/special_abilities.csv / adjust_special_chance", "推奨補正量": "+10〜+20%から検証", "影響範囲": "通常青特・赤特・緑特", "回帰確認項目": "保有率差分、保有者内不整合率"})
    if not high_consistency.empty:
        adjustment_rows.append({"対象能力または能力群": "保有者内不整合率20%以上の能力群", "現状値": "special_ability_consistency_summary参照", "実在値": "該当なし", "問題": "能力値や適正と特殊能力の対応が弱い", "修正方針": "生成確率ではなく条件連動を次段階で検討", "修正対象の関数・マスタ": "adjust_special_chance / ranked_weight_items_for_group", "推奨補正量": "条件外で-20〜-50%を候補", "影響範囲": "該当能力群", "回帰確認項目": "保有者内不整合率"})
    conclusion = "通常青特・赤特・緑特の再調整が必要" if not too_low.empty or not too_much.empty else "特殊能力生成は現状のまま完成扱い可能"
    if not high_consistency.empty and conclusion == "特殊能力生成は現状のまま完成扱い可能":
        conclusion = "軽微調整のみ必要"
    lines = ["# 特殊能力 調整対象絞り込み計画", "", "## 前提", "- usageは今回の調整・比較対象外です。", "- 金特は実在0件・生成0件で一致しているため変更しません。", "- ランク系はD補完せず、全行ではなく主要差分だけをMarkdownへ掲載します。詳細はCSVを参照してください。", "", "## 実在12球団と架空球団用の投手・野手別総量比較", md(main_kind, 20), "", "## 青特・赤特・緑特の平均個数と保有率", md(main_kind[["データ","対象","カテゴリ","1人あたり平均個数","1件以上保有率%","0個率%","5個以上率%"]] if not main_kind.empty else main_kind, 20), "", "## 差分が大きい特殊能力上位", "### 生成側が多い", md(too_much.sort_values("保有率差分", ascending=False).head(15) if not too_much.empty else too_much, 15), "", "### 生成側が少ない", md(too_low.sort_values("保有率差分").head(15) if not too_low.empty else too_low, 15), "", "## 整合性警告の集約値", "- 調整判断はまず架空球団用の投手／野手全体（player_type=全体）を使用します。player_type別は、特殊能力保有者数20人以上または全対象比1%以上のみ根拠採用可です。", md(consistency.sort_values(["カテゴリ","対象","player_type","保有者内不整合率%"], ascending=[True, True, True, False]) if not consistency.empty else consistency, 80), "", "## 衝突件数", f"- 衝突合計: {conflict_total}件", md(conflict, 20), "", "## ランク系の主要差分", md(rank_major, 20), "", "## 調整方針", md(pd.DataFrame(adjustment_rows), 10), "- 総量は選手格スケール、player_typeの能力連動、カテゴリ別スケール、個別能力条件、上限・重複除去の順で調整します。", "- 保有者数が少ない100%行だけを理由に生成確率を変更しません。", "", "## 分類監査", md(audit, 20), "", "## 最終結論", f"**{conclusion}。** usageと金特は判断対象外です。詳細明細はCSVに残しています。"]
    (output_dir / "special_ability_adjustment_plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_special_adjustment_review(tables: dict[str, pd.DataFrame], output_dir: Path) -> None:
    kind = tables.get("special_kind_metrics_compare", pd.DataFrame())
    counts = tables.get("special_count_distribution_compare", pd.DataFrame())
    consistency = tables.get("special_ability_consistency_summary", pd.DataFrame())
    conflict = tables.get("special_ability_conflict_summary", pd.DataFrame())
    rank = tables.get("ranked_ability_family_distribution_compare", pd.DataFrame())
    context = tables.get("generated_special_context_metrics", pd.DataFrame())
    fielder = tables.get("fielder_ability_compare", pd.DataFrame())
    pitcher = tables.get("pitcher_ability_compare", pd.DataFrame())
    breaking = tables.get("breaking_ball_compare", pd.DataFrame())

    def md(df: pd.DataFrame, max_rows: int = 30) -> str:
        if df.empty:
            return "該当なし"
        view = df.head(max_rows).fillna("")
        cols = list(view.columns)
        out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
        for _, row in view.iterrows():
            out.append("| " + " | ".join(str(row[c]) for c in cols) + " |")
        return "\n".join(out)

    target_kind = kind[(kind["データ"].isin(["実在12球団", "架空球団用", "ドラフト候補用", "助っ人外国人用"])) & (kind["対象"].isin(["投手", "野手"]))] if not kind.empty else pd.DataFrame()
    conflict_total = int(pd.to_numeric(conflict.get("件数", pd.Series(dtype=int)), errors="coerce").fillna(0).sum()) if not conflict.empty else 0
    rank_key = rank[(rank.get("データ", pd.Series(dtype=str)).eq("架空球団用")) & (rank.get("ランク", pd.Series(dtype=str)).isin(list("ABCEFG")))].head(30) if not rank.empty else pd.DataFrame()
    ability_regression = pd.concat([
        fielder[fielder.get("カテゴリ", pd.Series(dtype=str)).eq("架空球団用")].assign(区分="野手基本能力"),
        pitcher[pitcher.get("カテゴリ", pd.Series(dtype=str)).eq("架空球団用")].assign(区分="投手基本能力"),
    ], ignore_index=True, sort=False) if not fielder.empty or not pitcher.empty else pd.DataFrame()
    movement = breaking[breaking.get("カテゴリ", pd.Series(dtype=str)).isin(["実在12球団", "架空球団用"])].head(40) if not breaking.empty else pd.DataFrame()
    lines = [
        "# 特殊能力 調整レビュー",
        "",
        "## 修正した関数・係数",
        "- `app.py`: `player_special_scale` を追加し、選手格・カテゴリ・年齢で通常特殊能力の基礎スケールを調整。",
        "- `app.py`: `adjust_special_chance` で青特・赤特・緑特の能力依存、野手赤特、野手緑特、投手青特、投手赤特の軽微抑制を調整。",
        "- `app.py`: `generate_specials` で緑特などの相反ペア除外とカテゴリ別上限を維持。",
        "- `app.py`: `ranked_shift_for_group` でノビ系と盗塁・走塁系の能力連動を強化。",
        "- `scripts/compare_real_and_generated_balance.py`: Markdownを要約中心にし、明細はCSVへ退避。整合性警告に全生成・カテゴリ別・投手/野手別・player_type別と根拠採用可否を出力。",
        "",
        "## 投手／野手別のbefore・after・実在値",
        "- このレビューはafter比較ディレクトリで生成されるため、after・実在値は下表、before値は `reports/real_vs_generated_balance_5000_special_before` がある場合にCSV同士で確認してください。",
        md(target_kind, 30),
        "",
        "## 青特・赤特・緑特の個数分布",
        md(counts[counts.get("データ", pd.Series(dtype=str)).isin(["実在12球団", "架空球団用"])].head(40) if not counts.empty else counts, 40),
        "",
        "## カテゴリ別の影響",
        md(kind[kind.get("データ", pd.Series(dtype=str)).isin(["架空球団用", "ドラフト候補用", "助っ人外国人用"])] if not kind.empty else kind, 40),
        "",
        "## player_type別の影響",
        md(context[context.get("集計軸", pd.Series(dtype=str)).eq("player_type")] if not context.empty else context, 30),
        "",
        "## 整合性警告のbefore・after",
        "- afterの集約値は下表です。player_type別の小母数行は `調整根拠採用可=参考のみ` として扱います。",
        md(consistency, 60),
        "",
        "## 衝突が0件であること",
        f"- 衝突合計: {conflict_total}件。",
        md(conflict, 20),
        "",
        "## ランク系への影響",
        "- 実在側D補完は行わず、生成Dは仕様として維持しています。Markdownには主要差分のみ掲載します。",
        md(rank_key, 30),
        "",
        "## 基本能力・変化球への回帰がないこと",
        "- 今回の変更対象は特殊能力生成ロジックのみで、野手基本能力・投手基本能力・変化球生成は変更していません。比較CSVで平均差分を確認してください。",
        md(ability_regression, 30),
        "",
        "### 変化球系参考",
        md(movement, 40),
        "",
        "## 残っている差",
        "- 個別能力の実在差分は `special_name_metrics_compare.csv`、ランク系詳細は `ranked_ability_family_distribution_compare.csv` を確認してください。",
        "",
        "## 特殊能力生成を完成扱いにできるか",
        "- 衝突0件、usage 0件、金特0件、専用能力の対象外所持0件を満たし、架空球団用の投手／野手全体が目標レンジ内なら第1段階は完成扱い可能です。",
    ]
    (output_dir / "special_adjustment_review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    special_review = special_review_tables(real, data["real_specials"], gen)
    real_optional = data["_real_optional"]
    generated_optional = data["_generated_optional"]
    severity_summary, high_warnings = generated_warning_tables(generated_optional)
    tables = {"overall_compare": overall, "fielder_ability_compare": fielder, "pitcher_ability_compare": pitcher, "position_compare": position, "pitcher_role_compare": pitch_role, "breaking_ball_compare": breaking, "special_ability_category_compare": special_cat, "special_ability_name_compare": special_name, "rank_ability_compare": rank_name, "percentile_compare": percentile_compare(fielder, pitcher)}
    tables.update(special_review)
    tables.update({
        "trajectory_distribution_compare": trajectory_distribution_compare(real, gen),
        "position_rate_compare": position_rate_compare(real, gen),
        "generated_warning_severity_summary": severity_summary,
        "generated_high_warnings": high_warnings,
        "sub_position_compare": sub_position_compare(real_optional, generated_optional),
        "pitcher_aptitude_compare": pitcher_aptitude_compare(real_optional, generated_optional, gen),
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
    write_special_review_memo(tables, args.output_dir)
    write_special_adjustment_plan(tables, args.output_dir)
    write_special_adjustment_review(tables, args.output_dir)
    print(f"比較レポートを出力しました: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
