import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


def numeric(abilities, key):
    value = abilities[key]
    return value["value"] if isinstance(value, dict) else value


def assert_form(form_type, number, is_generic, ranges):
    total_max, generic_max = ranges[form_type]
    assert 1 <= number <= total_max
    assert (number <= generic_max) if is_generic else (number > generic_max)


def test_seed_reproduces_profile_forms_pitcher_fielding_equipment():
    master = app.load_master_data()
    first = app.generate_player("投手", "ドラフト候補用", master, seed=24680)
    second = app.generate_player("投手", "ドラフト候補用", master, seed=24680)
    keys = [
        "birth_month", "birth_day", "pitching_form_type", "pitching_form_number", "pitching_form_is_generic",
        "batting_form_type", "batting_form_number", "batting_form_is_generic", "bat_color", "glove_color",
        "wristband_left_enabled", "wristband_left_color", "wristband_right_enabled", "wristband_right_color",
        "draft_source_type", "age",
    ]
    assert {key: first[key] for key in keys} == {key: second[key] for key in keys}
    fielding_keys = ["弾道", "ミート", "パワー", "走力", "肩力", "守備力", "捕球"]
    assert {key: first["abilities"][key] for key in fielding_keys} == {key: second["abilities"][key] for key in fielding_keys}


def test_form_ranges_and_pitcher_ability_ranges():
    master = app.load_master_data()
    for seed in range(300):
        player = app.generate_player("投手", "架空球団用", master, seed=seed)
        assert_form(player["pitching_form_type"], player["pitching_form_number"], player["pitching_form_is_generic"], app.PITCHING_FORM_RANGES)
        assert_form(player["batting_form_type"], player["batting_form_number"], player["batting_form_is_generic"], app.BATTING_FORM_RANGES)
        abilities = player["abilities"]
        assert 4 <= numeric(abilities, "ミート") <= 31
        assert 6 <= numeric(abilities, "パワー") <= 44
        assert 28 <= numeric(abilities, "走力") <= 77
        assert 49 <= numeric(abilities, "肩力") <= 82
        assert 28 <= numeric(abilities, "守備力") <= 78
        assert 25 <= numeric(abilities, "捕球") <= 75
        pitch_speed = app.pitcher_speed_value(abilities)
        assert numeric(abilities, "肩力") == app.clamp(numeric(abilities, "肩力"), 49, 82)
        if 131 <= pitch_speed <= 163:
            assert pitch_speed - 82 <= numeric(abilities, "肩力") <= pitch_speed - 79
        assert player["glove_color"] != "シルバー"


def test_draft_source_age_ranges():
    master = app.load_master_data()
    valid = {source: {age for age, _ in ages} for source, ages in app.DRAFT_SOURCE_AGE_WEIGHTS.items()}
    for seed in range(500):
        player = app.generate_player("野手", "ドラフト候補用", master, seed=10000 + seed)
        assert player["age"] in valid[player["draft_source_type"]]


def test_db_roundtrip_and_legacy_migration(tmp_path, monkeypatch):
    db = tmp_path / "players.sqlite3"
    monkeypatch.setattr(app, "DB_PATH", db)
    master = app.load_master_data()
    player = app.generate_player("投手", "ドラフト候補用", master, seed=13579)
    app.save_players([player])
    history = app.load_history()
    row = history.iloc[0]
    for key in ["birth_month", "birth_day", "pitching_form_type", "pitching_form_number", "batting_form_type", "bat_color", "glove_color", "draft_source_type"]:
        assert row[key] == player[key]
    restored = app.player_from_history_row(row)
    assert restored["abilities"]["ミート"] == player["abilities"]["ミート"]

    legacy = tmp_path / "legacy.sqlite3"
    monkeypatch.setattr(app, "DB_PATH", legacy)
    with sqlite3.connect(legacy) as conn:
        conn.execute("CREATE TABLE players (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL DEFAULT '')")
        conn.execute("INSERT INTO players (name) VALUES ('旧選手')")
    app.init_db()
    migrated = app.load_history()
    assert "birth_month" in migrated.columns
