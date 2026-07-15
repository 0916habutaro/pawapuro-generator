import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import compare_real_direct_balance as direct


def test_usage_specials_are_not_counted_as_normal_specials():
    assert direct.non_usage_specials(["おまかせ", "調子次第", "奪三振", "セーブ狙い"]) == ["奪三振"]


def test_ranked_d_is_standard_and_non_d_is_feature():
    assert direct.rank_is_non_d("対ピンチD") is False
    assert direct.rank_is_non_d("対ピンチC") is True
    assert direct.rank_is_non_d("対ピンチE") is True


def test_pitch_count_metrics_separate_primary_display_and_second_fastball():
    balls = [
        {"kind": "breaking", "name": "スライダー", "movement": 3, "is_second_pitch": False},
        {"kind": "breaking", "name": "フォーク", "movement": 2, "is_second_pitch": False},
        {"kind": "breaking", "name": "Hスライダー", "movement": 1, "is_second_pitch": True},
        {"kind": "second_fastball", "name": "ツーシームファスト", "movement": 0},
    ]

    metrics = direct.generated_pitch_metrics(balls)

    assert metrics["通常球種数"] == 2
    assert metrics["表示球種数"] == 4
    assert metrics["第二球種あり"] is True
    assert metrics["ストレート系第二種あり"] is True
    assert metrics["第二球種+ストレート系第二種あり"] is True
    assert metrics["総変化量"] == 5


def test_real_workbook_can_be_read_when_local_file_exists():
    path = Path(__file__).resolve().parents[1] / "local_data" / "real_powerpro_players.xlsx"
    if not path.exists():
        pytest.skip("local real workbook is intentionally gitignored")

    players, events = direct.load_real_xlsx(path)

    assert {"投手", "野手"}.issubset(set(players["role"]))
    assert {"通常球種数", "表示球種数", "総変化量"}.issubset(players.columns)
    assert events[events["event_type"].eq("normal") & events["special"].isin(direct.USAGE_NAMES)].empty
