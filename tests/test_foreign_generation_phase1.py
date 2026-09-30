import hashlib
import json
import sqlite3
from unittest.mock import patch

import app


REGRESSION_KEYS = [
    "seed", "role", "category", "name", "age", "entry_route", "pro_entry_age", "pro_years",
    "nationality", "birthplace", "position", "player_type", "player_class", "growth_type",
    "archetype", "position_style", "development_stage", "acquisition_role", "weakness_profile",
    "batting_throwing", "height", "weight", "abilities", "special_abilities", "breaking_balls",
    "sub_positions",
]
SEED_REGRESSION = {
    ("投手", "架空球団用", 246810): "bcbbaca07edfa085475d067be7ca48794463925d80541458d3135d4b8b61d697",
    ("野手", "架空球団用", 246811): "a919be3daf07b875ae34a9b6a1cbef9461d8a187dd646447423cb9f498ae1df5",
    ("投手", "ドラフト候補用", 135790): "4a6e65206503a2f1ee8eeb48aef9b6c01d0132ad5a1c1495a5a24e95518b83c0",
    ("野手", "ドラフト候補用", 135791): "debaf11f861abc72218a861cf9e0be71fbc7fbcef87eab20c3f5a606705ec9e7",
}


def regression_hash(player: dict) -> str:
    payload = json.dumps(
        {key: player.get(key) for key in REGRESSION_KEYS},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_foreign_context_is_deterministic_and_valid():
    for role in ("投手", "野手"):
        first = app.generate_foreign_context(20260928, role)
        second = app.generate_foreign_context(20260928, role)
        assert first == second
        assert first["roster_origin"] == "foreign_import"
        assert first["foreign_route"] in app.FOREIGN_ROUTES
        assert first["nationality"] != "日本"
        assert first["npb_years"] >= 1


def test_foreign_category_always_uses_common_import_context():
    master = app.load_master_data()
    foreign_classes = {label for label, _ in app.PLAYER_CLASS_WEIGHTS["助っ人外国人用"]}
    for role in ("投手", "野手"):
        for seed in range(8):
            player = app.generate_player(role, "助っ人外国人用", master, seed=seed)
            assert player["roster_origin"] == "foreign_import"
            assert player["foreign_route"] in app.FOREIGN_ROUTES
            assert player["player_class"] in foreign_classes


def test_fictional_japanese_players_are_domestic_and_seed_regression_is_unchanged():
    master = app.load_master_data()
    for (role, category, seed), expected_hash in SEED_REGRESSION.items():
        player = app.generate_player(role, category, master, seed=seed)
        assert player["roster_origin"] == "domestic"
        assert player["foreign_route"] == ""
        assert regression_hash(player) == expected_hash


def test_fictional_foreign_national_can_use_domestic_route():
    master = app.load_master_data()
    assert app.determine_roster_origin("架空球団用", "台湾", 1) == "domestic"
    with patch.object(app, "choose_nationality", return_value="台湾"), patch.object(app, "generate_foreign_profile", return_value=None):
        player = app.generate_player("野手", "架空球団用", master, seed=1)
    assert player["nationality"] == "台湾"
    assert player["roster_origin"] == "domestic"
    assert player["foreign_route"] == ""


def test_fictional_import_keeps_display_category_and_uses_foreign_class():
    master = app.load_master_data()
    foreign_classes = {label for label, _ in app.PLAYER_CLASS_WEIGHTS["助っ人外国人用"]}
    with patch.object(app, "choose_nationality", return_value="アメリカ"), patch.object(app, "determine_roster_origin", return_value="foreign_import"):
        player = app.generate_player("投手", "架空球団用", master, seed=99)
    assert player["category"] == "架空球団用"
    assert player["roster_origin"] == "foreign_import"
    assert player["foreign_route"] in app.FOREIGN_ROUTES
    assert player["player_class"] in foreign_classes


def test_old_database_migrates_and_history_exposes_foreign_context(tmp_path, monkeypatch):
    db = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE players (id INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '')")
        conn.execute("INSERT INTO players (id, name) VALUES (7, '旧選手')")
    monkeypatch.setattr(app, "DB_PATH", db)

    history = app.load_history()

    for column in ("roster_origin", "foreign_route", "npb_years", "npb_first_entry_year", "npb_stint_start_year", "is_returnee"):
        assert column in history.columns
    row = history.iloc[0]
    assert row["name"] == "旧選手"
    assert row["roster_origin"] == ""
    assert row["foreign_route"] == ""
    assert row["npb_years"] == 0


def test_foreign_context_sqlite_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DB_PATH", tmp_path / "players.sqlite3")
    player = app.generate_player("野手", "助っ人外国人用", app.load_master_data(), seed=8080)

    app.save_players([player])
    restored = app.load_history().iloc[0]

    for key in ("roster_origin", "foreign_route", "npb_years", "npb_first_entry_year", "npb_stint_start_year"):
        assert restored[key] == player[key]
    assert bool(restored["is_returnee"]) == player["is_returnee"]


def test_profile_displays_foreign_route_and_tenure():
    html = app.render_profile_right({
        "name": "TEST PLAYER",
        "age": 30,
        "roster_origin": "foreign_import",
        "foreign_route": "north_america_pro",
        "npb_years": 2,
        "entry_route": "海外プロ経由",
        "pro_years": 2,
    })
    assert "加入区分" in html and "外国人補強" in html
    assert "経由" in html and "北米プロ" in html
    assert "NPB在籍" in html and "2年目" in html
