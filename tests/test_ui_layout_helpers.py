import re
import unittest

import app


def special_cell_count(html: str) -> int:
    return len(re.findall(r'<div class="pp-special(?: |")', html))


class UiLayoutHelpersTest(unittest.TestCase):
    def setUp(self):
        self.master = app.MasterData(
            names={},
            places={},
            abilities=[
                {"name": "速球中心", "kind": "green", "target_role": "投手"},
                {"name": "テンポ○", "kind": "green", "target_role": "投手"},
                {"name": "調子次第", "kind": "green", "target_role": "共通"},
                {"name": "フル出場", "kind": "green", "target_role": "共通"},
                {"name": "人気者", "kind": "green", "target_role": "共通"},
                {"name": "ミート多用", "kind": "green", "target_role": "野手"},
                {"name": "強振多用", "kind": "green", "target_role": "野手"},
                {"name": "積極打法", "kind": "green", "target_role": "野手"},
                {"name": "積極盗塁", "kind": "green", "target_role": "野手"},
                {"name": "積極守備", "kind": "green", "target_role": "野手"},
                {"name": "広角打法", "kind": "blue", "target_role": "野手"},
                {"name": "奪三振", "kind": "blue", "target_role": "投手"},
            ],
        )

    def test_legacy_player_tab_is_converted_by_role(self):
        self.assertEqual(app.normalize_selected_tab_value({"role": "投手"}, "選手能力"), "投手能力")
        self.assertEqual(app.normalize_selected_tab_value({"role": "野手"}, "選手能力"), "野手能力")

    def test_pitcher_and_fielder_special_grids_have_minimum_32_cells(self):
        pitcher = {"role": "投手", "position": "先発", "abilities": {}, "special_abilities": ["奪三振"]}
        fielder = {"role": "野手", "position": "外野手", "abilities": {}, "special_abilities": ["広角打法"]}
        self.assertEqual(special_cell_count(app.render_special_grid_html(pitcher, self.master, mode="pitcher")), 32)
        self.assertEqual(special_cell_count(app.render_special_grid_html(fielder, self.master, mode="fielder")), 32)

    def test_special_grid_expands_past_32_without_summary_cell(self):
        player = {"role": "野手", "position": "外野手", "abilities": {}, "special_abilities": ["広角打法"] * 33}
        html = app.render_special_grid_html(player, self.master, mode="fielder")
        self.assertGreaterEqual(html.count("広角打法"), 33)
        self.assertNotIn("ほか", html)
        self.assertGreaterEqual(special_cell_count(html), 44)

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

    def test_usage_categories_render_as_four_column_grid(self):
        player = {"role": "投手", "special_abilities": ["調子次第", "速球中心", "テンポ○", "人気者"]}
        html = app.render_usage_categories_html(player, self.master)
        self.assertIn('class="pp-usage-grid"', html)
        self.assertEqual(html.count('pp-usage-cell'), 12)
        self.assertIn('pp-usage-label">起用法', html)
        self.assertIn('pp-usage-value">速球中心', html)

    def test_empty_usage_categories_show_empty_grid_only(self):
        player = {"role": "野手", "special_abilities": []}
        html = app.render_usage_categories_html(player, self.master)
        self.assertIn('class="pp-usage-grid"', html)
        self.assertIn("設定なし", html)
        self.assertEqual(html.count('pp-usage-cell'), 4)

    def test_header_has_no_overall_star(self):
        html = app.render_header_html({"role": "野手", "name": "山田", "position": "三塁手", "seed": 1, "batting_throwing": "右投右打"})
        self.assertNotIn("★", html)
        self.assertNotIn("pp-score", html)
        self.assertIn("守備位置　三", html)

    def test_profile_renders_seed_once(self):
        html = app.render_profile_right({"name": "山田", "age": 20, "batting_throwing": "右投右打", "nationality": "日本", "birthplace": "東京", "height": 180, "weight": 80, "category": "架空球団用", "player_type": "巧打型", "seed": 123})
        self.assertEqual(html.count("seed"), 1)
        self.assertNotIn("pp-seed-note", html)

    def test_defense_table_always_renders_six_positions_with_split_rank_and_value(self):
        player = {"role": "野手", "position": "一塁手", "seed": 1, "abilities": {"走力": app.ability(50), "肩力": app.ability(50), "守備力": app.ability(56), "捕球": app.ability(50)}, "sub_positions": []}
        html = app.render_defense_usage_left(player)
        self.assertEqual(html.count('class="pp-defense-pos'), 6)
        self.assertIn('class="pp-defense-rank"', html)
        self.assertIn('class="pp-defense-num"', html)

    def test_same_direction_pitch_labels_are_split_horizontally(self):
        html = app.render_pitch_chart_svg([
            {"kind": "breaking", "direction_code": "3", "name": "SFF", "movement": 3},
            {"kind": "breaking", "direction_code": "3", "name": "フォーク", "movement": 4},
        ])
        labels = re.findall(r'<text x="([0-9.]+)" y="[0-9.]+" text-anchor="(end|start)"[^>]*>(SFF|フォーク)</text>', html)
        self.assertEqual(len(labels), 2)
        anchors = {label: anchor for _x, anchor, label in labels}
        xs = {label: float(x) for x, _anchor, label in labels}
        self.assertEqual(anchors["SFF"], "end")
        self.assertEqual(anchors["フォーク"], "start")
        self.assertLess(xs["SFF"], xs["フォーク"])


if __name__ == "__main__":
    unittest.main()
