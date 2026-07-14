import random
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


class JapaneseIdentityGenerationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.load_japanese_surname_master.cache_clear()
        cls.surname_master = app.load_japanese_surname_master()
        cls.master = app.load_master_data()

    def test_prefecture_weight_master_is_valid(self):
        self.assertEqual(len(app.JAPANESE_PREFECTURE_WEIGHTS), 47)
        self.assertEqual(sum(app.JAPANESE_PREFECTURE_WEIGHTS.values()), 919)
        self.assertTrue(all(isinstance(weight, int) and weight > 0 for weight in app.JAPANESE_PREFECTURE_WEIGHTS.values()))

    def test_surname_csv_master_is_valid(self):
        header = pd.read_csv(app.JAPANESE_SURNAME_PATH, encoding="utf-8-sig", nrows=0)
        self.assertEqual(list(header.columns), ["place", "surname", "number"])

        df = pd.read_csv(app.JAPANESE_SURNAME_PATH, encoding="utf-8-sig")
        self.assertEqual(set(df["place"].astype(str).str.strip()), set(app.JAPANESE_PREFECTURE_WEIGHTS))
        self.assertEqual(set(self.surname_master), set(app.JAPANESE_PREFECTURE_WEIGHTS))
        self.assertTrue((pd.to_numeric(df["number"], errors="coerce") >= 1).all())
        surnames = df["surname"].astype("string").str.strip()
        self.assertFalse(surnames.isna().any())
        self.assertFalse(surnames.eq("").any())
        self.assertFalse(surnames.str.contains("?", regex=False).any())
        self.assertFalse(surnames.str.contains("？", regex=False).any())
        self.assertFalse(surnames.str.contains("※希望により削除", regex=False).any())

    def test_generated_japanese_player_surname_belongs_to_birthplace(self):
        checked = 0
        for seed in range(3000, 3400):
            player = app.generate_player("野手", "ドラフト候補用", self.master, seed=seed)
            if player["nationality"] != "日本":
                continue
            birthplace = player["birthplace"]
            surname = player["name"].split()[0]
            self.assertIn(birthplace, app.JAPANESE_PREFECTURE_WEIGHTS)
            self.assertIn(surname, self.surname_master[birthplace]["surnames"])
            checked += 1
        self.assertGreaterEqual(checked, 300)

    def test_seed_reproduces_japanese_identity(self):
        seed = next(
            candidate
            for candidate in range(5000, 5200)
            if app.generate_player("投手", "ドラフト候補用", self.master, seed=candidate)["nationality"] == "日本"
        )
        first = app.generate_player("投手", "ドラフト候補用", self.master, seed=seed)
        second = app.generate_player("投手", "ドラフト候補用", self.master, seed=seed)
        self.assertEqual(first["nationality"], second["nationality"])
        self.assertEqual(first["birthplace"], second["birthplace"])
        self.assertEqual(first["name"].split()[0], second["name"].split()[0])
        self.assertEqual(first["name"].split()[1], second["name"].split()[1])
        self.assertEqual(first["name"], second["name"])

    def test_prefecture_distribution_uses_all_weighted_candidates(self):
        rng = random.Random(20260714)
        counter = {}
        for _ in range(100000):
            prefecture = app.choose_japanese_prefecture(rng)
            counter[prefecture] = counter.get(prefecture, 0) + 1
        self.assertEqual(set(counter), set(app.JAPANESE_PREFECTURE_WEIGHTS))
        self.assertGreater(counter["大阪府"], counter["山梨県"])
        self.assertGreater(counter["東京都"], counter["山口県"])

    def test_high_weight_surnames_are_more_common_within_prefecture(self):
        for prefecture in ["大阪府", "東京都", "北海道", "沖縄県"]:
            data = self.surname_master[prefecture]
            pairs = sorted(zip(data["surnames"], data["weights"], strict=True), key=lambda item: item[1], reverse=True)
            high_surname = pairs[0][0]
            low_surname = pairs[-1][0]
            rng = random.Random(f"test:{prefecture}")
            generated = [app.choose_japanese_surname(prefecture, rng, self.surname_master) for _ in range(20000)]
            self.assertGreater(generated.count(high_surname), generated.count(low_surname))

    def test_japanese_prefecture_aliases_are_normalized_for_history_display(self):
        self.assertEqual(app.normalize_japanese_prefecture_name("東京"), "東京都")
        self.assertEqual(app.normalize_japanese_prefecture_name("大阪"), "大阪府")
        self.assertEqual(app.normalize_japanese_prefecture_name("神奈川"), "神奈川県")

    def test_generated_japanese_name_is_consistent_in_history_audit(self):
        birthplace = "沖縄県"
        surname = self.surname_master[birthplace]["surnames"][-1]
        given_name = self.master.names["日本"]["名"][0]
        name = f"{surname} {given_name}"
        df = pd.DataFrame([{"name": name, "nationality": "日本", "birthplace": birthplace}])
        self.assertTrue(app.name_matches_nationality(name, "日本", self.master, birthplace))
        self.assertEqual(app.classify_name_type(name, self.master, "日本", birthplace), "日本")
        self.assertEqual(app.inconsistency_count(df, self.master, "name"), 0)

    def test_foreign_generation_does_not_load_japanese_surname_master(self):
        original_generate_foreign_profile = app.generate_foreign_profile
        original_load_japanese_surname_master = app.load_japanese_surname_master
        try:
            app.generate_foreign_profile = lambda *args, **kwargs: None

            def fail_load(*args, **kwargs):
                raise AssertionError("日本人苗字CSVを読み込んではいけません")

            app.load_japanese_surname_master = fail_load
            master = app.MasterData(
                names={"日本": {"姓": ["佐藤"], "名": ["蓮"]}, "アメリカ": {"姓": ["Smith"], "名": ["John"]}},
                places={"日本": ["東京都"], "アメリカ": ["テキサス州"]},
                abilities=[],
            )
            player = app.generate_player("野手", "助っ人外国人用", master, seed=2)
        finally:
            app.generate_foreign_profile = original_generate_foreign_profile
            app.load_japanese_surname_master = original_load_japanese_surname_master

        self.assertIn(player["nationality"], app.FOREIGN_NATIONS)
        self.assertTrue(player["name_generation_fallback"])

    def test_surname_master_is_cached_once(self):
        app.load_japanese_surname_master.cache_clear()
        first = app.load_japanese_surname_master()
        second = app.load_japanese_surname_master()
        self.assertIs(first, second)
        self.assertEqual(app.load_japanese_surname_master.cache_info().misses, 1)
        self.assertGreaterEqual(app.load_japanese_surname_master.cache_info().hits, 1)

    def test_invalid_surname_csv_fails_clearly(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            bad_header = Path(td) / "bad_header.csv"
            bad_header.write_text("place,rank,surname,number\n東京都,1,佐藤,1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "列が不正"):
                app.load_japanese_surname_master(str(bad_header))

            missing_prefecture = Path(td) / "missing_prefecture.csv"
            missing_prefecture.write_text("place,surname,number\n東京都,佐藤,1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "存在しない都道府県"):
                app.load_japanese_surname_master(str(missing_prefecture))

            non_positive = Path(td) / "non_positive.csv"
            pd.DataFrame({
                "place": list(app.JAPANESE_PREFECTURE_WEIGHTS),
                "surname": [f"姓{i}" for i in range(len(app.JAPANESE_PREFECTURE_WEIGHTS))],
                "number": [1] * (len(app.JAPANESE_PREFECTURE_WEIGHTS) - 1) + [0],
            }).to_csv(non_positive, index=False, encoding="utf-8-sig")
            with self.assertRaisesRegex(ValueError, "0以下"):
                app.load_japanese_surname_master(str(non_positive))


if __name__ == "__main__":
    unittest.main()
