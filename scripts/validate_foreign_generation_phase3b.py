"""外国人生成 Phase 3B の特殊能力・球種指標を軽量監査する。

実在ブックに特殊能力・球種明細がない場合は target を推測せず、生成側の
監視指標と回帰結果だけを出力する。
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app
from scripts import validate_foreign_generation_phase2 as phase2
from scripts import validate_foreign_generation_phase3a as phase3a


REAL_SHEET = "combined_2022_2025_complete"
EXPECTED_REAL_COUNTS = {"投手": 127, "野手": 85}
REAL_SPECIAL_COLUMNS = {
    "special_abilities", "specials", "normal_specials", "ranked_specials",
    "special", "special_kind",
}
REAL_PITCH_COLUMNS = {
    "breaking_balls", "breaking_ball", "pitch_type", "canonical_pitch_type",
    "direction_code", "movement", "is_second_pitch", "kind",
}
SPECIAL_KINDS = ("blue", "red", "mixed", "green", "gold", "rank")
PHASE3A_TARGETS = {
    "投手": {"球速": 156.24, "コントロール": 50.41, "スタミナ": 54.08},
    "野手": {
        "ミート": 46.47, "パワー": 70.17, "走力": 54.15,
        "肩力": 67.32, "守備力": 47.41, "捕球": 47.27,
        "6能力合計": 332.79,
    },
}


def load_real_scope(path: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    book = pd.ExcelFile(path)
    if REAL_SHEET not in book.sheet_names:
        raise ValueError(f"実在ブックに {REAL_SHEET!r} シートがありません。")
    frame = pd.read_excel(path, sheet_name=REAL_SHEET)
    if "include_foreign_analysis" in frame:
        included = frame["include_foreign_analysis"].fillna(False).astype(bool)
        frame = frame[included].copy()
    frame["role"] = frame["pitch_speed"].notna().map({True: "投手", False: "野手"})
    counts = frame["role"].value_counts().to_dict()
    if counts != EXPECTED_REAL_COUNTS:
        raise ValueError(f"実在対象人数が想定外です: {counts}")
    columns = set(map(str, frame.columns))
    coverage = {
        "対象player-season": len(frame),
        "投手": counts.get("投手", 0),
        "野手": counts.get("野手", 0),
        "特殊能力明細": bool(columns & REAL_SPECIAL_COLUMNS),
        "球種明細": bool(columns & REAL_PITCH_COLUMNS),
        "判定": (
            "取得可能" if columns & (REAL_SPECIAL_COLUMNS | REAL_PITCH_COLUMNS)
            else "実在側データ不足のため今回未調整"
        ),
    }
    return frame, coverage


def special_master_maps(master: app.MasterData) -> tuple[dict[str, str], dict[str, str]]:
    kind_by_name = {str(row.get("name", "")): str(row.get("kind", "")) for row in master.abilities}
    power_by_name = {str(row.get("name", "")): str(row.get("power", "")) for row in master.abilities}
    return kind_by_name, power_by_name


def ranked_non_d(player: dict) -> list[str]:
    ranked = player.get("abilities", {}).get("ranked_specials", {})
    if not isinstance(ranked, dict):
        return []
    return [str(value) for value in ranked.values() if str(value)[-1:] != "D"]


def special_metrics(player: dict, kind_by_name: dict[str, str], power_by_name: dict[str, str]) -> dict[str, object]:
    specials = [str(name) for name in player.get("special_abilities", [])]
    countable = [name for name in specials if app.is_countable_special(name)]
    ranks = ranked_non_d(player)
    kinds = Counter()
    for name in specials:
        if not app.is_countable_special(name):
            kinds["usage"] += 1
        elif power_by_name.get(name) == "gold":
            kinds["gold"] += 1
        else:
            kinds[kind_by_name.get(name, "unknown")] += 1
    return {
        "countable_specials": len(countable),
        "display_specials": len(specials) + len(ranks),
        **{f"special_{kind}": kinds[kind] for kind in SPECIAL_KINDS if kind != "rank"},
        "special_rank": len(ranks),
        "special_usage": kinds["usage"],
        "special_names": tuple(specials),
        "ranked_names": tuple(ranks),
    }


def pitch_metrics(player: dict) -> dict[str, object]:
    balls = list(player.get("breaking_balls", []))
    primary = [ball for ball in balls if ball.get("kind") == "breaking" and not ball.get("is_second_pitch")]
    second = [ball for ball in balls if ball.get("kind") == "breaking" and ball.get("is_second_pitch")]
    fastballs = [ball for ball in balls if ball.get("kind") == "second_fastball"]
    primary_by_direction = {str(ball.get("direction_code")): ball for ball in primary}
    differences = [
        app.pitch_movement(primary_by_direction[str(ball.get("direction_code"))]) - app.pitch_movement(ball)
        for ball in second
        if str(ball.get("direction_code")) in primary_by_direction
    ]
    return {
        "primary_directions": len(primary_by_direction),
        "breaking_pitch_count": len(primary) + len(second),
        "final_pitch_count": len(balls),
        "has_second_pitch": bool(second),
        "has_second_fastball": bool(fastballs),
        "second_pitch_movement": sum(app.pitch_movement(ball) for ball in second) / len(second) if second else float("nan"),
        "first_second_difference": sum(differences) / len(differences) if differences else float("nan"),
        "primary_total_movement": sum(app.pitch_movement(ball) for ball in primary),
        "all_breaking_total_movement": sum(app.pitch_movement(ball) for ball in primary + second),
        "movement_vector": "[" + ",".join(map(str, sorted((app.pitch_movement(ball) for ball in primary), reverse=True))) + "]",
        "primary_directions_list": tuple(str(ball.get("direction_code")) for ball in primary),
        "second_directions_list": tuple(str(ball.get("direction_code")) for ball in second),
        "second_fastball_names": tuple(str(ball.get("name", "")) for ball in fastballs),
    }


def player_row(player: dict, kind_by_name: dict[str, str], power_by_name: dict[str, str]) -> dict[str, object]:
    row = phase3a.player_row(player)
    row.update({
        "age_band": phase2.age_band(player["age"]) if hasattr(phase2, "age_band") else (
            "19-24" if player["age"] <= 24 else "25-27" if player["age"] <= 27
            else "28-30" if player["age"] <= 30 else "31-33" if player["age"] <= 33 else "34+"
        ),
        "route_group": "north_america_pro" if player["foreign_route"] == "north_america_pro" else "その他route",
    })
    row.update(special_metrics(player, kind_by_name, power_by_name))
    if player["role"] == "投手":
        row.update(pitch_metrics(player))
    return row


def generate_sample(count: int, base_seed: int) -> pd.DataFrame:
    master = app.load_master_data()
    kind_by_name, power_by_name = special_master_maps(master)
    rows = []
    for role_index, role in enumerate(phase2.ROLES):
        for offset in range(count):
            player = app.generate_player(
                role, "助っ人外国人用", master,
                seed=base_seed + role_index * 10_000_000 + offset,
            )
            rows.append(player_row(player, kind_by_name, power_by_name))
    return pd.DataFrame(rows)


def percentile(values: pd.Series, q: float) -> float:
    return float(values.quantile(q))


def special_count_rows(frame: pd.DataFrame, dataset: str) -> list[dict[str, object]]:
    rows = []
    for role in phase2.ROLES:
        values = frame.loc[frame["role"].eq(role), "countable_specials"]
        summary = {
            "平均": values.mean(), "中央値": values.median(), "P75": percentile(values, .75),
            "P90": percentile(values, .90), "P95": percentile(values, .95), "最大": values.max(),
            "5個以上率_pct": 100 * values.ge(5).mean(), "8個以上率_pct": 100 * values.ge(8).mean(),
        }
        for metric, value in summary.items():
            rows.append({"dataset": dataset, "守備": role, "指標": metric, "値": round(float(value), 2)})
        bands = {
            "0-2個": values.le(2), "3-4個": values.between(3, 4),
            "5-7個": values.between(5, 7), "8個以上": values.ge(8),
        }
        for label, mask in bands.items():
            rows.append({"dataset": dataset, "守備": role, "指標": label, "値": round(100 * mask.mean(), 2)})
    return rows


def special_kind_rows(frame: pd.DataFrame, dataset: str) -> list[dict[str, object]]:
    rows = []
    for role in phase2.ROLES:
        part = frame[frame["role"].eq(role)]
        for kind in (*SPECIAL_KINDS, "usage"):
            column = f"special_{kind}"
            rows.append({
                "dataset": dataset, "守備": role, "区分": kind,
                "1人平均": round(float(part[column].mean()), 3),
                "保有率_pct": round(100 * float(part[column].gt(0).mean()), 2),
            })
    return rows


def special_top_rows(frame: pd.DataFrame, dataset: str) -> list[dict[str, object]]:
    rows = []
    for role in phase2.ROLES:
        part = frame[frame["role"].eq(role)]
        counts = Counter(name for names in part["special_names"] for name in names)
        counts.update(name for names in part["ranked_names"] for name in names)
        for name, count in counts.most_common(30):
            rows.append({"dataset": dataset, "守備": role, "特殊能力": name, "件数": count, "出現率_pct": round(100 * count / len(part), 2)})
    return rows


def grouped_special_rows(frame: pd.DataFrame, dataset: str) -> list[dict[str, object]]:
    rows = []
    for columns, label in [(["role", "在籍年数帯"], "tenure"), (["role", "player_class"], "player_class")]:
        for keys, part in frame.groupby(columns, observed=False):
            role, group = keys
            values = part["countable_specials"]
            rows.append({
                "dataset": dataset, "集計": label, "守備": role, "区分": group, "人数": len(part),
                "平均": round(float(values.mean()), 2), "5個以上率_pct": round(100 * float(values.ge(5).mean()), 2),
                "8個以上率_pct": round(100 * float(values.ge(8).mean()), 2),
            })
    return rows


def distribution_rows(values: pd.Series, labels: list[str], dataset: str, metric: str) -> list[dict[str, object]]:
    counts = values.value_counts()
    total = len(values)
    return [{"dataset": dataset, "指標": metric, "区分": label, "人数": int(counts.get(label, 0)), "割合_pct": round(100 * int(counts.get(label, 0)) / total, 2)} for label in labels]


def pitch_report_frames(frame: pd.DataFrame, dataset: str) -> dict[str, pd.DataFrame]:
    pitchers = frame[frame["role"].eq("投手")].copy()
    pitch_labels = ["1球種", "2球種", "3球種", "4球種", "5球種以上"]
    pitch_band = pitchers["final_pitch_count"].map(lambda value: f"{int(value)}球種" if value < 5 else "5球種以上")
    pitch_count = pd.DataFrame(distribution_rows(pitch_band, pitch_labels, dataset, "最終総球種数"))
    for metric in ("primary_directions", "breaking_pitch_count"):
        labels = sorted(pitchers[metric].unique())
        rows = [{"dataset": dataset, "指標": metric, "区分": str(label), "人数": int(pitchers[metric].eq(label).sum()), "割合_pct": round(100 * float(pitchers[metric].eq(label).mean()), 2)} for label in labels]
        pitch_count = pd.concat([pitch_count, pd.DataFrame(rows)], ignore_index=True)

    movement_rows = []
    for metric in ("primary_total_movement", "all_breaking_total_movement"):
        values = pitchers[metric]
        for label, value in {
            "平均": values.mean(), "中央値": values.median(), "P75": percentile(values, .75),
            "P90": percentile(values, .90), "最大": values.max(),
        }.items():
            movement_rows.append({"dataset": dataset, "指標": metric, "統計": label, "値": round(float(value), 2)})
    movement_vectors = pitchers.groupby(["primary_directions", "movement_vector"], observed=False).size().reset_index(name="人数")
    movement_vectors["dataset"] = dataset
    movement_vectors["割合_pct"] = movement_vectors.groupby("primary_directions")["人数"].transform(lambda values: (100 * values / values.sum()).round(2))

    second_rows = []
    for group_name, part in [("全体", pitchers), *list(pitchers.groupby("position", observed=False))]:
        second_rows.append({
            "dataset": dataset, "役割": group_name, "人数": len(part),
            "第二球種率_pct": round(100 * float(part["has_second_pitch"].mean()), 2),
            "第二球種変化量平均": round(float(part["second_pitch_movement"].mean()), 2),
            "第一球種との差平均": round(float(part["first_second_difference"].mean()), 2),
        })
    fastball_rows = []
    for group_name, part in [("全体", pitchers), *list(pitchers.groupby("position", observed=False))]:
        fastball_rows.append({
            "dataset": dataset, "役割": group_name, "人数": len(part),
            "ストレート系第二種率_pct": round(100 * float(part["has_second_fastball"].mean()), 2),
            "併存breaking球種数平均": round(float(part.loc[part["has_second_fastball"], "breaking_pitch_count"].mean()), 2),
        })

    direction_counts = Counter(code for values in pitchers["primary_directions_list"] for code in values)
    direction_rows = [{
        "dataset": dataset, "direction_code": code, "方向": app.DIRECTION_NAMES.get(code, code),
        "件数": count, "投手保有率_pct": round(100 * count / len(pitchers), 2),
    } for code, count in sorted(direction_counts.items())]

    age_rows = []
    for grouping in ("age_band", "在籍年数帯", "route_group"):
        for label, part in pitchers.groupby(grouping, observed=False):
            age_rows.append({
                "dataset": dataset, "集計": grouping, "区分": label, "人数": len(part),
                "平均球種数": round(float(part["final_pitch_count"].mean()), 2),
                "平均primary_total_movement": round(float(part["primary_total_movement"].mean()), 2),
                "第二球種率_pct": round(100 * float(part["has_second_pitch"].mean()), 2),
                "ストレート系第二種率_pct": round(100 * float(part["has_second_fastball"].mean()), 2),
            })
    return {
        "pitch_count_compare.csv": pitch_count,
        "movement_compare.csv": pd.DataFrame(movement_rows),
        "movement_vector_compare.csv": movement_vectors,
        "second_pitch_compare.csv": pd.DataFrame(second_rows),
        "second_fastball_compare.csv": pd.DataFrame(fastball_rows),
        "pitch_direction_compare.csv": pd.DataFrame(direction_rows),
        "pitch_age_compare.csv": pd.DataFrame(age_rows),
    }


def ability_stability_rows(frame: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for role, targets in PHASE3A_TARGETS.items():
        part = frame[frame["role"].eq(role)]
        for metric, target in targets.items():
            actual = float(part[metric].mean())
            rows.append({"守備": role, "指標": metric, "Phase3A final": target, "Phase3B": round(actual, 2), "差": round(actual - target, 2)})
    return rows


def baseline_monitor_values(baseline_dir: Path | None) -> tuple[dict[tuple[str, str], float], dict[str, float]]:
    specials: dict[tuple[str, str], float] = {}
    pitches: dict[str, float] = {}
    if not baseline_dir:
        return specials, pitches
    special_path = baseline_dir / "special_count_compare.csv"
    if special_path.exists():
        data = pd.read_csv(special_path)
        for row in data.itertuples(index=False):
            specials[(str(row.守備), str(row.指標))] = float(row.値)
    pitch_path = baseline_dir / "pitch_count_compare.csv"
    if pitch_path.exists():
        data = pd.read_csv(pitch_path)
        for metric, target in (("最終総球種数", "平均最終総球種数"), ("primary_directions", "平均第一球種方向数")):
            part = data[data["指標"].eq(metric)]
            if not part.empty:
                numeric = part["区分"].astype(str).str.extract(r"(\d+)", expand=False).astype(float)
                pitches[target] = float((numeric * part["人数"]).sum() / part["人数"].sum())
    movement_path = baseline_dir / "movement_compare.csv"
    if movement_path.exists():
        data = pd.read_csv(movement_path)
        row = data[(data["指標"].eq("primary_total_movement")) & (data["統計"].eq("平均"))]
        if not row.empty:
            pitches["平均primary total movement"] = float(row.iloc[0]["値"])
    second_path = baseline_dir / "second_pitch_compare.csv"
    if second_path.exists():
        data = pd.read_csv(second_path)
        row = data[data["役割"].eq("全体")]
        if not row.empty:
            pitches["第二球種率_pct"] = float(row.iloc[0]["第二球種率_pct"])
    fastball_path = baseline_dir / "second_fastball_compare.csv"
    if fastball_path.exists():
        data = pd.read_csv(fastball_path)
        row = data[data["役割"].eq("全体")]
        if not row.empty:
            pitches["ストレート系第二種率_pct"] = float(row.iloc[0]["ストレート系第二種率_pct"])
    return specials, pitches


def markdown_table(frame: pd.DataFrame) -> str:
    return phase2.markdown_table(frame)


def write_reports(frame: pd.DataFrame, real_coverage: dict[str, object], output_dir: Path, baseline_dir: Path | None, test_result: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset = f"生成{int(frame['role'].eq('投手').sum()):,}人/role"
    special_count = pd.DataFrame(special_count_rows(frame, dataset))
    special_kind = pd.DataFrame(special_kind_rows(frame, dataset))
    special_top = pd.DataFrame(special_top_rows(frame, dataset))
    special_tenure = pd.DataFrame(grouped_special_rows(frame, dataset))
    pitch_frames = pitch_report_frames(frame, dataset)
    ability = pd.DataFrame(ability_stability_rows(frame))
    seed = pd.DataFrame(phase3a.seed_regression_rows())
    coverage = pd.DataFrame([real_coverage])
    frames = {
        "real_data_coverage.csv": coverage,
        "special_count_compare.csv": special_count,
        "special_kind_compare.csv": special_kind,
        "special_top_compare.csv": special_top,
        "special_tenure_compare.csv": special_tenure,
        "phase3a_ability_stability.csv": ability,
        "seed_regression.csv": seed,
        **pitch_frames,
    }
    for name, data in frames.items():
        data.to_csv(output_dir / name, index=False, encoding="utf-8-sig", lineterminator="\n")

    baseline_note = "500人/role baselineは未指定"
    if baseline_dir:
        baseline_file = baseline_dir / "special_count_compare.csv"
        if baseline_file.exists():
            baseline_note = f"500人/role baselineを `{baseline_dir.name}` に保存。モデル変更なしのため差はsampling差のみ。"

    special_focus = special_count[special_count["指標"].isin(["平均", "5個以上率_pct", "8個以上率_pct", "最大"])]
    pitch_focus = pd.DataFrame([
        {"指標": "平均最終総球種数", "値": round(float(frame.loc[frame['role'].eq('投手'), 'final_pitch_count'].mean()), 2)},
        {"指標": "平均第一球種方向数", "値": round(float(frame.loc[frame['role'].eq('投手'), 'primary_directions'].mean()), 2)},
        {"指標": "平均primary total movement", "値": round(float(frame.loc[frame['role'].eq('投手'), 'primary_total_movement'].mean()), 2)},
        {"指標": "第二球種率_pct", "値": round(100 * float(frame.loc[frame['role'].eq('投手'), 'has_second_pitch'].mean()), 2)},
        {"指標": "ストレート系第二種率_pct", "値": round(100 * float(frame.loc[frame['role'].eq('投手'), 'has_second_fastball'].mean()), 2)},
    ])
    baseline_specials, baseline_pitches = baseline_monitor_values(baseline_dir)
    special_compare = pd.DataFrame([
        {
            "守備": row.守備, "指標": row.指標, "実在": "取得不可",
            "修正前(500)": baseline_specials.get((row.守備, row.指標), "未実行"),
            "修正後(5,000)": row.値, "備考": "モデル変更なし・sampling差のみ",
        }
        for row in special_focus.itertuples(index=False)
    ])
    pitch_compare = pd.DataFrame([
        {
            "指標": row.指標, "実在": "取得不可",
            "修正前(500)": round(baseline_pitches[row.指標], 2) if row.指標 in baseline_pitches else "未実行",
            "修正後(5,000)": row.値, "備考": "モデル変更なし・sampling差のみ",
        }
        for row in pitch_focus.itertuples(index=False)
    ])
    top_vectors = pitch_frames["movement_vector_compare.csv"].sort_values("人数", ascending=False).head(10)
    age_focus = pitch_frames["pitch_age_compare.csv"]
    summary = f"""# 外国人生成基盤 Phase 3B

## 実在データの取得範囲

- `combined_2022_2025_complete` は分析対象212 player-season（投手127、野手85）を再現した。
- 通常能力、年齢、NPB在籍年数、routeは取得できた。
- 特殊能力・ランク特殊能力・球種・変化量の明細列は存在しない。
- 結論: **実在側データ不足のため今回未調整**。既存ページや別年度からtargetを推測していない。

## Phase 3B-S 特殊能力

- 修正前のcap（通常6、高能力foreign 7）と個別chanceを監査したが、実在分布を算出できないため変更していない。
- 青・赤・緑・ランク系、個別能力も生成側のみ監視。実在出現5件以上の判定ができないため個別倍率は追加していない。
- 修正前＝修正後。{baseline_note}

{markdown_table(special_compare)}

## Phase 3B-P 投手球種・変化量

- 実在側の球種数、方向、第二球種、ストレート系第二種、変化量、movement vectorを算出できないため変更していない。
- 年齢・tenure・route専用補正は追加していない。
- 修正前＝修正後。生成側の最終監視値は以下。

{markdown_table(pitch_compare)}

### 主要movement vector

{markdown_table(top_vectors[["primary_directions", "movement_vector", "人数", "割合_pct"]])}

### 年齢・tenure・route監視

{markdown_table(age_focus)}

## Phase 3A能力維持と回帰

{markdown_table(ability)}

- seed regression: {int(seed['result'].eq('PASS').sum())}/{len(seed)} PASS。
- pytest: {test_result}
- 最終シミュレーション: 投手 {int(frame['role'].eq('投手').sum()):,}人 / 野手 {int(frame['role'].eq('野手').sum()):,}人。
- app生成ロジックの変更なし。特殊能力と球種間のRNG系列も変更なし。

## 未解決残差 / Phase 3C送り

- 212 player-seasonに対応する特殊能力・ランク特殊能力・球種明細を含む実在データが得られた時点で3Bの実在比較を再開する。
- route別残差、体格、再来日率、外国人数、架空球団ロスター構成、獲得・退団を含むロスター動態はPhase 3C以降へ残す。
- 少標本route専用補正は追加していない。
"""
    (output_dir / "summary.md").write_text(summary, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-xlsx", type=Path, default=ROOT / "local_data" / "pawapuro_foreign_2022_2024_2025_complete_v6.xlsx")
    parser.add_argument("--players-per-role", type=int, default=5_000)
    parser.add_argument("--base-seed", type=int, default=9_280_000)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "foreign_generation_phase3b")
    parser.add_argument("--baseline-dir", type=Path)
    parser.add_argument("--test-result", default="pytestは別途実行")
    args = parser.parse_args()
    _real, coverage = load_real_scope(args.real_xlsx)
    frame = generate_sample(args.players_per_role, args.base_seed)
    write_reports(frame, coverage, args.output_dir, args.baseline_dir, args.test_result)
    print(f"実在{coverage['対象player-season']}件と生成{len(frame):,}人分のPhase 3B監査結果を {args.output_dir} に出力しました。")


if __name__ == "__main__":
    main()
