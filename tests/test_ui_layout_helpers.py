import itertools
import json
import math
import re
import sys
import tempfile
import unittest
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


class ClassTreeParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.header_children = []
        self.name_attrs = None
        self.name_text = []
        self._in_name = False

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        classes = attr_dict.get("class", "").split()
        if self.stack and "pp-header" in self.stack[-1] and tag == "div":
            self.header_children.append(attr_dict.get("class", ""))
        if "pp-name" in classes:
            self.name_attrs = attr_dict
            self._in_name = True
        self.stack.append(classes)

    def handle_data(self, data):
        if self._in_name:
            self.name_text.append(data)

    def handle_endtag(self, tag):
        if self.stack:
            classes = self.stack.pop()
            if "pp-name" in classes:
                self._in_name = False


def special_cell_count(html: str) -> int:
    return len(re.findall(r'<div class="pp-special(?: |")', html))


def css_block(source: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)} \{{([^}}]+)\}}", source)
    if not match:
        raise AssertionError(f"CSS block not found: {selector}")
    return match.group(1)


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

    def test_saved_player_tab_is_converted_by_role(self):
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
        self.assertIn('<span class="pp-mini-label">守備位置</span>', html)
        self.assertIn('<span class="pp-pos-item main">三</span>', html)


    def test_header_direct_children_are_three_blocks(self):
        html = app.render_header_html({"role": "野手", "name": "山田", "position": "三塁手", "seed": 1, "category": "架空球団用", "batting_throwing": "右投右打"})
        parser = ClassTreeParser()
        parser.feed(html)
        self.assertEqual(parser.header_children, ["pp-header-main", "pp-face", "pp-info"])
        for cls in ["pp-header-main", "pp-face", "pp-info"]:
            self.assertEqual(html.count(f'class="{cls}"'), 1)
        self.assertNotIn('class="pp-header-left"', html)

    def test_header_display_content_is_preserved(self):
        pitcher = {"role": "投手", "name": "山田 太郎", "position": "先発", "seed": 1, "category": "架空球団用", "batting_throwing": "右投右打"}
        fielder = {"role": "野手", "name": "佐藤 次郎", "position": "三塁手", "seed": 2, "category": "ドラフト候補用", "batting_throwing": "左投左打"}
        pitcher_html = app.render_header_html(pitcher)
        self.assertIn("山田 太郎", pitcher_html)
        for text in ["pp-category-mark", "pp-number-box", "pp-face", "成績", "フォーム", "投打", "適性"]:
            self.assertIn(text, pitcher_html)
        for text in ["★", "pp-score", "seed", "タイプ"]:
            self.assertNotIn(text, pitcher_html)
        fielder_html = app.render_header_html(fielder)
        self.assertIn('<span class="pp-mini-label">守備位置</span>', fielder_html)
        self.assertIn('<span class="pp-pos-item main">三</span>', fielder_html)

    def test_header_position_shows_sub_positions_and_sized_pitcher_aptitudes(self):
        fielder = {"role": "野手", "name": "佐藤", "position": "遊撃手", "seed": 2, "batting_throwing": "右投右打", "sub_positions": [{"position": "外野手", "aptitude": "△"}, {"position": "三塁手", "aptitude": "○"}]}
        html = app.header_position_html(fielder)
        self.assertIn('<span class="pp-pos-item main">遊</span><span class="pp-pos-item sub">三</span><span class="pp-pos-item sub">外</span>', html)
        pitcher = {"role": "投手", "name": "山田", "position": "中継ぎ", "seed": 1, "starter_aptitude": "○", "reliever_aptitude": "◎", "closer_aptitude": "－"}
        html = app.header_position_html(pitcher)
        self.assertIn('<span class="pp-mini-label">適性</span>', html)
        self.assertIn('class="pp-pos-item lv2" title="先○">先</span>', html)
        self.assertIn('class="pp-pos-item lv3" title="中◎">中</span>', html)
        self.assertNotIn(">抑<", html)

    def test_header_name_has_escaped_title_and_text(self):
        name = 'A&B <Ace> "Slugger"'
        html = app.render_header_html({"role": "野手", "name": name, "position": "三塁手", "seed": 1, "category": "架空球団用", "batting_throwing": "右投右打"})
        parser = ClassTreeParser()
        parser.feed(html)
        self.assertEqual(parser.name_attrs.get("title"), name)
        self.assertEqual("".join(parser.name_text).strip(), name)
        self.assertIn('title="A&amp;B &lt;Ace&gt; &quot;Slugger&quot;"', html)
        self.assertIn('A&amp;B &lt;Ace&gt; &quot;Slugger&quot;', html)
        self.assertNotIn("<Ace>", html)

    def test_layout_css_has_three_header_columns_and_horizontal_info(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn(".pp-header {display:grid; grid-template-columns:minmax(330px, 1.2fr) 126px minmax(400px, 1.45fr);", source)
        self.assertIn(".pp-header-main {display:grid; grid-template-rows:76px 43px;", source)
        self.assertIn(".pp-name-line {display:grid; grid-template-columns:minmax(0, 1fr) 48px 62px;", source)
        self.assertIn(".pp-info {display:grid; grid-template-columns:minmax(170px, 1.3fr) minmax(130px, 1fr) minmax(100px, .72fr);", source)
        self.assertNotIn("pp-header-left", source)

    def test_player_section_has_one_selector_and_one_card(self):
        source = Path("app.py").read_text(encoding="utf-8")
        section_source = source[source.index("def render_player_section"):source.index("def history_excel_bytes")]
        self.assertIn("previous_col, select_col, count_col, next_col = st.columns(", section_source)
        self.assertIn("key=PLAYER_SELECT_KEY", section_source)
        self.assertEqual(section_source.count("on_click=select_relative_player"), 2)
        self.assertEqual(section_source.count("render_detail_panel("), 1)
        self.assertIn("{current_index + 1} / {len(player_ids)}", section_source)
        main_source = source[source.index("def main"):]
        self.assertNotIn("render_player_browser", source)
        self.assertNotIn("st.expander", main_source)
        self.assertNotIn("selected_index", source)

    def test_player_choice_ids_are_newest_first_and_include_latest(self):
        history_ids = [f"db:{number}" for number in range(10, 0, -1)]
        self.assertEqual(app.player_choice_ids(history_ids, ["db:10", "db:9"], None), history_ids)
        self.assertEqual(app.player_choice_ids(history_ids, ["latest:1:山田:先発:0"], None)[0], "latest:1:山田:先発:0")

    def test_player_choice_ids_keep_selected_player_beyond_limit_in_order(self):
        history_ids = [f"db:{number}" for number in range(10, 0, -1)]
        self.assertEqual(app.player_choice_ids(history_ids, [], "db:2", limit=3), ["db:10", "db:9", "db:8", "db:2"])


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
        labels = [app.player_label(player) for player in players]
        self.assertEqual(len(set(ids)), 2)
        self.assertNotEqual(ids[0], ids[1])
        self.assertIn("山田", labels[0])
        self.assertTrue(app.player_label(players[0], is_new=True).startswith("【NEW】"))
        self.assertFalse(labels[0].startswith("1."))

    def test_history_db_id_has_priority_over_latest_display_id(self):
        self.assertEqual(app.player_unique_id({"id": 42, "seed": 10, "name": "山田", "position": "先発"}, 0), "db:42")

    def test_detail_card_keeps_latest_key_prefix_for_card_css(self):
        self.assertEqual(app.DETAIL_KEY_PREFIX, "latest")


    def test_ui_rank_color_e_is_green(self):
        self.assertEqual(app.ui_rank_color("E"), "#20a84a")

    def test_ui_rank_colors_except_e_are_unchanged(self):
        expected = {
            "S": "#ff5da2",
            "A": "#ff3bbd",
            "B": "#ff315d",
            "C": "#ff9d00",
            "D": "#d7c900",
            "F": "#63a4ff",
            "G": "#9aa4af",
        }
        for rank_text, color in expected.items():
            with self.subTest(rank=rank_text):
                self.assertEqual(app.ui_rank_color(rank_text), color)

    def test_basic_ability_rank_boundaries_include_s(self):
        expected = {
            0: "G", 19: "G", 20: "F", 39: "F", 40: "E", 49: "E",
            50: "D", 59: "D", 60: "C", 69: "C", 70: "B", 79: "B",
            80: "A", 89: "A", 90: "S", 100: "S",
        }
        for value, rank_text in expected.items():
            with self.subTest(value=value):
                self.assertEqual(app.rank(value), rank_text)

    def test_ability_clamps_to_zero_and_one_hundred(self):
        self.assertEqual(app.ability(-1), {"value": 0, "rank": "G"})
        self.assertEqual(app.ability(101), {"value": 100, "rank": "S"})

    def test_rank_colors_add_s_without_changing_a_to_g(self):
        expected = {
            "S": "#ff5da2",
            "A": "#ff5a5a",
            "B": "#ff9f43",
            "C": "#ffd166",
            "D": "#6ee7b7",
            "E": "#60a5fa",
            "F": "#a78bfa",
            "G": "#cbd5e1",
        }
        self.assertEqual(app.RANK_COLORS, expected)

    def test_basic_ability_rows_render_zero_and_s_rank_values(self):
        html = app.render_ability_rows([
            ("A0", app.ability(0)),
            ("A90", app.ability(90)),
            ("A99", app.ability(99)),
            ("A100", app.ability(100)),
        ])
        self.assertIn(">G</div><div class=\"pp-value\">0</div>", html)
        self.assertEqual(html.count(">S</div>"), 3)
        self.assertIn("#ff5da2", html)

    def test_csv_and_excel_preserve_s_rank_ability_json(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            df = pd.DataFrame([{
                "name": "S-rank test",
                "abilities_json": json.dumps({"A90": app.ability(90), "A100": app.ability(100)}, ensure_ascii=False),
            }])
            csv_path = tmp / "players.csv"
            xlsx_path = tmp / "players.xlsx"
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name="players", index=False)

            csv_abilities = json.loads(pd.read_csv(csv_path, encoding="utf-8-sig").loc[0, "abilities_json"])
            excel_abilities = json.loads(pd.read_excel(xlsx_path).loc[0, "abilities_json"])
            self.assertEqual(csv_abilities["A90"], {"value": 90, "rank": "S"})
            self.assertEqual(excel_abilities["A100"], {"value": 100, "rank": "S"})

    def test_sqlite_history_reload_preserves_s_rank_and_zero_value(self):
        original_db_path = app.DB_PATH
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            app.DB_PATH = Path(tmp_dir) / "players.sqlite3"
            try:
                app.save_players([{
                    "seed": 1,
                    "role": "fielder",
                    "category": "test",
                    "name": "S-rank test",
                    "age": 20,
                    "nationality": "test",
                    "birthplace": "test",
                    "position": "test",
                    "player_type": "test",
                    "handedness": "right",
                    "batting_throwing": "right/right",
                    "height": 180,
                    "weight": 80,
                    "abilities": {"A90": app.ability(90), "A0": app.ability(0)},
                    "special_abilities": [],
                    "breaking_balls": [],
                    "sub_positions": [],
                }])
                player = app.player_from_history_row(app.load_history().iloc[0])
            finally:
                app.DB_PATH = original_db_path

        self.assertEqual(player["abilities"]["A90"], {"value": 90, "rank": "S"})
        self.assertEqual(player["abilities"]["A0"], {"value": 0, "rank": "G"})

    def test_new_classification_generation_is_deterministic_and_legacy_compatible(self):
        master = app.load_master_data()
        stable_keys = [
            "player_class", "archetype", "position_style", "development_stage", "acquisition_role",
            "weakness_profile", "name", "age", "nationality", "position", "player_type",
            "starter_aptitude", "reliever_aptitude", "closer_aptitude", "abilities",
            "breaking_balls", "special_abilities", "sub_positions",
        ]
        for seed, role, category in [
            (10101, "投手", "架空球団用"),
            (10102, "野手", "架空球団用"),
            (10103, "投手", "ドラフト候補用"),
            (10104, "野手", "ドラフト候補用"),
            (10105, "投手", "助っ人外国人用"),
            (10106, "野手", "助っ人外国人用"),
        ]:
            with self.subTest(role=role, category=category):
                first = app.generate_player(role, category, master, seed=seed)
                second = app.generate_player(role, category, master, seed=seed)
                self.assertEqual({key: first.get(key) for key in stable_keys}, {key: second.get(key) for key in stable_keys})
                self.assertTrue(first["player_class"])
                self.assertTrue(first["archetype"])
                self.assertTrue(first["position_style"])
                self.assertEqual(first["player_type"], app.legacy_player_type_from_archetype(role, first["archetype"]))
                if category == "ドラフト候補用":
                    self.assertTrue(first["development_stage"])
                else:
                    self.assertEqual(first["development_stage"], "")
                if first.get("roster_origin") == "foreign_import":
                    self.assertTrue(first["acquisition_role"])
                    self.assertTrue(first["weakness_profile"])
                else:
                    self.assertEqual(first["acquisition_role"], "")
                    self.assertEqual(first["weakness_profile"], "")

    def test_new_classification_is_saved_loaded_and_displayed(self):
        original_db_path = app.DB_PATH
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            app.DB_PATH = Path(tmp_dir) / "players.sqlite3"
            try:
                player = app.generate_player("野手", "助っ人外国人用", app.load_master_data(), seed=20240713)
                app.save_players([player])
                history = app.load_history()
                loaded = app.player_from_history_row(history.iloc[0])
            finally:
                app.DB_PATH = original_db_path

        for column in app.CLASSIFICATION_COLUMNS:
            self.assertIn(column, history.columns)
            self.assertEqual(loaded[column], player[column])
        for label in ["選手格", "アーキタイプ", "ポジションスタイル", "獲得目的", "弱点プロファイル"]:
            self.assertIn(label, history.columns)
        html = app.render_generation_info_html(loaded)
        self.assertIn("選手格", html)
        self.assertIn("アーキタイプ", html)
        self.assertIn("ポジションスタイル", html)

    def test_generation_info_omits_empty_classification_fields(self):
        html = app.render_generation_info_html({"category": "架空球団用", "player_type": "巧打型", "player_class": "一軍主力級", "archetype": "巧打", "position_style": "打撃型二塁手", "development_stage": "", "acquisition_role": "", "weakness_profile": "", "seed": 123})
        self.assertIn("選手格", html)
        self.assertNotIn("完成度", html)
        self.assertNotIn("獲得目的", html)
        self.assertNotIn("弱点プロファイル", html)

    def test_ability_body_ratios_match_game_screen(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn(".pp-body {display:grid; grid-template-columns:33% 67%;", source)
        self.assertIn(".pp-body-pitcher {grid-template-columns:35% 65%;", source)
        self.assertNotIn(".pp-body {display:grid; grid-template-columns:36% 64%;", source)
        self.assertNotIn(".pp-body-pitcher {grid-template-columns:40% 60%;", source)

    def test_ability_row_density_css_is_42px(self):
        source = Path("app.py").read_text(encoding="utf-8")
        ability_row = css_block(source, ".pp-ability-row")
        label = css_block(source, ".pp-label")
        rank = css_block(source, ".pp-rank")
        value = css_block(source, ".pp-value")
        self.assertIn("grid-template-columns:minmax(102px,38%) 50px 1fr", ability_row)
        self.assertIn("margin:3px 0", ability_row)
        self.assertIn("min-height:42px", ability_row)
        self.assertIn("height:42px", ability_row)
        self.assertIn("border-radius:7px", ability_row)
        self.assertIn("box-shadow:inset 0 1px rgba(255,255,255,.72)", ability_row)
        self.assertIn("font-size:17px", label)
        self.assertIn("padding:2px 7px", label)
        self.assertIn("font-size:26px", rank)
        self.assertIn("font-size:24px", value)

    def test_empty_special_and_usage_cells_are_pale(self):
        source = Path("app.py").read_text(encoding="utf-8")
        empty = css_block(source, ".pp-special.empty")
        blue = css_block(source, ".pp-special")
        self.assertIn("#ffffff", empty)
        self.assertIn("border-color:#dcebef", empty)
        self.assertIn("box-shadow:none", empty)
        self.assertNotEqual(empty, blue)
        usage = css_block(source, ".pp-usage-empty")
        self.assertIn("box-shadow:none", usage)

    def test_normal_blue_special_cell_keeps_42px_grid_cell_and_clear_outline(self):
        source = Path("app.py").read_text(encoding="utf-8")
        block = css_block(source, ".pp-special")
        self.assertIn("background:linear-gradient(180deg,#f0fdff 0%,#b8eef4 58%,#83dce7 100%)", block)
        self.assertIn("border:2px solid #3fb5cb", block)
        self.assertIn("height:42px", block)

    def test_navigation_disabled_buttons_remain_legible(self):
        source = Path("app.py").read_text(encoding="utf-8")
        css = app.app_chrome_css()
        self.assertNotIn('div[data-testid="stButton"] > button:disabled', source)
        for key in ["player_prev", "player_next"]:
            self.assertIn(f'div[class*="st-key-{key}"] button:disabled', css)
        self.assertIn("cursor:not-allowed", css)
        self.assertIn("border:1px dashed", css)

    def test_global_text_color_does_not_override_streamlit_controls(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertNotIn(".stApp p,", source)
        self.assertNotIn(".stApp label,", source)

    def test_control_text_colors_are_scoped_by_purpose(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn('div[class*="st-key-latest_tab_"] button *', source)
        self.assertIn('div[class*="st-key-history_tab_"] button *', source)
        self.assertIn("color:#ffffff!important", source)
        css = app.app_chrome_css()
        self.assertIn('[data-testid="stSidebar"] label', css)
        self.assertIn("--ui-sidebar-bg:#0B2A5B;", css)
        self.assertIn('[data-testid="stSidebar"] input {background:var(--ui-surface); color:var(--ui-text);', css)

    def test_page_description_uses_scoped_dark_text_and_escapes_html(self):
        source = Path("app.py").read_text(encoding="utf-8")
        block = css_block(app.app_chrome_css(), ".pp-page-description")
        self.assertIn("color:var(--ui-text)", block)
        self.assertNotIn(".stApp p,", source)
        self.assertNotIn(".stApp label,", source)
        self.assertEqual(
            app.page_description_html('<生成条件 & "説明">'),
            '<p class="pp-page-description">&lt;生成条件 &amp; &quot;説明&quot;&gt;</p>',
        )
        self.assertIn('render_page_description("投手/野手、カテゴリ、生成人数だけを選ぶと', source)
        self.assertIn('render_page_description("保存済み選手をSQLiteから読み込み', source)

    def test_generation_message_is_toast_without_sqlite_wording(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn('st.session_state["pending_toast"] = f"{len(players)}人の選手を生成しました"', source)
        self.assertIn('st.toast(st.session_state.pop("pending_toast"), icon="✅")', source)
        self.assertNotIn("SQLiteに", source)
        self.assertNotIn("pp-success-message", source)
        self.assertNotIn("同じseedを使うことで", source)
        self.assertNotIn('.stApp [data-testid="stAlert"] {color:', source)

    def test_history_display_frame_uses_japanese_values_without_changing_source(self):
        history = pd.DataFrame([
            {"id": 3, "created_at": "2026-09-30 10:52:41", "seed": 5, "name": "山田", "category": "助っ人外国人用", "position": "先発", "player_type": "本格派", "age": 28, "batting_throwing": "右投右打", "entry_route": "海外プロ経由", "roster_origin": "foreign_import", "foreign_route": "latin_development", "is_returnee": 0},
            {"id": 2, "created_at": "2026-09-29 08:01:00", "seed": 6, "name": "佐藤", "category": "架空球団用", "position": "捕手", "player_type": "巧打", "age": 22, "batting_throwing": "右投左打", "entry_route": "高卒", "roster_origin": "unknown_value", "foreign_route": "", "is_returnee": 1},
        ])
        display, columns = app.history_display_frame(history)
        self.assertEqual(columns, ["name", "category", "position", "player_type", "age", "batting_throwing", "entry_route", "created_at"])
        self.assertEqual(display.loc[0, "created_at"], "2026/09/30 10:52")
        self.assertEqual(display.loc[0, "roster_origin"], "外国人補強")
        self.assertEqual(display.loc[0, "foreign_route"], "中南米育成")
        self.assertEqual(display.loc[1, "roster_origin"], "unknown_value")
        self.assertEqual(display.loc[1, "is_returnee"], "はい")
        self.assertEqual(history.loc[0, "roster_origin"], "foreign_import")
        _display, detail_columns = app.history_display_frame(history, show_details=True)
        self.assertIn("id", detail_columns)
        self.assertIn("seed", detail_columns)
        self.assertEqual(detail_columns[:8], columns)

    def test_history_columns_have_japanese_labels(self):
        for column in app.HISTORY_DEFAULT_COLUMNS:
            self.assertTrue(any(ord(char) > 127 for char in app.HISTORY_COLUMN_LABELS[column]))

    def test_page_switch_uses_top_navigation_and_sidebar_only_has_conditions(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn('st.navigation(pages, position="top")', source)
        self.assertNotIn("表示する画面", source)
        sidebar_source = source[source.index("def render_generation_sidebar"):source.index("def render_app_title")]
        for label in ["生成条件", "投手 / 野手", "カテゴリ", "生成人数", "生成する", "Version"]:
            self.assertIn(label, sidebar_source)

    def test_app_name_is_unified(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertEqual(app.APP_NAME, "パワプロ風 架空選手生成")
        self.assertNotIn("選手能力詳細ジェネレーター", source)
        self.assertIn("page_title=APP_NAME", source)

    def test_background_has_no_diagonal_stripes(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertNotIn("repeating-linear-gradient(135deg", source)
        self.assertNotIn(".stApp:before", source)

    def test_parse_seed_text(self):
        self.assertIsNone(app.parse_seed_text(""))
        self.assertIsNone(app.parse_seed_text("   "))
        self.assertEqual(app.parse_seed_text(" 12345 "), 12345)
        for invalid in ["abc", "1.5", "-1", str(2**63)]:
            with self.assertRaises(ValueError):
                app.parse_seed_text(invalid)

    def test_seed_generation_is_single_player_and_reproducible(self):
        source = Path("app.py").read_text(encoding="utf-8")
        generation_source = source[source.index("def generate_and_save_players"):source.index("def start_generation")]
        self.assertIn("players.append(generate_player(role, category, master, seed=seed, used_names=set()))", generation_source)
        sidebar_source = source[source.index("def render_generation_sidebar"):source.index("def render_app_title")]
        self.assertIn("disabled=seed_given", sidebar_source)
        self.assertIn("seed指定時は1人だけ生成します", sidebar_source)
        self.assertIn('disabled=bool(st.session_state.get("generating"))', sidebar_source)
        self.assertIn('st.spinner("選手を生成中です...")', generation_source)

    def test_seed_copy_html_escapes_seed(self):
        html = app.seed_copy_html('1<2>"3')
        self.assertIn("seedをコピー", html)
        self.assertIn("1&lt;2&gt;&quot;3", html)
        self.assertIn('const seed = "1<2>\\"3";', html)

    def test_filter_history_table(self):
        history = pd.DataFrame([
            {"id": 3, "created_at": "2026-09-30 10:00:00", "name": "山田 太郎", "category": "架空球団用", "position": "先発"},
            {"id": 2, "created_at": "2026-09-26 10:00:00", "name": "Tom Sutton", "category": "助っ人外国人用", "position": "捕手"},
            {"id": 1, "created_at": "2026-08-01 10:00:00", "name": "佐藤 次郎", "category": "架空球団用", "position": "捕手"},
        ])
        today = "2026-09-30 18:00:00"
        ids = lambda frame: frame["id"].tolist()
        self.assertEqual(ids(app.filter_history_table(history, [], [], "すべて", "", today)), [3, 2, 1])
        self.assertEqual(ids(app.filter_history_table(history, ["架空球団用"], [], "すべて", "", today)), [3, 1])
        self.assertEqual(ids(app.filter_history_table(history, [], ["捕手"], "すべて", "", today)), [2, 1])
        self.assertEqual(ids(app.filter_history_table(history, [], [], "今日", "", today)), [3])
        self.assertEqual(ids(app.filter_history_table(history, [], [], "7日以内", "", today)), [3, 2])
        self.assertEqual(ids(app.filter_history_table(history, [], [], "すべて", "tom", today)), [2])

    def test_main_defense_position_has_distinct_emphasis(self):
        source = Path("app.py").read_text(encoding="utf-8")
        block = css_block(source, ".pp-defense-pos.main")
        self.assertIn("background:#dff3ff", block)
        self.assertIn("box-shadow:inset 4px 0 0 #0b8fe0", block)

    def test_help_band_is_removed_and_profile_css_order_is_kept(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertNotIn("pp-help", source)
        self.assertNotIn("球速、制球、スタミナ、変化球と投手特殊能力を確認します。", source)
        profile_definition = source.index(".pp-profile-table {display:grid")
        responsive_definition = source.index(".pp-profile-table {grid-template-columns:88px", profile_definition)
        self.assertGreater(responsive_definition, profile_definition)

    def test_profile_game_area_is_ordered_table_and_excludes_generation_fields(self):
        player = {"name": "山田", "age": 20, "batting_throwing": "右投右打", "nationality": "日本", "birthplace": "東京", "height": 180, "weight": 80, "back_name": "YAMADA", "category": "架空球団用", "player_type": "巧打型", "seed": 123}
        html = app.render_profile_right(player)
        for cls in ["pp-profile-table", "pp-profile-label", "pp-profile-value", "pp-profile-span-3"]:
            self.assertIn(cls, html)
        labels = re.findall(r'<div class="pp-profile-label">([^<]+)</div>', html)
        self.assertEqual(labels, ["氏名", "年齢", "投打", "国籍", "出身地", "身長", "体重", "表示名"])
        self.assertIn('class="pp-profile-value pp-profile-span-3">山田</div>', html)
        self.assertIn('class="pp-profile-value pp-profile-span-3">YAMADA</div>', html)
        for text in ["seed", "カテゴリ", "タイプ", "pp-profile-grid", "pp-mini-card"]:
            self.assertNotIn(text, html)

    def test_generation_info_contains_seed_category_and_type(self):
        html = app.render_generation_info_html({"category": "架空球団用", "player_type": "巧打型", "seed": 123})
        self.assertIn("seed", html)
        self.assertIn("カテゴリ", html)
        self.assertIn("タイプ", html)
        self.assertIn("pp-generation-grid", html)
        self.assertNotIn("pp-profile-grid", html)
        self.assertNotIn("pp-mini-card", html)

    def test_defense_table_always_renders_seven_positions_with_split_rank_and_value(self):
        player = {"role": "野手", "position": "一塁手", "seed": 1, "abilities": {"走力": app.ability(50), "肩力": app.ability(50), "守備力": app.ability(56), "捕球": app.ability(50)}, "sub_positions": []}
        html = app.render_defense_usage_left(player)
        self.assertEqual(html.count('class="pp-defense-pos'), 7)
        self.assertIn('class="pp-defense-label"', html)
        self.assertIn('<span class="pp-defense-short">投</span><span class="pp-defense-empty">－－</span>', html)
        self.assertIn('class="pp-defense-rank', html)
        self.assertIn('class="pp-defense-num"', html)

    def test_pitcher_defense_table_uses_pitcher_as_main_position(self):
        player = {"role": "投手", "position": "先発", "seed": 1, "abilities": {"弾道": 1, "ミート": app.ability(20), "パワー": app.ability(20), "走力": app.ability(50), "肩力": app.ability(50), "守備力": app.ability(52), "捕球": app.ability(50)}, "sub_positions": []}
        html = app.render_defense_usage_left(player)
        self.assertEqual(html.count('class="pp-defense-pos'), 7)
        self.assertIn('<div class="pp-defense-pos main"><span class="pp-defense-short">投</span>', html)
        self.assertIn('<span class="pp-defense-num">◎ 52</span>', html)
        self.assertIn("pp-pitcher-usage-row", html)

    def test_sub_position_fielding_display_uses_aptitude_rates_and_floor(self):
        self.assertEqual(app.calculate_sub_position_fielding(73, "◎"), 73)
        self.assertEqual(app.calculate_sub_position_fielding(73, "○"), 58)
        self.assertEqual(app.calculate_sub_position_fielding(73, "△"), 51)
        self.assertEqual(app.calculate_sub_position_fielding(65, "○"), 52)
        self.assertEqual(app.calculate_sub_position_fielding(65, "△"), 45)
        self.assertEqual(app.calculate_sub_position_fielding(66, "△"), 46)
        self.assertEqual(app.SUB_POSITION_FIELDING_RATES, {"◎": 1.00, "○": 0.80, "△": 0.70})

    def test_defense_table_shows_sub_position_marks_calculated_values_and_empty_slots(self):
        player = {
            "role": "野手",
            "position": "遊撃手",
            "seed": 1,
            "abilities": {"走力": app.ability(50), "肩力": app.ability(50), "守備力": app.ability(73), "捕球": app.ability(50)},
            "sub_positions": [{"position": "二塁手", "aptitude": "○"}, {"position": "三塁手", "aptitude": "△"}],
        }
        html = app.render_defense_usage_left(player)
        self.assertIn("遊</span><span", html)
        self.assertIn(">B</span><span class=\"pp-defense-num\">◎ 73</span>", html)
        self.assertIn("二</span><span", html)
        self.assertIn(">D</span><span class=\"pp-defense-num\">○ 58</span>", html)
        self.assertIn("三</span><span", html)
        self.assertIn(">D</span><span class=\"pp-defense-num\">△ 51</span>", html)
        self.assertIn('<span class="pp-defense-empty">－－</span>', html)

    def test_saved_numeric_sub_position_aptitudes_are_converted_before_display(self):
        self.assertEqual(app.normalize_sub_positions('[{"position":"二塁手","aptitude":2}]'), [{"position": "二塁手", "aptitude": "○"}])
        player = {
            "role": "野手",
            "position": "遊撃手",
            "seed": 1,
            "abilities": {"走力": app.ability(50), "肩力": app.ability(50), "守備力": app.ability(65), "捕球": app.ability(50)},
            "sub_positions": [{"position": "二塁手", "aptitude": 2}],
        }
        html = app.render_defense_usage_left(player)
        self.assertIn(">D</span><span class=\"pp-defense-num\">○ 52</span>", html)


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

    def test_trajectory_row_clamps_values(self):
        cases = [(None, 1), ("abc", 1), (0, 1), (1, 1), (2, 2), (3, 3), (4, 4), (5, 4)]
        for value, expected in cases:
            with self.subTest(value=value):
                html = app.render_trajectory_row_html(value)
                self.assertIn("pp-trajectory-row", html)
                self.assertIn("pp-trajectory-icon", html)
                self.assertIn("pp-trajectory-value", html)
                self.assertIn(f"trajectory-{expected}", html)
                self.assertIn(f'>{expected}</div></div>', html)

    def test_trajectory_row_uses_color_svg_for_each_value(self):
        expected_colors = {1: "#d8c900", 2: "#ef8200", 3: "#f03662", 4: "#df32d7"}
        for value, color in expected_colors.items():
            with self.subTest(value=value):
                html = app.render_trajectory_row_html(value)
                self.assertIn(f'stroke="{color}"', html)
                self.assertIn(f'fill="{color}"', html)
                self.assertIn('stroke="#ffffff"', html)
                self.assertIn('drop-shadow', html)

    def test_mixed_special_css_uses_two_color_split(self):
        source = Path("app.py").read_text(encoding="utf-8")
        mixed = css_block(source, ".pp-special.mixed")
        self.assertIn("linear-gradient(to right", mixed)
        self.assertIn("#83dce7 50%", mixed)
        self.assertIn("#ffe0e0 50%", mixed)

    def test_fielder_detail_uses_trajectory_row(self):
        player = {
            "role": "野手", "position": "三塁手", "abilities": {"弾道": 3},
            "special_abilities": [],
        }
        html = app.render_detail_body_html(player, self.master, "野手能力")
        self.assertIn("pp-trajectory-row", html)
        self.assertIn("trajectory-3", html)
        self.assertNotIn('<div class="pp-label">弾道</div><div class="pp-rank"', html)

    def test_pitch_chart_uses_fixed_svg_size(self):
        html = app.render_pitch_chart_svg([])
        for expected in ['viewBox="0 0 280 210"', 'width="270"', 'height="200"', 'rx="7"']:
            self.assertIn(expected, html)
        for old in ['viewBox="0 0 240 218"', 'width="230"', 'height="208"', 'rx="12"']:
            self.assertNotIn(old, html)

    def test_pitch_chart_wrap_is_compact_and_clipped(self):
        source = Path("app.py").read_text(encoding="utf-8")
        block = css_block(source, ".pp-chart-wrap")
        for expected in ["height:286px", "min-height:286px", "max-height:286px", "overflow:hidden"]:
            self.assertIn(expected, block)
        self.assertNotIn("height:346px", block)
        self.assertNotIn("overflow:visible", block)

    def test_pitch_display_names_use_formal_names_like_game(self):
        for formal in (
            "シンキングツーシーム", "シンキングスプリット", "サークルチェンジ", "ファストチェンジ", "ドロップカーブ",
            "ナックルカーブ", "パワーカーブ", "ツーシームファスト", "ムービングファスト", "超スローボール", "123456789",
        ):
            with self.subTest(formal=formal):
                self.assertEqual(app.pitch_display_name(formal), formal)
        svg = app.render_pitch_chart_svg([
            {"kind": "second_fastball", "name": "ツーシームファスト"},
            {"kind": "breaking", "direction_code": "4", "name": "ファストチェンジ", "movement": 1},
        ])
        self.assertIn(">ツーシームファスト<", svg)
        self.assertIn(">ファストチェンジ<", svg)

    def test_pitch_chart_handles_invalid_input(self):
        self.assertIn("ストレート", app.render_pitch_chart_svg(None))
        html = app.render_pitch_chart_svg([
            {"kind": "breaking", "direction_code": "9", "name": "無効球", "movement": 3},
            {"kind": "breaking", "direction_code": "1", "name": "第一球", "movement": "abc"},
            {"kind": "breaking", "direction_code": "1", "name": "第二球", "movement": 2, "is_second_pitch": True},
            {"kind": "breaking", "direction_code": "1", "name": "第三球", "movement": 2, "is_second_pitch": True, "slot": 2},
        ])
        self.assertNotIn("無効球", html)
        self.assertIn("第一球", html)
        self.assertIn("第二球", html)
        self.assertNotIn("第三球", html)

class PitchBlockChartTest(unittest.TestCase):
    U = app.PITCH_CHART_UNIT

    @staticmethod
    def breaking(movement, direction="1", name="球種A", **extra):
        return {"kind": "breaking", "direction_code": direction, "name": name, "movement": movement, **extra}

    @staticmethod
    def cells(svg, direction=None, lane=None):
        pattern = r'<polygon class="pitch-cell" data-direction="(\d)" data-lane="(\d)" data-index="(\d)" data-active="(true|false)" points="[^"]+" fill="(#[0-9A-F]{6})"/>'
        return [
            match for match in re.findall(pattern, svg)
            if (direction is None or match[0] == direction) and (lane is None or match[1] == str(lane))
        ]

    def test_fixed_frame_background_and_wrap(self):
        svg = app.render_pitch_chart_svg([])
        self.assertIn('viewBox="0 0 280 210"', svg)
        self.assertIn('<rect x="5" y="5" width="270" height="200" rx="7" fill="#EDF5F6" stroke="#ffffff"', svg)
        source = Path("app.py").read_text(encoding="utf-8")
        wrap = css_block(source, ".pp-chart-wrap")
        for expected in ("height:286px", "min-height:286px", "max-height:286px", "overflow:hidden"):
            self.assertIn(expected, wrap)

    def test_every_direction_is_one_continuous_frame_with_seven_cells(self):
        svg = app.render_pitch_chart_svg([])
        self.assertEqual(svg.count('class="pitch-lane-frame"'), 5)
        self.assertEqual(svg.count(f'fill="{app.PITCH_FRAME_COLOR}"'), 5 + 1)  # 5本のバー + ストレート印
        for direction in "12345":
            self.assertEqual(len(self.cells(svg, direction)), 7)
        self.assertNotIn('data-active="true"', svg)

    def test_bar_dimensions_follow_unit_ratios(self):
        u = self.U
        cx, cy = app.PITCH_CHART_CENTER
        for direction in "12345":
            with self.subTest(direction=direction):
                bar = app.pitch_bar_shape(direction)
                start = ((bar.frame[0][0] + bar.frame[4][0]) / 2, (bar.frame[0][1] + bar.frame[4][1]) / 2)
                tip = bar.frame[2]
                self.assertAlmostEqual(math.dist(start, tip), 7.5 * u, delta=0.05)
                self.assertAlmostEqual(math.dist(bar.frame[0], bar.frame[4]), 1.375 * u, delta=0.05)
                self.assertAlmostEqual(math.dist((cx, cy), start), (1.05 + 0.75) * u, delta=0.05)
                # 最外セルは矢じり形（五角形）、それ以外は四角形
                self.assertEqual([len(cell) for cell in bar.cells], [4] * 6 + [5])
                first, second = bar.cells[0], bar.cells[1]
                first_mid = (sum(x for x, _y in first) / 4, sum(y for _x, y in first) / 4)
                second_mid = (sum(x for x, _y in second) / 4, sum(y for _x, y in second) / 4)
                self.assertAlmostEqual(math.dist(first_mid, second_mid), u, delta=0.05)
                self.assertAlmostEqual(math.dist(first[0], first[1]), 0.75 * u, delta=0.05)

    def test_paired_lanes_share_one_thicker_frame(self):
        u = self.U
        for direction in "12345":
            with self.subTest(direction=direction):
                lane0 = app.pitch_bar_shape(direction, 0, True)
                lane1 = app.pitch_bar_shape(direction, 1, True)
                nx, ny = app.PITCH_GAUGE_GEOMETRY[direction]["lane_side"]
                crosses = [x * nx + y * ny for x, y in lane0.frame + lane1.frame]
                self.assertAlmostEqual(max(crosses) - min(crosses), 1.8 * u, delta=0.05)
                # 2本の列フレームは中央の仕切りで重なり、隙間がない
                lane0_cross = [x * nx + y * ny for x, y in lane0.frame]
                lane1_cross = [x * nx + y * ny for x, y in lane1.frame]
                self.assertLess(min(lane0_cross), max(lane1_cross))
                self.assertEqual(len(lane0.cells), 7)
                self.assertEqual(len(lane1.cells), 7)

    def test_paired_lanes_are_not_staggered_in_any_direction(self):
        # 2列は根元・先端・セル境界がそろう（斜めも段違いにしない）
        for direction in "12345":
            lane0 = app.pitch_bar_shape(direction, 0, True)
            lane1 = app.pitch_bar_shape(direction, 1, True)
            ax, ay = app.PITCH_GAUGE_GEOMETRY[direction]["axis"]
            along = lambda point: point[0] * ax + point[1] * ay
            self.assertAlmostEqual(along(lane1.frame[2]), along(lane0.frame[2]), delta=0.05, msg=direction)
            self.assertAlmostEqual(along(lane1.frame[0]), along(lane0.frame[0]), delta=0.05, msg=direction)
            for index in range(7):
                self.assertAlmostEqual(along(lane1.cells[index][0]), along(lane0.cells[index][0]), delta=0.05, msg=direction)

    def test_empty_cells_brighten_toward_tip(self):
        svg = app.render_pitch_chart_svg([])
        colors = [match[4] for match in self.cells(svg, "1")]
        self.assertEqual(colors[0], "#0A96FF")
        self.assertEqual(colors[-1], "#42B5FF")
        self.assertEqual(len(set(colors)), 7)

    def test_active_cells_use_fixed_color_per_position(self):
        svg = app.render_pitch_chart_svg([self.breaking(7, "2", "カーブ")])
        colors = [match[4] for match in self.cells(svg, "2")]
        self.assertEqual(tuple(colors), app.PITCH_CELL_ACTIVE_COLORS)
        self.assertEqual(app.PITCH_CELL_ACTIVE_COLORS, ("#FF7E00", "#FFC800", "#FFDA00", "#FFA700", "#FF5C00", "#FF1D00", "#FF3100"))
        three = app.render_pitch_chart_svg([self.breaking(3, "2", "カーブ")])
        self.assertEqual([match[4] for match in self.cells(three, "2")][:3], ["#FF7E00", "#FFC800", "#FFDA00"])

    def test_movement_normalization_and_active_cell_count(self):
        cases = [(1, 1), (3, 3), (7, 7), (8, 7), (0, 0), (-2, 0), ("bad", 0)]
        for movement, expected in cases:
            with self.subTest(movement=movement):
                svg = app.render_pitch_chart_svg([self.breaking(movement)])
                self.assertEqual(svg.count('class="pitch-cell"'), 35)
                self.assertEqual(svg.count('data-active="true"'), expected)

    def test_paired_lanes_have_independent_active_counts(self):
        for first_movement, second_movement in ((7, 1), (1, 7), (3, 5)):
            with self.subTest(first=first_movement, second=second_movement):
                svg = app.render_pitch_chart_svg([
                    self.breaking(first_movement, "2", "カーブ"),
                    self.breaking(second_movement, "2", "Dカーブ", is_second_pitch=True, slot=2),
                ])
                for lane, expected in ((0, first_movement), (1, second_movement)):
                    cells = self.cells(svg, "2", lane)
                    self.assertEqual(len(cells), 7)
                    self.assertEqual(sum(cell[3] == "true" for cell in cells), expected)
                    self.assertEqual([cell[4] for cell in cells[:expected]], list(app.PITCH_CELL_ACTIVE_COLORS[:expected]))

    def test_same_direction_uses_two_lanes_and_ignores_third(self):
        balls = [
            self.breaking(2, "3", "球種A", slot=1),
            self.breaking(4, "3", "球種B", slot=2, is_second_pitch=True),
            self.breaking(7, "3", "球種C", slot=3, is_second_pitch=True),
        ]
        self.assertEqual(len(app.build_pitch_chart_lanes(balls, False)), 2)
        svg = app.render_pitch_chart_svg(balls)
        self.assertEqual(svg.count('class="pitch-lane-frame" data-direction="3"'), 2)
        self.assertNotIn("球種C", svg)

    def test_center_ball_is_round_with_thin_ring(self):
        svg = app.render_pitch_chart_svg([])
        self.assertIn('class="pitch-center-ball"', svg)
        ring = re.search(r'<circle cx="140" cy="72" r="([0-9.]+)" fill="#ffffff" stroke="#008FF5" stroke-width="([0-9.]+)"', svg)
        self.assertIsNotNone(ring)
        radius, width = float(ring.group(1)), float(ring.group(2))
        self.assertAlmostEqual(2 * radius + width, 2.1 * self.U, delta=0.05)
        self.assertAlmostEqual(width, 0.25 * self.U, delta=0.05)
        self.assertNotIn("<ellipse", svg)
        self.assertNotIn("★", svg)

    def test_straight_marker_is_home_plate_and_doubles_as_joined_shape(self):
        u = self.U
        single = app.layout_pitch_chart([])
        xs = [x for x, _y in single.straight_frame]
        ys = [y for _x, y in single.straight_frame]
        self.assertEqual(len(single.straight_frame), 5)
        self.assertAlmostEqual(max(xs) - min(xs), 1.25 * u, delta=0.05)
        self.assertAlmostEqual(max(ys) - min(ys), 1.55 * u, delta=0.05)
        self.assertEqual(len(single.straight_fills), 1)
        double = app.layout_pitch_chart([{"kind": "second_fastball", "name": "ムービングファスト"}])
        xs = [x for x, _y in double.straight_frame]
        self.assertAlmostEqual(max(xs) - min(xs), 1.8 * u, delta=0.05)
        self.assertEqual(len(double.straight_fills), 2)
        svg = app.render_pitch_chart_svg([{"kind": "second_fastball", "name": "ムービングファスト"}])
        self.assertEqual(svg.count('class="straight-marker-frame"'), 1)
        self.assertEqual(svg.count('class="straight-marker"'), 2)
        self.assertIn('fill="#FF7E00"', svg)

    def test_straight_labels_split_left_and_right_when_two_fastballs(self):
        single = [label for label in app.layout_pitch_chart([]).labels if label.kind != "pitch"]
        self.assertEqual([(label.text, label.anchor) for label in single], [("ストレート", "middle")])
        double = [label for label in app.layout_pitch_chart([
            {"kind": "second_fastball", "name": "ツーシームファスト"},
            {"kind": "second_fastball", "name": "ムービングファスト"},
        ]).labels if label.kind != "pitch"]
        self.assertEqual([(label.text, label.anchor) for label in double], [("ストレート", "end"), ("ツーシームファスト", "start")])
        self.assertLess(double[0].x, app.PITCH_CHART_CENTER[0])
        self.assertGreater(double[1].x, app.PITCH_CHART_CENTER[0])

    def test_draw_order_is_straight_bars_ball_labels(self):
        svg = app.render_pitch_chart_svg([self.breaking(2)])
        self.assertLess(svg.index('class="pitch-straight-area"'), svg.index('class="pitch-lane-frame"'))
        self.assertLess(svg.rindex('class="pitch-lane-frame"'), svg.index('class="pitch-cell"'))
        self.assertLess(svg.rindex('class="pitch-cell"'), svg.index('class="pitch-center-ball"'))
        self.assertLess(svg.index('class="pitch-center-ball"'), svg.index('class="pitch-label"'))

    def test_label_text_style(self):
        svg = app.render_pitch_chart_svg([self.breaking(3, "3", "SFF")])
        label = re.search(r'<text class="pitch-label"[^>]*>([^<]+)</text>', svg)
        self.assertEqual(label.group(1), "ＳＦＦ")
        self.assertIn('fill="#2177C0"', label.group(0))
        self.assertIn('font-weight="400"', label.group(0))
        self.assertIn(f'font-size="{1.2 * self.U:.1f}"', label.group(0))
        self.assertNotIn('font-weight="900"', svg)
        self.assertEqual(app.pitch_label_text("Hスライダー"), "Ｈスライダー")

    def test_long_pitch_names_are_compressed_not_truncated(self):
        svg = app.render_pitch_chart_svg([self.breaking(3, "5", "シンキングツーシーム", is_second_pitch=True), self.breaking(2, "5", "シュート")])
        self.assertIn("シンキングツーシーム", svg)
        self.assertNotIn("…", svg)
        long_name = "長い長い長い長い長い長い球種名"
        layout = app.layout_pitch_chart([self.breaking(3, "3", long_name)])
        label = next(label for label in layout.labels if label.kind == "pitch")
        self.assertTrue(label.compressed)
        self.assertLessEqual(label.width, app.PITCH_LABEL_MAX_WIDTH * self.U + 0.01)
        rendered = app.render_pitch_chart_svg([self.breaking(3, "3", long_name)])
        self.assertIn('lengthAdjust="spacingAndGlyphs"', rendered)
        self.assertIn(long_name, rendered)

    def test_labels_stay_inside_chart_like_game_samples(self):
        samples = [
            [{"kind": "second_fastball", "name": "ツーシームファスト"}, self.breaking(0, "5", "シンキングツーシーム"), self.breaking(1, "2", "パワーカーブ"), self.breaking(1, "4", "ファストチェンジ")],
            [{"kind": "second_fastball", "name": "超スローボール"}, self.breaking(1, "2", "ドロップカーブ"), self.breaking(1, "4", "シンキングスプリット")],
            [{"kind": "second_fastball", "name": "ムービングファスト"}, self.breaking(1, "5", "Hシュート"), self.breaking(1, "2", "Dスライダー"), self.breaking(1, "2", "ナックルカーブ", is_second_pitch=True), self.breaking(1, "4", "スクリュー")],
        ]
        for balls in samples:
            layout = app.layout_pitch_chart(balls, "左投左打")
            for label in layout.labels:
                x0, y0, x1, y1 = label.rect()
                self.assertGreaterEqual(x0, 5, label.text)
                self.assertLessEqual(x1, 275, label.text)
                # 10文字の球種名だけ最大幅に合わせて1割弱詰める（実機も同程度に詰まっている）
                self.assertGreaterEqual(label.width / label.natural_width, 0.9, label.text)

    def pitch_label(self, layout, direction, lane=0):
        return next(label for label in layout.labels if label.kind == "pitch" and label.direction_code == direction and label.lane_index == lane)

    def bar(self, layout, direction, lane=0):
        return next(bar for bar in layout.bars if bar.direction_code == direction and bar.lane_index == lane)

    def test_side_labels_sit_above_bar_and_second_pitch_below(self):
        for direction in ("1", "5"):
            with self.subTest(direction=direction):
                single = app.layout_pitch_chart([self.breaking(3, direction, "スライダー")])
                label = self.pitch_label(single, direction)
                self.assertLessEqual(label.rect()[3], min(y for _x, y in self.bar(single, direction).frame))
                paired = app.layout_pitch_chart([
                    self.breaking(3, direction, "シュート"),
                    self.breaking(1, direction, "Hシュート", is_second_pitch=True),
                ])
                top = self.pitch_label(paired, direction, 0)
                bottom = self.pitch_label(paired, direction, 1)
                frame_ys = [y for bar in paired.bars if bar.direction_code == direction for _x, y in bar.frame]
                self.assertLessEqual(top.rect()[3], min(frame_ys))
                self.assertGreaterEqual(bottom.rect()[1], max(frame_ys))
                # 実機準拠：バーの外寄り（中心から 7.2u）に中央揃え
                expected_x = app.PITCH_CHART_CENTER[0] + (1 if direction == "1" else -1) * app.PITCH_SIDE_LABEL_CENTER * self.U
                self.assertEqual((label.anchor, label.x), ("middle", round(expected_x, 2)))

    def test_fork_labels_center_or_split_left_and_right(self):
        single = self.pitch_label(app.layout_pitch_chart([self.breaking(3, "3", "フォーク")]), "3")
        self.assertEqual((single.x, single.anchor), (app.PITCH_CHART_CENTER[0], "middle"))
        paired = app.layout_pitch_chart([self.breaking(5, "3", "フォーク"), self.breaking(3, "3", "SFF", is_second_pitch=True)])
        left, right = self.pitch_label(paired, "3", 0), self.pitch_label(paired, "3", 1)
        self.assertEqual((left.anchor, right.anchor), ("end", "start"))
        self.assertEqual(left.y, right.y)
        tip_y = max(y for bar in paired.bars if bar.direction_code == "3" for _x, y in bar.frame)
        self.assertGreater(left.rect()[1], tip_y)

    def test_diagonal_labels_go_below_tip_or_outer_middle_for_two_pitches(self):
        single = app.layout_pitch_chart([self.breaking(3, "2", "カーブ")])
        label = self.pitch_label(single, "2")
        self.assertGreater(label.rect()[1], max(y for _x, y in self.bar(single, "2").frame))
        paired = app.layout_pitch_chart([self.breaking(3, "2", "カーブ"), self.breaking(2, "2", "スローカーブ", is_second_pitch=True)])
        first, second = self.pitch_label(paired, "2", 0), self.pitch_label(paired, "2", 1)
        # 1球種目はバーの外側（右上側）、2球種目は先端の下
        self.assertEqual(first.anchor, "start")
        self.assertLess(first.rect()[3], second.rect()[1])
        self.assertGreater(second.rect()[1], max(y for _x, y in self.bar(paired, "2", 1).frame))

    def test_left_pitcher_mirrors_bars_and_labels(self):
        balls = [
            {"kind": "second_fastball", "name": "ツーシームファスト"},
            self.breaking(3, "1", "スライダー"), self.breaking(2, "1", "カットボール", is_second_pitch=True),
            self.breaking(3, "2", "カーブ"), self.breaking(5, "3", "フォーク"), self.breaking(3, "3", "SFF", is_second_pitch=True),
            self.breaking(2, "4", "シンカー"), self.breaking(3, "5", "シュート"), self.breaking(1, "5", "Hシュート", is_second_pitch=True),
        ]
        right = app.layout_pitch_chart(balls, "右投右打")
        left = app.layout_pitch_chart([dict(ball, name="スクリュー") if ball.get("direction_code") == "4" else ball for ball in balls], "左投左打")
        self.assertTrue(left.is_left)
        for r_bar, l_bar in zip(right.bars, left.bars):
            self.assertEqual((r_bar.direction_code, r_bar.lane_index), (l_bar.direction_code, l_bar.lane_index))
            if r_bar.direction_code == "3":
                continue
            self.assertEqual([(round(280 - x, 2), y) for x, y in r_bar.frame], [(round(x, 2), y) for x, y in l_bar.frame])
        swap = {"start": "end", "end": "start", "middle": "middle"}
        right_labels = {(label.direction_code, label.lane_index): label for label in right.labels if label.kind == "pitch" and label.direction_code not in "34"}
        left_labels = {(label.direction_code, label.lane_index): label for label in left.labels if label.kind == "pitch" and label.direction_code not in "34"}
        for key, r_label in right_labels.items():
            l_label = left_labels[key]
            self.assertAlmostEqual(l_label.x, 280 - r_label.x, delta=0.02)
            self.assertEqual(l_label.y, r_label.y)
            self.assertEqual(l_label.anchor, swap[r_label.anchor])
        # フォーク方向の2列は反転しない（実機：左投げでも1球種目が左下、2球種目が右下）
        for layout in (right, left):
            first, second = self.pitch_label(layout, "3", 0), self.pitch_label(layout, "3", 1)
            self.assertEqual((first.text, first.anchor), ("フォーク", "end"))
            self.assertEqual((second.text, second.anchor), ("ＳＦＦ", "start"))
            lane0_x = sum(x for x, _y in self.bar(layout, "3", 0).frame) / 5
            lane1_x = sum(x for x, _y in self.bar(layout, "3", 1).frame) / 5
            self.assertLess(lane0_x, lane1_x)
        # ストレート表示は反転しない
        self.assertEqual(right.straight_frame, left.straight_frame)
        self.assertEqual([label for label in right.labels if label.kind != "pitch"], [label for label in left.labels if label.kind != "pitch"])

    def test_labels_never_overlap_bars_or_each_other_in_any_combination(self):
        long_names = {
            "1": ("Hスライダー", "カットボール"), "2": ("スローカーブ", "ナックルカーブ"), "3": ("チェンジアップ", "Vスライダー"),
            "4": ("シンキングスプリット", "サークルチェンジ"), "5": ("シンキングツーシーム", "Hシュート"),
        }
        cx, cy = app.PITCH_CHART_CENTER
        radius = 1.05 * self.U
        ball_box = ((cx - radius, cy - radius), (cx + radius, cy - radius), (cx + radius, cy + radius), (cx - radius, cy + radius))
        for counts in itertools.product((0, 1, 2), repeat=5):
            for fastballs in (0, 1):
                balls = [{"kind": "second_fastball", "name": "ムービングファスト"}] if fastballs else []
                for code, count in zip("12345", counts):
                    for lane in range(count):
                        balls.append(self.breaking(4, code, long_names[code][lane], is_second_pitch=lane == 1, slot=lane + 1))
                for hand in ("右投右打", "左投左打"):
                    layout = app.layout_pitch_chart(balls, hand)
                    rects = [label.rect() for label in layout.labels]
                    obstacles = [bar.frame for bar in layout.bars] + [layout.straight_frame, ball_box]
                    for index, rect in enumerate(rects):
                        polygon = app._rect_polygon(rect)
                        context = f"{counts} fastballs={fastballs} {hand} {layout.labels[index].text}"
                        self.assertGreaterEqual(rect[0], 5, context)
                        self.assertLessEqual(rect[2], 275, context)
                        self.assertGreaterEqual(rect[1], 5, context)
                        self.assertLessEqual(rect[3], 205, context)
                        for obstacle in obstacles:
                            self.assertFalse(app._convex_polygons_overlap(polygon, obstacle), context)
                        for other in rects[index + 1:]:
                            self.assertFalse(app._convex_polygons_overlap(polygon, app._rect_polygon(other)), context)
                        # 横圧縮しすぎて読めない幅にはしない
                        self.assertGreaterEqual(layout.labels[index].width / layout.labels[index].natural_width, 0.5, context)

    def test_bars_never_overlap_other_directions(self):
        # 斜めバーの根元が隣の横バー・フォークバーに食い込まない（全組み合わせ・左右両投げ）
        for counts in itertools.product((0, 1, 2), repeat=5):
            balls = [
                self.breaking(1, code, "球種", is_second_pitch=lane == 1, slot=lane + 1)
                for code, count in zip("12345", counts) for lane in range(count)
            ]
            for hand in ("右投右打", "左投左打"):
                bars = app.layout_pitch_chart(balls, hand).bars
                for first, second in itertools.combinations(bars, 2):
                    if first.direction_code == second.direction_code:
                        continue
                    self.assertFalse(
                        app._convex_polygons_overlap(first.frame, second.frame),
                        f"{counts} {hand} {first.direction_code}-{first.lane_index} / {second.direction_code}-{second.lane_index}",
                    )

    def test_diagonal_root_moves_out_only_when_crowded(self):
        u = self.U
        cx, cy = app.PITCH_CHART_CENTER
        self.assertEqual(app.diagonal_bar_start("2", set()), app.PITCH_BAR_START)
        for direction in ("2", "4"):
            self.assertGreater(app.diagonal_bar_start(direction, {direction}), app.PITCH_BAR_START)
            layout = app.layout_pitch_chart([
                self.breaking(3, direction, "球種A"), self.breaking(2, direction, "球種B", is_second_pitch=True),
            ])
            lanes = [bar for bar in layout.bars if bar.direction_code == direction]
            roots = [math.dist((cx, cy), ((bar.frame[0][0] + bar.frame[4][0]) / 2, (bar.frame[0][1] + bar.frame[4][1]) / 2)) for bar in lanes]
            # 2列の根元は、2列の中心線上でボールから同じ距離にある
            ax, ay = app.PITCH_GAUGE_GEOMETRY[direction]["axis"]
            alongs = [(bar.frame[0][0] - cx) * ax + (bar.frame[0][1] - cy) * ay for bar in lanes]
            self.assertAlmostEqual(alongs[0], alongs[1], delta=0.05)
            self.assertAlmostEqual(alongs[0], app.diagonal_bar_start(direction, {direction}) * u, delta=0.05)


if __name__ == "__main__":
    unittest.main()
