from __future__ import annotations

import json
import logging
import random
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = APP_DIR / "data" / "imported" / "foreign_names.sqlite"
DEFAULT_CONFIG_PATH = APP_DIR / "data" / "config" / "ootp_name_config.json"
LOGGER = logging.getLogger(__name__)
SCHEMA_VERSION = "1"
REQUIRED_TABLE_COLUMNS = {
    "metadata": {"key", "value"},
    "nations": {"name", "code", "display_nationality", "base_ethnicity_id", "bbqual", "name_order"},
    "nation_ethnicities": {"nation_name", "ethnicity_id", "weight"},
    "ethnicities": {"id", "name", "african", "asian", "east_indian", "caucasian", "hispanic"},
    "names": {"kind", "lid", "name", "weight"},
}
GAME_NATIONALITIES = {
    "韓国",
    "台湾",
    "中国",
    "南アフリカ",
    "イタリア",
    "オランダ",
    "オーストラリア",
    "イスラエル",
    "キューバ",
    "メキシコ",
    "ベネズエラ",
    "ドミニカ共和国",
    "パナマ",
    "コロンビア",
    "アメリカ",
    "カナダ",
    "プエルトリコ",
    "ニカラグア",
    "チェコ",
    "イギリス",
    "ブラジル",
}


@dataclass(frozen=True)
class ForeignNameProfile:
    name: str
    nationality: str
    actual_nationality: str
    nationality_code: str
    name_group_id: int
    name_group_name: str
    skin_color: int
    name_generation_fallback: bool = False


def weighted_choice(rng: random.Random, items: list[tuple[Any, int]]) -> Any:
    positive = [(value, int(weight)) for value, weight in items if int(weight) > 0]
    if not positive:
        raise ValueError("weighted_choice requires at least one positive weight")
    return rng.choices([value for value, _weight in positive], weights=[weight for _value, weight in positive], k=1)[0]


@lru_cache(maxsize=4)
def load_config(config_path: str = str(DEFAULT_CONFIG_PATH)) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def imported_db_ready(db_path: Path | str = DEFAULT_DB_PATH) -> bool:
    path = Path(db_path)
    if not path.exists():
        return False
    try:
        with sqlite3.connect(path) as conn:
            required = set(REQUIRED_TABLE_COLUMNS)
            existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not required.issubset(existing):
                return False
            for table, required_columns in REQUIRED_TABLE_COLUMNS.items():
                columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                if not required_columns.issubset(columns):
                    return False
            metadata = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
            return metadata.get("schema_version") == SCHEMA_VERSION
    except sqlite3.Error:
        return False


@lru_cache(maxsize=4)
def load_nations(db_path: str = str(DEFAULT_DB_PATH)) -> dict[str, dict[str, Any]]:
    if not imported_db_ready(db_path):
        return {}
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT name, code, display_nationality, base_ethnicity_id, bbqual, name_order FROM nations"
        ).fetchall()
    return {row["name"]: dict(row) for row in rows}


@lru_cache(maxsize=4)
def load_available_lids(db_path: str = str(DEFAULT_DB_PATH)) -> frozenset[int]:
    if not imported_db_ready(db_path):
        return frozenset()
    with sqlite3.connect(db_path) as conn:
        first_lids = {row[0] for row in conn.execute("SELECT DISTINCT lid FROM names WHERE kind = 'first'")}
        last_lids = {row[0] for row in conn.execute("SELECT DISTINCT lid FROM names WHERE kind = 'last'")}
    return frozenset(first_lids & last_lids)


@lru_cache(maxsize=4096)
def load_names_for_lid(lid: int, kind: str, db_path: str = str(DEFAULT_DB_PATH)) -> tuple[tuple[str, int], ...]:
    if not imported_db_ready(db_path):
        return ()
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name, weight FROM names WHERE lid = ? AND kind = ? AND weight > 0",
            (int(lid), kind),
        ).fetchall()
    return tuple((str(name), int(weight)) for name, weight in rows)


@lru_cache(maxsize=4)
def load_nation_ethnicities(db_path: str = str(DEFAULT_DB_PATH)) -> dict[str, tuple[tuple[int, int], ...]]:
    if not imported_db_ready(db_path):
        return {}
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT nation_name, ethnicity_id, weight FROM nation_ethnicities WHERE weight > 0"
        ).fetchall()
    grouped: dict[str, list[tuple[int, int]]] = {}
    for nation_name, ethnicity_id, weight in rows:
        grouped.setdefault(str(nation_name), []).append((int(ethnicity_id), int(weight)))
    return {nation: tuple(items) for nation, items in grouped.items()}


@lru_cache(maxsize=4096)
def load_ethnicity(ethnicity_id: int, db_path: str = str(DEFAULT_DB_PATH)) -> dict[str, Any] | None:
    if not imported_db_ready(db_path):
        return None
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, name, african, asian, east_indian, caucasian, hispanic
            FROM ethnicities
            WHERE id = ?
            """,
            (int(ethnicity_id),),
        ).fetchone()
    return dict(row) if row else None


def candidate_actual_nationalities(rng: random.Random, category: str, display_nationality: str | None, config: dict[str, Any]) -> list[tuple[str, int]]:
    if display_nationality:
        mapping = config.get("display_to_actual_candidates", {}).get(display_nationality)
        if isinstance(mapping, dict):
            return [(str(name), int(weight)) for name, weight in mapping.items()]
        return []
    weights = dict(config.get("foreign_nationality_weights", {}))
    other_weight = int(weights.pop("other", 0) or 0)
    candidates = [(str(name), int(weight)) for name, weight in weights.items()]
    if other_weight > 0:
        other_items = [(str(name), int(weight)) for name, weight in config.get("other_nationality_weights", {}).items()]
        if other_items:
            candidates.append((weighted_choice(rng, other_items), other_weight))
    return candidates


def usable_group_ids(actual_nationality: str, db_path: Path | str = DEFAULT_DB_PATH) -> tuple[tuple[int, int], ...]:
    db_key = str(db_path)
    available_lids = load_available_lids(db_key)
    groups = load_nation_ethnicities(db_key).get(actual_nationality, ())
    usable = tuple((lid, weight) for lid, weight in groups if lid in available_lids)
    if usable:
        return usable
    nation = load_nations(db_key).get(actual_nationality)
    base_lid = int(nation["base_ethnicity_id"]) if nation else -1
    return ((base_lid, 100),) if base_lid in available_lids else ()


def display_nationality_for(actual_nationality: str, config: dict[str, Any]) -> str:
    display = config.get("display_nationality_map", {}).get(actual_nationality, "その他")
    return display if display in GAME_NATIONALITIES else "その他"


def skin_color_from_ethnicity(rng: random.Random, ethnicity: dict[str, Any], config: dict[str, Any]) -> int:
    category_weights = []
    for key in ("african", "asian", "east_indian", "caucasian", "hispanic"):
        category_weights.append((key, int(ethnicity.get(key, 0) or 0)))
    selected_category = weighted_choice(rng, category_weights) if any(weight > 0 for _key, weight in category_weights) else "caucasian"
    skin_weights = config.get("skin_color_weights", {}).get(selected_category) or {"1": 1}
    return int(weighted_choice(rng, [(int(color), int(weight)) for color, weight in skin_weights.items()]))


def build_name(rng: random.Random, lid: int, order: str, db_path: Path | str = DEFAULT_DB_PATH) -> str | None:
    first_names = load_names_for_lid(int(lid), "first", str(db_path))
    last_names = load_names_for_lid(int(lid), "last", str(db_path))
    if not first_names or not last_names:
        return None
    first = weighted_choice(rng, list(first_names))
    last = weighted_choice(rng, list(last_names))
    return f"{last} {first}" if order == "surname_given" else f"{first} {last}"


def generate_foreign_profile(
    rng: random.Random,
    category: str,
    *,
    display_nationality: str | None = None,
    used_names: set[str] | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> ForeignNameProfile | None:
    db_key = str(db_path)
    if not imported_db_ready(db_key):
        LOGGER.warning("OOTP外国人名DBを利用できないため既存外国人名マスタへフォールバックします: %s", db_key)
        return None
    config = load_config(str(config_path))
    nations = load_nations(db_key)
    candidates = candidate_actual_nationalities(rng, category, display_nationality, config)
    if not candidates:
        LOGGER.warning("OOTP外国人名DBに使用可能な国籍候補がないため既存外国人名マスタへフォールバックします: display_nationality=%s", display_nationality)
        return None

    retry_limit = int(config.get("duplicate_name_retry_limit", 8) or 8)
    for _ in range(max(1, retry_limit + 1)):
        actual = weighted_choice(rng, candidates)
        nation = nations.get(actual)
        if not nation:
            LOGGER.warning("OOTP外国人名DBの国籍が未解決です: actual_nationality=%s", actual)
            continue
        groups = usable_group_ids(actual, db_key)
        if not groups:
            LOGGER.warning("OOTP外国人名DBに使用可能な名前グループがありません: actual_nationality=%s", actual)
            continue
        lid = int(weighted_choice(rng, list(groups)))
        name = build_name(rng, lid, str(nation.get("name_order", "given_surname")), db_key)
        ethnicity = load_ethnicity(lid, db_key)
        if not name or not ethnicity:
            LOGGER.warning("OOTP外国人名DBの名前または民族情報が不足しています: actual_nationality=%s name_group_id=%s", actual, lid)
            continue
        if used_names is not None and name in used_names:
            continue
        if used_names is not None:
            used_names.add(name)
        return ForeignNameProfile(
            name=name,
            nationality=display_nationality_for(actual, config),
            actual_nationality=actual,
            nationality_code=str(nation.get("code", "")),
            name_group_id=lid,
            name_group_name=str(ethnicity.get("name", "")),
            skin_color=skin_color_from_ethnicity(rng, ethnicity, config),
        )
    LOGGER.warning("OOTP外国人名生成の再試行上限に達したため既存外国人名マスタへフォールバックします: display_nationality=%s", display_nationality)
    return None


def clear_caches() -> None:
    imported_db_ready.cache_clear()
    load_config.cache_clear()
    load_nations.cache_clear()
    load_available_lids.cache_clear()
    load_names_for_lid.cache_clear()
    load_nation_ethnicities.cache_clear()
    load_ethnicity.cache_clear()
