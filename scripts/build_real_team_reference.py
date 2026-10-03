"""実在球団（2022〜2026年版パワプロ、12球団×5年＝60チーム）の比較用データを作る。

一度実行すれば、以後アプリ（球団分析）は出力ファイルだけを読む（アプリ起動時に HTML を解析しない）。

    python scripts/build_real_team_reference.py \
      --zip-2022-2025 data/raw/powerpro_2022_2025/real_2022_2025.zip \
      --raw-2026 data/raw/powerpro_2026_2027 \
      --entry-route local_data/pawapuro_players_entry_route_2026.xlsx \
      --foreign-list local_data/pawapuro_foreign_2022_2024_2025_complete_v6.xlsx

出力:
    local_data/real_players_2022_2026.csv          選手単位（正規化済み。コミットしない）
    data/reference/real_team_stats_2022_2026.csv   球団単位の集計（縦持ち。コミットする）
    reports/real_team_reference/summary.md         件数・人数構成CSVとの整合チェック・外国人数の差・主要指標の分布

HTML の取り込みは scripts/import_real_powerpro_players.py の関数（read_sources → parse_cards → combine_results）を
そのまま使う。zip は年版ごとに一時フォルダへ展開する（年版はフォルダ名「2022年版データ」などから決める。
ファイル名は年版と合わないことがあるため使わない）。
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "scripts"))

import pandas as pd  # noqa: E402

import import_real_powerpro_players as importer  # noqa: E402
from generator import real_data  # noqa: E402
from generator import team_analysis as ta  # noqa: E402

DEFAULT_ZIP = APP_DIR / "data" / "raw" / "powerpro_2022_2025" / "real_2022_2025.zip"
DEFAULT_RAW_2026 = APP_DIR / "data" / "raw" / "powerpro_2026_2027"
DEFAULT_ENTRY_ROUTE = APP_DIR / "local_data" / "pawapuro_players_entry_route_2026.xlsx"
DEFAULT_FOREIGN_LIST = APP_DIR / "local_data" / "pawapuro_foreign_2022_2024_2025_complete_v6.xlsx"
FOREIGN_LIST_SHEET = "combined_2022_2025_complete"
COMPOSITION_PATH = APP_DIR / "data" / "reference" / "real_team_composition_2022_2026.csv"
REPORT_DIR = APP_DIR / "reports" / "real_team_reference"
SEASON_FOLDER_RE = re.compile(r"^(\d{4})年版")
# 外国人一覧で照合する年版（2023年版は一覧に無い）
FOREIGN_LIST_SEASONS = (2022, 2024, 2025)
# 外国人一覧の球団の略称 → 正式名（HTML の球団名）
TEAM_SHORT_NAMES = {
    "阪神": "阪神タイガース", "ヤクルト": "東京ヤクルトスワローズ", "巨人": "読売ジャイアンツ", "広島": "広島東洋カープ",
    "中日": "中日ドラゴンズ", "DeNA": "横浜DeNAベイスターズ", "西武": "埼玉西武ライオンズ", "日本ハム": "北海道日本ハムファイターズ",
    "ソフトバンク": "福岡ソフトバンクホークス", "楽天": "東北楽天ゴールデンイーグルス", "ロッテ": "千葉ロッテマリーンズ", "オリックス": "オリックスバファローズ",
}
KATAKANA_ONLY_RE = re.compile(r"^[ァ-ヶー・･]+$")
# 二刀流（投手・野手の両方のデータを持つ選手）。名前の class に投手（p・r）と野手（c・i・o）の両方の文字がある
TWO_WAY_CLASS_RE = re.compile(r'class="nm ([a-z]*)"[^>]*>(.*?)</b>', re.S)
CONSISTENCY_COLUMNS = ("total", "pitchers", "fielders", "pos_C", "pos_1B", "pos_2B", "pos_3B", "pos_SS", "pos_OF", "left_pitchers", "main_starter", "main_reliever")
POSITION_COLUMNS = {"捕手": "pos_C", "一塁手": "pos_1B", "二塁手": "pos_2B", "三塁手": "pos_3B", "遊撃手": "pos_SS", "外野手": "pos_OF"}
NUMERIC_PLAYER_COLUMNS = ("number", "top_speed", "control", "stamina", "trajectory", "contact", "power", "run_speed", "arm_strength", "fielding", "catching")
# 指示書 6-1 の参考値（取り込み結果から計算した球団平均の能力。60チーム）
EXPECTED_TEAM_ABILITY = {
    ("投手", "球速"): (150.2, 150.6, 151.5, 152.7, 153.2),
    ("投手", "コントロール"): (45.9, 48.8, 50.8, 53.2, 55.2),
    ("投手", "スタミナ"): (50.0, 50.9, 51.9, 53.7, 55.9),
    ("野手", "弾道"): (2.3, 2.5, 2.6, 2.7, 2.9),
    ("野手", "ミート"): (33.8, 35.3, 41.1, 43.5, 45.6),
    ("野手", "パワー"): (50.3, 51.8, 53.5, 55.9, 57.0),
    ("野手", "走力"): (59.2, 61.3, 63.6, 66.2, 67.7),
    ("野手", "肩力"): (62.2, 63.6, 66.5, 68.3, 70.1),
    ("野手", "守備力"): (48.4, 49.8, 51.6, 53.4, 55.2),
    ("野手", "捕球"): (45.0, 46.5, 48.2, 50.2, 52.7),
}


def compact_name(value: Any) -> str:
    return re.sub(r"[\s　]", "", str(value or ""))


# ---------------------------------------------------------------------------
# 取り込み
# ---------------------------------------------------------------------------
def extract_seasons(zip_path: Path, destination: Path) -> dict[int, Path]:
    """zip を年版ごとのフォルダに展開する。zip 内のフォルダ名「2022年版データ」の下だけを使う。"""
    folders: dict[int, Path] = {}
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            parts = importer.decode_zip_member_name(info.filename).split("/")
            index = next((i for i, part in enumerate(parts) if SEASON_FOLDER_RE.match(part)), None)
            if index is None or index == len(parts) - 1:
                continue
            season = int(SEASON_FOLDER_RE.match(parts[index]).group(1))
            target = destination / str(season) / Path(*parts[index + 1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
            folders[season] = destination / str(season)
    return dict(sorted(folders.items()))


def parse_directory(input_dir: Path) -> tuple[dict[str, pd.DataFrame], list[Any]]:
    """既存の取り込み処理で1つの年版を読み、選手・特殊能力・変化球の表にする。"""
    docs, source_failures = importer.read_sources(input_dir)
    combined = importer.combine_results([importer.parse_cards(doc) for doc in docs], source_failures)
    players = pd.DataFrame(combined.players).reindex(columns=importer.PLAYER_COLUMNS + ["source"])
    for column in NUMERIC_PLAYER_COLUMNS:
        players[column] = pd.to_numeric(players[column], errors="coerce")
    for column in ("sub_positions", "pitcher_roles"):
        players[column] = players[column].replace("", float("nan"))
    tables = {
        "players": players,
        "specials": pd.DataFrame(combined.specials).reindex(columns=importer.SPECIAL_COLUMNS),
        "breaking": pd.DataFrame(combined.breaking).reindex(columns=importer.BREAKING_BALL_COLUMNS),
        "failed": pd.DataFrame(combined.failed_players).reindex(columns=importer.FAILED_PLAYER_COLUMNS),
        "input_errors": pd.DataFrame(combined.input_errors).reindex(columns=importer.INPUT_ERROR_COLUMNS),
    }
    return tables, docs


def two_way_players(docs: list[Any]) -> list[tuple[str, str, str]]:
    """二刀流の選手（球団, 登録名, 名前の class）。取り込み処理は野手として読む。"""
    found = []
    for doc in docs:
        title = re.search(r"<title>(.*?)</title>", doc.html_text, re.I | re.S)
        parts = [part.strip() for part in importer.clean_text(title.group(1)).split("｜")] if title else []
        team = parts[1] if len(parts) >= 2 else ""
        for classes, name in TWO_WAY_CLASS_RE.findall(doc.html_text):
            if re.search(r"[pr]", classes) and re.search(r"[cio]", classes):
                found.append((team, importer.clean_text(name), classes))
    return found


# ---------------------------------------------------------------------------
# 外国人・年齢
# ---------------------------------------------------------------------------
def foreign_list_keys(path: Path) -> set[tuple[int, str, str]]:
    """外国人一覧（2022・2024・2025年版）の (年版, 球団, 名前の候補)。

    一覧は「A.J.コール」「スチュワートJr.」のような登録名なので、HTML の短い登録名とも合うよう候補を作る。
    日本の学校出身で分析から外した選手（include_foreign_analysis が False）は含めない。
    """
    frame = pd.read_excel(path, sheet_name=FOREIGN_LIST_SHEET)
    frame = frame[frame["include_foreign_analysis"].astype(bool)]
    keys = set()
    for row in frame.itertuples():
        team = TEAM_SHORT_NAMES.get(str(row.team), str(row.team))
        for candidate in name_candidates(str(row.name)):
            keys.add((int(row.season), team, candidate))
    return keys


def name_candidates(name: str) -> set[str]:
    base = compact_name(name)
    without_suffix = re.sub(r"(Jr\.?|ジュニア)$", "", base)
    candidates = {base, without_suffix}
    pieces = [piece for piece in re.split(r"[.．・]", without_suffix) if piece]
    if pieces:
        candidates.add(pieces[-1])
        candidates.add(pieces[0])
    return {candidate for candidate in candidates if candidate}


def is_katakana_only(name: str) -> bool:
    return bool(KATAKANA_ONLY_RE.match(compact_name(name)))


def load_entry_route(path: Path) -> pd.DataFrame:
    frame = pd.read_excel(path, sheet_name="players")
    frame["compact"] = frame["name"].map(compact_name)
    return frame[["team", "compact", "age", "pro_years", "entry_route"]].drop_duplicates(["team", "compact"])


def decorate_season(players: pd.DataFrame, season: int, foreign_keys: set[tuple[int, str, str]], entry: pd.DataFrame) -> pd.DataFrame:
    """外国人の判定・年齢（2026年版のみ）・逆算年齢を足す。"""
    out = players.copy()
    out["season"] = season
    out["compact"] = out["name"].map(compact_name)
    merged = out.merge(entry, on=["team", "compact"], how="left")
    katakana = merged["name"].map(is_katakana_only)
    if season == real_data.AGE_SEASON:
        merged["is_foreign"] = merged["entry_route"].eq("海外・その他") & katakana
        merged["foreign_basis"] = "入団経路＋カタカナ名"
        merged["age_backcalc"] = merged["age"]
    else:
        in_list = [(season, team, name) in foreign_keys for team, name in zip(merged["team"], merged["compact"])]
        if season in FOREIGN_LIST_SEASONS:
            merged["is_foreign"] = pd.Series(in_list, index=merged.index) | katakana
            merged["foreign_basis"] = ["外国人一覧" if hit else ("カタカナ名" if kata else "") for hit, kata in zip(in_list, katakana)]
        else:
            merged["is_foreign"] = katakana
            merged["foreign_basis"] = ["カタカナ名" if kata else "" for kata in katakana]
        merged["age_backcalc"] = merged["age"] - (real_data.AGE_SEASON - season)
        # 年齢・プロ年数・入団経路は2026年版だけ（逆算は「2026年まで残った選手」に偏るため比較には使わない）
        merged["age"] = float("nan")
        merged["pro_years"] = float("nan")
        merged["entry_route"] = None
    return merged.drop(columns=["compact"])


# ---------------------------------------------------------------------------
# 集計と検証
# ---------------------------------------------------------------------------
def composition_counts(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (season, team), group in frame.groupby(["season", "team"]):
        pitchers = group[group["role"] == "投手"]
        fielders = group[group["role"] != "投手"]
        row = {
            "season": int(season), "team": team, "total": len(group), "pitchers": len(pitchers), "fielders": len(fielders),
            "left_pitchers": int((pitchers["throws"] == "左").sum()),
            "main_starter": int((pitchers["pitcher_role"] == "先発").sum()),
            "main_reliever": int((pitchers["pitcher_role"] != "先発").sum()),
            "foreign": int(group["is_foreign"].sum()),
        }
        for position, column in POSITION_COLUMNS.items():
            row[column] = int((fielders["position"] == position).sum())
        rows.append(row)
    return pd.DataFrame(rows)


def consistency_check(counts: pd.DataFrame, composition: pd.DataFrame) -> pd.DataFrame:
    merged = counts.merge(composition, on=["season", "team"], how="outer", suffixes=("", "_csv"), indicator=True)
    rows = []
    for record in merged.to_dict("records"):
        if record["_merge"] != "both":
            rows.append({"season": record["season"], "team": record["team"], "item": "球団", "built": record["_merge"], "csv": ""})
            continue
        for column in CONSISTENCY_COLUMNS:
            built, expected = record[column], record[f"{column}_csv"]
            if pd.isna(expected) or int(built) != int(expected):
                rows.append({"season": int(record["season"]), "team": record["team"], "item": column, "built": int(built), "csv": expected})
    return pd.DataFrame(rows, columns=["season", "team", "item", "built", "csv"])


def foreign_differences(counts: pd.DataFrame, composition: pd.DataFrame) -> pd.DataFrame:
    merged = counts[["season", "team", "foreign"]].merge(composition[["season", "team", "foreign"]], on=["season", "team"], suffixes=("", "_csv"))
    merged["diff"] = merged["foreign"] - merged["foreign_csv"]
    return merged[merged["diff"] != 0].reset_index(drop=True)


def stats_with_season(long: pd.DataFrame) -> pd.DataFrame:
    keys = [ta.parse_real_team_key(key) for key in long["team_key"]]
    out = long.copy()
    out.insert(0, "season", [season for season, _team in keys])
    out.insert(1, "team", [team for _season, team in keys])
    return out.drop(columns=["team_key"])


def distribution_rows(values: pd.Series) -> dict[str, float]:
    stats = ta.describe_values(values)
    return {key: round(stats[key], 1) for key in ("最小", "10%", "中央", "90%", "最大")}


def to_markdown(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "（なし）"
    columns = [str(column) for column in frame.columns]
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for row in frame.itertuples(index=False):
        lines.append("| " + " | ".join("" if pd.isna(value) else (f"{value:.1f}" if isinstance(value, float) else str(value)) for value in row) + " |")
    return "\n".join(lines)


def write_summary(path: Path, *, season_counts: pd.DataFrame, check: pd.DataFrame, two_way: pd.DataFrame, foreign_diff: pd.DataFrame,
                  headline: pd.DataFrame, abilities: pd.DataFrame, contact_by_season: pd.DataFrame, cuts: dict[str, dict[str, float]],
                  stats_rows: int) -> None:
    lines = [
        "# 実在球団の比較用データ（build_real_team_reference.py）",
        "",
        "## 件数",
        to_markdown(season_counts),
        "",
        f"球団単位の集計: {stats_rows}行（data/reference/real_team_stats_2022_2026.csv）",
        "",
        "## 人数構成CSV（real_team_composition_2022_2026.csv）との整合チェック",
        f"比べた項目: {', '.join(CONSISTENCY_COLUMNS)}（年版×球団）",
        "",
        f"不一致: {len(check)}件",
        "",
        to_markdown(check),
        "",
    ]
    if not check.empty:
        lines += [
            "### 不一致の理由",
            "不一致はすべて、二刀流の選手（HTML で投手・野手の両方のデータを持つ選手）を含む球団です。",
            "取り込み処理（import_real_powerpro_players.py、変更なし）は名前の class に投手の記号（p・pr・r・rp）だけがある選手を投手とし、",
            "二刀流の class（rpo・pro・pri など）は野手として読みます。人数構成CSVは2022〜2025年版ではこの選手を投手として数え、",
            "2026年版では野手として数えています（CSV 側の作り方の違い）。比較用データは全年版で取り込み処理どおり野手として扱います。",
            "",
            to_markdown(two_way),
            "",
        ]
    lines += [
        "## 外国人数（人数構成CSVの foreign 列との差。外国人数は目安）",
        "判定: 2022・2024・2025年版は外国人一覧（球団＋登録名）、2023年版と一覧で照合できなかった選手は登録名がカタカナのみ、",
        "2026年版は入団経路が「海外・その他」かつ登録名がカタカナのみ。",
        "",
        to_markdown(foreign_diff),
        "",
        "## 査定帯の境界（実在の全選手、役割別の分位点）",
        to_markdown(pd.DataFrame([{"役割": role, **values} for role, values in cuts.items()])),
        "",
        "## 実在60チームの主要指標の分布（年齢系は2026年版の12チーム）",
        to_markdown(headline),
        "",
        "## 球団平均の能力（60チーム）と指示書の参考値",
        "上段が今回の値、（ ）は指示書 6-1 の参考値。",
        "",
        to_markdown(abilities),
        "",
        "## 年版ごとの野手ミート（球団平均の平均）",
        "2022・2023年版と2024年版以降でミートに段差があります（ゲームの仕様変更とみられる）。",
        "",
        to_markdown(contact_by_season),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="実在球団（2022〜2026年版）の比較用データを作ります。")
    parser.add_argument("--zip-2022-2025", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--raw-2026", type=Path, default=DEFAULT_RAW_2026)
    parser.add_argument("--entry-route", type=Path, default=DEFAULT_ENTRY_ROUTE)
    parser.add_argument("--foreign-list", type=Path, default=DEFAULT_FOREIGN_LIST)
    parser.add_argument("--players-output", type=Path, default=real_data.REAL_PLAYERS_PATH)
    parser.add_argument("--stats-output", type=Path, default=real_data.REAL_TEAM_STATS_PATH)
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR, format="%(levelname)s: %(message)s")

    foreign_keys = foreign_list_keys(args.foreign_list)
    entry = load_entry_route(args.entry_route)
    frames, count_rows, two_way_rows = [], [], []
    with tempfile.TemporaryDirectory() as temp:
        folders = extract_seasons(args.zip_2022_2025, Path(temp))
        folders[real_data.AGE_SEASON] = args.raw_2026
        for season, folder in folders.items():
            tables, docs = parse_directory(folder)
            players = decorate_season(tables["players"], season, foreign_keys, entry)
            rows = real_data.attach_real_details(players, tables["specials"], tables["breaking"])
            frame = ta.real_players_to_frame(rows)
            frames.append(frame)
            two_way_rows += [{"年版": season, "球団": team, "選手": name, "class": classes} for team, name, classes in two_way_players(docs)]
            count_rows.append({
                "年版": season, "選手数": len(frame), "投手": int((frame["role"] == "投手").sum()), "野手": int((frame["role"] != "投手").sum()),
                "球団数": frame["team"].nunique(), "取り込み失敗": len(tables["failed"]), "入力エラー": len(tables["input_errors"]),
                "外国人": int(frame["is_foreign"].sum()), "年齢あり": int(frame["age"].notna().sum()),
            })
            print(f"{season}: {len(frame)}人（{frame['team'].nunique()}球団）", flush=True)
    real = pd.concat(frames, ignore_index=True)
    cuts = ta.rating_cuts_from_frame(real)
    categorized = ta.assign_categories(real, cuts)
    long = ta.team_long_stats(categorized, ta.REAL_AXES)
    stats = pd.concat([ta.rating_cut_rows(cuts), stats_with_season(long)], ignore_index=True)

    args.players_output.parent.mkdir(parents=True, exist_ok=True)
    real.to_csv(args.players_output, index=False, encoding="utf-8-sig")
    args.stats_output.parent.mkdir(parents=True, exist_ok=True)
    stats.to_csv(args.stats_output, index=False, encoding="utf-8-sig", lineterminator="\n")

    composition = pd.read_csv(COMPOSITION_PATH, encoding="utf-8-sig")
    counts = composition_counts(real)
    check = consistency_check(counts, composition)
    foreign_diff = foreign_differences(counts, composition).rename(columns={"foreign": "判定した外国人", "foreign_csv": "CSV", "diff": "差"})
    two_way = pd.DataFrame(two_way_rows)
    headline_rows = []
    for metric in ta.HEADLINE_METRICS:
        values = long[(long["axis"] == ta.AXIS_HEADLINE) & (long["metric"] == metric)]["value"]
        headline_rows.append({"指標": metric, "チーム数": int(values.count()), **distribution_rows(values)})
    ability_rows = []
    for (role, ability), expected in EXPECTED_TEAM_ABILITY.items():
        values = long[(long["axis"] == ta.AXIS_ROLE) & (long["group"] == role) & (long["metric"] == ability)]["value"]
        built = distribution_rows(values)
        ability_rows.append({"能力（球団内平均）": f"{role} {ability}", **{key: f"{built[key]:.1f}（{exp:.1f}）" for key, exp in zip(built, expected)}})
    contact = long[(long["axis"] == ta.AXIS_ROLE) & (long["group"] == "野手") & (long["metric"] == "ミート")].copy()
    contact["season"] = [ta.parse_real_team_key(key)[0] for key in contact["team_key"]]
    contact_by_season = contact.groupby("season")["value"].agg(["mean", "min", "max"]).reset_index().rename(columns={"season": "年版", "mean": "平均", "min": "最小", "max": "最大"})
    args.report_dir.mkdir(parents=True, exist_ok=True)
    write_summary(
        args.report_dir / "summary.md", season_counts=pd.DataFrame(count_rows), check=check, two_way=two_way, foreign_diff=foreign_diff,
        headline=pd.DataFrame(headline_rows), abilities=pd.DataFrame(ability_rows), contact_by_season=contact_by_season, cuts=cuts, stats_rows=len(stats),
    )
    print(f"選手単位: {args.players_output}（{len(real)}行）")
    print(f"球団単位の集計: {args.stats_output}（{len(stats)}行）")
    print(f"整合チェックの不一致: {len(check)}件、外国人数の差: {len(foreign_diff)}球団")
    print(f"レポート: {args.report_dir / 'summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
