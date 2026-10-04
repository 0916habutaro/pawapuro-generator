"""検証スクリプト共通の、判定の種類・誤差・合否・受け入れ記録・基準値（判定の整理_改修指示.md）。

判定の種類（1章）:
    実在 … 実在データに合わせる。範囲の外でも「境界からの距離 ≦ 2×誤差」なら「要注意」、超えたら「不合格」。
    固定 … 改修前から変わっていないことを確かめる。data/config/check_baselines.json の値±幅と比べる。
    設計 … 実在とは別に決めた条件。範囲の内側なら合格、外側なら不合格（誤差は見ない）。
    参考 … 合否を付けない表示。

誤差（2章）: 判定に使う値そのもののばらつきを、同じ評価関数を再抽出（ブートストラップ）した標本で何度も計算して求める。
    生成側 … 球団単位の値は球団、選手単位の値は選手（または球団ごとのまとまり）を単位に再抽出する。
    実在側 … 実在の選手・チームを同じように再抽出する（データが手元にあるとき）。無いときは生成側の誤差を人数比で換算する。
    合わせた誤差 = √(生成側² + 実在側²)。範囲を実在から決めていない項目（固定・設計・実在に当たらない閾値）は生成側だけ。

受け入れ済みの不合格（3章）: data/config/accepted_deviations.json。記録された値より悪くなっていなければ「受け入れ済み」、
    誤差の2倍を超えて悪化したら「不合格」。範囲に戻ったら「合格」と表示し、記録を外すよう促す。

基準値（4章）: data/config/check_baselines.json。各スクリプトの `--update-baselines --reason "理由" --only <id または節>` で更新する（--only なしは全部を書き換えるので確認が出る。--yes で省略）。
"""
from __future__ import annotations

import csv
import json
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

APP_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = APP_DIR / "data" / "config"
BASELINES_PATH = CONFIG_DIR / "check_baselines.json"
ACCEPTED_PATH = CONFIG_DIR / "accepted_deviations.json"
CHECKS_DIR = APP_DIR / "reports" / "checks"
SNAPSHOT_PATH = CONFIG_DIR / "check_snapshot.csv"
SNAPSHOT_META_PATH = CONFIG_DIR / "check_snapshot_meta.json"
# 前回の正式な結果から、範囲の中心（目標）から遠ざかる向きに、生成側の誤差のこの倍数を超えて動いたら「悪化」
SNAPSHOT_SIGMAS = 3.0

for _stream in (sys.stdout, sys.stderr):  # Windows の既定（cp932）でも「✗」などを出せるようにする
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

KIND_REAL, KIND_FIXED, KIND_DESIGN, KIND_INFO = "実在", "固定", "設計", "参考"
KINDS = (KIND_REAL, KIND_FIXED, KIND_DESIGN, KIND_INFO)
PASS, WARN, ACCEPTED, FAIL, INFO = "合格", "要注意", "受け入れ済み", "不合格", "参考"
STATUSES = (PASS, WARN, ACCEPTED, FAIL, INFO)
# 要注意の幅（誤差の何倍まで）
WARN_SIGMAS = 2.0
DEFAULT_BOOTSTRAP = 200


# ---------------------------------------------------------------------------
# 範囲の判定（bool のように使え、値と範囲も持つ）
# ---------------------------------------------------------------------------
class Verdict:
    """`in_range` の結果。`if verdict:` で bool として使え、`Result.add` が値・範囲を取り出す。"""

    __slots__ = ("ok", "value", "low", "high")

    def __init__(self, ok: bool, value: float, low: float | None, high: float | None):
        self.ok, self.value, self.low, self.high = ok, value, low, high

    def __bool__(self) -> bool:
        return self.ok


def _isnan(value: Any) -> bool:
    try:
        return value is None or bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def in_range(value: Any, lo: float | None = None, hi: float | None = None, *, low: float | None = None, high: float | None = None) -> Verdict:
    low, high = (lo if low is None else low), (hi if high is None else high)
    if _isnan(value):
        return Verdict(False, math.nan, low, high)
    value = float(value)
    return Verdict((low is None or value >= low) and (high is None or value <= high), value, low, high)


def distance_outside(value: float, low: float | None, high: float | None) -> float:
    """範囲の外側にどれだけ出ているか（内側なら 0）。"""
    if value is None or math.isnan(value):
        return math.inf
    if low is not None and value < low:
        return low - value
    if high is not None and value > high:
        return value - high
    return 0.0


# ---------------------------------------------------------------------------
# 判定1件
# ---------------------------------------------------------------------------
@dataclass
class Check:
    id: str
    kind: str
    label: str
    value: float
    low: float | None = None
    high: float | None = None
    section: str = ""
    shown: str = ""            # 値の表示（「12.3%」など）
    target: str = ""           # 範囲の表示
    real: str = ""             # 実在の値の表示
    se_gen: float | None = None
    se_real: float | None = None
    direction: str = ""        # 受け入れ記録で「悪い向き」を決める（upper／lower）。空なら外れた向き
    status: str = ""
    reason: str = ""
    sigmas: float | None = None  # 境界からの距離（誤差の何倍か）

    @property
    def se(self) -> float | None:
        if self.se_gen is None and self.se_real is None:
            return None
        return math.hypot(self.se_gen or 0.0, self.se_real or 0.0)

    def range_text(self) -> str:
        if self.target:
            return self.target
        if self.low is None and self.high is None:
            return ""
        if self.low is None:
            return f"{self.high:g}以下"
        if self.high is None:
            return f"{self.low:g}以上"
        return f"{self.low:g}〜{self.high:g}"


class Checks:
    """1つのスクリプトの判定の集まり。評価関数がこれを返し、`grade` で合否を付ける。"""

    def __init__(self, script: str = ""):
        self.script = script
        self.items: list[Check] = []

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def extend(self, other: "Checks | Iterable[Check]") -> None:
        self.items.extend(list(other))

    def add(self, id: str, kind: str, label: str, value: Any, low: float | None = None, high: float | None = None, *,
            section: str = "", shown: str | None = None, target: str = "", real: str = "", direction: str = "") -> Check:
        if kind not in KINDS:
            raise ValueError(f"判定の種類が不明: {kind}（{id}）")
        number = math.nan if _isnan(value) else float(value)
        check = Check(id=id, kind=kind, label=label, value=number, low=low, high=high, section=section,
                      shown=shown if shown is not None else _num_text(number), target=target, real=real, direction=direction)
        self.items.append(check)
        return check

    def fixed(self, id: str, label: str, value: Any, default_width: float, *, section: str = "", shown: str | None = None,
              real: str = "") -> Check:
        """「固定」の判定。基準値ファイルの値±幅と比べる（ファイルに無いときは基準なし＝不合格）。"""
        entry = baselines().get(id)
        if entry is None:
            check = self.add(id, KIND_FIXED, label, value, section=section, shown=shown, real=real)
            check.reason = "基準値なし（--update-baselines --reason で登録する）"
            check.target = f"基準値なし（幅 ±{default_width:g}）"
            check.low = check.high = math.nan
            check.direction = f"width={default_width:g}"
            return check
        base, width, mode = float(entry["value"]), float(entry.get("width", default_width)), entry.get("direction", "both")
        if mode == "lower":
            low, high, target = base, None, f"{base:g}以上（固定）"
        elif mode == "upper":
            low, high, target = None, base, f"{base:g}以下（固定）"
        else:
            low, high, target = base - width, base + width, f"基準値{base:g}±{width:g}"
        return self.add(id, KIND_FIXED, label, value, low, high, section=section, shown=shown, target=target, real=real)

    def info(self, id: str, label: str, value: Any, *, section: str = "", shown: str | None = None, target: str = "", real: str = "") -> Check:
        return self.add(id, KIND_INFO, label, value, section=section, shown=shown, target=target, real=real)


def _num_text(value: float) -> str:
    return "—" if math.isnan(value) else f"{value:.2f}"


# ---------------------------------------------------------------------------
# 基準値・受け入れ記録
# ---------------------------------------------------------------------------
_CACHE: dict[str, Any] = {}


def _load_json(path: Path) -> dict[str, Any]:
    key = str(path)
    if key not in _CACHE:
        _CACHE[key] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"items": {}}
    return _CACHE[key]


def reload_config() -> None:
    _CACHE.clear()


def baselines(path: Path | None = None) -> dict[str, dict[str, Any]]:
    return _load_json(path or BASELINES_PATH).get("items", {})


def accepted_deviations(path: Path | None = None) -> dict[str, dict[str, Any]]:
    items = _load_json(path or ACCEPTED_PATH).get("items", [])
    return {item["id"]: item for item in items} if isinstance(items, list) else dict(items)


def _matches_only(check_id: str, only: Iterable[str] | None) -> bool:
    """only が空なら全部。id が一致するか、「節」（id の先頭部分。末尾の . は省略可）に当たれば True。"""
    patterns = [p.strip() for p in (only or []) if p.strip()]
    if not patterns:
        return True
    return any(check_id == p or check_id.startswith(p if p.endswith(".") else p + ".") for p in patterns)


def update_baselines(
    checks: Iterable[Check], reason: str, *, pr: str = "", path: Path | None = None,
    only: Iterable[str] | None = None, confirm: Callable[[list[tuple[str, float | None, float]]], bool] | None = None,
) -> list[tuple[str, float | None, float]]:
    """「固定」の判定の今の値を基準値ファイルに書く。reason が空なら書かない。(id, 前の値, 新しい値) を返す。

    only に id（または節＝idの先頭部分）を渡すと、それに当たる項目だけを更新する。only が空（全部を書き換える）で
    confirm が渡されたときは、書く前に変更の一覧で confirm を呼び、False なら何も書かずに空を返す。"""
    if not reason.strip():
        raise SystemExit("--update-baselines には --reason \"理由\" が必要です（基準値は書き換えていません）")
    path = path or BASELINES_PATH
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1, "items": {}}
    items = data.setdefault("items", {})
    plan: list[tuple[Check, dict[str, Any] | None, float]] = []
    for check in checks:
        if check.kind != KIND_FIXED or math.isnan(check.value) or not _matches_only(check.id, only):
            continue
        old = items.get(check.id)
        new_value = round(float(check.value), 4)
        if old and abs(float(old["value"]) - new_value) < 1e-9:
            continue
        plan.append((check, old, new_value))
    changed = [(check.id, float(old["value"]) if old else None, new_value) for check, old, new_value in plan]
    if not [p for p in (only or []) if p.strip()] and confirm is not None and changed and not confirm(changed):
        return []
    for check, old, new_value in plan:
        width = float(old["width"]) if old else _default_width(check)
        items[check.id] = {
            "value": new_value, "width": width, "direction": old.get("direction", "both") if old else "both",
            "label": check.label, "pr": pr or (old or {}).get("pr", ""), "reason": reason.strip(), "date": date.today().isoformat(),
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reload_config()
    return changed


def confirm_all_baselines(changed: list[tuple[str, float | None, float]], assume_yes: bool = False) -> bool:
    """絞り込みなしで全部の基準値を書き換えるときの確認。一覧を出し、--yes か、端末での「yes」の入力で進める。"""
    print(f"\n[確認] 絞り込み（--only）なしで、基準値 {len(changed)} 項目を書き換えます:")
    for key, old, new in changed:
        print(f"  {key}: {'（新規）' if old is None else old} → {new}")
    if assume_yes:
        return True
    if sys.stdin is not None and sys.stdin.isatty():
        return input("書き換えてよければ yes と入力: ").strip().lower() == "yes"
    print("書き換えていません。進めるには --yes を付けるか、--only <id または節> で項目を絞ってください。")
    return False


def _default_width(check: Check) -> float:
    match = re.search(r"width=([0-9.]+)", check.direction)
    return float(match.group(1)) if match else 0.0


# ---------------------------------------------------------------------------
# 合否
# ---------------------------------------------------------------------------
def grade(checks: Iterable[Check], *, se_gen: dict[str, float] | None = None, se_real: dict[str, float] | None = None,
          accepted: dict[str, dict[str, Any]] | None = None, all_info: bool = False) -> list[Check]:
    """判定に合否を付ける。all_info=True なら、すべて「参考」にする（簡易版）。"""
    accepted = accepted_deviations() if accepted is None else accepted
    se_gen, se_real = se_gen or {}, se_real or {}
    graded = list(checks)
    for check in graded:
        if check.id in se_gen:
            check.se_gen = se_gen[check.id]
        if check.kind == KIND_REAL and check.id in se_real:
            check.se_real = se_real[check.id]
        if check.kind != KIND_REAL:
            check.se_real = None
        _decide(check, accepted.get(check.id))
        if all_info:
            check.reason = (check.reason + "（簡易版: 合否には使わない）").strip()
            check.status = INFO
    return graded


def _decide(check: Check, record: dict[str, Any] | None) -> None:
    if check.kind == KIND_INFO:
        check.status = INFO
        return
    if check.reason.startswith("基準値なし"):
        check.status = FAIL
        return
    se = check.se if check.kind == KIND_REAL else None
    dist = distance_outside(check.value, check.low, check.high)
    if math.isnan(check.value):
        check.status, check.reason = FAIL, "値が計算できない（該当者なし）"
        return
    if se:
        check.sigmas = dist / se
    if dist == 0:
        check.status = PASS
        if record:
            check.reason = "合格の範囲に戻った。accepted_deviations.json から外してよい"
        return
    if record:
        accepted_value, worse = float(record["accepted_value"]), record.get("direction", "")
        beyond = _beyond(check.value, accepted_value, worse, check.low, check.high)
        tolerance = WARN_SIGMAS * (check.se or 0.0)
        if beyond <= tolerance:
            check.status = ACCEPTED
            check.reason = f"受け入れ済み（記録 {accepted_value:g}。{record.get('reason', '')}）"
            return
        check.status = FAIL
        check.reason = f"受け入れた値より悪化（記録 {accepted_value:g} → {check.value:.4g}。誤差×{WARN_SIGMAS:g}={tolerance:.3g}を超えた）"
        return
    if check.kind == KIND_REAL and se and dist <= WARN_SIGMAS * se:
        check.status = WARN
        check.reason = f"範囲の外だが境界から誤差の{dist / se:.1f}倍（{WARN_SIGMAS:g}倍以内）"
        return
    check.status = FAIL
    if check.kind == KIND_REAL and se:
        check.reason = f"境界から誤差の{dist / se:.1f}倍（{WARN_SIGMAS:g}倍超）"


def _beyond(value: float, accepted_value: float, direction: str, low: float | None, high: float | None) -> float:
    """受け入れた値より、悪い向きにどれだけ進んだか（進んでいなければ 0）。"""
    if direction not in ("upper", "lower"):
        direction = "upper" if (high is not None and value > high) else "lower"
    delta = value - accepted_value if direction == "upper" else accepted_value - value
    return max(0.0, delta)


def counts(checks: Iterable[Check]) -> dict[str, int]:
    result = {status: 0 for status in STATUSES}
    for check in checks:
        result[check.status] += 1
    return result


def exit_code(checks: Iterable[Check]) -> int:
    return 1 if any(check.status == FAIL for check in checks) else 0


# ---------------------------------------------------------------------------
# 誤差（ブートストラップ）
# ---------------------------------------------------------------------------
def resample_frame(frame: pd.DataFrame, rng: np.random.Generator, cluster: str | None = None) -> pd.DataFrame:
    """行（cluster 指定ならそのまとまり）を重複を許して引き直す。"""
    if cluster is None:
        return frame.iloc[rng.integers(0, len(frame), len(frame))].reset_index(drop=True)
    groups = list(frame.groupby(cluster, sort=False).indices.values())
    picks = rng.integers(0, len(groups), len(groups))
    return frame.iloc[np.concatenate([groups[i] for i in picks])].reset_index(drop=True)


def resample_list(items: list[Any], rng: np.random.Generator) -> list[Any]:
    return [items[i] for i in rng.integers(0, len(items), len(items))]


def _reference(check: Check) -> float:
    """範囲の基準点（両側なら中央、片側ならその境界）。実在側の誤差では、値と基準点のずれの揺れを見る。"""
    if check.low is not None and check.high is not None:
        return (check.low + check.high) / 2
    bound = check.low if check.low is not None else check.high
    return 0.0 if bound is None else bound


def _boot_values(evaluate: Callable[[Any], Checks], data: Any, resample: Callable[[Any, np.random.Generator], Any], seeds: list[Any],
                 offset: bool = False) -> list[dict[str, float]]:
    out = []
    for seed in seeds:
        rng = np.random.default_rng(seed)
        out.append({check.id: (check.value - _reference(check) if offset else check.value) for check in evaluate(resample(data, rng))})
    return out


def bootstrap_se(evaluate: Callable[[Any], Checks], data: Any, resample: Callable[[Any, np.random.Generator], Any], *,
                 n: int = DEFAULT_BOOTSTRAP, seed: int = 20261004, workers: int = 1, offset: bool = False) -> dict[str, float]:
    """evaluate(再抽出した data) を n 回計算し、判定ごとの値の標準偏差（標準誤差）を返す。

    workers > 1 なら複数プロセスで計算する（evaluate・resample は import できる関数であること）。
    offset=True なら、値そのものではなく「値と範囲の基準点とのずれ」の揺れを返す。実在側を再抽出するとき、
    範囲の境界が実在の値から決まる判定（境界が動く）と、値が実在で割る判定（値が動く）の両方を、同じ見方で扱える。
    """
    if n <= 0:
        return {}
    seeds = np.random.SeedSequence(seed).spawn(n)
    if workers > 1 and n >= workers:
        from concurrent.futures import ProcessPoolExecutor

        chunks = [seeds[i::workers] for i in range(workers)]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_boot_values, evaluate, data, resample, chunk, offset) for chunk in chunks if chunk]
            results = [row for future in futures for row in future.result()]
    else:
        results = _boot_values(evaluate, data, resample, seeds, offset)
    values: dict[str, list[float]] = {}
    for row in results:
        for key, value in row.items():
            values.setdefault(key, []).append(value)
    out = {}
    for key, series in values.items():
        arr = np.asarray(series, dtype=float)
        arr = arr[~np.isnan(arr)]
        out[key] = float(arr.std(ddof=1)) if len(arr) >= 2 else math.nan
    return out


def scale_se(se: dict[str, float], n_gen: float, n_real: float) -> dict[str, float]:
    """生成側の誤差を、実在の人数に換算する（実在の選手データが手元に無いときの見積もり。同じ分布を仮定）。"""
    factor = math.sqrt(n_gen / n_real) if n_real else 0.0
    return {key: value * factor for key, value in se.items()}


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------
CSV_COLUMNS = ("id", "種類", "節", "表示名", "値", "範囲", "誤差", "境界からの距離(誤差の倍)", "合否", "理由",
               "値(数値)", "下限", "上限", "生成側誤差")


def _g(value: float | None) -> str:
    return "" if value is None or math.isnan(value) else f"{value:.10g}"


def _se_text(check: Check) -> str:
    se = check.se
    return "" if not se else f"{se:.3g}"


def write_csv(checks: Iterable[Check], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for check in checks:
            writer.writerow([
                check.id, check.kind, check.section, check.label, check.shown or _num_text(check.value), check.range_text(),
                _se_text(check), "" if check.sigmas is None else f"{check.sigmas:.1f}", check.status, check.reason,
                _g(check.value), _g(check.low), _g(check.high), _g(check.se_gen),
            ])


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)


MARKS = {PASS: "  ", WARN: "! ", ACCEPTED: "~ ", FAIL: "✗ ", INFO: "  "}


def print_checks(checks: list[Check], title: str) -> None:
    print(f"\n===== {title} =====")
    if not checks:
        print("（対象なし）")
        return
    width = max(len(check.label) for check in checks)
    current = None
    for check in checks:
        if check.section != current:
            print(f"\n[{check.section}]")
            current = check.section
        se = _se_text(check)
        extra = f"  誤差={se}" if se else ""
        note = f"  ← {check.reason}" if check.reason and check.status in (WARN, ACCEPTED, FAIL) else ""
        print(f"{MARKS[check.status]}{check.status:<6}[{check.kind}] {check.label.ljust(width)}  値={check.shown or _num_text(check.value):<10} "
              f"範囲={check.range_text():<18} 実在={check.real}{extra}{note}")
    print("\n" + summary_line(checks))


def summary_line(checks: list[Check]) -> str:
    c = counts(checks)
    judged = sum(v for k, v in c.items() if k != INFO)
    return f"合計 {judged} 項目 / 合格 {c[PASS]} / 要注意 {c[WARN]} / 受け入れ済み {c[ACCEPTED]} / 不合格 {c[FAIL]}（参考 {c[INFO]}）"


def markdown_rows(checks: Iterable[Check]) -> list[str]:
    lines = ["| 合否 | 種類 | 項目 | 値 | 範囲 | 誤差 | 理由 |", "|---|---|---|---|---|---|---|"]
    for check in checks:
        lines.append(f"| {check.status} | {check.kind} | {check.label}（{check.id}） | {check.shown or _num_text(check.value)} | {check.range_text()} | {_se_text(check)} | {check.reason} |")
    return lines


# ---------------------------------------------------------------------------
# スクリプト共通の引数
# ---------------------------------------------------------------------------
def add_common_args(parser: Any, *, default_boot: int = DEFAULT_BOOTSTRAP) -> None:
    parser.add_argument("--boot", type=int, default=default_boot, help="誤差の見積もりに使うブートストラップの回数（0で誤差なし＝要注意なし）")
    parser.add_argument("--update-baselines", action="store_true", help="「固定」の判定の今の値を基準値ファイルに書く（--reason が必要）")
    parser.add_argument("--reason", default="", help="--update-baselines の理由（空なら書かない）")
    parser.add_argument("--only", default="", help="--update-baselines で更新する項目を id（または節＝idの先頭部分）で絞る。カンマ区切りで複数。空なら全部（確認が出る）")
    parser.add_argument("--yes", action="store_true", help="--update-baselines で絞り込みなしに全部を書き換える確認を省く")
    parser.add_argument("--baseline-pr", default="", help="--update-baselines を行うPR（記録用）")
    parser.add_argument("--quick", action="store_true", help="簡易版: すべての合否を『参考』にする（正式な判定には使わない）")
    parser.add_argument("--checks-csv", type=Path, default=None, help="判定の一覧CSVの出力先（既定: reports/checks/<スクリプト名>.csv）")


def finish(script: str, checks: list[Check], args: Any) -> int:
    """基準値の更新・CSV出力を行い、終了コードを返す。"""
    if getattr(args, "update_baselines", False):
        only = [p for p in (getattr(args, "only", "") or "").split(",") if p.strip()]
        changed = update_baselines(
            checks, args.reason, pr=getattr(args, "baseline_pr", ""), only=only,
            confirm=lambda items: confirm_all_baselines(items, getattr(args, "yes", False)),
        )
        print("\n[基準値の更新]")
        for key, old, new in changed:
            print(f"  {key}: {'（新規）' if old is None else old} → {new}")
        if not changed:
            print("  変更なし")
    path = getattr(args, "checks_csv", None) or CHECKS_DIR / f"{script}.csv"
    write_csv(checks, path)
    print(f"判定の一覧: {path}")
    return exit_code(checks)


# ---------------------------------------------------------------------------
# 前回の正式な結果（スナップショット）との比較
# ---------------------------------------------------------------------------
SNAPSHOT_COLUMNS = ("id", "種類", "値(数値)", "生成側誤差")
WORSE, BETTER = "悪化", "改善"


def checks_frame(checks: Iterable[Check]) -> pd.DataFrame:
    """判定を、比較に使う列（CSVと同じ列名）の表にする。"""
    rows = [{"id": c.id, "種類": c.kind, "値(数値)": _g(c.value), "下限": _g(c.low), "上限": _g(c.high), "生成側誤差": _g(c.se_gen)} for c in checks]
    return pd.DataFrame(rows, columns=["id", "種類", "値(数値)", "下限", "上限", "生成側誤差"], dtype=str)


def load_snapshot(path: Path | None = None) -> pd.DataFrame | None:
    path = path or SNAPSHOT_PATH
    return read_csv(path) if path.exists() else None


def _num(text: Any) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return math.nan


def compare_snapshot(frame: pd.DataFrame, snapshot: pd.DataFrame | None, sigmas: float = SNAPSHOT_SIGMAS) -> pd.DataFrame:
    """今回の「実在」「設計」の判定を、スナップショットと比べる。生成側の誤差だけで評価する（実在側の誤差は前回と共通）。
    範囲の中心（片側だけの範囲ならその境界）から遠ざかる向きに、誤差×sigmas を超えて動いたら「悪化」、近づく向きなら「改善」。
    列: id, 変化（悪化／改善／空）, 前回, 今回, 動き（誤差の倍）。"""
    columns = ["id", "変化", "前回", "今回", "動き"]
    if snapshot is None or frame.empty:
        return pd.DataFrame(columns=columns)
    old = snapshot.set_index("id")["値(数値)"].map(_num)
    rows = []
    for row in frame.to_dict("records"):
        if row["種類"] not in (KIND_REAL, KIND_DESIGN) or row["id"] not in old.index:
            continue
        now, prev, low, high = _num(row["値(数値)"]), old[row["id"]], _num(row["下限"]), _num(row["上限"])
        if math.isnan(now) or math.isnan(prev) or (math.isnan(low) and math.isnan(high)):
            continue
        if not math.isnan(low) and not math.isnan(high):
            center = (low + high) / 2
            toward_bad = abs(now - center) - abs(prev - center)
        elif not math.isnan(high):
            toward_bad = now - prev      # 上限だけ: 増えるほど悪い
        else:
            toward_bad = prev - now      # 下限だけ: 減るほど悪い
        se = _num(row["生成側誤差"])
        limit = sigmas * se if se and not math.isnan(se) else 1e-9
        if toward_bad > limit:
            change = WORSE
        elif -toward_bad > limit:
            change = BETTER
        else:
            continue
        rows.append({"id": row["id"], "変化": change, "前回": prev, "今回": now, "動き": (toward_bad / se) if se and not math.isnan(se) else math.inf})
    return pd.DataFrame(rows, columns=columns)


def write_snapshot(frame: pd.DataFrame, reason: str, commit: str = "", only_scripts_prefix: tuple[str, ...] | None = None,
                   path: Path | None = None) -> list[tuple[str, float | None, float]]:
    """正式な結果（frame）をスナップショットに書く。reason が空なら書かない。(id, 前の値, 新しい値) の変わった項目を返す。
    only_scripts_prefix を渡すと、その接頭辞の id だけ入れ替える（--only で一部だけ流したとき）。"""
    if not reason.strip():
        raise SystemExit("--update-snapshot には --reason \"理由\" が必要です（スナップショットは書き換えていません）")
    path = path or SNAPSHOT_PATH
    old = load_snapshot(path)
    new = frame[frame["種類"].isin([KIND_REAL, KIND_DESIGN])][["id", "種類", "値(数値)", "生成側誤差"]].copy()
    if old is not None and only_scripts_prefix:
        keep = old[~old["id"].str.startswith(only_scripts_prefix)]
        new = pd.concat([keep, new], ignore_index=True)
    new = new.drop_duplicates("id", keep="last").sort_values("id")
    before = old.set_index("id")["値(数値)"].map(_num) if old is not None else pd.Series(dtype=float)
    changed = []
    for row in new.to_dict("records"):
        value = _num(row["値(数値)"])
        prev = before.get(row["id"])
        if prev is None or (not (math.isnan(prev) and math.isnan(value)) and abs(prev - value) > 1e-9):
            changed.append((row["id"], None if prev is None else float(prev), value))
    path.parent.mkdir(parents=True, exist_ok=True)
    new.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
    meta = {"date": date.today().isoformat(), "reason": reason.strip(), "commit": commit}
    SNAPSHOT_META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reload_config()
    return changed
