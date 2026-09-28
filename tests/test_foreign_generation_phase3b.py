from pathlib import Path
import random

import app
from scripts import validate_foreign_generation_phase3b as phase3b


ROOT = Path(__file__).resolve().parents[1]


def test_phase3b_real_scope_is_212_and_missing_special_pitch_details():
    _frame, coverage = phase3b.load_real_scope(
        ROOT / "local_data" / "pawapuro_foreign_2022_2024_2025_complete_v6.xlsx"
    )

    assert coverage["対象player-season"] == 212
    assert coverage["投手"] == 127
    assert coverage["野手"] == 85
    assert coverage["特殊能力明細"] is False
    assert coverage["球種明細"] is False
    assert coverage["判定"] == "実在側データ不足のため今回未調整"


def test_phase3b_special_metrics_separate_usage_and_non_d_rank():
    master = app.load_master_data()
    kind_by_name, power_by_name = phase3b.special_master_maps(master)
    player = {
        "special_abilities": ["奪三振", "四球", "速球中心"],
        "abilities": {"ranked_specials": {"対ピンチ": "対ピンチB", "回復": "回復D"}},
    }

    metrics = phase3b.special_metrics(player, kind_by_name, power_by_name)

    assert metrics["countable_specials"] == 2
    assert metrics["display_specials"] == 4
    assert metrics["special_usage"] == 1
    assert metrics["special_rank"] == 1


def test_phase3b_pitch_metrics_follow_repertoire_definitions():
    balls = [
        app.make_breaking_ball("スライダー", 4, False, 1),
        app.make_breaking_ball("カットボール", 2, True, 2),
        app.make_breaking_ball("カーブ", 3, False, 1),
        app.select_second_fastball_type(random.Random(1)),
    ]

    metrics = phase3b.pitch_metrics({"breaking_balls": balls})

    assert metrics["primary_directions"] == 2
    assert metrics["breaking_pitch_count"] == 3
    assert metrics["final_pitch_count"] == 4
    assert metrics["has_second_pitch"] is True
    assert metrics["has_second_fastball"] is True
    assert metrics["primary_total_movement"] == 7
    assert metrics["all_breaking_total_movement"] == 9
    assert metrics["movement_vector"] == "[4,3]"
    assert metrics["first_second_difference"] == 2
