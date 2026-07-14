import json
import random
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app
from generator import foreign_names
from scripts import import_ootp_name_data


class OotpNameGenerationTest(unittest.TestCase):
    def build_imported_db(self, tmp: Path) -> Path:
        config = {
            "display_nationality_map": {
                "The United States": "アメリカ",
                "Atlantis": "その他",
                "South Korea": "韓国",
            },
            "foreign_nationality_weights": {"The United States": 100},
            "display_to_actual_candidates": {"アメリカ": {"The United States": 100}},
            "name_order": {"South Korea": "surname_given"},
            "exclude_initial_first_names": True,
            "excluded_single_last_names": ["De", "La"],
            "skin_color_weights": {
                "african": {"1": 1, "2": 1},
                "asian": {"2": 1, "3": 1},
                "east_indian": {"3": 1, "4": 1},
                "caucasian": {"1": 1, "2": 1},
                "hispanic": {"2": 1, "3": 1},
            },
        }
        config_path = tmp / "config.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        world_xml = tmp / "world.xml"
        world_xml.write_text(
            """<WORLD><ETHNICITIES>
            <ETHNICITY id="0" name="U.S. (Modern)" african="2" asian="5" east_indian="10" caucasian="980" hispanic="3" />
            <ETHNICITY id="3" name="Korean" african="0" asian="1000" east_indian="0" caucasian="0" hispanic="0" />
            <ETHNICITY id="99" name="Atlantian" african="10" asian="10" east_indian="10" caucasian="10" hispanic="10" />
            </ETHNICITIES><CONTINENTS><CONTINENT><NATIONS>
            <NATION id="1" name="The United States" abbr="USA" etid="0" bbqual="5"><ETHN_PCTS><ETHN_PCT etid="0" pct="100" /></ETHN_PCTS></NATION>
            <NATION id="2" name="Atlantis" abbr="ATL" etid="99" bbqual="1"><ETHN_PCTS><ETHN_PCT etid="99" pct="100" /></ETHN_PCTS></NATION>
            <NATION id="3" name="South Korea" abbr="KOR" etid="3" bbqual="4"><ETHN_PCTS><ETHN_PCT etid="3" pct="100" /></ETHN_PCTS></NATION>
            </NATIONS></CONTINENT></CONTINENTS></WORLD>""",
            encoding="utf-8",
        )
        names_xml = tmp / "names.xml"
        names_xml.write_text(
            """<NAMES><FIRST_NAMES>
            <N nid="1"><EN>John</EN><NL><L lid="0" dist="10" /></NL></N>
            <N nid="1"><EN>John</EN><NL><L lid="0" dist="5" /></NL></N>
            <N nid="2"><EN>Rare</EN><NL><L lid="0" dist="1" /></NL></N>
            <N nid="3"><EN>A.J.</EN><NL><L lid="0" dist="50" /></NL></N>
            <N nid="4"><EN>Ghost</EN><NL /></N>
            <N nid="5"><EN>Minjun</EN><NL><L lid="3" dist="10" /></NL></N>
            <N nid="6"><EN>Nemo</EN><NL><L lid="99" dist="10" /></NL></N>
            </FIRST_NAMES><LAST_NAMES>
            <N nid="10"><EN>Smith</EN><NL><L lid="0" dist="30" /></NL></N>
            <N nid="11"><EN>Smith</EN><NL><L lid="0" dist="20" /></NL></N>
            <N nid="12"><EN>De</EN><NL><L lid="0" dist="100" /></NL></N>
            <N nid="13"><EN>De La Cruz</EN><NL><L lid="0" dist="10" /></NL></N>
            <N nid="14"><EN>Kim</EN><NL><L lid="3" dist="10" /></NL></N>
            <N nid="15"><EN>Ocean</EN><NL><L lid="99" dist="10" /></NL></N>
            </LAST_NAMES><NICK_NAMES><N nid="99"><EN>Skip</EN><NL><L lid="0" dist="1" /></NL></N></NICK_NAMES></NAMES>""",
            encoding="utf-8",
        )
        db_path = tmp / "foreign_names.sqlite"
        conn = import_ootp_name_data.connect_output(db_path)
        with conn:
            import_ootp_name_data.import_world(conn, world_xml, config)
            import_ootp_name_data.import_names(conn, names_xml, config)
            import_ootp_name_data.create_indexes(conn)
            conn.execute("INSERT INTO metadata (key, value) VALUES (?, ?)", ("schema_version", import_ootp_name_data.SCHEMA_VERSION))
        conn.close()
        return db_path

    def build_source_files(self, tmp: Path) -> tuple[Path, Path, Path]:
        db_path = self.build_imported_db(tmp)
        db_path.unlink()
        return tmp / "names.xml", tmp / "world.xml", tmp / "config.json"

    def run_import_main(self, names_xml: Path, world_xml: Path, config_path: Path, output_path: Path) -> None:
        argv = [
            "import_ootp_name_data.py",
            "--names-xml", str(names_xml),
            "--world-xml", str(world_xml),
            "--config", str(config_path),
            "--output", str(output_path),
        ]
        with patch.object(sys, "argv", argv), redirect_stdout(StringIO()):
            import_ootp_name_data.main()

    def setUp(self):
        foreign_names.clear_caches()

    def tearDown(self):
        foreign_names.clear_caches()

    def test_xml_import_handles_duplicate_nid_and_name_weight_rules(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            db_path = self.build_imported_db(Path(td))
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("SELECT weight FROM names WHERE kind='first' AND lid=0 AND name='John'").fetchone()[0], 15)
                self.assertEqual(conn.execute("SELECT weight FROM names WHERE kind='last' AND lid=0 AND name='Smith'").fetchone()[0], 50)
                self.assertIsNone(conn.execute("SELECT 1 FROM names WHERE name='Ghost'").fetchone())
                self.assertIsNone(conn.execute("SELECT 1 FROM names WHERE name='A.J.'").fetchone())
                self.assertIsNone(conn.execute("SELECT 1 FROM names WHERE name='De'").fetchone())
                self.assertIsNotNone(conn.execute("SELECT 1 FROM names WHERE name='De La Cruz'").fetchone())

    def test_seed_reproduces_name_nationality_and_skin(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            db_path = self.build_imported_db(Path(td))
            rng1 = random.Random(7)
            rng2 = random.Random(7)
            p1 = foreign_names.generate_foreign_profile(rng1, "助っ人外国人用", db_path=db_path, config_path=Path(td) / "config.json")
            p2 = foreign_names.generate_foreign_profile(rng2, "助っ人外国人用", db_path=db_path, config_path=Path(td) / "config.json")
            self.assertEqual(p1, p2)
            self.assertEqual(p1.nationality, "アメリカ")

    def test_other_display_keeps_actual_nationality(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            db_path = self.build_imported_db(Path(td))
            config = json.loads((Path(td) / "config.json").read_text(encoding="utf-8"))
            config["foreign_nationality_weights"] = {"Atlantis": 100}
            (Path(td) / "config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            foreign_names.clear_caches()
            profile = foreign_names.generate_foreign_profile(random.Random(3), "助っ人外国人用", db_path=db_path, config_path=Path(td) / "config.json")
            self.assertEqual(profile.nationality, "その他")
            self.assertEqual(profile.actual_nationality, "Atlantis")

    def test_weighted_last_name_is_statistically_more_common(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            db_path = self.build_imported_db(Path(td))
            config_path = Path(td) / "config.json"
            surnames = []
            for seed in range(200):
                profile = foreign_names.generate_foreign_profile(random.Random(seed), "助っ人外国人用", db_path=db_path, config_path=config_path)
                surnames.append(profile.name.split()[-1])
            self.assertGreater(surnames.count("Smith"), surnames.count("Cruz"))

    def test_japanese_name_generation_stays_on_existing_master(self):
        master = app.MasterData(names={"日本": {"姓": ["佐藤"], "名": ["蓮"]}}, places={"日本": ["東京都"]}, abilities=[])
        player = app.generate_player("野手", "ドラフト候補用", master, seed=1)
        self.assertEqual(player["nationality"], "日本")
        self.assertEqual(player["name"], "佐藤 蓮")
        self.assertEqual(player["actual_nationality"], "")
        self.assertIn(player["skin_color"], range(1, 7))

    def test_missing_imported_db_falls_back_to_existing_foreign_master(self):
        master = app.MasterData(
            names={"日本": {"姓": ["佐藤"], "名": ["蓮"]}, "アメリカ": {"姓": ["Smith"], "名": ["John"]}},
            places={"日本": ["東京都"], "アメリカ": ["テキサス州"]},
            abilities=[],
        )
        original = app.generate_foreign_profile
        try:
            app.generate_foreign_profile = lambda *args, **kwargs: None
            player = app.generate_player("野手", "助っ人外国人用", master, seed=2)
        finally:
            app.generate_foreign_profile = original
        self.assertTrue(player["name_generation_fallback"])
        self.assertIn(player["nationality"], app.FOREIGN_NATIONS)
        self.assertIn(player["skin_color"], range(1, 7))

    def test_missing_imported_db_logs_fallback_warning(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            missing_db = Path(td) / "missing.sqlite"
            with self.assertLogs("generator.foreign_names", level="WARNING") as logs:
                profile = foreign_names.generate_foreign_profile(random.Random(1), "助っ人外国人用", db_path=missing_db)
            self.assertIsNone(profile)
            self.assertIn("フォールバック", "\n".join(logs.output))

    def test_imported_db_metadata_and_validation_are_present(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            names_xml, world_xml, config_path = self.build_source_files(Path(td))
            output_path = Path(td) / "foreign_names.sqlite"
            self.run_import_main(names_xml, world_xml, config_path, output_path)
            import_ootp_name_data.validate_imported_database(output_path)
            with sqlite3.connect(output_path) as conn:
                metadata = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
            self.assertEqual(metadata["schema_version"], import_ootp_name_data.SCHEMA_VERSION)
            self.assertIn("world_counts_json", metadata)

    def test_import_script_can_run_twice_without_duplicate_or_corruption(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            names_xml, world_xml, config_path = self.build_source_files(Path(td))
            output_path = Path(td) / "foreign_names.sqlite"
            self.run_import_main(names_xml, world_xml, config_path, output_path)
            self.run_import_main(names_xml, world_xml, config_path, output_path)
            with sqlite3.connect(output_path) as conn:
                counts = {
                    table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("ethnicities", "nations", "nation_ethnicities", "names")
                }
            self.assertEqual(counts, {"ethnicities": 3, "nations": 3, "nation_ethnicities": 3, "names": 8})

    def test_failed_import_keeps_existing_database_intact(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            names_xml, world_xml, config_path = self.build_source_files(Path(td))
            output_path = Path(td) / "foreign_names.sqlite"
            self.run_import_main(names_xml, world_xml, config_path, output_path)
            with sqlite3.connect(output_path) as conn:
                before = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
            with patch("scripts.import_ootp_name_data.import_names", side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError):
                    self.run_import_main(names_xml, world_xml, config_path, output_path)
            with sqlite3.connect(output_path) as conn:
                after = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
            self.assertEqual(before, after)

    def test_incomplete_imported_db_is_not_ready_and_does_not_raise(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            db_path = Path(td) / "old.sqlite"
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE names (kind TEXT, lid INTEGER, name TEXT, weight INTEGER)")
            foreign_names.clear_caches()
            self.assertFalse(foreign_names.imported_db_ready(str(db_path)))
            with self.assertLogs("generator.foreign_names", level="WARNING"):
                self.assertIsNone(foreign_names.generate_foreign_profile(random.Random(1), "助っ人外国人用", db_path=db_path))


if __name__ == "__main__":
    unittest.main()
