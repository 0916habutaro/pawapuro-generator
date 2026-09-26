import sqlite3
import sys
from collections import Counter
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


def career(age: int, seed: int, category: str = "架空球団用", source: str = ""):
    return app.generate_career_history(category=category, age=age, seed=seed, role="野手", draft_source_type=source)


def test_fictional_career_invariants_and_route_age_compatibility():
    for age in range(18, 47):
        for seed in range(400):
            result = career(age, age * 10_000 + seed)
            assert result["pro_years"] >= 1
            assert result["pro_entry_age"] <= age
            assert result["pro_years"] == age - result["pro_entry_age"] + 1
            if age == 19:
                assert result["entry_route"] != "大卒"


def test_age_22_can_generate_high_school_and_college_routes():
    routes = {career(22, seed)["entry_route"] for seed in range(2_000)}
    assert {"高卒", "大卒"}.issubset(routes)


def test_same_age_generates_multiple_pro_years_and_requested_examples():
    age_22 = [career(22, seed) for seed in range(5_000)]
    age_28 = [career(28, 10_000 + seed) for seed in range(10_000)]
    age_35 = [career(35, 30_000 + seed) for seed in range(10_000)]
    assert len({item["pro_years"] for item in age_28}) >= 8
    assert any(item["entry_route"] == "高卒" and item["pro_years"] == 5 for item in age_22)
    assert any(item["entry_route"] == "大卒" and item["pro_years"] == 1 for item in age_22)
    assert any(item["entry_route"] == "高卒" and item["pro_years"] == 11 for item in age_28)
    assert any(item["entry_route"] == "大卒" and item["pro_years"] == 7 for item in age_28)
    assert any(item["entry_route"] == "社会人" and 3 <= item["pro_years"] <= 6 for item in age_28)
    assert any(item["entry_route"] == "高卒" and item["pro_years"] >= 16 for item in age_35)
    assert any(item["entry_route"] == "大卒" and item["pro_years"] >= 12 for item in age_35)
    assert any(item["entry_route"] == "社会人" and item["pro_years"] <= 11 for item in age_35)


def test_late_entries_and_long_tenure_remain_possible():
    age_35 = [career(35, 60_000 + seed) for seed in range(10_000)]
    age_40 = [career(40, 80_000 + seed) for seed in range(10_000)]
    assert any(item["pro_entry_age"] >= 30 and item["pro_years"] <= 6 for item in age_35)
    assert any(item["pro_years"] >= 20 for item in age_40)


def test_fixed_seed_route_distribution_is_stable_and_complete():
    samples = []
    for start in [100_000, 200_000, 300_000]:
        routes = Counter(career(28, start + offset)["entry_route"] for offset in range(5_000))
        samples.append({route: routes[route] / 5_000 for route, _ in app.FICTIONAL_ENTRY_ROUTE_WEIGHTS})
    assert all(all(sample[route] > 0 for route, _ in app.FICTIONAL_ENTRY_ROUTE_WEIGHTS) for sample in samples)
    for route, _ in app.FICTIONAL_ENTRY_ROUTE_WEIGHTS:
        rates = [sample[route] for sample in samples]
        assert max(rates) - min(rates) < 0.03


def test_draft_candidates_have_no_pro_experience():
    for source in app.DRAFT_SOURCE_AGE_WEIGHTS:
        result = career(22, 1234, "ドラフト候補用", source)
        assert result["pro_years"] == 0
        assert result["pro_entry_age"] <= 22


def test_foreign_npb_tenure_is_first_year_centered_and_age_safe():
    sample = [career(24, seed, "助っ人外国人用") for seed in range(10_000)]
    counts = Counter(item["pro_years"] for item in sample)
    assert counts[1] / len(sample) >= 0.45
    assert sum(count for years, count in counts.items() if 2 <= years <= 4) / len(sample) >= 0.25
    assert 0 < sum(count for years, count in counts.items() if years >= 5) / len(sample) < len(sample) * 0.15
    assert all(item["pro_entry_age"] <= 24 for item in sample)


def test_career_seed_reproducibility():
    first = career(28, 8675309)
    second = career(28, 8675309)
    assert first == second


def test_generated_player_career_is_seed_reproducible():
    master = app.load_master_data()
    first = app.generate_player("投手", "架空球団用", master, seed=24681357)
    second = app.generate_player("投手", "架空球団用", master, seed=24681357)
    assert {key: first[key] for key in ["entry_route", "pro_entry_age", "pro_years"]} == {
        key: second[key] for key in ["entry_route", "pro_entry_age", "pro_years"]
    }


def test_profile_displays_pro_year_or_no_experience():
    experienced = app.render_profile_right({"name": "現役選手", "age": 28, "entry_route": "大卒", "pro_years": 7})
    draft = app.render_profile_right({"name": "候補選手", "age": 22, "entry_route": "大卒", "pro_years": 0})
    legacy = app.render_profile_right({"name": "旧選手", "age": 30, "entry_route": "", "pro_years": 0})
    assert "プロ" in experienced and "7年目" in experienced
    assert "プロ" in draft and "未経験" in draft
    assert "プロ" in legacy and "不明" in legacy


def test_career_history_does_not_modify_abilities_or_specials(monkeypatch):
    master = app.load_master_data()
    baseline = app.generate_player("投手", "架空球団用", master, seed=314159)
    monkeypatch.setattr(
        app,
        "generate_career_history",
        lambda **_kwargs: {"entry_route": "その他", "pro_entry_age": 27, "pro_years": 2},
    )
    changed_history = app.generate_player("投手", "架空球団用", master, seed=314159)
    assert changed_history["abilities"] == baseline["abilities"]
    assert changed_history["special_abilities"] == baseline["special_abilities"]
    assert changed_history["breaking_balls"] == baseline["breaking_balls"]
    assert changed_history["player_class"] == baseline["player_class"]
    assert changed_history["growth_type"] == baseline["growth_type"]
    assert changed_history["archetype"] == baseline["archetype"]


def test_career_rng_does_not_change_age_rng_stream():
    import random

    expected_rng = random.Random(20260926)
    actual_rng = random.Random(20260926)
    expected = [app.age_for(expected_rng, "架空球団用") for _ in range(1_000)]
    actual = []
    for seed in range(1_000):
        age = app.age_for(actual_rng, "架空球団用")
        app.generate_career_history(category="架空球団用", age=age, seed=seed, role="投手")
        actual.append(age)
    assert actual == expected


def test_generated_players_and_sqlite_roundtrip(tmp_path, monkeypatch):
    db = tmp_path / "players.sqlite3"
    monkeypatch.setattr(app, "DB_PATH", db)
    master = app.load_master_data()
    players = [
        app.generate_player("投手", "架空球団用", master, seed=1001),
        app.generate_player("野手", "ドラフト候補用", master, seed=1002),
        app.generate_player("野手", "助っ人外国人用", master, seed=1003),
    ]
    app.save_players(players)
    history = app.load_history().sort_values("seed")
    for expected, (_, restored) in zip(players, history.iterrows()):
        for key in ["entry_route", "pro_entry_age", "pro_years"]:
            assert restored[key] == expected[key]


def test_existing_database_migrates_without_rebuild(tmp_path, monkeypatch):
    db = tmp_path / "legacy.sqlite3"
    monkeypatch.setattr(app, "DB_PATH", db)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE players (id INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '')")
        conn.execute("INSERT INTO players (id, name) VALUES (7, '旧選手')")
    app.init_db()
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT id, name, entry_route, pro_entry_age, pro_years FROM players").fetchone()
    assert row == (7, "旧選手", "", 0, 0)


def test_impossible_combinations_are_absent():
    sample_19 = [career(19, seed) for seed in range(5_000)]
    sample_20 = [career(20, 10_000 + seed) for seed in range(5_000)]
    sample_22 = [career(22, 20_000 + seed) for seed in range(5_000)]
    assert not any(item["entry_route"] == "大卒" for item in sample_19)
    assert not any(item["pro_years"] == 10 for item in sample_20)
    assert not any(item["pro_years"] == 15 for item in sample_22)
