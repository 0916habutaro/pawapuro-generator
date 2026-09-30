"""助っ人外国人の生成サンプルを CSV に書き出す（check_foreign_balance.py 用）。

使い方:
    python scripts/generate_foreign_balance_sample.py 投手 1000 reports/foreign_pitchers.csv [開始seed]

seed は開始seedから連番で使うため、同じ引数なら毎回同じ選手が生成される。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402


def player_row(player: dict) -> dict:
    abilities = dict(player.get("abilities", {}))
    ranked = abilities.get("ranked_specials", {})
    row = {key: value for key, value in player.items() if not isinstance(value, (dict, list))}
    row.update({
        "abilities_json": json.dumps(abilities, ensure_ascii=False),
        "special_abilities_json": json.dumps(player.get("special_abilities", []), ensure_ascii=False),
        "ranked_special_abilities_json": json.dumps(ranked, ensure_ascii=False),
        "breaking_balls_json": json.dumps(player.get("breaking_balls", []), ensure_ascii=False),
        "sub_positions_json": json.dumps(player.get("sub_positions", []), ensure_ascii=False),
    })
    return row


def main(role: str = "投手", count: int = 1000, out: str = "reports/foreign_balance_sample.csv", seed_start: int = 1) -> None:
    master = app.load_master_data()
    rows = [player_row(app.generate_player(role, "助っ人外国人用", master, seed=seed)) for seed in range(seed_start, seed_start + count)]
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"{len(rows)}人を書き出しました: {out}")


if __name__ == "__main__":
    args = sys.argv[1:]
    main(
        args[0] if args else "投手",
        int(args[1]) if len(args) > 1 else 1000,
        args[2] if len(args) > 2 else "reports/foreign_balance_sample.csv",
        int(args[3]) if len(args) > 3 else 1,
    )
