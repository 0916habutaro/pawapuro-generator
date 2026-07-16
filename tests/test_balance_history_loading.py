import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


def create_legacy_players_db(path: Path, *, include_breaking_column: bool = True) -> None:
    with sqlite3.connect(path) as conn:
        breaking_definition = ", breaking_balls_json TEXT" if include_breaking_column else ""
        conn.execute(
            f"""
            CREATE TABLE players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                abilities_json TEXT NOT NULL DEFAULT '{{}}',
                special_abilities_json TEXT NOT NULL DEFAULT '[]'
                {breaking_definition}
            )
            """
        )


def test_load_history_for_balance_parses_breaking_balls_json(tmp_path, monkeypatch):
    db = tmp_path / "players.sqlite3"
    create_legacy_players_db(db)
    breaking_balls = '[{"name":"カーブ","direction":"下","direction_code":"4","movement":3}]'
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO players (role, category, name, breaking_balls_json) VALUES (?, ?, ?, ?)",
            ("投手", "架空球団用", "変化 太郎", breaking_balls),
        )
    monkeypatch.setattr(app, "DB_PATH", db)

    history = app.load_history_for_balance()

    assert history.loc[0, "breaking_balls"] == [{"name": "カーブ", "direction": "下", "direction_code": "4", "movement": 3}]
    assert isinstance(history.loc[0, "breaking_balls"], list)


def test_load_history_for_balance_uses_empty_list_for_null_empty_and_invalid_json(tmp_path, monkeypatch):
    db = tmp_path / "players.sqlite3"
    create_legacy_players_db(db)
    with sqlite3.connect(db) as conn:
        conn.executemany(
            "INSERT INTO players (role, category, name, breaking_balls_json) VALUES (?, ?, ?, ?)",
            [
                ("投手", "架空球団用", "NULL投手", None),
                ("投手", "架空球団用", "空文字投手", ""),
                ("投手", "架空球団用", "不正JSON投手", "{"),
            ],
        )
    monkeypatch.setattr(app, "DB_PATH", db)

    history = app.load_history_for_balance()

    by_name = dict(zip(history["name"], history["breaking_balls"]))
    assert by_name["NULL投手"] == []
    assert by_name["空文字投手"] == []
    assert by_name["不正JSON投手"] == ["{"]
    assert all(isinstance(value, list) for value in history["breaking_balls"])


def test_load_history_for_balance_migrates_old_db_missing_new_columns(tmp_path, monkeypatch):
    db = tmp_path / "legacy.sqlite3"
    create_legacy_players_db(db, include_breaking_column=False)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO players (role, category, name) VALUES ('投手', '架空球団用', '旧投手')")
    monkeypatch.setattr(app, "DB_PATH", db)

    history = app.load_history_for_balance()

    expected_new_columns = [
        "breaking_balls_json",
        "birth_month",
        "birth_day",
        "pitching_form_type",
        "pitching_form_number",
        "pitching_form_is_generic",
        "batting_form_type",
        "batting_form_number",
        "batting_form_is_generic",
        "bat_color",
        "glove_color",
        "wristband_left_enabled",
        "wristband_left_color",
        "wristband_right_enabled",
        "wristband_right_color",
        "draft_source_type",
    ]
    for column in expected_new_columns:
        assert column in history.columns
    assert history.loc[0, "breaking_balls"] == []
    assert isinstance(history.loc[0, "breaking_balls"], list)


def test_load_history_for_balance_handles_empty_history(tmp_path, monkeypatch):
    db = tmp_path / "empty.sqlite3"
    monkeypatch.setattr(app, "DB_PATH", db)

    history = app.load_history_for_balance()

    assert history.empty
