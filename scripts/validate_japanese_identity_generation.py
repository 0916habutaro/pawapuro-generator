from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


def pct(count: int, total: int) -> float:
    return round(count / total * 100, 4) if total else 0.0


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def prefecture_distribution(count: int, seed: int) -> list[dict[str, object]]:
    rng = random.Random(seed)
    counter = Counter(app.choose_japanese_prefecture(rng) for _ in range(count))
    rows = []
    for prefecture, weight in app.JAPANESE_PREFECTURE_WEIGHTS.items():
        expected_rate = app.JAPANESE_PREFECTURE_EXPECTED_RATES[prefecture] * 100
        generated_count = counter[prefecture]
        generated_rate = pct(generated_count, count)
        rows.append({
            "都道府県": prefecture,
            "設定重み": weight,
            "期待割合%": round(expected_rate, 4),
            "生成人数": generated_count,
            "生成割合%": generated_rate,
            "期待値との差pt": round(generated_rate - expected_rate, 4),
        })
    return rows


def surname_distribution(prefectures: list[str], count: int, seed: int) -> list[dict[str, object]]:
    master = app.load_japanese_surname_master()
    rows: list[dict[str, object]] = []
    for index, prefecture in enumerate(prefectures):
        rng = random.Random(seed + index)
        counter = Counter(app.choose_japanese_surname(prefecture, rng, master) for _ in range(count))
        weight_by_surname = dict(zip(master[prefecture]["surnames"], master[prefecture]["weights"], strict=True))
        for surname, generated_count in counter.most_common(20):
            rows.append({
                "都道府県": prefecture,
                "苗字": surname,
                "number": weight_by_surname[surname],
                "生成人数": generated_count,
                "生成割合%": pct(generated_count, count),
            })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="日本人選手の出身都道府県・苗字生成を検証します。")
    parser.add_argument("--count", type=int, default=100000)
    parser.add_argument("--surname-count", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=20260714)
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/pawapuro-japanese-identity-check"))
    parser.add_argument("--prefecture", action="append", dest="prefectures", default=None)
    args = parser.parse_args()

    if args.count < 100000:
        raise SystemExit("--count は100000以上を指定してください。")

    master = app.load_japanese_surname_master()
    missing = set(app.JAPANESE_PREFECTURE_WEIGHTS) - set(master)
    if missing:
        raise SystemExit(f"苗字マスタに存在しない都道府県があります: {', '.join(sorted(missing))}")

    prefecture_rows = prefecture_distribution(args.count, args.seed)
    surname_rows = surname_distribution(args.prefectures or ["大阪府", "東京都", "北海道", "沖縄県"], args.surname_count, args.seed + 1000)
    write_csv(args.output_dir / "prefecture_distribution.csv", prefecture_rows)
    write_csv(args.output_dir / "surname_distribution.csv", surname_rows)

    print(f"検証結果を出力しました: {args.output_dir}")
    print("都道府県抽選 上位:")
    for row in sorted(prefecture_rows, key=lambda item: int(item["生成人数"]), reverse=True)[:10]:
        print(f"- {row['都道府県']}: {row['生成人数']}件 ({row['生成割合%']}%, 期待差 {row['期待値との差pt']}pt)")
    print("苗字抽選 上位:")
    for row in surname_rows[:12]:
        print(f"- {row['都道府県']} {row['苗字']}: {row['生成人数']}件 (number={row['number']})")


if __name__ == "__main__":
    main()
