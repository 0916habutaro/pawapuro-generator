import unittest

import app


class UiLayoutHelpersTest(unittest.TestCase):
    def setUp(self):
        self.master = app.MasterData(
            names={},
            places={},
            abilities=[
                {"name": "速球中心", "kind": "green", "target_role": "投手"},
                {"name": "テンポ○", "kind": "green", "target_role": "投手"},
                {"name": "フル出場", "kind": "green", "target_role": "共通"},
                {"name": "人気者", "kind": "green", "target_role": "共通"},
                {"name": "ミート多用", "kind": "green", "target_role": "野手"},
                {"name": "積極盗塁", "kind": "green", "target_role": "野手"},
                {"name": "積極守備", "kind": "green", "target_role": "野手"},
                {"name": "広角打法", "kind": "blue", "target_role": "野手"},
            ],
        )

    def test_legacy_player_tab_is_converted_by_role(self):
        self.assertEqual(app.normalize_selected_tab_value({"role": "投手"}, "選手能力"), "投手能力")
        self.assertEqual(app.normalize_selected_tab_value({"role": "野手"}, "選手能力"), "野手能力")

    def test_special_grid_expands_past_24_without_summary_cell(self):
        player = {"role": "野手", "position": "外野手", "abilities": {}, "special_abilities": ["広角打法"] * 25}
        html = app.render_special_grid_html(player, self.master, mode="fielder")
        self.assertGreaterEqual(html.count("広角打法"), 25)
        self.assertNotIn("ほか", html)
        self.assertGreaterEqual(html.count('class="pp-special'), 36)

    def test_pitcher_usage_categories_do_not_include_fielder_policy(self):
        player = {"role": "投手", "special_abilities": ["速球中心", "テンポ○", "ミート多用", "フル出場", "人気者"]}
        categories = app.usage_special_categories(player, self.master)
        self.assertEqual(categories["投球方針"], ["速球中心", "テンポ○"])
        self.assertEqual(categories["起用法"], ["フル出場"])
        self.assertNotIn("ミート多用", str(categories))

    def test_fielder_usage_categories_do_not_include_pitcher_policy(self):
        player = {"role": "野手", "special_abilities": ["速球中心", "ミート多用", "積極盗塁", "積極守備", "人気者"]}
        categories = app.usage_special_categories(player, self.master)
        self.assertEqual(categories["打撃方針"], ["ミート多用"])
        self.assertEqual(categories["走塁方針"], ["積極盗塁"])
        self.assertEqual(categories["守備方針"], ["積極守備"])
        self.assertNotIn("速球中心", str(categories))

    def test_empty_usage_categories_are_hidden(self):
        player = {"role": "野手", "special_abilities": ["ミート多用"]}
        html = app.render_usage_categories_html(player, self.master)
        self.assertIn("打撃方針", html)
        self.assertNotIn("走塁方針", html)
        self.assertNotIn("守備方針", html)

    def test_defense_table_always_renders_six_positions(self):
        player = {"role": "野手", "position": "一塁手", "seed": 1, "abilities": {"走力": app.ability(50), "肩力": app.ability(50), "守備力": app.ability(56), "捕球": app.ability(50)}, "sub_positions": []}
        html = app.render_defense_usage_left(player)
        self.assertEqual(html.count('class="pp-defense-pos'), 6)
        self.assertIn("一</span>", html)
        self.assertIn("D56", html.replace("</span>", "").replace("<span>", ""))


if __name__ == "__main__":
    unittest.main()
