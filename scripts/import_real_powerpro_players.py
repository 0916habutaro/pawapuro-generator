from __future__ import annotations

import argparse
import html
import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

LOGGER = logging.getLogger("real_powerpro_import")
V_CLASS_RE = re.compile(r"\bv(\d{2,3})\b", re.I)
TAG_RE = re.compile(r"<[^>]+>")
CELL_RE = re.compile(r"<(?:td|th)\b([^>]*)>(.*?)</(?:td|th)>", re.I | re.S)
ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.I | re.S)

DIRECTION_NAMES = {
    "1": "スライダー方向",
    "2": "カーブ方向",
    "3": "フォーク方向",
    "4": "シンカー方向",
    "5": "シュート方向",
    "6": "特殊方向6",
    "7": "特殊方向7",
    "8": "特殊方向8",
    "9": "特殊方向9",
}
PLAYER_COLUMNS = [
    "team", "name", "number", "role", "throws_bats", "main_position",
    "sub_positions", "pitcher_roles", "usage", "top_speed", "control", "stamina",
    "trajectory", "contact", "power", "run_speed", "arm_strength", "fielding", "catching",
]
BREAKING_BALL_COLUMNS = [
    "source", "team", "name", "direction_code", "direction", "slot", "pitch_type", "movement", "source_class", "status",
]
SPECIAL_COLUMNS = ["source", "team", "name", "special", "special_kind"]
UNKNOWN_CLASS_COLUMNS = ["source", "team", "name", "source_class", "detail"]
UNKNOWN_BREAKING_COLUMNS = ["source", "team", "name", "source_class", "slot", "movement", "detail"]
FAILED_PLAYER_COLUMNS = ["source", "team", "name", "reason", "detail"]

LABEL_ALIASES = {
    "球団名": "team", "球団": "team", "チーム": "team",
    "選手名": "name", "名前": "name", "氏名": "name",
    "背番号": "number", "番号": "number",
    "投手野手": "role", "区分": "role", "種別": "role",
    "投打": "throws_bats", "利き腕": "throws_bats",
    "主ポジション": "main_position", "ポジション": "main_position",
    "サブポジション": "sub_positions", "サブポジ": "sub_positions",
    "投手起用適正": "pitcher_roles", "適正": "pitcher_roles",
    "起用法": "usage", "役割": "usage",
    "球速": "top_speed", "最高球速": "top_speed",
    "コントロール": "control", "コン": "control",
    "スタミナ": "stamina", "スタ": "stamina",
    "弾道": "trajectory", "ミート": "contact", "パワー": "power", "走力": "run_speed",
    "肩力": "arm_strength", "守備力": "fielding", "守備": "fielding", "捕球": "catching",
    "特殊能力": "specials", "特能": "specials", "ランク系特殊能力": "ranked_specials",
    "変化球": "breaking_balls", "球種": "breaking_balls",
}


@dataclass
class SourceDoc:
    source_name: str
    html_text: str
    css_texts: dict[str, str] = field(default_factory=dict)


@dataclass
class ParseResult:
    players: list[dict[str, str]] = field(default_factory=list)
    breaking: list[dict[str, str]] = field(default_factory=list)
    specials: list[dict[str, str]] = field(default_factory=list)
    unknown_classes: list[dict[str, str]] = field(default_factory=list)
    unknown_breaking: list[dict[str, str]] = field(default_factory=list)
    failed_players: list[dict[str, str]] = field(default_factory=list)


def clean_text(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " / ", value, flags=re.I)
    value = TAG_RE.sub(" ", value)
    return re.sub(r"\s+", " ", html.unescape(value).replace("\xa0", " ")).strip()


def normalize_label(value: str) -> str:
    return re.sub(r"[\s:：/／・_-]+", "", value)


def to_int(value: str) -> int | None:
    m = re.search(r"\d+", value or "")
    return int(m.group(0)) if m else None


def split_values(value: str) -> list[str]:
    return [v.strip() for v in re.split(r"[,、/／|｜\n]+", value or "") if v.strip()]


def read_sources(input_dir: Path) -> tuple[list[SourceDoc], list[dict[str, str]]]:
    docs: list[SourceDoc] = []
    failures: list[dict[str, str]] = []
    for path in sorted(input_dir.glob("*.zip")):
        try:
            with zipfile.ZipFile(path) as zf:
                html_names = [n for n in zf.namelist() if n.lower().endswith((".html", ".htm", ".mhtml", ".mht"))]
                css_names = [n for n in zf.namelist() if n.lower().endswith(".css")]
                css_texts = {n: zf.read(n).decode("utf-8", errors="ignore") for n in css_names}
                if not html_names:
                    failures.append({"source": path.name, "team": "", "name": "", "reason": "html_not_found", "detail": "ZIP内にHTML/MHTMLがありません"})
                for name in html_names:
                    try:
                        docs.append(SourceDoc(f"{path.name}:{name}", zf.read(name).decode("utf-8", errors="ignore"), css_texts))
                    except Exception as exc:  # noqa: BLE001 - diagnostics CSVに詳細を残す
                        failures.append({"source": f"{path.name}:{name}", "team": "", "name": "", "reason": "html_read_failed", "detail": f"{type(exc).__name__}: {exc}"})
        except Exception as exc:  # noqa: BLE001 - diagnostics CSVに詳細を残す
            failures.append({"source": path.name, "team": "", "name": "", "reason": "zip_read_failed", "detail": f"{type(exc).__name__}: {exc}"})
    for path in sorted(input_dir.glob("*.htm*")) + sorted(input_dir.glob("*.mht*")):
        try:
            css_texts = {str(css): css.read_text(encoding="utf-8", errors="ignore") for css in input_dir.glob("**/*.css")}
            docs.append(SourceDoc(path.name, path.read_text(encoding="utf-8", errors="ignore"), css_texts))
        except Exception as exc:  # noqa: BLE001 - diagnostics CSVに詳細を残す
            failures.append({"source": path.name, "team": "", "name": "", "reason": "html_read_failed", "detail": f"{type(exc).__name__}: {exc}"})
    return docs, failures


def parse_rows(body: str) -> list[list[tuple[str, str]]]:
    rows = []
    for row in ROW_RE.findall(body):
        cells = [(attrs, cell) for attrs, cell in CELL_RE.findall(row)]
        if cells:
            rows.append(cells)
    return rows


def row_to_record(cells: list[tuple[str, str]], current_team: str) -> tuple[dict[str, str], str]:
    record: dict[str, str] = {"team": current_team}
    if len(cells) == 2:
        label = normalize_label(clean_text(cells[0][1]))
        key = LABEL_ALIASES.get(label)
        if key:
            record[key] = clean_text(cells[1][1])
    else:
        texts = [clean_text(c[1]) for c in cells]
        headers = [normalize_label(t) for t in texts]
        if any(h in LABEL_ALIASES for h in headers):
            return {}, current_team
        # 横持ち表や最小fixture向けのフォールバック。
        keys = ["number", "name", "role", "throws_bats", "main_position", "sub_positions", "pitcher_roles", "usage", "top_speed", "control", "stamina", "trajectory", "contact", "power", "run_speed", "arm_strength", "fielding", "catching", "specials"]
        for key, text in zip(keys, texts):
            record[key] = text
    if record.get("team"):
        current_team = record["team"]
    return record, current_team


def parse_cards(doc: SourceDoc) -> ParseResult:
    result = ParseResult()
    current: dict[str, str] = {}
    current_team = "unknown"
    css_classes = set(V_CLASS_RE.findall("\n".join(doc.css_texts.values())))

    for cells in parse_rows(doc.html_text):
        rec, current_team = row_to_record(cells, current_team)
        if rec.get("name") and current.get("name"):
            flush_player(current, result, doc.source_name)
            current = {"team": current_team}
        current.update({k: v for k, v in rec.items() if v})
        result.breaking.extend(parse_breaking_ball_row(cells, current, css_classes, doc.source_name, result))
    if current.get("name"):
        flush_player(current, result, doc.source_name)
    elif current and any(k != "team" for k in current):
        result.failed_players.append({"source": doc.source_name, "team": current.get("team", ""), "name": current.get("name", ""), "reason": "name_missing", "detail": str(current)})
    return result


def flush_player(current: dict[str, str], result: ParseResult, source: str) -> None:
    row = {col: current.get(col, "") for col in PLAYER_COLUMNS}
    row["source"] = source
    missing = [col for col in ("name", "role") if not row.get(col)]
    if missing:
        result.failed_players.append({"source": source, "team": row.get("team", ""), "name": row.get("name", ""), "reason": "required_field_missing", "detail": ",".join(missing)})
    for col in ["number", "top_speed", "control", "stamina", "trajectory", "contact", "power", "run_speed", "arm_strength", "fielding", "catching"]:
        val = to_int(str(row.get(col, "")))
        row[col] = val if val is not None else ""
    result.players.append(row)
    for key, kind in [("specials", "normal"), ("ranked_specials", "rank")]:
        for sp in split_values(current.get(key, "")):
            result.specials.append({"source": source, "team": row["team"], "name": row["name"], "special": sp, "special_kind": kind})


def parse_breaking_ball_row(cells: list[tuple[str, str]], current: dict[str, str], css_classes: set[str], source: str, result: ParseResult) -> list[dict[str, str]]:
    out = []
    row_html = " ".join(cell for _, cell in cells)
    matches = V_CLASS_RE.findall(row_html)
    if not matches:
        return out
    texts = [clean_text(c[1]) for c in cells]
    pitch_names = [t for t in texts if t and not V_CLASS_RE.search(t) and normalize_label(t) not in LABEL_ALIASES]
    for code in matches:
        source_class = f"v{code}"
        if code not in css_classes:
            detail = "ball.css等のCSSにclass定義が見つかりません"
            result.unknown_classes.append({"source": source, "team": current.get("team", "unknown"), "name": current.get("name", "unknown"), "source_class": source_class, "detail": detail})
            LOGGER.warning("CSSに定義がない変化球class: %s (%s / %s / %s)", source_class, current.get("name", "unknown"), current.get("team", "unknown"), source)
        direction_code = code[0]
        amounts = list(code[1:])
        for idx, amount in enumerate(amounts, start=1):
            pitch_type = pitch_names[idx - 1] if idx - 1 < len(pitch_names) else "unknown"
            status = "ok" if pitch_type != "unknown" else "unknown"
            row = {
                "source": source, "team": current.get("team", "unknown"), "name": current.get("name", "unknown"),
                "direction_code": direction_code, "direction": DIRECTION_NAMES.get(direction_code, "unknown"),
                "slot": idx, "pitch_type": pitch_type, "movement": int(amount), "source_class": source_class,
                "status": status,
            }
            if status == "unknown":
                result.unknown_breaking.append({"source": source, "team": row["team"], "name": row["name"], "source_class": source_class, "slot": idx, "movement": int(amount), "detail": "同一行から球種名を特定できません"})
            out.append(row)
    return out


def combine_results(results: list[ParseResult], source_failures: list[dict[str, str]]) -> ParseResult:
    combined = ParseResult(failed_players=list(source_failures))
    for result in results:
        combined.players.extend(result.players)
        combined.breaking.extend(result.breaking)
        combined.specials.extend(result.specials)
        combined.unknown_classes.extend(result.unknown_classes)
        combined.unknown_breaking.extend(result.unknown_breaking)
        combined.failed_players.extend(result.failed_players)
    return combined


def write_outputs(result: ParseResult, output_dir: Path, excel: bool) -> dict[str, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)
    dfs = {
        "players": pd.DataFrame(result.players),
        "breaking_balls": pd.DataFrame(result.breaking),
        "special_abilities": pd.DataFrame(result.specials),
        "unknown_classes": pd.DataFrame(result.unknown_classes),
        "unknown_breaking_balls": pd.DataFrame(result.unknown_breaking),
        "failed_players": pd.DataFrame(result.failed_players),
    }
    required_columns = {
        "players": PLAYER_COLUMNS + ["source"],
        "breaking_balls": BREAKING_BALL_COLUMNS,
        "special_abilities": SPECIAL_COLUMNS,
        "unknown_classes": UNKNOWN_CLASS_COLUMNS,
        "unknown_breaking_balls": UNKNOWN_BREAKING_COLUMNS,
        "failed_players": FAILED_PLAYER_COLUMNS,
    }
    for name, columns in required_columns.items():
        if dfs[name].empty:
            dfs[name] = pd.DataFrame(columns=columns)
        else:
            dfs[name] = dfs[name].reindex(columns=columns)
    dfs["position_summary"] = summarize(dfs["players"], "main_position")
    dfs["pitcher_role_summary"] = summarize(dfs["players"], "pitcher_roles")
    dfs["breaking_ball_summary"] = summarize(dfs["breaking_balls"], "pitch_type", numeric="movement")
    for name, df in dfs.items():
        df.to_csv(output_dir / f"{name}.csv", index=False, encoding="utf-8-sig")
    if excel:
        with pd.ExcelWriter(output_dir / "real_powerpro_players.xlsx") as writer:
            for name, df in dfs.items():
                df.to_excel(writer, sheet_name=name[:31], index=False)
    return dfs


def summarize(df: pd.DataFrame, key: str, numeric: str | None = None) -> pd.DataFrame:
    if df.empty or key not in df.columns:
        return pd.DataFrame(columns=[key, "count"])
    group = df.fillna("").groupby(key, dropna=False)
    out = group.size().reset_index(name="count")
    if numeric and numeric in df.columns:
        avg = group[numeric].mean().reset_index(name=f"avg_{numeric}")
        out = out.merge(avg, on=key, how="left")
    return out.sort_values("count", ascending=False)


def print_smoke_summary(docs: list[SourceDoc], dfs: dict[str, pd.DataFrame], output_dir: Path) -> None:
    players = dfs["players"]
    roles = players["role"].fillna("") if "role" in players else pd.Series(dtype=str)
    pitcher_count = int(roles.str.contains("投手", na=False).sum())
    fielder_count = int(roles.str.contains("野手", na=False).sum())
    print("=== 実在パワプロ選手データ取り込みサマリー ===")
    print(f"入力HTML数: {len(docs)}")
    print(f"選手数: {len(players)}")
    print(f"投手数: {pitcher_count}")
    print(f"野手数: {fielder_count}")
    print(f"変化球数: {len(dfs['breaking_balls'])}")
    print(f"特殊能力数: {len(dfs['special_abilities'])}")
    print(f"未解釈class数: {len(dfs['unknown_classes'])} -> {output_dir / 'unknown_classes.csv'}")
    print(f"unknown変化球数: {len(dfs['unknown_breaking_balls'])} -> {output_dir / 'unknown_breaking_balls.csv'}")
    print(f"取得失敗/要確認選手数: {len(dfs['failed_players'])} -> {output_dir / 'failed_players.csv'}")
    print(f"出力先: {output_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(description="パワプロ実在選手HTML/ZIPをCSV集計へ変換します。")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--excel", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(levelname)s: %(message)s")

    docs, source_failures = read_sources(args.input_dir)
    if not docs and not source_failures:
        LOGGER.error("入力HTML/ZIPが見つかりません: %s", args.input_dir)
        return 1
    results = [parse_cards(doc) for doc in docs]
    combined = combine_results(results, source_failures)
    dfs = write_outputs(combined, args.output_dir, args.excel)
    print_smoke_summary(docs, dfs, args.output_dir)
    LOGGER.info("出力完了: players=%d breaking_balls=%d special_abilities=%d output=%s", len(combined.players), len(combined.breaking), len(combined.specials), args.output_dir)
    return 0 if docs else 1


if __name__ == "__main__":
    raise SystemExit(main())
