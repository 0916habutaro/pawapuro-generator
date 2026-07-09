from __future__ import annotations

import argparse
import html
import logging
import re
import unicodedata
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
}
ALLOWED_PITCHES_BY_DIRECTION_RIGHT = {
    "1": {"スライダー", "Hスライダー", "カットボール"},
    "2": {"カーブ", "スローカーブ", "ドロップカーブ", "スラーブ", "ナックルカーブ", "パワーカーブ", "Dスライダー"},
    "3": {"フォーク", "パーム", "チェンジアップ", "Vスライダー", "SFF", "ナックル"},
    "4": {"シンカー", "Hシンカー", "サークルチェンジ", "シンキングスプリット", "ファストチェンジ"},
    "5": {"シュート", "Hシュート", "シンキングツーシーム"},
}
ALLOWED_PITCHES_BY_DIRECTION_LEFT = {
    "1": {"スライダー", "Hスライダー", "カットボール"},
    "2": {"カーブ", "スローカーブ", "ドロップカーブ", "スラーブ", "ナックルカーブ", "パワーカーブ", "Dスライダー"},
    "3": {"フォーク", "パーム", "チェンジアップ", "Vスライダー", "SFF", "ナックル"},
    "4": {"スクリュー", "サークルチェンジ", "シンキングスプリット", "ファストチェンジ"},
    "5": {"シュート", "Hシュート", "シンキングツーシーム"},
}
SECOND_FASTBALL_TYPES = {"ツーシームファスト", "ムービングファスト", "超スローボール"}
FIXED_FASTBALL_TYPES = {"ストレート"}
CANONICAL_PITCH_TYPES = {"スクリュー": "シンカー"}
PLAYER_COLUMNS = [
    "team", "name", "number", "role", "throws_bats", "main_position",
    "sub_positions", "pitcher_roles", "usage", "top_speed", "control", "stamina",
    "trajectory", "contact", "power", "run_speed", "arm_strength", "fielding", "catching",
]
BREAKING_BALL_COLUMNS = [
    "source", "team", "name", "throws_bats", "direction_code", "direction", "slot", "raw_pitch_type", "pitch_type", "canonical_pitch_type", "movement", "source_class", "status", "kind", "raw_text", "normalized_text", "raw_neighbor_text", "detail",
]
SPECIAL_COLUMNS = ["source", "team", "name", "special", "special_kind"]
UNKNOWN_CLASS_COLUMNS = ["source", "team", "name", "source_class", "detail"]
UNKNOWN_BREAKING_COLUMNS = ["source", "team", "name", "source_class", "slot", "movement", "detail", "raw_text", "normalized_text"]
FAILED_PLAYER_COLUMNS = ["source", "team", "name", "reason", "detail"]
INPUT_ERROR_COLUMNS = ["source", "reason", "detail"]


POSITION_ALIASES = {
    "捕": "捕手", "捕手": "捕手", "キャッチャー": "捕手",
    "一": "一塁手", "一塁": "一塁手", "一塁手": "一塁手", "ファースト": "一塁手",
    "二": "二塁手", "二塁": "二塁手", "二塁手": "二塁手", "セカンド": "二塁手",
    "三": "三塁手", "三塁": "三塁手", "三塁手": "三塁手", "サード": "三塁手",
    "遊": "遊撃手", "遊撃": "遊撃手", "遊撃手": "遊撃手", "ショート": "遊撃手",
    "外": "外野手", "外野": "外野手", "外野手": "外野手",
    "左": "左翼手", "左翼": "左翼手", "左翼手": "左翼手", "レフト": "左翼手",
    "中堅": "中堅手", "中堅手": "中堅手", "センター": "中堅手",
    "右": "右翼手", "右翼": "右翼手", "右翼手": "右翼手", "ライト": "右翼手",
}
POSITION_PATTERN = re.compile("捕手|一塁手|二塁手|三塁手|遊撃手|外野手|左翼手|中堅手|右翼手|キャッチャー|ファースト|セカンド|サード|ショート|レフト|センター|ライト|捕|一|二|三|遊|外")
PITCH_TYPE_NAMES = [
    "ストレート", "ツーシームファスト", "ムービングファスト", "超スローボール",
    "スライダー", "Hスライダー", "カットボール",
    "カーブ", "スローカーブ", "ドロップカーブ", "スラーブ", "ナックルカーブ", "パワーカーブ", "Dスライダー",
    "フォーク", "パーム", "チェンジアップ", "Vスライダー", "SFF", "ナックル",
    "シンカー", "Hシンカー", "スクリュー", "サークルチェンジ", "シンキングスプリット", "ファストチェンジ",
    "シュート", "Hシュート", "シンキングツーシーム",
]
PITCH_TYPE_RE = re.compile("|".join(re.escape(name) for name in sorted(PITCH_TYPE_NAMES, key=len, reverse=True)))


GREEN_USAGE_SPECIALS = {
    "積極打法",
    "慎重打法",
    "積極走塁",
    "積極盗塁",
    "積極守備",
    "強振多用",
    "ミート多用",
    "速球中心",
    "変化球中心",
    "テンポ○",
    "選球眼",
    "チームプレイ○",
    "チームプレイ×",
}

USAGE_HEADER_LABELS = {"起用法"}

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
    encoding: str = ""
    css_texts: dict[str, str] = field(default_factory=dict)


@dataclass
class ParseResult:
    players: list[dict[str, str]] = field(default_factory=list)
    breaking: list[dict[str, str]] = field(default_factory=list)
    specials: list[dict[str, str]] = field(default_factory=list)
    unknown_classes: list[dict[str, str]] = field(default_factory=list)
    unknown_breaking: list[dict[str, str]] = field(default_factory=list)
    failed_players: list[dict[str, str]] = field(default_factory=list)
    input_errors: list[dict[str, str]] = field(default_factory=list)


def clean_text(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " / ", value, flags=re.I)
    value = TAG_RE.sub(" ", value)
    return re.sub(r"\s+", " ", html.unescape(value).replace("\xa0", " ")).strip()



def normalize_pitch_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "")


def allowed_pitches_for(direction_code: str, throws_bats: str) -> set[str]:
    is_left = str(throws_bats).startswith("左投")
    table = ALLOWED_PITCHES_BY_DIRECTION_LEFT if is_left else ALLOWED_PITCHES_BY_DIRECTION_RIGHT
    return table.get(direction_code, set())


def is_pitch_allowed_for_direction(direction_code: str, pitch_type: str, throws_bats: str) -> bool:
    return pitch_type in allowed_pitches_for(direction_code, throws_bats)


def canonical_pitch_type(pitch_type: str) -> str:
    return CANONICAL_PITCH_TYPES.get(pitch_type, pitch_type)

def normalize_label(value: str) -> str:
    return re.sub(r"[\s:：/／・_-]+", "", value)


def to_int(value: str) -> int | None:
    m = re.search(r"\d+", value or "")
    return int(m.group(0)) if m else None


def split_values(value: str) -> list[str]:
    return [v.strip() for v in re.split(r"[,、/／|｜\n]+", value or "") if v.strip()]


def meta_charset(raw: bytes) -> str | None:
    head = raw[:4096].decode("ascii", errors="ignore")
    m = re.search(r"<meta[^>]+charset=[\"']?([A-Za-z0-9_\-]+)", head, re.I)
    if m:
        enc = m.group(1).lower().replace("shift-jis", "shift_jis")
        return "cp932" if enc in {"x-sjis", "windows-31j", "ms932"} else enc
    return None


def mojibake_score(text: str) -> int:
    return sum(text.count(ch) for ch in "�□■?｣｣") + len(re.findall(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text))


def japanese_score(text: str) -> int:
    return len(re.findall(r"[ぁ-んァ-ヶ一-龠ー]", text))


def decode_html(raw: bytes) -> tuple[str, str, str | None]:
    candidates: list[str] = []
    meta = meta_charset(raw)
    if meta:
        candidates.append(meta)
    candidates.extend(["cp932", "shift_jis", "utf-8", "utf-8-sig"])
    seen: set[str] = set()
    best: tuple[int, int, str, str] | None = None
    errors: list[str] = []
    for enc in candidates:
        if enc in seen:
            continue
        seen.add(enc)
        try:
            text = raw.decode(enc)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{enc}: {type(exc).__name__}: {exc}")
            continue
        score = japanese_score(text)
        bad = mojibake_score(text)
        candidate = (score - bad * 20, score, enc, text)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
        if score >= 20 and bad <= max(5, score // 50):
            return text, enc, None
    if best and best[1] >= 5:
        return best[3], best[2], "文字コード判定の妥当性が低い可能性があります: " + "; ".join(errors)
    return raw.decode("utf-8", errors="replace"), "utf-8-replace", "HTMLを妥当にデコードできません: " + "; ".join(errors)


def decode_text_file(raw: bytes) -> str:
    for enc in ("utf-8", "cp932", "shift_jis"):
        try:
            return raw.decode(enc)
        except Exception:  # noqa: BLE001
            pass
    return raw.decode("utf-8", errors="ignore")



def decode_zip_member_name(name: str) -> str:
    try:
        return name.encode("cp437").decode("cp932")
    except Exception:  # noqa: BLE001
        return name

def read_sources(input_dir: Path) -> tuple[list[SourceDoc], list[dict[str, str]]]:
    docs: list[SourceDoc] = []
    failures: list[dict[str, str]] = []
    for path in sorted(input_dir.glob("*.zip")):
        try:
            with zipfile.ZipFile(path) as zf:
                html_names = [n for n in zf.namelist() if n.lower().endswith((".html", ".htm", ".mhtml", ".mht"))]
                css_names = [n for n in zf.namelist() if n.lower().endswith(".css")]
                css_texts = {decode_zip_member_name(n): decode_text_file(zf.read(n)) for n in css_names}
                if not html_names:
                    failures.append({"source": path.name, "reason": "html_not_found", "detail": "ZIP内にHTML/MHTMLがありません"})
                for name in html_names:
                    try:
                        text, enc, warn = decode_html(zf.read(name))
                        docs.append(SourceDoc(f"{path.name}:{decode_zip_member_name(name)}", text, enc, css_texts))
                        if warn:
                            failures.append({"source": f"{path.name}:{decode_zip_member_name(name)}", "reason": "decode_warning", "detail": warn})
                    except Exception as exc:  # noqa: BLE001
                        failures.append({"source": f"{path.name}:{decode_zip_member_name(name)}", "reason": "html_read_failed", "detail": f"{type(exc).__name__}: {exc}"})
        except Exception as exc:  # noqa: BLE001
            failures.append({"source": path.name, "reason": "zip_read_failed", "detail": f"{type(exc).__name__}: {exc}"})
    for path in sorted(input_dir.glob("*.htm*")) + sorted(input_dir.glob("*.mht*")):
        try:
            css_texts = {str(css): decode_text_file(css.read_bytes()) for css in input_dir.glob("**/*.css")}
            text, enc, warn = decode_html(path.read_bytes())
            docs.append(SourceDoc(path.name, text, enc, css_texts))
            if warn:
                failures.append({"source": path.name, "reason": "decode_warning", "detail": warn})
        except Exception as exc:  # noqa: BLE001
            failures.append({"source": path.name, "reason": "html_read_failed", "detail": f"{type(exc).__name__}: {exc}"})
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



def extract_class_text(block: str, class_name: str) -> str:
    m = re.search(rf'<b\b[^>]*class="[^"]*\b{re.escape(class_name)}\b[^"]*"[^>]*>(.*?)</b>', block, re.I | re.S)
    return clean_text(m.group(1)) if m else ""


def extract_b_class_blocks(block: str, class_name: str) -> list[str]:
    """指定classを持つ <b> の内側HTMLを、ネストした <b> を考慮して取得します。"""
    start_re = re.compile(rf'<b\b[^>]*class="[^"]*\b{re.escape(class_name)}\b[^"]*"[^>]*>', re.I)
    tag_re = re.compile(r"</?b\b[^>]*>", re.I)
    blocks: list[str] = []
    search_pos = 0
    while True:
        start = start_re.search(block, search_pos)
        if not start:
            break
        depth = 1
        inner_start = start.end()
        for tag in tag_re.finditer(block, inner_start):
            if tag.group(0).lower().startswith("</"):
                depth -= 1
                if depth == 0:
                    blocks.append(block[inner_start:tag.start()])
                    search_pos = tag.end()
                    break
            else:
                depth += 1
        else:
            search_pos = start.end()
    return blocks


def extract_nested_b_texts(block: str) -> list[str]:
    values: list[str] = []
    for text in re.findall(r"<b\b[^>]*>([^<>]*)</b>", block, re.I | re.S):
        cleaned = clean_text(text)
        if cleaned and cleaned not in values:
            values.append(cleaned)
    if not values:
        fallback = clean_text(block)
        for value in split_values(fallback):
            if value and value not in values:
                values.append(value)
    return values


def parse_usage_block_specials(block: str) -> tuple[list[str], list[str]]:
    """class=y の起用法ブロックから、緑特と起用法を分離します。"""
    green: list[str] = []
    usage: list[str] = []
    for usage_block in extract_b_class_blocks(block, "y"):
        for value in extract_nested_b_texts(usage_block):
            if value in USAGE_HEADER_LABELS:
                continue
            if value in GREEN_USAGE_SPECIALS:
                if value not in green:
                    green.append(value)
            elif value not in usage:
                usage.append(value)
    return green, usage


def html_text_with_attrs(block: str) -> str:
    attr_texts = re.findall(r'\b(?:alt|title|aria-label)=["\']([^"\']+)["\']', block, re.I)
    return clean_text(block + " " + " ".join(attr_texts))


def normalize_position(value: str) -> str:
    return POSITION_ALIASES.get(value.strip(), value.strip())


def extract_positions_from_text(value: str) -> list[str]:
    found: list[str] = []
    for token in POSITION_PATTERN.findall(value or ""):
        pos = normalize_position(token)
        if pos and pos not in found:
            found.append(pos)
    return found



def extract_fielder_positions_from_ability_block(block: str) -> list[str]:
    """野手能力ブロック内の c8 w から守備位置略称を取得します。"""
    class_re = r'(?=[^"]*\bc8\b)(?=[^"]*\bw\b)[^"]*'
    for m in re.finditer(rf'<b\b[^>]*class="{class_re}"[^>]*>(.*?)</b>\s*</b>', block, re.I | re.S):
        inner = m.group(1)
        nested = re.findall(r'<b\b[^>]*>(.*?)</b>', inner, re.I | re.S)
        candidates = [clean_text(value) for value in nested if clean_text(value)]
        candidates.append(clean_text(inner))
        for candidate in reversed(candidates):
            positions = extract_positions_from_text(candidate)
            if positions:
                return positions
    m = re.search(rf'<b\b[^>]*class="{class_re}"[^>]*>(.*?)(?=<b\b[^>]*class=|</p>|<a\s+name=|\Z)', block, re.I | re.S)
    if m:
        return extract_positions_from_text(clean_text(m.group(1)))
    return []

def extract_pitch_names(value: str) -> list[str]:
    names: list[str] = []
    for name in PITCH_TYPE_RE.findall(normalize_pitch_text(value or "")):
        if name not in names:
            names.append(name)
    if names:
        return names
    cleaned = re.sub(r"v\d{2,3}|\d+|変化球|球種|方向|第[一二１２]球種|[：:]", " ", value or "", flags=re.I)
    return [v for v in split_values(cleaned.replace(" ", "、")) if japanese_score(v) > 0]


def inner_by_id(block: str, tag_id: str) -> str:
    m = re.search(rf'<b\b[^>]*id="{re.escape(tag_id)}"[^>]*>(.*?)(?=<b\b[^>]*id="|</p>|<a\s+name=|\Z)', block, re.I | re.S)
    return m.group(1) if m else ""


def parse_real_blocks(doc: SourceDoc) -> ParseResult:
    result = ParseResult()
    team = "unknown"
    title = re.search(r"<title>(.*?)</title>", doc.html_text, re.I | re.S)
    if title:
        parts = [x.strip() for x in clean_text(title.group(1)).split("｜") if x.strip()]
        if len(parts) >= 2:
            team = parts[1]
    anchors = list(re.finditer(r'<a\s+name="?(\d+)"?\s*>', doc.html_text, re.I))
    if len(anchors) < 10:
        return result
    for i, a in enumerate(anchors):
        num_id = a.group(1)
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(doc.html_text)
        block = doc.html_text[a.start():end]
        name_m = re.search(r'<b\b[^>]*class="([^"]*\bnm\b[^"]*)"[^>]*>(.*?)</b>', block, re.I | re.S)
        if not name_m:
            continue
        name = clean_text(name_m.group(2))
        nm_classes = name_m.group(1).lower().split()
        role = "投手" if any(c in {"p", "pr", "r", "rp"} for c in nm_classes) else "野手"
        row: dict[str, str] = {"team": team, "name": name, "number": extract_class_text(block, "se"), "role": role}
        field = inner_by_id(block, f"pf{num_id}") or inner_by_id(block, f"bf{num_id}")
        ft = clean_text(field)
        tb = re.search(r"[左右]投[左右両]打", ft)
        row["throws_bats"] = tb.group(0) if tb else ""
        ability_block = inner_by_id(block, f"p{num_id}") if role == "投手" else inner_by_id(block, f"b{num_id}")
        posblock = inner_by_id(block, f"pr{num_id}") if role == "投手" else inner_by_id(block, f"br{num_id}")
        post = clean_text(posblock)
        if role == "投手":
            m = re.search(r"(先|中|抑|先中|中抑|先中抑)+", post)
            row["main_position"] = "投手"
            row["pitcher_roles"] = m.group(0) if m else ""
        else:
            detail_block = inner_by_id(block, f"d{num_id}")
            positions = (
                extract_fielder_positions_from_ability_block(ability_block)
                or extract_fielder_positions_from_ability_block(detail_block)
                or extract_positions_from_text(post)
                or extract_positions_from_text(html_text_with_attrs(posblock))
            )
            row["main_position"] = positions[0] if positions else ""
            row["sub_positions"] = ";".join(positions[1:])
        vals = [clean_text(x) for x in re.findall(r'<(?:b|i)\b[^>]*>(\d+)</(?:b|i)>', ability_block, re.I | re.S)]
        if role == "投手":
            for key, val in zip(["top_speed", "control", "stamina"], vals[:3]): row[key] = val
        else:
            for key, val in zip(["trajectory", "contact", "power", "run_speed", "arm_strength", "fielding", "catching"], vals[:7]): row[key] = val
        current = row.copy()
        for bb in parse_breaking_from_block(ability_block, current, doc.source_name, result):
            result.breaking.append(bb)
        for sf in parse_second_fastballs_from_block(ability_block, current, doc.source_name):
            result.breaking.append(sf)
        specials_block = (inner_by_id(block, f"pa{num_id}") if role == "投手" else inner_by_id(block, f"ba{num_id}"))
        ranked = [clean_text(a + b) for a, b in re.findall(r'<b\b[^>]*class="[^"]*[PNM][^"]*"[^>]*>\s*<b>(.*?)</b>\s*<b>(.*?)</b>', specials_block, re.I | re.S)]
        normals = [clean_text(x) for x in re.findall(r'<b\b[^>]*class="[^"]*[PNM][^"]*"[^>]*>([^<][^<>]*?)</b>', specials_block, re.I | re.S)]
        green_specials, usage_values = parse_usage_block_specials(specials_block)
        current["ranked_specials"] = "、".join(ranked)
        current["specials"] = "、".join([n for n in normals if n not in {"起用法"}])
        current["green_specials"] = "、".join(green_specials)
        current["usage_specials"] = "、".join(usage_values)
        if usage_values:
            current["usage"] = "、".join([*split_values(current.get("usage", "")), *usage_values])
        flush_player(current, result, doc.source_name)
    return result



def classify_pitch(direction_code: str, pitch_type: str, throws_bats: str) -> tuple[str, str]:
    if pitch_type in FIXED_FASTBALL_TYPES:
        return "excluded_fixed_fastball", "fixed_fastball"
    if pitch_type in SECOND_FASTBALL_TYPES:
        return "second_fastball", "second_fastball"
    if pitch_type == "unknown":
        return "unknown", "unknown"
    if is_pitch_allowed_for_direction(direction_code, pitch_type, throws_bats):
        return "ok", "breaking"
    return "invalid_direction", "breaking"


def make_breaking_row(source: str, current: dict[str, str], direction_code: str, slot: int | None, amount: str | int, source_class: str, pitch_type: str, raw_text: str, normalized_text: str, raw_neighbor_text: str = "", detail: str = "") -> dict[str, str]:
    throws_bats = current.get("throws_bats", "")
    status, kind = classify_pitch(direction_code, pitch_type, throws_bats)
    if status == "invalid_direction" and not detail:
        detail = "球種候補は見つかりましたが方向コードと一致しません"
    return {
        "source": source, "team": current.get("team", "unknown"), "name": current.get("name", "unknown"), "throws_bats": throws_bats,
        "direction_code": direction_code, "direction": DIRECTION_NAMES.get(direction_code, "unknown"), "slot": slot,
        "raw_pitch_type": pitch_type, "pitch_type": pitch_type, "canonical_pitch_type": canonical_pitch_type(pitch_type),
        "movement": int(amount), "source_class": source_class, "status": status, "kind": kind,
        "raw_text": raw_text, "normalized_text": normalized_text, "raw_neighbor_text": raw_neighbor_text, "detail": detail,
    }


def unique_pitch_names(*texts: str) -> list[str]:
    names: list[str] = []
    for text in texts:
        for name in extract_pitch_names(normalize_pitch_text(text or "")):
            if name not in names:
                names.append(name)
    return names


def select_pitch_names_for_code(raw_text: str, raw_neighbor_text: str, direction_code: str, throws_bats: str, slot_count: int) -> tuple[list[str], str, str]:
    raw_names = unique_pitch_names(raw_text)
    neighbor_names = unique_pitch_names(raw_neighbor_text)
    names = []
    for name in [*raw_names, *neighbor_names]:
        if name not in names:
            names.append(name)
    allowed = [name for name in names if is_pitch_allowed_for_direction(direction_code, name, throws_bats)]
    if len(allowed) >= slot_count:
        return allowed[:slot_count], "ok", "raw_text/neighbor_textから方向一致候補を採用"
    if len(allowed) == 1:
        return allowed * slot_count, "ok", "raw_text/neighbor_textから唯一の方向一致候補を採用"
    direction_mismatches = [name for name in names if name not in SECOND_FASTBALL_TYPES and name not in FIXED_FASTBALL_TYPES]
    if direction_mismatches:
        return direction_mismatches[:slot_count] or [direction_mismatches[0]] * slot_count, "invalid_direction", "球種候補は見つかりましたが方向コードと一致しません"
    if names:
        return names[:slot_count] or [names[0]] * slot_count, "unknown", "候補球種は通常変化球ではありません"
    return ["unknown"] * slot_count, "unknown", "球種候補を特定できません"


def make_second_fastball_row(source: str, current: dict[str, str], pitch_type: str, raw_text: str) -> dict[str, str]:
    return {
        "source": source, "team": current.get("team", "unknown"), "name": current.get("name", "unknown"), "throws_bats": current.get("throws_bats", ""),
        "direction_code": "", "direction": "ストレート系第二種", "slot": "",
        "raw_pitch_type": pitch_type, "pitch_type": pitch_type, "canonical_pitch_type": pitch_type,
        "movement": 0, "source_class": "", "status": "second_fastball", "kind": "second_fastball",
        "raw_text": raw_text, "normalized_text": normalize_pitch_text(raw_text), "raw_neighbor_text": raw_text, "detail": "投手能力ブロック全体から検出",
    }


def parse_second_fastballs_from_block(block: str, current: dict[str, str], source: str) -> list[dict[str, str]]:
    text = html_text_with_attrs(block)
    found = []
    for pitch_type in SECOND_FASTBALL_TYPES:
        if pitch_type in normalize_pitch_text(text):
            found.append(make_second_fastball_row(source, current, pitch_type, text))
    return sorted(found, key=lambda row: normalize_pitch_text(text).find(row["pitch_type"]))

def parse_breaking_from_block(block: str, current: dict[str, str], source: str, result: ParseResult) -> list[dict[str, str]]:
    out = []
    block_text = html_text_with_attrs(block)
    for m in re.finditer(r'<b\b[^>]*class="[^"]*\bv(\d{2,3})\b[^"]*"[^>]*>(.*?)</b>', block, re.I | re.S):
        code = m.group(1)
        direction_code = code[0]
        amounts = list(code[1:])
        raw_text = clean_text(m.group(2)).replace(" / ", " ").strip()
        raw_neighbor_text = html_text_with_attrs(block[max(0, m.start() - 180): min(len(block), m.end() + 180)]) or block_text
        normalized_text = normalize_pitch_text(raw_text)
        names, selection_status, detail = select_pitch_names_for_code(raw_text, raw_neighbor_text or block_text, direction_code, current.get("throws_bats", ""), len(amounts))
        for idx, amount in enumerate(amounts, start=1):
            pitch_type = names[idx - 1] if idx - 1 < len(names) else (names[0] if names else "unknown")
            row = make_breaking_row(source, current, direction_code, idx, amount, f"v{code}", pitch_type, raw_text, normalized_text, raw_neighbor_text, detail)
            if selection_status == "invalid_direction":
                row["status"] = "invalid_direction"
                row["kind"] = "breaking"
            if row["status"] == "unknown":
                result.unknown_breaking.append({"source": source, "team": row["team"], "name": row["name"], "source_class": row["source_class"], "slot": idx, "movement": int(amount), "detail": detail, "raw_text": raw_text, "normalized_text": normalized_text})
            out.append(row)
    return out

def parse_cards(doc: SourceDoc) -> ParseResult:
    real = parse_real_blocks(doc)
    if real.players:
        return real
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



def looks_garbled(value: str) -> bool:
    if not value:
        return False
    if mojibake_score(value) > 0:
        return True
    jp = japanese_score(value)
    ascii_symbols = len(re.findall(r"[`@{}\\^~\[\]]", value))
    return jp == 0 and ascii_symbols >= 1


def ability_values(row: dict[str, str]) -> list[str]:
    return [str(row.get(col, "")) for col in ["top_speed", "control", "stamina", "trajectory", "contact", "power", "run_speed", "arm_strength", "fielding", "catching"] if str(row.get(col, ""))]

def flush_player(current: dict[str, str], result: ParseResult, source: str) -> None:
    row = {col: current.get(col, "") for col in PLAYER_COLUMNS}
    row["source"] = source
    missing = [col for col in ("name", "role") if not row.get(col)]
    if missing:
        result.failed_players.append({"source": source, "team": row.get("team", ""), "name": row.get("name", ""), "reason": "required_field_missing", "detail": ",".join(missing)})
    if looks_garbled(str(row.get("name", ""))) or looks_garbled(str(row.get("main_position", ""))):
        result.failed_players.append({"source": source, "team": row.get("team", ""), "name": row.get("name", ""), "reason": "mojibake_suspected", "detail": f"name={row.get('name', '')} main_position={row.get('main_position', '')}"})
    if not ability_values(row):
        result.failed_players.append({"source": source, "team": row.get("team", ""), "name": row.get("name", ""), "reason": "abilities_missing", "detail": "能力値がすべて空です"})
    for col in ["number", "top_speed", "control", "stamina", "trajectory", "contact", "power", "run_speed", "arm_strength", "fielding", "catching"]:
        val = to_int(str(row.get(col, "")))
        row[col] = val if val is not None else ""
    result.players.append(row)
    for key, kind in [("specials", "normal"), ("ranked_specials", "rank"), ("green_specials", "green"), ("usage_specials", "usage")]:
        for sp in split_values(current.get(key, "")):
            result.specials.append({"source": source, "team": row["team"], "name": row["name"], "special": sp, "special_kind": kind})


def parse_breaking_ball_row(cells: list[tuple[str, str]], current: dict[str, str], css_classes: set[str], source: str, result: ParseResult) -> list[dict[str, str]]:
    out = []
    row_html = " ".join(cell for _, cell in cells)
    matches = V_CLASS_RE.findall(row_html)
    if not matches:
        return out
    raw_text = " ".join(html_text_with_attrs(c[1]) for c in cells)
    normalized_text = normalize_pitch_text(raw_text)
    for code in matches:
        source_class = f"v{code}"
        if code not in css_classes:
            detail = "ball.css等のCSSにclass定義が見つかりません"
            result.unknown_classes.append({"source": source, "team": current.get("team", "unknown"), "name": current.get("name", "unknown"), "source_class": source_class, "detail": detail})
            LOGGER.warning("CSSに定義がない変化球class: %s (%s / %s / %s)", source_class, current.get("name", "unknown"), current.get("team", "unknown"), source)
        direction_code = code[0]
        amounts = list(code[1:])
        names, selection_status, detail = select_pitch_names_for_code(raw_text, normalized_text, direction_code, current.get("throws_bats", ""), len(amounts))
        for idx, amount in enumerate(amounts, start=1):
            pitch_type = names[idx - 1] if idx - 1 < len(names) else "unknown"
            row = make_breaking_row(source, current, direction_code, idx, amount, source_class, pitch_type, raw_text, normalized_text, normalized_text, detail)
            if selection_status == "invalid_direction":
                row["status"] = "invalid_direction"
                row["kind"] = "breaking"
            if row["status"] == "unknown":
                result.unknown_breaking.append({"source": source, "team": row["team"], "name": row["name"], "source_class": source_class, "slot": idx, "movement": int(amount), "detail": detail, "raw_text": raw_text, "normalized_text": normalized_text})
            out.append(row)
    return out

def combine_results(results: list[ParseResult], source_failures: list[dict[str, str]]) -> ParseResult:
    combined = ParseResult(input_errors=list(source_failures))
    for result in results:
        combined.players.extend(result.players)
        combined.breaking.extend(result.breaking)
        combined.specials.extend(result.specials)
        combined.unknown_classes.extend(result.unknown_classes)
        combined.unknown_breaking.extend(result.unknown_breaking)
        combined.failed_players.extend(result.failed_players)
        combined.input_errors.extend(result.input_errors)
    return combined



def numeric_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def average_by(df: pd.DataFrame, key: str, columns: list[str]) -> pd.DataFrame:
    present = [col for col in columns if col in df.columns]
    if df.empty or key not in df.columns or not present:
        return pd.DataFrame(columns=[key, "count", *[f"avg_{col}" for col in present]])
    work = numeric_columns(df, present).fillna({key: ""})
    grouped = work.groupby(key, dropna=False)
    counts = grouped.size().reset_index(name="count")
    avgs = grouped[present].mean().round(2).add_prefix("avg_").reset_index()
    return counts.merge(avgs, on=key, how="left").sort_values("count", ascending=False)


def team_roster_summary(players: pd.DataFrame) -> pd.DataFrame:
    if players.empty:
        return pd.DataFrame(columns=["team", "players", "pitchers", "fielders"])
    work = players.copy()
    work["is_pitcher"] = work["role"].fillna("").eq("投手")
    work["is_fielder"] = work["role"].fillna("").eq("野手")
    out = work.groupby("team", dropna=False).agg(players=("name", "count"), pitchers=("is_pitcher", "sum"), fielders=("is_fielder", "sum")).reset_index()
    return out.sort_values("players", ascending=False)


def normal_breaking_df(breaking: pd.DataFrame) -> pd.DataFrame:
    if breaking.empty:
        return pd.DataFrame(columns=BREAKING_BALL_COLUMNS)
    kind = breaking.get("kind", pd.Series(dtype=str)).fillna("breaking")
    status = breaking.get("status", pd.Series(dtype=str)).fillna("ok")
    return breaking[kind.eq("breaking") & status.isin(["ok", "corrected_by_direction_filter"]) & ~breaking.get("pitch_type", pd.Series(dtype=str)).isin(["ストレート", *SECOND_FASTBALL_TYPES])].copy()


def second_fastball_df(breaking: pd.DataFrame) -> pd.DataFrame:
    if breaking.empty:
        return pd.DataFrame(columns=BREAKING_BALL_COLUMNS)
    return breaking[breaking.get("kind", pd.Series(dtype=str)).eq("second_fastball") | breaking.get("pitch_type", pd.Series(dtype=str)).isin(SECOND_FASTBALL_TYPES)].copy()


def pitcher_breaking_metrics(players: pd.DataFrame, breaking: pd.DataFrame) -> pd.DataFrame:
    pitchers = players[players.get("role", pd.Series(dtype=str)).eq("投手")].copy() if not players.empty else pd.DataFrame()
    if pitchers.empty:
        return pitchers
    b = normal_breaking_df(breaking)
    if not b.empty:
        b["movement"] = pd.to_numeric(b["movement"], errors="coerce").fillna(0)
        per = b.groupby(["source", "team", "name"], dropna=False).agg(breaking_ball_count=("pitch_type", "count"), total_movement=("movement", "sum"), has_second_pitch=("slot", lambda x: (pd.to_numeric(x, errors="coerce") >= 2).any())).reset_index()
        pitchers = pitchers.merge(per, on=["source", "team", "name"], how="left")
    else:
        pitchers["breaking_ball_count"] = 0
        pitchers["total_movement"] = 0
        pitchers["has_second_pitch"] = False
    sf = second_fastball_df(breaking)
    if not sf.empty:
        has_sf = sf.groupby(["source", "team", "name"], dropna=False).size().reset_index(name="second_fastball_count")
        pitchers = pitchers.merge(has_sf, on=["source", "team", "name"], how="left")
    else:
        pitchers["second_fastball_count"] = 0
    pitchers[["breaking_ball_count", "total_movement", "second_fastball_count"]] = pitchers[["breaking_ball_count", "total_movement", "second_fastball_count"]].fillna(0)
    pitchers["has_second_pitch"] = pitchers["has_second_pitch"].fillna(False).astype(bool)
    pitchers["has_second_fastball"] = pitchers["second_fastball_count"].fillna(0).gt(0)
    return pitchers


def distribution(df: pd.DataFrame, column: str) -> pd.DataFrame:
    if df.empty or column not in df.columns:
        return pd.DataFrame(columns=[column, "count"])
    return df.groupby(column, dropna=False).size().reset_index(name="count").sort_values(column)


def ratio_summary(label: str, numerator: int, denominator: int) -> pd.DataFrame:
    ratio = round(numerator / denominator * 100, 2) if denominator else 0.0
    return pd.DataFrame([{"item": label, "count": numerator, "total": denominator, "ratio_percent": ratio}])

def write_outputs(result: ParseResult, output_dir: Path, excel: bool) -> dict[str, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)
    dfs = {
        "players": pd.DataFrame(result.players),
        "breaking_balls": pd.DataFrame(result.breaking),
        "special_abilities": pd.DataFrame(result.specials),
        "unknown_classes": pd.DataFrame(result.unknown_classes),
        "unknown_breaking_balls": pd.DataFrame(result.unknown_breaking),
        "failed_players": pd.DataFrame(result.failed_players),
        "input_errors": pd.DataFrame(result.input_errors),
    }
    required_columns = {
        "players": PLAYER_COLUMNS + ["source"],
        "breaking_balls": BREAKING_BALL_COLUMNS,
        "special_abilities": SPECIAL_COLUMNS,
        "unknown_classes": UNKNOWN_CLASS_COLUMNS,
        "unknown_breaking_balls": UNKNOWN_BREAKING_COLUMNS,
        "failed_players": FAILED_PLAYER_COLUMNS,
        "input_errors": INPUT_ERROR_COLUMNS,
    }
    for name, columns in required_columns.items():
        if dfs[name].empty:
            dfs[name] = pd.DataFrame(columns=columns)
        else:
            dfs[name] = dfs[name].reindex(columns=columns)
    players = dfs["players"]
    pitchers = players[players["role"].fillna("").eq("投手")] if not players.empty else pd.DataFrame(columns=players.columns)
    fielders = players[players["role"].fillna("").eq("野手")] if not players.empty else pd.DataFrame(columns=players.columns)
    normal_breaking = normal_breaking_df(dfs["breaking_balls"])
    second_fastballs = second_fastball_df(dfs["breaking_balls"])
    invalid_directions = dfs["breaking_balls"][dfs["breaking_balls"].get("status", pd.Series(dtype=str)).eq("invalid_direction")].copy() if not dfs["breaking_balls"].empty else pd.DataFrame(columns=BREAKING_BALL_COLUMNS)
    dfs["invalid_pitch_directions"] = invalid_directions
    pitcher_metrics = pitcher_breaking_metrics(players, dfs["breaking_balls"])
    dfs["position_summary"] = summarize(players, "main_position")
    dfs["pitcher_role_summary"] = summarize(pitchers[pitchers["pitcher_roles"].fillna("").ne("")], "pitcher_roles")
    dfs["breaking_ball_summary"] = summarize(normal_breaking, "canonical_pitch_type", numeric="movement")
    dfs["team_roster_summary"] = team_roster_summary(players)
    dfs["team_pitcher_ability_average"] = average_by(pitchers, "team", ["top_speed", "control", "stamina"])
    dfs["team_fielder_ability_average"] = average_by(fielders, "team", ["trajectory", "contact", "power", "run_speed", "arm_strength", "fielding", "catching"])
    dfs["position_ability_average"] = average_by(fielders, "main_position", ["trajectory", "contact", "power", "run_speed", "arm_strength", "fielding", "catching"])
    dfs["pitcher_role_ability_average"] = average_by(pitcher_metrics[pitcher_metrics["pitcher_roles"].fillna("").ne("")], "pitcher_roles", ["top_speed", "control", "stamina", "breaking_ball_count", "total_movement"])
    dfs["breaking_ball_count_distribution"] = distribution(pitcher_metrics, "breaking_ball_count")
    dfs["second_pitch_summary"] = ratio_summary("第二球種あり投手", int(pitcher_metrics.get("has_second_pitch", pd.Series(dtype=bool)).sum()), len(pitcher_metrics))
    dfs["second_fastball_summary"] = ratio_summary("ストレート系第二種あり投手", int(pitcher_metrics.get("has_second_fastball", pd.Series(dtype=bool)).sum()), len(pitcher_metrics))
    dfs["second_fastball_type_summary"] = summarize(second_fastballs, "pitch_type")
    dfs["pitch_direction_summary"] = summarize(normal_breaking, "direction")
    dfs["raw_pitch_type_summary"] = summarize(normal_breaking, "raw_pitch_type")
    dfs["canonical_pitch_type_summary"] = summarize(normal_breaking, "canonical_pitch_type", numeric="movement")
    dfs["raw_vs_canonical_pitch_summary"] = normal_breaking.groupby(["raw_pitch_type", "canonical_pitch_type"], dropna=False).size().reset_index(name="count") if not normal_breaking.empty else pd.DataFrame(columns=["raw_pitch_type", "canonical_pitch_type", "count"])
    dfs["invalid_pitch_direction_summary"] = summarize(invalid_directions, "pitch_type")
    dfs["direction_code_pitch_type_crosstab"] = pd.crosstab(normal_breaking["direction_code"], normal_breaking["pitch_type"]).reset_index() if not normal_breaking.empty else pd.DataFrame()
    dfs["total_movement_distribution"] = distribution(pitcher_metrics, "total_movement")
    subpos_count = int(fielders["sub_positions"].fillna("").ne("").sum()) if "sub_positions" in fielders else 0
    dfs["fielder_sub_position_summary"] = ratio_summary("サブポジあり野手", subpos_count, len(fielders))
    dfs["special_kind_summary"] = summarize(dfs["special_abilities"], "special_kind")
    normal_specials = dfs["special_abilities"][dfs["special_abilities"].get("special_kind", pd.Series(dtype=str)).eq("normal")] if not dfs["special_abilities"].empty else pd.DataFrame(columns=SPECIAL_COLUMNS)
    rank_specials = dfs["special_abilities"][dfs["special_abilities"].get("special_kind", pd.Series(dtype=str)).eq("rank")] if not dfs["special_abilities"].empty else pd.DataFrame(columns=SPECIAL_COLUMNS)
    green_specials = dfs["special_abilities"][dfs["special_abilities"].get("special_kind", pd.Series(dtype=str)).eq("green")] if not dfs["special_abilities"].empty else pd.DataFrame(columns=SPECIAL_COLUMNS)
    usage_specials = dfs["special_abilities"][dfs["special_abilities"].get("special_kind", pd.Series(dtype=str)).eq("usage")] if not dfs["special_abilities"].empty else pd.DataFrame(columns=SPECIAL_COLUMNS)
    dfs["normal_special_summary"] = summarize(normal_specials, "special")
    dfs["ranked_special_summary"] = summarize(rank_specials, "special")
    dfs["green_special_summary"] = summarize(green_specials, "special")
    dfs["player_usage_summary"] = summarize(usage_specials, "special")
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
    print(f"入力エラー/警告数: {len(dfs['input_errors'])} -> {output_dir / 'input_errors.csv'}")
    for doc in docs:
        src_players = players[players["source"].eq(doc.source_name)] if "source" in players else pd.DataFrame()
        src_roles = src_players["role"].fillna("") if "role" in src_players else pd.Series(dtype=str)
        src_breaking = dfs["breaking_balls"][dfs["breaking_balls"].get("source", pd.Series(dtype=str)).eq(doc.source_name)] if "source" in dfs["breaking_balls"] else pd.DataFrame()
        src_specials = dfs["special_abilities"][dfs["special_abilities"].get("source", pd.Series(dtype=str)).eq(doc.source_name)] if "source" in dfs["special_abilities"] else pd.DataFrame()
        src_unknown = dfs["unknown_classes"][dfs["unknown_classes"].get("source", pd.Series(dtype=str)).eq(doc.source_name)] if "source" in dfs["unknown_classes"] else pd.DataFrame()
        src_failed = dfs["failed_players"][dfs["failed_players"].get("source", pd.Series(dtype=str)).eq(doc.source_name)] if "source" in dfs["failed_players"] else pd.DataFrame()
        print(f"- {doc.source_name} / encoding={doc.encoding} / 選手数={len(src_players)} / 投手数={int(src_roles.str.contains('投手', na=False).sum())} / 野手数={int(src_roles.str.contains('野手', na=False).sum())} / 変化球数={len(src_breaking)} / 特殊能力数={len(src_specials)} / unknown={len(src_unknown)} / failed={len(src_failed)}")
    if len(players) < 10:
        print("警告: 1入力あたりの選手数が10件未満です。選手ブロック抽出に失敗している可能性があります。")
    if len(dfs["breaking_balls"]) == 0:
        print("警告: breaking_balls が0件です。変化球解析に失敗している可能性があります。")
    if len(dfs["special_abilities"]) == 0:
        print("警告: special_abilities が0件です。特殊能力解析に失敗している可能性があります。")
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
