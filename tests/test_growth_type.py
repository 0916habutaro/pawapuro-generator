import random
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


def test_choose_growth_type_valid_all_categories_and_seeded():
    for category in app.CATEGORIES:
        one = app.choose_growth_type(category=category, age=22, player_class="一軍控え級", development_stage="標準型", acquisition_role="", rng=random.Random(123))
        two = app.choose_growth_type(category=category, age=22, player_class="一軍控え級", development_stage="標準型", acquisition_role="", rng=random.Random(123))
        assert one == two
        assert one in app.VALID_GROWTH_TYPES
    seen = {app.choose_growth_type(category="架空球団用", age=25, player_class="一軍控え級", development_stage="", acquisition_role="", rng=random.Random(seed)) for seed in range(50)}
    assert len(seen) >= 3


def test_growth_type_weight_corrections():
    base = app.growth_type_weight_map("架空球団用", 24, "一軍控え級", "", "")
    project = app.growth_type_weight_map("架空球団用", 20, "若手素材型", "", "")
    regular = app.growth_type_weight_map("架空球団用", 24, "一軍主力級", "", "")
    ready = app.growth_type_weight_map("ドラフト候補用", 22, "上位候補", "即戦力型", "")
    high_school = app.growth_type_weight_map("ドラフト候補用", 18, "育成候補", "素材型", "")
    assert project["late"] + project["very_late"] > base["late"] + base["very_late"]
    assert regular["very_early"] + regular["early"] > base["very_early"] + base["early"]
    assert ready["early"] + ready["normal"] > app.GROWTH_TYPE_BASE_WEIGHTS["ドラフト候補用"]["early"] + app.GROWTH_TYPE_BASE_WEIGHTS["ドラフト候補用"]["normal"]
    assert high_school["late"] + high_school["very_late"] > app.GROWTH_TYPE_BASE_WEIGHTS["ドラフト候補用"]["late"] + app.GROWTH_TYPE_BASE_WEIGHTS["ドラフト候補用"]["very_late"]


def test_growth_age_mods_direction_and_bounds():
    young_early = {k: 50 for k in app.FIELDER_ABILITY_KEYS}
    young_late = {k: 50 for k in app.FIELDER_ABILITY_KEYS}
    app.apply_fielder_growth_mods(young_early, 20, "very_early", "バランス", "")
    app.apply_fielder_growth_mods(young_late, 20, "very_late", "バランス", "")
    assert sum(young_early.values()) > sum(young_late.values())
    old_early = {k: 50 for k in app.FIELDER_ABILITY_KEYS}
    old_normal = {k: 50 for k in app.FIELDER_ABILITY_KEYS}
    old_late = {k: 50 for k in app.FIELDER_ABILITY_KEYS}
    app.apply_fielder_growth_mods(old_early, 38, "very_early", "バランス", "")
    app.apply_fielder_growth_mods(old_normal, 38, "normal", "バランス", "")
    app.apply_fielder_growth_mods(old_late, 38, "very_late", "バランス", "")
    assert sum(old_early.values()) < sum(old_normal.values()) < sum(old_late.values()) < 300


def test_generated_players_include_growth_type_pitcher_and_fielder():
    master = app.load_master_data()
    for role in ["投手", "野手"]:
        player = app.generate_player(role, "架空球団用", master, seed=777)
        assert player["growth_type"] in app.VALID_GROWTH_TYPES
        assert player["growth_type_label"] == app.growth_type_label(player["growth_type"])


def test_db_migration_and_fallback(monkeypatch):
    db = Path(tempfile.mkdtemp()) / "old.sqlite3"
    monkeypatch.setattr(app, "DB_PATH", db)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE players (id INTEGER PRIMARY KEY AUTOINCREMENT, seed INTEGER, role TEXT, category TEXT, name TEXT, age INTEGER, abilities_json TEXT, special_abilities_json TEXT, breaking_balls_json TEXT)")
        conn.execute("INSERT INTO players (seed, role, category, name, age, abilities_json, special_abilities_json, breaking_balls_json) VALUES (1, '野手', '架空球団用', '旧選手', 30, '{}', '[]', '[]')")
    app.init_db()
    hist = app.load_history()
    assert "growth_type" in hist.columns
    assert hist.iloc[0]["growth_type"] == "normal"
    assert app.player_from_history_row(hist.iloc[0])["growth_type"] == "normal"


def test_usage_growth_type_green_cell_and_not_counted():
    master = app.MasterData(names=[], places=[], abilities=[])
    player = {"role": "野手", "growth_type": "late", "special_abilities": []}
    html = app.render_usage_categories_html(player, master)
    assert "晩成" in html
    assert "成長タイプ" not in html
    assert 'class="pp-special green"' in html
    assert html.count("pp-usage-cell") % 4 == 0
    assert app.collect_special_entries(player, master, "usage") == []
