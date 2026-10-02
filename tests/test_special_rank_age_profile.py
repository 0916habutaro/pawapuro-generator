"""特能ランク年齢補正_改修指示.md：特殊能力の数・ランク特能の年齢補正。"""
import statistics
import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "scripts"))

import app  # noqa: E402
import check_age_profile  # noqa: E402


class AgeRankWeightTest(unittest.TestCase):
    def test_young_players_get_fewer_high_ranks_and_narrower_spread(self):
        weights = app.FICTIONAL_FIELDER_RANKED_WEIGHTS["チャンス"]
        young = app.fictional_age_rank_weights(weights, "チャンス", "野手", 19)
        veteran = app.fictional_age_rank_weights(weights, "チャンス", "野手", 31)
        share = lambda w, letters: sum(w[x] for x in letters) / sum(w.values())  # noqa: E731
        self.assertLess(share(young, "AB"), share(weights, "AB") * 0.3)
        self.assertGreater(share(veteran, "AB"), share(weights, "AB"))
        self.assertLess(share(young, "FG"), share(weights, "FG"))

    def test_a_and_g_weights_never_increase(self):
        for role, table in (("野手", app.FICTIONAL_FIELDER_RANKED_WEIGHTS), ("投手", app.FICTIONAL_PITCHER_RANKED_WEIGHTS)):
            for group, weights in table.items():
                for age in range(18, 43):
                    tilted = app.fictional_age_rank_weights(weights, group.removesuffix("_左投"), role, age)
                    self.assertLessEqual(tilted["A"], weights["A"] + 1e-12)
                    self.assertLessEqual(tilted["G"], weights["G"] + 1e-12)

    def test_multipliers_are_continuous(self):
        for role, kinds in app.FICTIONAL_AGE_SPECIAL_MULTIPLIERS.items():
            for kind in kinds:
                values = [app.fictional_age_special_multiplier(role, kind, age) for age in range(18, 43)]
                self.assertLess(max(abs(a - b) for a, b in zip(values, values[1:])), 0.2)
        self.assertEqual(app.fictional_age_special_multiplier("投手", "neg", 20), 1.0)


class AgeProfileGenerationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        master = app.load_master_data()
        cls.rows = {
            role: [
                check_age_profile.player_metrics(player, "個別")
                for player in (app.generate_player(role, "架空球団用", master, seed=seed) for seed in range(1, 401))
                if check_age_profile.is_target(player)
            ]
            for role in ("投手", "野手")
        }

    def test_specials_and_ranks_increase_with_age(self):
        for role, rows in self.rows.items():
            young = [row for row in rows if row["age"] <= 22]
            prime = [row for row in rows if 29 <= row["age"] <= 34]
            for metric in ("n_pos", "n_green", "rk_pts"):
                self.assertGreater(
                    statistics.fmean(row[metric] for row in prime), statistics.fmean(row[metric] for row in young), (role, metric),
                )
            self.assertLess(statistics.fmean(row["rk_hi"] for row in young), 0.2, role)

    def test_specials_stay_within_class_bounds_and_real_list(self):
        master = app.load_master_data()
        for seed in range(1, 201):
            for role in ("投手", "野手"):
                player = app.generate_player(role, "架空球団用", master, seed=seed)
                if not check_age_profile.is_target(player):
                    continue
                names = player["special_abilities"]
                self.assertEqual(len(names), len(set(names)))
                self.assertFalse(set(names) & app.FICTIONAL_NOT_REAL_SPECIALS[role])
                low, high = app.special_count_bounds("架空球団用", player["player_class"])
                self.assertLessEqual(sum(app.is_countable_special(name) for name in names), high)


if __name__ == "__main__":
    unittest.main()
