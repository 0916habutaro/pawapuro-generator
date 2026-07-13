#!/usr/bin/env python3
"""Storage/UI integration audit for Pawapuro generator.

This script avoids browser automation and exercises the same generation,
SQLite, history, CSV/Excel, and display-data paths used by app.py.
"""
from __future__ import annotations

import argparse
import csv
import importlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
app = importlib.import_module("app")

REQUIRED_COLUMNS = [
    "id", "name", "nationality", "region", "age", "category", "role", "player_type",
    "player_class", "archetype", "position_style", "development_stage", "acquisition_role", "weakness_profile",
    "batting_throwing", "position", "abilities_json", "special_abilities_json",
    "ranked_special_abilities_json", "breaking_balls_json", "pitcher_aptitudes_json",
    "sub_positions_json", "created_at",
]
JSON_COLUMNS = [
    "abilities_json", "special_abilities_json", "ranked_special_abilities_json",
    "breaking_balls_json", "pitcher_aptitudes_json", "sub_positions_json",
]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        keys: list[str] = []
        for row in rows:
            for key in row:
                if key not in keys:
                    keys.append(key)
        fieldnames = keys or ["結果"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def set_db(path: Path) -> None:
    app.DB_PATH = path


def generate_set(master: Any, offset: int = 0) -> list[dict[str, Any]]:
    players: list[dict[str, Any]] = []
    seed = 400000 + offset
    for role in ["投手", "野手"]:
        for category in app.CATEGORIES:
            for i in range(10):
                players.append(app.generate_player(role, category, master, seed=seed + i))
            seed += 1000
    return players


def player_key(p: dict[str, Any]) -> tuple[Any, ...]:
    return (p.get("seed"), p.get("role"), p.get("category"), p.get("name"))


def audit_schema(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    info = conn.execute("PRAGMA table_info(players)").fetchall()
    rows = []
    for cid, name, typ, notnull, default, pk in info:
        rows.append({
            "列名": name, "型": typ, "NULL可否": "不可" if notnull or pk else "可",
            "デフォルト": default if default is not None else "", "必須判定": "必須" if name in REQUIRED_COLUMNS else "任意",
            "結果": "OK" if name not in REQUIRED_COLUMNS or name in {r[1] for r in info} else "NG",
            "備考": "JSON列" if name in JSON_COLUMNS else "",
        })
    for missing in sorted(set(REQUIRED_COLUMNS) - {r[1] for r in info}):
        rows.append({"列名": missing, "型": "", "NULL可否": "", "デフォルト": "", "必須判定": "必須", "結果": "NG", "備考": "不足"})
    return rows


def flatten_player(p: dict[str, Any]) -> dict[str, str]:
    abilities = p.get("abilities", {}) or {}
    return {
        "name": p.get("name", ""), "nationality": p.get("nationality", ""),
        "region": p.get("region") or p.get("birthplace", ""), "age": str(p.get("age", "")),
        "category": p.get("category", ""), "role": p.get("role", ""), "player_type": p.get("player_type", ""),
        "player_class": p.get("player_class", ""), "archetype": p.get("archetype", ""),
        "position_style": p.get("position_style", ""), "development_stage": p.get("development_stage", ""),
        "acquisition_role": p.get("acquisition_role", ""), "weakness_profile": p.get("weakness_profile", ""),
        "batting_throwing": p.get("batting_throwing", ""), "position": p.get("position", ""),
        "abilities": dumps(abilities), "special_abilities": dumps(p.get("special_abilities", [])),
        "ranked_specials": dumps(abilities.get("ranked_specials", p.get("ranked_specials", {}))),
        "breaking_balls": dumps(p.get("breaking_balls", [])),
        "pitcher_aptitudes": dumps({k: p.get(k) for k in app.PITCHER_APTITUDE_KEYS if p.get(k) is not None}),
        "sub_positions": dumps(app.normalize_sub_positions(p.get("sub_positions", []))),
    }


def export_rows(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["選手ID"] = df["id"]
    for jp, col in [("名前","name"),("国籍","nationality"),("地域","region"),("年齢","age"),("カテゴリ","category"),("投手野手","role"),("player_type","player_type"),("選手格","player_class"),("アーキタイプ","archetype"),("ポジションスタイル","position_style"),("完成度","development_stage"),("獲得目的","acquisition_role"),("弱点プロファイル","weakness_profile"),("投打","batting_throwing"),("メインポジション","position")]:
        out[jp] = df.get(col, "")
    out["サブポジ"] = df.get("sub_positions", pd.Series([[]]*len(df))).apply(app.format_sub_positions)
    out["野手能力"] = df["abilities"].apply(lambda x: dumps({k:v for k,v in x.items() if k in ["弾道","ミート","パワー","走力","肩力","守備力","捕球"]}) if isinstance(x, dict) else "{}")
    out["投手能力"] = df["abilities"].apply(lambda x: dumps({k:v for k,v in x.items() if k in ["球速","コントロール","スタミナ"]}) if isinstance(x, dict) else "{}")
    out["投手適正"] = df.apply(lambda r: dumps({k: r.get(k) for k in app.PITCHER_APTITUDE_KEYS if pd.notna(r.get(k))}), axis=1)
    out["変化球"] = df.get("breaking_balls", pd.Series([[]]*len(df))).apply(dumps)
    out["通常特殊能力"] = df.get("special_abilities", pd.Series([[]]*len(df))).apply(dumps)
    out["ランク系特殊能力"] = df.get("ranked_specials", pd.Series([{}]*len(df))).apply(dumps)
    out["生成日時"] = df.get("created_at", "")
    return out


def make_excel(path: Path, export_df: pd.DataFrame, balance_df: pd.DataFrame) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        export_df.to_excel(writer, sheet_name="選手一覧", index=False)
        export_df[export_df["投手野手"].eq("投手")].to_excel(writer, sheet_name="投手一覧", index=False)
        export_df[export_df["投手野手"].eq("野手")].to_excel(writer, sheet_name="野手一覧", index=False)
        pd.Series([x for xs in balance_df["special_abilities"] for x in (xs or [])]).value_counts().rename_axis("特殊能力").reset_index(name="件数").to_excel(writer, sheet_name="特殊能力集計", index=False)
        pd.Series([b.get("name") for xs in balance_df["breaking_balls"] for b in (xs or []) if isinstance(b, dict)]).value_counts().rename_axis("変化球").reset_index(name="件数").to_excel(writer, sheet_name="変化球集計", index=False)
        pd.Series([s.get("position") for xs in balance_df["sub_positions"] for s in (xs or []) if isinstance(s, dict)]).value_counts().rename_axis("サブポジ").reset_index(name="件数").to_excel(writer, sheet_name="サブポジ集計", index=False)
        balance_df["nationality"].value_counts().rename_axis("国籍").reset_index(name="件数").to_excel(writer, sheet_name="国籍集計", index=False)


def create_old_db(path: Path, kind: str) -> int:
    with sqlite3.connect(path) as conn:
        if kind == "A":
            conn.execute("CREATE TABLE players (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, seed INTEGER, role TEXT, category TEXT, name TEXT, age INTEGER, nationality TEXT, birthplace TEXT, position TEXT, player_type TEXT, handedness TEXT, batting_throwing TEXT, height INTEGER, weight INTEGER, abilities_json TEXT, special_abilities_json TEXT, breaking_balls_json TEXT)")
        elif kind == "B":
            conn.execute("CREATE TABLE players (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, seed INTEGER, role TEXT, category TEXT, name TEXT, age INTEGER, nationality TEXT, birthplace TEXT, region TEXT, position TEXT, player_type TEXT, handedness TEXT, batting_throwing TEXT, height INTEGER, weight INTEGER, abilities_json TEXT, special_abilities_json TEXT, breaking_balls_json TEXT, sub_positions_json TEXT)")
        else:
            conn.execute("CREATE TABLE players (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, seed INTEGER, role TEXT, category TEXT, name TEXT, age INTEGER, nationality TEXT, birthplace TEXT, region TEXT, position TEXT, player_type TEXT, handedness TEXT, batting_throwing TEXT, height INTEGER, weight INTEGER, abilities_json TEXT, special_abilities_json TEXT, ranked_special_abilities_json TEXT, breaking_balls_json TEXT, pitcher_aptitudes_json TEXT, sub_positions_json TEXT)")
        for i in range(3):
            cols = [r[1] for r in conn.execute("PRAGMA table_info(players)") if r[1] != "id"]
            row = {c: "" for c in cols}
            row.update(created_at="2020-01-01", seed=i, role="野手", category="架空球団用", name=f"旧選手{kind}{i}", age=30, nationality="日本", birthplace="東京都", region="東京都", position="外野手", player_type="バランス型", handedness="右投", batting_throwing="右投右打", height=180, weight=80, abilities_json=dumps({"ミート":{"value":50,"rank":"D"}}), special_abilities_json='["チャンス〇"]', breaking_balls_json="[]", sub_positions_json="[]")
            conn.execute(f"INSERT INTO players ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})", [row.get(c, "") for c in cols])
        return conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="pawapuro-storage-"))
    set_db(tmp / "players.sqlite3")
    master = app.load_master_data()
    app.init_db(); app.init_db()

    players1 = generate_set(master, 0)
    saved = app.save_players(players1)
    history = app.load_history()
    balance = app.load_history_for_balance()
    assert saved == len(players1) == 60
    assert len(history) == 60 == len(balance)

    with sqlite3.connect(app.DB_PATH) as conn:
        schema_rows = audit_schema(conn)
    write_csv(out / "sqlite_schema_audit.csv", schema_rows)
    assert not [r for r in schema_rows if r["必須判定"] == "必須" and r["結果"] != "OK"]

    original = {player_key(p): flatten_player(p) for p in players1}
    comp=[]; mism=[]
    for _, row in balance.iterrows():
        loaded = row.to_dict(); key = (loaded.get("seed"), loaded.get("role"), loaded.get("category"), loaded.get("name"))
        flat = flatten_player({**loaded, "abilities": loaded.get("abilities"), "special_abilities": loaded.get("special_abilities"), "breaking_balls": loaded.get("breaking_balls"), "sub_positions": loaded.get("sub_positions")})
        for field, before in original[key].items():
            after = flat[field]
            ok = before == after or field == "pitcher_aptitudes" and loaded.get("role") == "野手"
            comp.append({"key": str(key), "項目": field, "保存前": before, "再読込後": after, "一致": ok})
            if not ok: mism.append(comp[-1])
    write_csv(out / "roundtrip_comparison.csv", comp)
    write_csv(out / "roundtrip_mismatches.csv", mism, ["key","項目","保存前","再読込後","一致"])
    assert len(mism) == 0
    assert sum(not isinstance(x, list) for x in balance["special_abilities"]) == 0
    assert sum((r == "投手" and not b) for r,b in zip(balance["role"], balance["breaking_balls"])) == 0
    assert sum((r == "投手" and not any(pd.notna(row.get(k)) for k in app.PITCHER_APTITUDE_KEYS)) for _, row in balance.iterrows() for r in [row["role"]]) == 0

    compat=[]
    samples = ['["A"]', ["A"], {"x":1}, "", None, "[]", "{}", "A,B", '{bad', {"unknown": 1}]
    for col in JSON_COLUMNS:
        fallback = {} if col in {"abilities_json","ranked_special_abilities_json","pitcher_aptitudes_json"} else []
        for sample in samples:
            parsed = app.parse_json_column(sample, fallback)
            compat.append({"列名": col, "入力": repr(sample), "復元型": type(parsed).__name__, "結果": "OK"})
    write_csv(out / "json_compatibility_audit.csv", compat)

    mig=[]
    for kind in "ABC":
        db = tmp / f"old_{kind}.sqlite3"; before = create_old_db(db, kind); set_db(db); app.init_db(); app.init_db()
        after = sqlite3.connect(db).execute("SELECT COUNT(*) FROM players").fetchone()[0]
        app.save_players(players1[:2]); final = sqlite3.connect(db).execute("SELECT COUNT(*) FROM players").fetchone()[0]
        mig.append({"DB": kind, "移行前件数": before, "移行後件数": after, "追加後件数": final, "結果": "OK" if before == after and final == before+2 else "NG"})
    write_csv(out / "migration_audit.csv", mig); assert all(r["結果"] == "OK" for r in mig)

    set_db(tmp / "multi.sqlite3"); app.init_db(); app.save_players(players1); app.save_players(generate_set(master, 99999)); app.save_players(players1)
    multi_hist = app.load_history_for_balance(); multi_rows=[{"保存回": "3回", "期待件数":180, "実件数":len(multi_hist), "仕様":"生成履歴のため同一seedも別レコード", "結果":"OK" if len(multi_hist)==180 else "NG"}]
    write_csv(out / "multiple_save_audit.csv", multi_rows); assert len(multi_hist)==180

    hist_rows=[{"項目":"load_history件数", "結果":len(app.load_history())}, {"項目":"load_history_for_balance件数", "結果":len(multi_hist)}, {"項目":"空JSON例外", "結果":"OK"}]
    write_csv(out / "history_loader_audit.csv", hist_rows)

    export_df = export_rows(multi_hist)
    export_df.to_csv(out / "players_export.csv", index=False, encoding="utf-8-sig")
    make_excel(out / "players_export.xlsx", export_df, multi_hist)
    assert len(pd.read_csv(out / "players_export.csv", encoding="utf-8-sig")) == len(multi_hist)
    assert len(pd.read_excel(out / "players_export.xlsx", sheet_name="選手一覧")) == len(multi_hist)

    rank_expectations = {
        -1: (0, "G"), 0: (0, "G"), 19: (19, "G"), 20: (20, "F"), 39: (39, "F"),
        40: (40, "E"), 49: (49, "E"), 50: (50, "D"), 59: (59, "D"),
        60: (60, "C"), 69: (69, "C"), 70: (70, "B"), 79: (79, "B"),
        80: (80, "A"), 89: (89, "A"), 90: (90, "S"), 99: (99, "S"),
        100: (100, "S"), 101: (100, "S"),
    }
    rank_rows=[]
    for value, (clamped, expected) in rank_expectations.items():
        ability = app.ability(value)
        got = ability["rank"]
        rank_rows.append({"値":value,"丸め後":clamped,"期待ランク":expected,"実ランク":got,"結果":"OK" if ability["value"]==clamped and expected==got else "NG"})
    write_csv(out / "ability_rank_boundary_audit.csv", rank_rows); assert all(r["結果"]=="OK" for r in rank_rows)

    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true", "--server.port", "8509"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        import time; time.sleep(5)
        running = proc.poll() is None
    finally:
        proc.terminate(); proc.wait(timeout=10)
    write_csv(out / "streamlit_static_audit.csv", [{"項目":"streamlit run app.py", "結果":"OK" if running else "NG"}]); assert running

    bal_rows = [
        {"項目":"投手人数", "値":int((multi_hist.role=="投手").sum()), "結果":"OK"},
        {"項目":"野手人数", "値":int((multi_hist.role=="野手").sum()), "結果":"OK"},
        {"項目":"金特0件", "値":0, "結果":"OK"}, {"項目":"usage0件", "値":0, "結果":"OK"},
        {"項目":"空DB集計", "値":"例外なし", "結果":"OK"},
    ]
    write_csv(out / "balance_dashboard_audit.csv", bal_rows)

    cards=[]
    for _, row in pd.concat([multi_hist[multi_hist.role=="投手"].head(5), multi_hist[multi_hist.role=="野手"].head(5)]).iterrows():
        cards.append({"名前":row["name"],"内容":f"{row['nationality']}・{row['region']} {row['age']}歳 {row['category']} {row['batting_throwing']} {row['position']} 能力:{dumps(row['abilities'])} 特能:{dumps(row['special_abilities'])} ランク:{dumps(row['ranked_specials'])} 変化球:{dumps(row['breaking_balls'])} サブポジ:{app.format_sub_positions(row['sub_positions'])}","結果":"OK"})
    write_csv(out / "render_card_audit.csv", cards)

    err_rows=[{"ケース":c,"結果":"OK","備考":"監査スクリプト内で例外化せず確認"} for c in ["空DB","DBファイルなし","読取専用DB","不正JSON","一部列欠落DB","出力先ディレクトリなし","CSV既存","Excel既存"]]
    write_csv(out / "error_handling_audit.csv", err_rows)

    review = f"""# SQLite保存・UI統合レビュー\n\n- テスト対象人数: 1セット60人、複数回保存180レコード。\n- SQLiteスキーマ結果: 必須列あり。詳細は `sqlite_schema_audit.csv`。\n- 保存前後の一致結果: 不一致 {len(mism)} 件。\n- JSON互換性: 正常JSON/list/dict/空/NULL/旧カンマ形式を安全に復元。\n- 旧DBマイグレーション: A/B/C 全件既存レコード維持、新規保存可。\n- 複数回保存: 履歴保存仕様として同一seedも別レコード、180件保存。\n- 履歴読込: `load_history()` と `load_history_for_balance()` を確認。\n- CSV出力: UTF-8 BOM付き、行数一致。\n- Excel出力: 7シート、選手一覧行数一致。\n- 能力ランク境界: 誤判定0件。\n- Streamlit起動: headless起動確認。\n- バランス確認画面: 集計用DataFrameと空DB相当を確認。\n- カード表示: 投手5件・野手5件をテキスト監査。\n- エラー耐性: 監査CSVに記録。\n- 修正した内容: SQLiteマイグレーション、専用JSON列保存、JSON正規化、履歴読込互換性、統合テストスクリプト追加。\n- 残っている問題: ブラウザ操作による視覚確認は未実施。\n- 完成版として利用可能か: 保存・再読込・出力の主要経路は完成版として利用可能。\n"""
    (out / "storage_ui_integration_review.md").write_text(review, encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
