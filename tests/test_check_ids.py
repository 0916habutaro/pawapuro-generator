"""個別生成のCSVを判定する3つの検証スクリプトの判定の id が、表示名の変更などで変わっていないこと（判定の整理_改修指示.md 4-2）。

基準値ファイル・受け入れ記録はこの id で項目を指すので、id が変わると記録が外れてしまう。
意図して id を増やす・直すときは、UPDATE_CHECK_IDS=1 を付けて流して tests/fixtures/check_ids.json を作り直す。
項目名を直すだけのときは、`Result.add(..., id="元のid")` で元の id を渡す。
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "scripts"))

import app  # noqa: E402
import check_draft_balance  # noqa: E402
import check_fictional_balance  # noqa: E402
import check_foreign_balance  # noqa: E402
import checklib  # noqa: E402
import pandas as pd  # noqa: E402
from generate_foreign_balance_sample import player_row  # noqa: E402

FIXTURE = APP_DIR / "tests" / "fixtures" / "check_ids.json"
SAMPLE = 150
MASTER = app.load_master_data()


@pytest.fixture(autouse=True)
def _restore_logging():
    """生成中は警告ログを止めるが、ほかのテストのログの確認に影響しないよう、終わったら戻す。"""
    yield
    logging.disable(logging.NOTSET)



def sample(category: str, role: str) -> pd.DataFrame:
    logging.disable(logging.WARNING)
    return pd.DataFrame([player_row(app.generate_player(role, category, MASTER, seed=seed)) for seed in range(1, SAMPLE + 1)])


def ids(result) -> list[str]:
    checks = result.checks if hasattr(result, "checks") else result
    return [check.id for check in checks]


def current_ids() -> dict[str, list[str]]:
    fictional_pitchers = sample("架空球団用", "投手")
    fictional_fielders = sample("架空球団用", "野手")
    fictional = pd.concat([fictional_pitchers, fictional_fielders], ignore_index=True)
    domestic = check_fictional_balance.normalize(fictional[fictional.roster_origin == "domestic"])
    draft = pd.concat([sample("ドラフト候補用", "投手"), sample("ドラフト候補用", "野手")], ignore_index=True)
    draft = draft[draft.player_class != "育成候補"].reset_index(drop=True)
    return {
        "check_fictional_balance": sorted(
            ids(check_fictional_balance.check_common(domestic))
            + ids(check_fictional_balance.check_pitchers(domestic[domestic.role == "投手"].reset_index(drop=True)))
            + ids(check_fictional_balance.check_fielders(domestic[domestic.role == "野手"].reset_index(drop=True)))
        ),
        "check_foreign_balance": sorted(
            ids(check_foreign_balance.check_pitchers(sample("助っ人外国人用", "投手"))) + ids(check_foreign_balance.check_fielders(sample("助っ人外国人用", "野手")))
        ),
        "check_draft_balance": sorted(ids(check_draft_balance.evaluate(draft))),
    }


def test_check_ids_are_stable_and_unique():
    current = current_ids()
    for script, values in current.items():
        assert len(values) == len(set(values)), f"{script}: id が重なっている"
    if os.environ.get("UPDATE_CHECK_IDS"):
        FIXTURE.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        pytest.skip("tests/fixtures/check_ids.json を作り直した")
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for script, values in current.items():
        missing, added = sorted(set(expected[script]) - set(values)), sorted(set(values) - set(expected[script]))
        assert not missing and not added, f"{script}: 消えた id {missing[:5]} ／ 増えた id {added[:5]}（意図した変更なら UPDATE_CHECK_IDS=1 で作り直す）"


def test_fixed_and_accepted_ids_use_known_script_prefixes():
    known = ("check_age_profile.", "check_pitcher_control.", "check_fielder_speed.", "check_fielder_batting.", "check_fielder_position.", "check_special_profile.", "check_fictional_balance.", "check_foreign_balance.", "check_draft_balance.", "validate_team_mode.")
    for key in list(checklib.baselines()) + list(checklib.accepted_deviations()):
        assert key.startswith(known), key
