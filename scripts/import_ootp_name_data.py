from __future__ import annotations

import argparse
import gc
import json
import sqlite3
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_NAMES_XML = APP_DIR / "data" / "external" / "ootp" / "names.xml"
DEFAULT_WORLD_XML = APP_DIR / "data" / "external" / "ootp" / "world_default.xml"
DEFAULT_CONFIG = APP_DIR / "data" / "config" / "ootp_name_config.json"
DEFAULT_OUTPUT = APP_DIR / "data" / "imported" / "foreign_names.sqlite"
SCHEMA_VERSION = "1"
REQUIRED_TABLES = {"metadata", "ethnicities", "nations", "nation_ethnicities", "names"}


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def int_attr(attrs: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(attrs.get(key, default))
    except (TypeError, ValueError):
        return default


def display_nationality(actual_name: str, config: dict[str, Any]) -> str:
    return config.get("display_nationality_map", {}).get(actual_name, "その他")


def name_order(actual_name: str, display_name: str, config: dict[str, Any]) -> str:
    return config.get("name_order", {}).get(
        actual_name,
        "surname_given" if display_name in {"韓国", "台湾", "中国"} else "given_surname",
    )


def is_initial_name(name: str) -> bool:
    parts = [part for part in name.replace(" ", "").split(".") if part]
    return bool(parts) and len(name.replace(" ", "")) <= 6 and all(len(part) == 1 for part in parts)


def connect_output(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    conn.executescript(
        """
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE ethnicities (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            african INTEGER NOT NULL,
            asian INTEGER NOT NULL,
            east_indian INTEGER NOT NULL,
            caucasian INTEGER NOT NULL,
            hispanic INTEGER NOT NULL
        );
        CREATE TABLE nations (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            code TEXT NOT NULL,
            display_nationality TEXT NOT NULL,
            base_ethnicity_id INTEGER NOT NULL,
            bbqual INTEGER NOT NULL,
            name_order TEXT NOT NULL
        );
        CREATE TABLE nation_ethnicities (
            nation_name TEXT NOT NULL,
            ethnicity_id INTEGER NOT NULL,
            weight INTEGER NOT NULL,
            PRIMARY KEY (nation_name, ethnicity_id)
        );
        CREATE TABLE names (
            kind TEXT NOT NULL,
            lid INTEGER NOT NULL,
            name TEXT NOT NULL,
            weight INTEGER NOT NULL,
            PRIMARY KEY (kind, lid, name)
        );
        """
    )
    return conn


def validate_imported_database(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = REQUIRED_TABLES - tables
        if missing:
            raise RuntimeError(f"変換済みSQLiteの必須テーブルが不足しています: {', '.join(sorted(missing))}")
        metadata = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
        if metadata.get("schema_version") != SCHEMA_VERSION:
            raise RuntimeError("変換済みSQLiteのschema_versionが不正です。")
        for table in ("ethnicities", "nations", "nation_ethnicities", "names"):
            count = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            if count <= 0:
                raise RuntimeError(f"変換済みSQLiteの{table}が空です。")


def unlink_with_retry(path: Path, attempts: int = 10) -> None:
    for attempt in range(attempts):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            gc.collect()
            time.sleep(0.1)


def replace_with_retry(source: Path, target: Path, attempts: int = 10) -> None:
    backup = target.with_name(f".{target.name}.bak")
    for attempt in range(attempts):
        try:
            source.replace(target)
            return
        except PermissionError:
            pass

        try:
            if backup.exists():
                backup.unlink()
            if target.exists():
                target.replace(backup)
            source.replace(target)
            if backup.exists():
                backup.unlink()
            return
        except PermissionError:
            if backup.exists() and not target.exists():
                backup.replace(target)
            if attempt == attempts - 1:
                raise
            gc.collect()
            time.sleep(0.1)
        except Exception:
            if backup.exists() and not target.exists():
                backup.replace(target)
            raise


def import_world(conn: sqlite3.Connection, world_xml: Path, config: dict[str, Any]) -> dict[str, int]:
    counts = {"ethnicities": 0, "nations": 0, "nation_ethnicities": 0}
    for _event, elem in ET.iterparse(world_xml, events=("end",)):
        tag = elem.tag.split("}", 1)[-1]
        if tag == "ETHNICITY":
            attrs = elem.attrib
            conn.execute(
                """
                INSERT INTO ethnicities
                    (id, name, african, asian, east_indian, caucasian, hispanic)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int_attr(attrs, "id"),
                    attrs.get("name", ""),
                    int_attr(attrs, "african"),
                    int_attr(attrs, "asian"),
                    int_attr(attrs, "east_indian"),
                    int_attr(attrs, "caucasian"),
                    int_attr(attrs, "hispanic"),
                ),
            )
            counts["ethnicities"] += 1
            elem.clear()
        elif tag == "NATION":
            attrs = elem.attrib
            actual_name = attrs.get("name", "")
            if not actual_name:
                elem.clear()
                continue
            display_name = display_nationality(actual_name, config)
            conn.execute(
                """
                INSERT INTO nations
                    (id, name, code, display_nationality, base_ethnicity_id, bbqual, name_order)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int_attr(attrs, "id"),
                    actual_name,
                    attrs.get("abbr", ""),
                    display_name,
                    int_attr(attrs, "etid"),
                    int_attr(attrs, "bbqual"),
                    name_order(actual_name, display_name, config),
                ),
            )
            counts["nations"] += 1
            eth_rows = [
                (actual_name, int_attr(child.attrib, "etid"), max(1, int_attr(child.attrib, "pct")))
                for child in elem.findall("./ETHN_PCTS/ETHN_PCT")
                if child.attrib.get("etid") is not None
            ]
            if not eth_rows and attrs.get("etid") is not None:
                eth_rows = [(actual_name, int_attr(attrs, "etid"), 100)]
            conn.executemany(
                """
                INSERT INTO nation_ethnicities (nation_name, ethnicity_id, weight)
                VALUES (?, ?, ?)
                ON CONFLICT(nation_name, ethnicity_id)
                DO UPDATE SET weight = weight + excluded.weight
                """,
                eth_rows,
            )
            counts["nation_ethnicities"] += len(eth_rows)
            elem.clear()
    return counts


def import_names(conn: sqlite3.Connection, names_xml: Path, config: dict[str, Any], batch_size: int = 50000) -> dict[str, int]:
    counts = {"first": 0, "last": 0, "empty_nl": 0, "initial_excluded": 0, "last_excluded": 0}
    exclude_initials = bool(config.get("exclude_initial_first_names", True))
    excluded_last = set(config.get("excluded_single_last_names", []))
    stack: list[str] = []
    batch: list[tuple[str, int, str, int]] = []

    def flush() -> None:
        if not batch:
            return
        conn.executemany(
            """
            INSERT INTO names (kind, lid, name, weight)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(kind, lid, name)
            DO UPDATE SET weight = weight + excluded.weight
            """,
            batch,
        )
        batch.clear()

    for event, elem in ET.iterparse(names_xml, events=("start", "end")):
        tag = elem.tag.split("}", 1)[-1]
        if event == "start":
            stack.append(tag)
            continue
        if tag == "N":
            if "FIRST_NAMES" in stack:
                kind = "first"
            elif "LAST_NAMES" in stack:
                kind = "last"
            else:
                kind = ""
            raw_name = (elem.findtext("EN") or "").strip()
            links = elem.findall("./NL/L")
            if kind and (not raw_name or not links):
                counts["empty_nl"] += 1
            elif kind == "first" and exclude_initials and is_initial_name(raw_name):
                counts["initial_excluded"] += 1
            elif kind == "last" and raw_name in excluded_last:
                counts["last_excluded"] += 1
            elif kind:
                for link in links:
                    lid = int_attr(link.attrib, "lid", -1)
                    dist = int_attr(link.attrib, "dist", 0)
                    if lid >= 0 and dist > 0:
                        batch.append((kind, lid, raw_name, dist))
                        counts[kind] += 1
                        if len(batch) >= batch_size:
                            flush()
            elem.clear()
        if stack:
            stack.pop()
    flush()
    return counts


def create_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX idx_names_lid_kind ON names (lid, kind);
        CREATE INDEX idx_nation_ethnicities_nation ON nation_ethnicities (nation_name);
        CREATE INDEX idx_nations_display ON nations (display_nationality);
        """
    )


def inspect_inputs(names_xml: Path, world_xml: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for path in (names_xml, world_xml):
        counts: dict[str, int] = {}
        for _event, elem in ET.iterparse(path, events=("start",)):
            tag = elem.tag.split("}", 1)[-1]
            counts[tag] = counts.get(tag, 0) + 1
        result[path.name] = {
            "exists": path.exists(),
            "size": path.stat().st_size if path.exists() else 0,
            "counts": counts,
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="OOTP形式の名前・国籍データをアプリ用SQLiteへ変換します。")
    parser.add_argument("--names-xml", type=Path, default=DEFAULT_NAMES_XML)
    parser.add_argument("--world-xml", type=Path, default=DEFAULT_WORLD_XML)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--inspect-only", action="store_true")
    args = parser.parse_args()

    for path in (args.names_xml, args.world_xml):
        if not path.exists():
            raise FileNotFoundError(path)

    inspection = inspect_inputs(args.names_xml, args.world_xml)
    print(json.dumps(inspection, ensure_ascii=False, indent=2))
    if args.inspect_only:
        return

    config = load_config(args.config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=f".{args.output.name}.", suffix=".tmp", dir=args.output.parent, delete=False) as tmp:
        tmp_output = Path(tmp.name)
    unlink_with_retry(tmp_output)
    conn: sqlite3.Connection | None = None
    try:
        conn = connect_output(tmp_output)
        with conn:
            world_counts = import_world(conn, args.world_xml, config)
            name_counts = import_names(conn, args.names_xml, config)
            create_indexes(conn)
            conn.executemany(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                [
                    ("schema_version", SCHEMA_VERSION),
                    ("source_names_xml", str(args.names_xml)),
                    ("source_world_xml", str(args.world_xml)),
                    ("world_counts_json", json.dumps(world_counts, ensure_ascii=False)),
                    ("name_counts_json", json.dumps(name_counts, ensure_ascii=False)),
                ],
            )
        conn.close()
        conn = None
        validate_imported_database(tmp_output)
        gc.collect()
        replace_with_retry(tmp_output, args.output)
    except Exception:
        if conn is not None:
            conn.close()
        unlink_with_retry(tmp_output)
        raise
    print(json.dumps({"output": str(args.output), "world": world_counts, "names": name_counts}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
