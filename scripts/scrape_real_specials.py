from __future__ import annotations

import argparse
import html
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import (  # noqa: E402
    CATEGORIES,
    SPECIAL_KIND_LABELS,
    STRONG_SPECIALS,
    generate_player,
    is_ranked_special,
    load_master_data,
)

CACHE_DIR = ROOT / "data" / "source_cache"
REPORT_PATH = ROOT / "reports" / "real_special_balance_comparison.md"
SAMPLE_PER_ROLE = 5000
PAGES = {
    "SPP": {"file": "abi_SPP_1_11.html", "role": "投手", "polarity": "プラス", "url": "http://www.baseless.org/data/2026/abi_SPP_1_11.html"},
    "SPM": {"file": "abi_SPM_1_11.html", "role": "投手", "polarity": "マイナス", "url": "http://www.baseless.org/data/2026/abi_SPM_1_11.html"},
    "SBP": {"file": "abi_SBP_1_11.html", "role": "野手", "polarity": "プラス", "url": "http://www.baseless.org/data/2026/abi_SBP_1_11.html"},
    "SBM": {"file": "abi_SBM_1_11.html", "role": "野手", "polarity": "マイナス", "url": "http://www.baseless.org/data/2026/abi_SBM_1_11.html"},
}
RANKS = ["A", "B", "C", "E", "F", "G"]
ABILITY_NORMALIZATION = {"対ランナー○": "対ランナー"}
ROLE_ABILITY_NORMALIZATION = {"存在感": {"投手": "投手存在感", "野手": "野手存在感"}}


@dataclass
class PageStatus:
    page: str
    source: str
    status: str
    ability_count: int
    pair_count: int
    detail: str = ""


@dataclass
class RealData:
    player_specials: dict[tuple[str, str], set[str]]
    page_statuses: list[PageStatus]
    excluded: Counter[str]


def read_page(page: str, info: dict[str, str]) -> tuple[str | None, str, str, str]:
    cache_path = CACHE_DIR / info["file"]
    if cache_path.exists():
        return cache_path.read_bytes().decode("shift_jis", errors="ignore"), "cache", "OK", ""
    try:
        req = urllib.request.Request(info["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
        return raw.decode("shift_jis", errors="ignore"), "url", "OK", ""
    except Exception as exc:  # noqa: BLE001 - report fetch failure and continue other pages
        return None, "url", "取得失敗", f"{type(exc).__name__}: {exc}"


def strip_tags(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).replace("\xa0", " ").strip()


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", "", value)


def parse_ability_name(cell: str) -> str:
    parts = [strip_tags(match) for match in re.findall(r"<b\b[^>]*>(.*?)</b>", cell, flags=re.I | re.S)]
    text = "".join(parts) if parts else strip_tags(cell)
    return normalize_space(text)


def parse_player_names(cell: str) -> list[str]:
    names = []
    for attrs, body in re.findall(r"<b\b([^>]*)>(.*?)</b>", cell, flags=re.I | re.S):
        class_match = re.search(r'class=["\']?([^"\' >]+)', attrs, flags=re.I)
        classes = set((class_match.group(1) if class_match else "").split())
        if "tl" in classes or any(cls.startswith("tm") for cls in classes):
            continue
        name = normalize_space(strip_tags(body))
        if name:
            names.append(name)
    return names


def normalize_ability_name(name: str, role: str) -> str:
    if name in ROLE_ABILITY_NORMALIZATION:
        return ROLE_ABILITY_NORMALIZATION[name].get(role, name)
    return ABILITY_NORMALIZATION.get(name, name)


def extract_page(body: str, role: str, known_names: set[str]) -> tuple[dict[tuple[str, str], set[str]], Counter[str], int, int]:
    player_specials: dict[tuple[str, str], set[str]] = defaultdict(set)
    excluded: Counter[str] = Counter()
    ability_count = 0
    pair_count = 0
    rows = re.findall(r"<tr>(.*?)</tr>", body, flags=re.I | re.S)
    for row in rows:
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, flags=re.I | re.S)
        if len(cells) < 2:
            continue
        ability = normalize_ability_name(parse_ability_name(cells[0]), role)
        if not ability or ability == "特殊能力":
            continue
        players = parse_player_names(cells[1])
        if not players:
            continue
        ability_count += 1
        if ability not in known_names:
            excluded[ability] += len(players)
            continue
        for player in players:
            player_specials[(role, player)].add(ability)
            pair_count += 1
    return player_specials, excluded, ability_count, pair_count


def collect_real_data(master) -> RealData:
    known_names = {str(row["name"]) for row in master.abilities}
    all_players: dict[tuple[str, str], set[str]] = defaultdict(set)
    all_excluded: Counter[str] = Counter()
    statuses = []
    for page, info in PAGES.items():
        body, source, status, detail = read_page(page, info)
        if body is None:
            statuses.append(PageStatus(page, source, status, 0, 0, detail))
            continue
        players, excluded, ability_count, pair_count = extract_page(body, info["role"], known_names)
        for key, values in players.items():
            all_players[key].update(values)
        all_excluded.update(excluded)
        statuses.append(PageStatus(page, source, status, ability_count, pair_count, detail))
    return RealData(dict(all_players), statuses, all_excluded)


def generate_samples(master):
    players = []
    seed = 202607080000
    for role in ("投手", "野手"):
        for i in range(SAMPLE_PER_ROLE):
            players.append(generate_player(role, CATEGORIES[i % len(CATEGORIES)], master, seed + len(players)))
    return players


def md_table(headers: list[str], rows: Iterable[Iterable[object]]) -> str:
    rows = [[str(c) for c in row] for row in rows]
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"] + ["| " + " | ".join(row) + " |" for row in rows])


def kind_label_map(master):
    return {str(row["name"]): SPECIAL_KIND_LABELS.get(str(row.get("kind")), "不明") for row in master.abilities}


def ranked_groups(master):
    return {str(row["name"]): str(row.get("group", "")) for row in master.abilities if is_ranked_special(row)}


def normal_names(master):
    ranked = set(ranked_groups(master))
    return {str(row["name"]) for row in master.abilities if str(row["name"]) not in ranked}


def real_classification(real: RealData, master):
    ranked = set(ranked_groups(master))
    normal = normal_names(master)
    normal_by_player = {player: {s for s in specials if s in normal} for player, specials in real.player_specials.items()}
    ranked_by_player = {player: {s for s in specials if s in ranked and not s.endswith("D")} for player, specials in real.player_specials.items()}
    return normal_by_player, ranked_by_player


def summarize_real(real: RealData, master) -> list[str]:
    kind_by_name = kind_label_map(master)
    group_by_name = ranked_groups(master)
    normal_by_player, ranked_by_player = real_classification(real, master)
    lines = []
    players = real.player_specials
    pitcher_count = sum(1 for role, _ in players if role == "投手")
    fielder_count = sum(1 for role, _ in players if role == "野手")
    normal_counts_by_player = [len(vals) for vals in normal_by_player.values()]
    ranked_counts_by_player = [len(vals) for vals in ranked_by_player.values()]
    all_normal = [s for vals in normal_by_player.values() for s in vals]
    all_ranked = [s for vals in ranked_by_player.values() for s in vals]
    normal_counter = Counter(all_normal)
    red_counter = Counter(s for s in all_normal if kind_by_name.get(s) == "赤特")
    kind_counts = Counter(kind_by_name.get(s, "不明") for s in all_normal)
    ranked_dist = Counter(s[-1] for s in all_ranked if s[-1] in RANKS)
    group_ranked_dist: dict[str, Counter[str]] = defaultdict(Counter)
    for special in all_ranked:
        group_ranked_dist[group_by_name.get(special, special[:-1])][special[-1]] += 1
    efg_counter = Counter(s for s in all_ranked if s[-1] in {"E", "F", "G"})
    normal_total = sum(kind_counts.values()) or 1
    lines.append("## 実在データサマリー")
    lines.append(md_table(["項目", "値"], [["実在選手数", len(players)], ["投手", pitcher_count], ["野手", fielder_count], ["1人あたり通常特殊能力数", f"{sum(normal_counts_by_player)/len(players):.3f}"], ["1人あたりランク系非D特殊能力数", f"{sum(ranked_counts_by_player)/len(players):.3f}"]]))
    lines.append("\n## 通常特殊能力: 青特/赤特/青赤特割合")
    lines.append(md_table(["種別", "件数", "割合"], [[k, kind_counts.get(k, 0), f"{kind_counts.get(k, 0)/normal_total*100:.2f}%"] for k in ["青特", "赤特", "青赤特"]]))
    lines.append("\n## 通常特殊能力上位30")
    lines.append(md_table(["能力", "件数"], normal_counter.most_common(30)))
    lines.append("\n## 通常特殊能力: 赤特上位")
    lines.append(md_table(["能力", "件数"], red_counter.most_common(30)))
    lines.append("\n## 通常特殊能力: 強特能出現数")
    lines.append(md_table(["能力", "件数"], [[name, normal_counter.get(name, 0)] for name in sorted(STRONG_SPECIALS)]))
    lines.append("\n## ランク系特殊能力: A/B/C/E/F/G分布")
    lines.append(md_table(["ランク", "件数"], [[r, ranked_dist.get(r, 0)] for r in RANKS]))
    lines.append("\n## ランク系特殊能力: グループ別A/B/C/E/F/G分布")
    lines.append(md_table(["グループ", *RANKS], [[group, *[counts.get(rank, 0) for rank in RANKS]] for group, counts in sorted(group_ranked_dist.items())]))
    lines.append("\n## ランク系特殊能力: E/F/G上位")
    lines.append(md_table(["能力", "件数"], efg_counter.most_common(30)))
    return lines

def generated_comparison(master, real: RealData) -> str:
    samples = generate_samples(master)
    kind_by_name = kind_label_map(master)
    _, real_ranked_by_player = real_classification(real, master)
    real_normal_by_player, _ = real_classification(real, master)
    real_normal = [s for vals in real_normal_by_player.values() for s in vals]
    gen_normal = [name for p in samples for name in p["special_abilities"]]
    gen_ranked_non_d = [name for p in samples for name in p["abilities"].get("ranked_specials", {}).values() if not name.endswith("D")]
    real_ranked_non_d = [s for vals in real_ranked_by_player.values() for s in vals]
    real_normal_total = len(real_normal) or 1
    gen_normal_total = len(gen_normal) or 1
    real_red_rate = sum(1 for s in real_normal if kind_by_name.get(s) == "赤特") / real_normal_total * 100
    gen_red_rate = sum(1 for s in gen_normal if kind_by_name.get(s) == "赤特") / gen_normal_total * 100
    real_mixed_rate = sum(1 for s in real_normal if kind_by_name.get(s) == "青赤特") / real_normal_total * 100
    gen_mixed_rate = sum(1 for s in gen_normal if kind_by_name.get(s) == "青赤特") / gen_normal_total * 100
    gen_green_rate = sum(1 for s in gen_normal if kind_by_name.get(s) == "緑特") / gen_normal_total * 100
    return "\n".join([
        "## 生成ロジック結果との横並び比較",
        md_table(
            ["項目", "実在", "生成", "備考"],
            [
                ["通常特殊能力平均", f"{len(real_normal)/len(real.player_specials):.3f}", f"{len(gen_normal)/len(samples):.3f}", "実在normal_specials / 生成special_abilities"],
                ["ランク系非D平均", f"{len(real_ranked_non_d)/len(real.player_specials):.3f}", f"{len(gen_ranked_non_d)/len(samples):.3f}", "A/B/C/E/F/Gのみ。Dは標準扱いで除外"],
                ["通常赤特割合", f"{real_red_rate:.2f}%", f"{gen_red_rate:.2f}%", "normal_specialsのred"],
                ["青赤特割合", f"{real_mixed_rate:.2f}%", f"{gen_mixed_rate:.2f}%", "normal_specialsのmixed"],
                ["緑特割合", "比較対象外", f"{gen_green_rate:.2f}%", "今回の実在4ページでは緑特が掲載されていない可能性があるため生成側のみ参考値"],
            ],
        ),
    ])

def write_report(real: RealData, master, completed: bool) -> None:
    REPORT_PATH.parent.mkdir(exist_ok=True)
    lines = ["# 実在選手特殊能力比較レポート"]
    lines.append("\n## 集計注記")
    lines.append("- 実在ページではランク系Dは標準のため未掲載として扱い、A/B/C/E/F/Gのみをランク系非D特殊能力として集計します。")
    lines.append("- 今回の対象4ページでは緑特が掲載されていない可能性があるため、緑特比較は参考外です。")
    lines.append("- special_abilities.csv に存在しない能力は除外しています。")
    if not completed:
        lines.append("\n**実在データ未取得のため比較未完了**")
    lines.append("\n## ページ別取得状況")
    lines.append(md_table(["ページ", "取得元", "ステータス", "抽出能力数", "抽出選手能力ペア数", "詳細"], [[s.page, s.source, s.status, s.ability_count, s.pair_count, s.detail] for s in real.page_statuses]))
    lines.append("\n## special_abilities.csv に存在しないため除外した能力")
    lines.append(md_table(["能力", "件数"], real.excluded.most_common() or [["なし", 0]]))
    if completed:
        lines.extend(["", *summarize_real(real, master), "", generated_comparison(master, real)])
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="実在選手特殊能力と生成ロジックの分布を比較します。")
    parser.add_argument("--allow-empty-real-data", action="store_true", help="実在データ0件でも終了コード0にします。")
    args = parser.parse_args()
    master = load_master_data()
    real = collect_real_data(master)
    completed = len(real.player_specials) > 0
    write_report(real, master, completed)
    print(f"report={REPORT_PATH}")
    if not completed and not args.allow_empty_real_data:
        print("実在データ未取得のため比較未完了", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
