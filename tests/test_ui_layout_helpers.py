import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
        self.assertEqual(html.count('pp-usage-cell'), 32)
        self.assertIn('pp-usage-label">起用法', html)
        self.assertIn('pp-usage-value">速球中心', html)

    def test_empty_usage_categories_show_32_cells_without_setting_none(self):
        player = {"role": "野手", "special_abilities": []}
        html = app.render_usage_categories_html(player, self.master)
        self.assertIn('class="pp-usage-grid"', html)
        self.assertNotIn("設定なし", html)
        self.assertIn('pp-usage-label">起用法', html)
        self.assertEqual(html.count('pp-usage-cell'), 32)

    def test_usage_categories_expand_by_four_after_32_cells(self):
        player = {"role": "野手", "special_abilities": ["ミート多用", "強振多用", "積極打法"] * 11}
        html = app.render_usage_categories_html(player, self.master)
        self.assertGreater(html.count('pp-usage-cell'), 32)
        self.assertEqual(html.count('pp-usage-cell') % 4, 0)

    def test_header_has_no_overall_star(self):
        html = app.render_header_html({"role": "野手", "name": "山田", "position": "三塁手", "seed": 1, "batting_throwing": "右投右打"})
        self.assertNotIn("★", html)
        self.assertNotIn("pp-score", html)
        self.assertIn("守備位置　三", html)


    def test_header_direct_children_stay_in_single_grid_row(self):
        html = app.render_header_html({"role": "野手", "name": "山田", "position": "三塁手", "seed": 1, "category": "架空球団用", "batting_throwing": "右投右打"})
        for cls in ["pp-header-left", "pp-category-mark", "pp-number-box", "pp-face", "pp-info"]:
            self.assertIn(f'class="{cls}', html)
        self.assertLess(html.index('class="pp-info"'), html.index('</div>"') if '</div>"' in html else len(html))

    def test_layout_css_has_five_header_columns_and_horizontal_info(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn(".pp-header {display:grid; grid-template-columns:minmax(230px,1.05fr) 52px 72px 112px minmax(450px,1.7fr);", source)
        self.assertIn(".pp-info {display:grid; grid-template-columns:minmax(190px,1.45fr) minmax(160px,1fr) minmax(104px,.8fr);", source)


    def test_relative_player_id_empty_list(self):
        self.assertIsNone(app.relative_player_id([], None, 1))

    def test_relative_player_id_single_player_is_clamped(self):
        self.assertEqual(app.relative_player_id(["p1"], "p1", 1), "p1")
        self.assertEqual(app.relative_player_id(["p1"], "p1", -1), "p1")

    def test_relative_player_id_head_previous_is_clamped(self):
        self.assertEqual(app.relative_player_id(["p1", "p2", "p3"], "p1", -1), "p1")

    def test_relative_player_id_head_next_moves_to_second(self):
        self.assertEqual(app.relative_player_id(["p1", "p2", "p3"], "p1", 1), "p2")

    def test_relative_player_id_middle_previous_moves_to_first(self):
        self.assertEqual(app.relative_player_id(["p1", "p2", "p3"], "p2", -1), "p1")

    def test_relative_player_id_middle_next_moves_to_third(self):
        self.assertEqual(app.relative_player_id(["p1", "p2", "p3"], "p2", 1), "p3")

    def test_relative_player_id_tail_next_is_clamped(self):
        self.assertEqual(app.relative_player_id(["p1", "p2", "p3"], "p3", 1), "p3")

    def test_relative_player_id_invalid_current_uses_first(self):
        self.assertEqual(app.relative_player_id(["p1", "p2", "p3"], "missing", 1), "p1")

    def test_relative_player_id_large_offset_is_clamped(self):
        self.assertEqual(app.relative_player_id(["p1", "p2", "p3"], "p1", 20), "p3")
        self.assertEqual(app.relative_player_id(["p1", "p2", "p3"], "p3", -20), "p1")

    def test_duplicate_player_labels_still_get_distinct_latest_ids(self):
        players = [
            {"seed": 10, "name": "山田", "position": "先発", "player_type": "本格派", "age": 20, "batting_throwing": "右投右打"},
            {"seed": 11, "name": "山田", "position": "先発", "player_type": "本格派", "age": 20, "batting_throwing": "右投右打"},
        ]
        ids = [app.player_unique_id(player, index) for index, player in enumerate(players)]
        labels = [app.player_label(player, index) for index, player in enumerate(players)]
        self.assertEqual(len(set(ids)), 2)
        self.assertNotEqual(ids[0], ids[1])
        self.assertIn("山田", labels[0])

    def test_history_db_id_has_priority_over_latest_display_id(self):
        self.assertEqual(app.player_unique_id({"id": 42, "seed": 10, "name": "山田", "position": "先発"}, 0), "db:42")

    def test_latest_and_history_selected_player_keys_are_distinct(self):
        self.assertNotEqual("latest_selected_player_id", "history_selected_player_id")

    def test_profile_game_area_excludes_generation_fields(self):
        player = {"name": "山田", "age": 20, "batting_throwing": "右投右打", "nationality": "日本", "birthplace": "東京", "height": 180, "weight": 80, "category": "架空球団用", "player_type": "巧打型", "seed": 123}
        html = app.render_profile_right(player)
        self.assertNotIn("seed", html)
        self.assertNotIn("カテゴリ", html)
        self.assertNotIn("タイプ", html)
        self.assertIn("表示名", html)

    def test_generation_info_contains_seed_category_and_type(self):
        html = app.render_generation_info_html({"category": "架空球団用", "player_type": "巧打型", "seed": 123})
        self.assertIn("seed", html)
        self.assertIn("カテゴリ", html)
        self.assertIn("タイプ", html)

    def test_defense_table_always_renders_six_positions_with_split_rank_and_value(self):
        player = {"role": "野手", "position": "一塁手", "seed": 1, "abilities": {"走力": app.ability(50), "肩力": app.ability(50), "守備力": app.ability(56), "捕球": app.ability(50)}, "sub_positions": []}
        html = app.render_defense_usage_left(player)
        self.assertEqual(html.count('class="pp-defense-pos'), 6)
        self.assertIn('class="pp-defense-rank"', html)
        self.assertIn('class="pp-defense-num"', html)


    def test_detail_body_has_no_pitcher_aptitude_row_or_section_titles(self):
        player = {"role": "投手", "position": "先発", "abilities": {"球速": "145 km/h", "コントロール": app.ability(50), "スタミナ": app.ability(50)}, "special_abilities": []}
        html = app.render_detail_body_html(player, self.master, "投手能力")
        self.assertNotIn("pp-aptitude-line", html)
        self.assertNotIn("適性　", html)
        self.assertNotIn("特殊能力", html)
        self.assertNotIn("pp-section-title", html)

    def test_detail_panel_uses_keyed_streamlit_container_and_no_split_panel_html(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn('st.container(key=f"{key_prefix}_detail_shell")', source)
        self.assertNotIn("st.markdown(f'<div class=\"pp-panel", source)
        self.assertNotIn("</div></div>', unsafe_allow_html=True)", source)

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
