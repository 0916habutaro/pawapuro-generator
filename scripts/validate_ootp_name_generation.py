from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


CENTER_NATIONS = {"アメリカ", "ベネズエラ", "ドミニカ共和国", "プエルトリコ", "キューバ", "メキシコ"}
CENTER_TARGETS = {"アメリカ": 34.0, "ドミニカ共和国": 17.0, "ベネズエラ": 15.0, "プエルトリコ": 7.0, "キューバ": 7.0, "メキシコ": 5.0}
EAST_ASIAN_NATIONS = {"韓国", "台湾", "中国"}
EXCLUDED_LAST_NAMES = {"De", "La"}


def pct(count: int, total: int) -> float:
    return round(count / total * 100, 2) if total else 0.0


def split_name(player: dict[str, Any]) -> tuple[str, str]:
    parts = str(player.get("name", "")).split()
    if not parts:
        return "", ""
    if str(player.get("nationality")) in EAST_ASIAN_NATIONS:
        return parts[0], " ".join(parts[1:])
    return " ".join(parts[1:]), parts[0]


def rows_from_counter(counter: Counter[str], total: int, label: str) -> list[dict[str, Any]]:
    return [{label: key, "件数": value, "割合%": pct(value, total)} for key, value in counter.most_common()]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        keys: list[str] = []
        for row in rows:
            for key in row:
                if key not in keys:
                    keys.append(key)
        fieldnames = keys or ["結果"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def generate_players(count: int, seed: int) -> list[dict[str, Any]]:
    master = app.load_master_data()
    used_names: set[str] = set()
    players = []
    for i in range(count):
        role = "投手" if i % 2 == 0 else "野手"
        players.append(app.generate_player(role, "助っ人外国人用", master, seed=seed + i, used_names=used_names))
    return players


def summarize(players: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    total = len(players)
    display_counter = Counter(str(p.get("nationality", "")) for p in players)
    actual_counter = Counter(str(p.get("actual_nationality", "")) for p in players)
    other_actual_counter = Counter(str(p.get("actual_nationality", "")) for p in players if str(p.get("nationality", "")) == "その他")
    group_counter = Counter((str(p.get("nationality", "")), str(p.get("name_group_name", ""))) for p in players)
    skin_counter = Counter(str(p.get("skin_color", "")) for p in players)
    skin_by_nation = Counter((str(p.get("nationality", "")), str(p.get("skin_color", ""))) for p in players)
    skin_by_group = Counter((str(p.get("name_group_name", "")), str(p.get("skin_color", ""))) for p in players)
    surname_by_nation: dict[str, Counter[str]] = defaultdict(Counter)
    given_by_nation: dict[str, Counter[str]] = defaultdict(Counter)
    full_name_counter = Counter(str(p.get("name", "")) for p in players)

    initials = 0
    excluded_last = 0
    for player in players:
        surname, given = split_name(player)
        nation = str(player.get("nationality", ""))
        surname_by_nation[nation][surname] += 1
        given_by_nation[nation][given] += 1
        if re.fullmatch(r"(?:[A-Z]\.){1,3}", given.replace(" ", "")):
            initials += 1
        if surname in EXCLUDED_LAST_NAMES:
            excluded_last += 1

    name_group_rows = [
        {"国籍": nation, "name_group": group, "件数": count, "割合%": pct(count, display_counter[nation])}
        for (nation, group), count in group_counter.most_common()
    ]
    top_surname_rows = [
        {"国籍": nation, "姓": name, "件数": count}
        for nation, counter in sorted(surname_by_nation.items())
        for name, count in counter.most_common(20)
    ]
    top_given_rows = [
        {"国籍": nation, "名": name, "件数": count}
        for nation, counter in sorted(given_by_nation.items())
        for name, count in counter.most_common(20)
    ]
    center_count = sum(display_counter[nation] for nation in CENTER_NATIONS)
    fallback_count = sum(1 for p in players if p.get("name_generation_fallback"))
    duplicate_full_names = sum(count - 1 for count in full_name_counter.values() if count > 1)
    metrics = [
        {"項目": "生成人数", "値": total},
        {"項目": "中心6か国合計%", "値": pct(center_count, total)},
        {"項目": "その他%", "値": pct(display_counter["その他"], total)},
        {"項目": "名前ユニーク率%", "値": pct(len(full_name_counter), total)},
        {"項目": "同姓同名率%", "値": pct(duplicate_full_names, total)},
        {"項目": "イニシャル名出現数", "値": initials},
        {"項目": "除外姓出現数", "値": excluded_last},
        {"項目": "フォールバック発生数", "値": fallback_count},
    ]
    center_diff_rows = [
        {
            "国籍": nation,
            "件数": display_counter[nation],
            "実績%": pct(display_counter[nation], total),
            "目標%": target,
            "差分pt": round(pct(display_counter[nation], total) - target, 2),
        }
        for nation, target in CENTER_TARGETS.items()
    ]
    warnings = []
    center_pct = pct(center_count, total)
    other_pct = pct(display_counter["その他"], total)
    if not 80 <= center_pct <= 88:
        warnings.append({"警告": "中心6か国が80～88%外", "値": center_pct})
    if not 2 <= other_pct <= 4:
        warnings.append({"警告": "その他が2～4%外", "値": other_pct})
    if initials:
        warnings.append({"警告": "イニシャル名が1件以上", "値": initials})
    if excluded_last:
        warnings.append({"警告": "除外姓が1件以上", "値": excluded_last})
    unresolved_groups = sum(1 for p in players if not p.get("name_group_name"))
    missing_actual = sum(1 for p in players if not p.get("actual_nationality"))
    if unresolved_groups:
        warnings.append({"警告": "name_group未解決", "値": unresolved_groups})
    if missing_actual:
        warnings.append({"警告": "actual_nationality欠損", "値": missing_actual})
    fixed_skin_nations = [
        nation for nation in display_counter
        if len({str(p.get("skin_color")) for p in players if p.get("nationality") == nation}) <= 1 and display_counter[nation] >= 20
    ]
    if fixed_skin_nations:
        warnings.append({"警告": "特定国で肌色が1種類に固定", "値": ", ".join(fixed_skin_nations)})
    if pct(fallback_count, total) > 1:
        warnings.append({"警告": "フォールバック率が高すぎる", "値": pct(fallback_count, total)})

    return {
        "metrics": metrics,
        "display_nationality_distribution": rows_from_counter(display_counter, total, "国籍"),
        "actual_nationality_distribution": rows_from_counter(actual_counter, total, "actual_nationality"),
        "center_nation_target_diff": center_diff_rows,
        "other_actual_nationality_top20": rows_from_counter(other_actual_counter, display_counter["その他"], "actual_nationality")[:20],
        "name_group_by_nationality": name_group_rows,
        "top20_surnames_by_nationality": top_surname_rows,
        "top20_given_names_by_nationality": top_given_rows,
        "skin_color_distribution": rows_from_counter(skin_counter, total, "肌色"),
        "skin_color_by_nationality": [
            {"国籍": nation, "肌色": skin, "件数": count, "割合%": pct(count, display_counter[nation])}
            for (nation, skin), count in skin_by_nation.most_common()
        ],
        "skin_color_by_name_group": [
            {"name_group": group, "肌色": skin, "件数": count}
            for (group, skin), count in skin_by_group.most_common()
        ],
        "warnings": warnings,
    }


def write_markdown(path: Path, tables: dict[str, list[dict[str, Any]]]) -> None:
    metrics = tables["metrics"]
    warnings = tables["warnings"]
    lines = ["# OOTP外国人名生成検証", ""]
    lines.extend(f"- {row['項目']}: {row['値']}" for row in metrics)
    lines.append("")
    lines.append("## 警告")
    lines.extend(f"- {row['警告']}: {row['値']}" for row in warnings) if warnings else lines.append("- なし")
    lines.append("")
    lines.append("## 上位国籍")
    for row in tables["display_nationality_distribution"][:12]:
        lines.append(f"- {row['国籍']}: {row['件数']}件 ({row['割合%']}%)")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="OOTP由来の外国人名・国籍・肌色生成を大量検証します。")
    parser.add_argument("--count", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20260714)
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/pawapuro-ootp-name-check"))
    args = parser.parse_args()

    players = generate_players(args.count, args.seed)
    tables = summarize(players)
    for name, rows in tables.items():
        write_csv(args.output_dir / f"{name}.csv", rows)
    write_markdown(args.output_dir / "summary.md", tables)
    print(f"検証結果を出力しました: {args.output_dir}")
    if tables["warnings"]:
        print(f"警告: {len(tables['warnings'])}件")


if __name__ == "__main__":
    main()
