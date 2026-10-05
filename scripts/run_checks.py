#!/usr/bin/env python3
"""全部の検証スクリプトを同じ条件で1回で流し、結果を1枚にまとめる（判定の整理_改修指示.md 5章）。

使い方:
    python scripts/run_checks.py                  # 正式な規模。結果は reports/checks/summary.md
    python scripts/run_checks.py --quick          # 簡易版。すべての合否が「参考」になる（reports/checks/quick/）
    python scripts/run_checks.py --only validate_team_mode,check_pitcher_control

- 流すスクリプトと正式な規模（既定値）:
    validate_team_mode      構成・背番号500球団、戦力600球団、カラー7×200球団、散らばり300球団
    check_pitcher_control   球団生成300球団
    check_fielder_speed     球団生成300球団（個別生成の架空球団用・野手のサンプルは参考表示に使う）
    check_age_profile       個別生成 投手・野手 各30000人 ＋ 球団生成500球団
    check_fictional_balance 架空球団用 投手・野手 各5000人（サンプルCSVを scripts/generate_fictional_balance_sample.py で作り、1つにまとめて渡す）
    check_foreign_balance   助っ人外国人用 投手・野手 各5000人
    check_draft_balance     ドラフト候補用 投手・野手 各5000人（1つのCSVにまとめて渡す）
- PYTHONHASHSEED=0 を固定して流す（ハッシュの値によらないことは tests/test_hash_independence.py で確かめている。念のため固定している）。
- 前回の正式な結果（data/config/check_snapshot.csv）との比較: 悪化した項目は不合格に数える。意図した変更なら
  `--update-snapshot --reason "理由"` で更新する（更新した項目と前後の値を表示）。
- 終了コード: 不合格が1件でもあれば 1。要注意・受け入れ済みは 0。スクリプトが異常終了したときは 2。
- 改修の完了報告には、このスクリプトの正式な結果（--quick なし）を使う。--quick の結果で合否を話さない。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR / "scripts"))

import pandas as pd  # noqa: E402

import checklib  # noqa: E402

SCRIPTS_DIR = APP_DIR / "scripts"
SCRIPT_NAMES = ("validate_team_mode", "check_pitcher_control", "check_fielder_speed", "check_age_profile", "check_fictional_balance", "check_foreign_balance", "check_draft_balance")
SAMPLE_COUNT = {"official": 5000, "quick": 500}
# 簡易版の規模
QUICK_ARGS = {
    "validate_team_mode": ["--teams", "40", "--strength-teams", "60", "--color-teams", "15", "--spread-teams", "40"],
    "check_pitcher_control": ["--teams", "40"],
    "check_fielder_speed": ["--teams", "40"],
    "check_age_profile": ["--players", "1500", "--teams", "40"],
}
SCALE_TEXT = {
    "official": {
        "validate_team_mode": "構成・背番号500球団／戦力600球団／カラー7×200球団／散らばり300球団",
        "check_pitcher_control": "球団生成300球団", "check_fielder_speed": "球団生成300球団",
        "check_age_profile": "個別生成 投手・野手 各30000人＋球団生成500球団",
        "check_fictional_balance": "投手・野手 各5000人", "check_foreign_balance": "投手・野手 各5000人", "check_draft_balance": "投手・野手 各5000人",
    },
    "quick": {
        "validate_team_mode": "構成・背番号40球団／戦力60球団／カラー7×15球団／散らばり40球団",
        "check_pitcher_control": "球団生成40球団", "check_fielder_speed": "球団生成40球団", "check_age_profile": "個別生成 各1500人＋球団生成40球団",
        "check_fictional_balance": "投手・野手 各500人", "check_foreign_balance": "投手・野手 各500人", "check_draft_balance": "投手・野手 各500人",
    },
}


def run(command: list[str], env: dict[str, str], log: Path) -> tuple[int, float]:
    """コマンドを流し、標準出力・標準エラーを log に書く。(終了コード, 所要秒) を返す。"""
    started = time.time()
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as handle:
        code = subprocess.run(command, cwd=APP_DIR, env=env, stdout=handle, stderr=subprocess.STDOUT).returncode
    return code, time.time() - started


def make_samples(out_dir: Path, count: int, env: dict[str, str], only: set[str]) -> float:
    """個別生成のサンプルCSVを並列に作る。"""
    jobs = []
    wanted = {"check_fictional_balance": ("fictional",), "check_fielder_speed": ("fictional",), "check_foreign_balance": ("foreign",), "check_draft_balance": ("draft",)}
    kinds = [kind for name, kinds_ in wanted.items() if name in only for kind in kinds_]
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    for kind in kinds:
        for role, tag in (("投手", "pitchers"), ("野手", "fielders")):
            command = [sys.executable, str(SCRIPTS_DIR / f"generate_{kind}_balance_sample.py"), role, str(count), str(out_dir / f"{kind}_{tag}.csv")]
            log = (out_dir / f"{kind}_{tag}.log").open("w", encoding="utf-8")
            jobs.append((subprocess.Popen(command, cwd=APP_DIR, env=env, stdout=log, stderr=subprocess.STDOUT), log))
    for process, log in jobs:
        process.wait()
        log.close()
        if process.returncode:
            raise SystemExit(f"サンプルの生成に失敗しました（{log.name}）")
    for kind, name in (("fictional", "check_fictional_balance"), ("draft", "check_draft_balance")):
        if name in only or (kind == "fictional" and "check_fielder_speed" in only):  # 架空球団用・ドラフト候補用は、投手・野手を1つのCSVにまとめて判定する（共通の項目が投手・野手の両方にかかる）
            frames = [pd.read_csv(out_dir / f"{kind}_{tag}.csv", encoding="utf-8-sig") for tag in ("pitchers", "fielders")]
            pd.concat(frames, ignore_index=True).to_csv(out_dir / f"{kind}_all.csv", index=False, encoding="utf-8-sig")
    return time.time() - started


def git_info() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=APP_DIR, capture_output=True, text=True, encoding="utf-8").stdout.strip()

    commit, branch = git("rev-parse", "--short", "HEAD"), git("rev-parse", "--abbrev-ref", "HEAD")
    dirty = " + 未コミットの変更あり" if git("status", "--porcelain", "--untracked-files=no") else ""
    return f"{commit}（ブランチ {branch}）{dirty}"


def snapshot_section(comparison: pd.DataFrame | None, has_snapshot: bool, quick: bool, updating: bool) -> list[str]:
    """前回の正式な結果（data/config/check_snapshot.csv）との比較の節。"""
    lines = ["## 前回の正式な結果との比較", ""]
    if quick:
        return lines + ["簡易版では比較しない。", ""]
    if not has_snapshot:
        return lines + ["スナップショット（data/config/check_snapshot.csv）がないので比較していない。", ""]
    meta_path = checklib.SNAPSHOT_META_PATH
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        lines += [f"基準: {meta.get('date', '')}（{meta.get('commit', '')}）の正式な結果。更新の理由: {meta.get('reason', '')}", ""]
    lines += [f"「実在」「設計」の判定が、範囲の中心（目標）から遠ざかる向きに生成側の誤差の{checklib.SNAPSHOT_SIGMAS:g}倍を超えて動いたら「悪化」（不合格として数える）。近づく向きは「改善」（表示だけ）。"
              + ("今回はスナップショットを更新するので、悪化は不合格に数えない。" if updating else ""), ""]
    for label in (checklib.WORSE, checklib.BETTER):
        part = comparison[comparison["変化"] == label] if comparison is not None else pd.DataFrame()
        lines += [f"### {label}（{len(part)}件）", ""]
        if part.empty:
            lines += ["（なし）", ""]
            continue
        lines += ["| id | 前回 | 今回 | 動き（誤差の倍） |", "|---|---|---|---|"]
        lines += [f"| {r.id} | {r.前回:.5g} | {r.今回:.5g} | {r.動き:.1f} |" for r in part.itertuples()]
        lines.append("")
    return lines


def build_summary(frame: pd.DataFrame, rows: list[dict[str, object]], out_dir: Path, quick: bool, only: list[str], boot: int,
                  comparison: pd.DataFrame | None = None, has_snapshot: bool = False, updating: bool = False) -> str:
    counts = frame["合否"].value_counts().to_dict()
    mode = "quick" if quick else "official"
    lines = ["# 検証のまとめ（run_checks.py）", ""]
    if quick:
        lines += ["**簡易版（合否には使わない）**。規模を小さくして流したため、すべての合否を「参考」として表示している。", ""]
    lines += [
        f"- 合格 {counts.get('合格', 0)} ／ 要注意 {counts.get('要注意', 0)} ／ 受け入れ済み {counts.get('受け入れ済み', 0)} ／ 不合格 {counts.get('不合格', 0)}（参考 {counts.get('参考', 0)}）",
        f"- 実行した main のコミット: {git_info()}",
        f"- 規模: {'簡易版（--quick）' if quick else '正式'}。誤差の見積もり: ブートストラップ{boot}回",
        f"- 流したスクリプト: {', '.join(only)}",
        f"- PYTHONHASHSEED=0 で実行。合計の所要時間: {sum(float(r['seconds']) for r in rows) / 60:.1f}分",
        "",
        "## 合格以外の項目", "",
    ]
    others = frame[~frame["合否"].isin(["合格", "参考"])].copy()
    if others.empty:
        lines += ["（なし）", ""]
    else:
        order = {"不合格": 0, "要注意": 1, "受け入れ済み": 2}
        others["順"] = others["合否"].map(order)
        others = others.sort_values(["順", "スクリプト", "id"])
        lines += ["| 合否 | id | 種類 | 項目 | 値 | 範囲 | 誤差 | 理由 |", "|---|---|---|---|---|---|---|---|"]
        for row in others.itertuples():
            lines.append(f"| {row.合否} | {row.id} | {row.種類} | {row.表示名} | {row.値} | {row.範囲} | {row.誤差} | {row.理由} |")
        lines.append("")
    lines += snapshot_section(comparison, has_snapshot, quick, updating)
    lines += ["## スクリプトごと", "", "| スクリプト | 規模 | 判定数 | 合格 | 要注意 | 受け入れ済み | 不合格 | 所要時間 | 詳細 |", "|---|---|---|---|---|---|---|---|---|"]
    for row in rows:
        part = frame[frame["スクリプト"] == row["script"]]
        c = part["合否"].value_counts().to_dict()
        lines.append(f"| {row['script']} | {SCALE_TEXT[mode][row['script']]} | {len(part)} | {c.get('合格', 0)} | {c.get('要注意', 0)} | {c.get('受け入れ済み', 0)} | {c.get('不合格', 0)} | "
                     f"{float(row['seconds']) / 60:.1f}分 | [{row['script']}.csv]({row['script']}.csv)・[実行ログ](logs/{row['script']}.log) |")
    lines += ["", "validate_team_mode の詳細レポートは `reports/team_mode/summary.md`（簡易版は quick/team_mode/summary.md）。", ""]
    kinds = frame["種類"].value_counts().to_dict()
    lines += ["## 種類ごとの件数", "", " ／ ".join(f"{k} {kinds.get(k, 0)}" for k in checklib.KINDS), ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="全部の検証スクリプトを同じ条件で流して、結果を1枚にまとめます。")
    parser.add_argument("--quick", action="store_true", help="簡易版（規模を小さくする。すべての合否を参考にする）")
    parser.add_argument("--only", default="", help="流すスクリプトをカンマ区切りで指定する（例: validate_team_mode,check_pitcher_control）")
    parser.add_argument("--boot", type=int, default=None, help="ブートストラップの回数（既定: 正式 200、簡易 20。年齢帯の判定は半分）")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    parser.add_argument("--update-snapshot", action="store_true", help="今回の正式な結果を、前回との比較の基準（data/config/check_snapshot.csv）に書く（--reason が必要）")
    parser.add_argument("--reason", default="", help="--update-snapshot の理由（空なら書かない）")
    args = parser.parse_args()
    if args.update_snapshot and args.quick:
        raise SystemExit("--quick の結果ではスナップショットを更新できません")
    if args.update_snapshot and not args.reason.strip():
        raise SystemExit("--update-snapshot には --reason "+chr(34)+"理由"+chr(34)+" が必要です（流す前に止めました）")

    only = [name.strip() for name in args.only.split(",") if name.strip()] or list(SCRIPT_NAMES)
    unknown = [name for name in only if name not in SCRIPT_NAMES]
    if unknown:
        raise SystemExit(f"不明なスクリプト: {', '.join(unknown)}（{', '.join(SCRIPT_NAMES)}）")
    mode = "quick" if args.quick else "official"
    out_dir = checklib.CHECKS_DIR / ("quick" if args.quick else "")
    boot = args.boot if args.boot is not None else (20 if args.quick else checklib.DEFAULT_BOOTSTRAP)
    age_boot = max(1, boot // 2) if boot else 0
    env = {**os.environ, "PYTHONHASHSEED": "0", "PYTHONUTF8": "1"}
    py = sys.executable
    sized = QUICK_ARGS if args.quick else {}  # 簡易版だけ規模を小さくする。正式は各スクリプトの既定値
    common = ["--boot", str(boot)] + (["--quick"] if args.quick else [])
    logs = out_dir / "logs"
    samples = out_dir / "samples"
    rows: list[dict[str, object]] = []

    only_set = set(only)
    sample_seconds = 0.0
    if only_set & {"check_fictional_balance", "check_fielder_speed", "check_foreign_balance", "check_draft_balance"}:
        print(f"[サンプル生成] 個別生成 各{SAMPLE_COUNT[mode]}人", flush=True)
        sample_seconds = make_samples(samples, SAMPLE_COUNT[mode], env, only_set)

    def csv_path(name: str) -> Path:
        return out_dir / f"{name}.csv"

    commands = {
        "validate_team_mode": [py, "scripts/validate_team_mode.py", *common, "--workers", str(args.workers), "--checks-csv", str(csv_path("validate_team_mode")),
                               *sized.get("validate_team_mode", []), *(["--output", str(out_dir / "team_mode")] if args.quick else [])],
        "check_pitcher_control": [py, "scripts/check_pitcher_control.py", *common, "--workers", str(args.workers), "--checks-csv", str(csv_path("check_pitcher_control")),
                                  *sized.get("check_pitcher_control", [])],
        "check_fielder_speed": [py, "scripts/check_fielder_speed.py", *common, "--workers", str(args.workers), "--checks-csv", str(csv_path("check_fielder_speed")),
                                "--single-csv", str(samples / "fictional_fielders.csv"), *sized.get("check_fielder_speed", [])],
        "check_age_profile": [py, "scripts/check_age_profile.py", "--boot", str(age_boot), *(["--quick"] if args.quick else []), "--workers", str(args.workers),
                              "--checks-csv", str(csv_path("check_age_profile")), *sized.get("check_age_profile", [])],
        "check_fictional_balance": [py, "scripts/check_fictional_balance.py", str(samples / "fictional_all.csv"), *common,
                                    "--checks-csv", str(csv_path("check_fictional_balance"))],
        "check_foreign_balance": [py, "scripts/check_foreign_balance.py", str(samples / "foreign_pitchers.csv"), str(samples / "foreign_fielders.csv"), *common,
                                  "--checks-csv", str(csv_path("check_foreign_balance"))],
        "check_draft_balance": [py, "scripts/check_draft_balance.py", str(samples / "draft_all.csv"), *common, "--checks-csv", str(csv_path("check_draft_balance"))],
    }
    crashed = False
    for name in only:
        print(f"[{name}] 実行中（{SCALE_TEXT[mode][name]}）", flush=True)
        code, seconds = run(commands[name], env, logs / f"{name}.log")
        if name.startswith(("check_fictional", "check_foreign", "check_draft")):
            seconds += sample_seconds / 3 if sample_seconds else 0.0  # サンプル生成の時間を3つのスクリプトで分ける
        rows.append({"script": name, "seconds": seconds, "code": code})
        print(f"[{name}] 終了コード {code}、{seconds / 60:.1f}分", flush=True)
        if code not in (0, 1) or not csv_path(name).exists():
            crashed = True
            print(f"  ✗ 異常終了。ログ: {logs / (name + '.log')}", flush=True)

    frames = []
    for row in rows:
        path = csv_path(str(row["script"]))
        if path.exists():
            frame = checklib.read_csv(path)
            frame.insert(0, "スクリプト", row["script"])
            frames.append(frame)
    if not frames:
        raise SystemExit("判定の一覧がありません")
    frame = pd.concat(frames, ignore_index=True)
    # validate_team_mode は年齢帯の判定（check_age_profile.py の球団生成と同じ id・同じ球団）も含むので、id が重なるときは check_age_profile のほうを使う
    if {"validate_team_mode", "check_age_profile"} <= set(frame["スクリプト"]):
        duplicated = frame["スクリプト"].eq("validate_team_mode") & frame["id"].isin(frame.loc[frame["スクリプト"] == "check_age_profile", "id"])
        frame = frame[~duplicated]
    duplicates = frame[frame["id"].duplicated(keep=False)]
    if not duplicates.empty:
        print("警告: id が重なっています:", ", ".join(sorted(set(duplicates["id"]))[:10]))
    out_dir.mkdir(parents=True, exist_ok=True)
    frame = frame.reset_index(drop=True)
    # 前回の正式な結果（スナップショット）との比較。簡易版・スナップショットを更新するときは判定に使わない
    snapshot = None if args.quick else checklib.load_snapshot()
    comparison = checklib.compare_snapshot(frame, snapshot)
    frame["前回比"] = ""
    for item in comparison.itertuples():
        frame.loc[frame["id"] == item.id, "前回比"] = item.変化
        if item.変化 == checklib.WORSE and not args.update_snapshot:
            mask = frame["id"] == item.id
            frame.loc[mask, "理由"] = (frame.loc[mask, "理由"] + f" 前回より悪化（{item.前回:.4g} → {item.今回:.4g}、生成側の誤差の{item.動き:.1f}倍）").str.strip()
            frame.loc[mask, "合否"] = "不合格"
    frame.to_csv(out_dir / "all_checks.csv", index=False, encoding="utf-8-sig")
    summary = build_summary(frame, rows, out_dir, args.quick, only, boot, comparison, snapshot is not None, args.update_snapshot)
    (out_dir / "summary.md").write_text(summary, encoding="utf-8")
    print(summary)
    print(f"まとめ: {out_dir / 'summary.md'}")
    if crashed:
        sys.exit(2)
    if args.update_snapshot:
        prefixes = None if set(only) == set(SCRIPT_NAMES) else tuple(f"{name}." for name in only)
        changed = checklib.write_snapshot(frame, args.reason, git_info(), prefixes)
        print(f"[スナップショットの更新] {len(changed)}項目が変わりました（理由: {args.reason.strip()}）")
        for key, prev, value in changed:
            print(f"  {key}: {'（新規）' if prev is None else f'{prev:.6g}'} → {value:.6g}")
    sys.exit(0 if args.quick or int((frame["合否"] == "不合格").sum()) == 0 else 1)


if __name__ == "__main__":
    main()
