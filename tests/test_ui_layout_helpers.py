import json
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
        self.assertIn("守備位置　三", html)


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
        self.assertIn("守備位置　三", app.render_header_html(fielder))

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

    def test_player_browser_uses_single_row_columns_without_state_changes(self):
        source = Path("app.py").read_text(encoding="utf-8")
        browser_source = source[source.index("def render_player_browser"):source.index("def main")]
        self.assertIn("""previous_col, select_col, next_col = st.columns(
        [0.16, 0.68, 0.16],
        gap="small",
    )""", browser_source)
        self.assertIn('st.selectbox("選手一覧", player_ids, format_func=lambda player_id: label_by_id[player_id], key=selected_player_id_key, label_visibility="collapsed")', browser_source)
        self.assertIn('selected_player_id_key = f"{key_prefix}_selected_player_id"', browser_source)
        self.assertEqual(browser_source.count("on_click=select_relative_player"), 2)
        self.assertIn("with previous_col:", browser_source)
        self.assertIn("with select_col:", browser_source)
        self.assertIn("with next_col:", browser_source)
        self.assertIn("def relative_player_id", source)
        self.assertNotIn("selected_index", source)


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
                if category == "助っ人外国人用":
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
        self.assertNotIn('div[data-testid="stButton"] > button:disabled', source)
        for key in ["latest_prev", "latest_next", "history_prev", "history_next"]:
            self.assertIn(f'div[class*="st-key-{key}"] button:disabled', source)
        self.assertIn("opacity:1!important", source)
        self.assertIn("cursor:not-allowed", source)
        self.assertIn('button:disabled * {color:#5f7484!important', source)

    def test_global_text_color_does_not_override_streamlit_controls(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertNotIn(".stApp p,", source)
        self.assertNotIn(".stApp label,", source)

    def test_control_text_colors_are_scoped_by_purpose(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn('div[class*="st-key-latest_tab_"] button *', source)
        self.assertIn('div[class*="st-key-history_tab_"] button *', source)
        self.assertIn("color:#ffffff!important", source)
        self.assertIn('[data-testid="stSidebar"] p', source)
        self.assertIn("color:#d8ecf7", source)
        self.assertIn('[data-testid="stExpander"] summary *', source)
        self.assertIn('[data-testid="stHeadingWithActionElements"] h1', source)
        self.assertIn("color:#073f68; text-shadow:none", source)

    def test_page_description_uses_scoped_dark_text_and_escapes_html(self):
        source = Path("app.py").read_text(encoding="utf-8")
        block = css_block(source, ".pp-page-description")
        self.assertIn("color:#073f68", block)
        self.assertNotIn(".stApp p,", source)
        self.assertNotIn(".stApp label,", source)
        self.assertEqual(
            app.page_description_html('<生成条件 & "説明">'),
            '<p class="pp-page-description">&lt;生成条件 &amp; &quot;説明&quot;&gt;</p>',
        )
        self.assertIn('render_page_description("投手/野手、カテゴリ、生成人数だけを選ぶと', source)
        self.assertIn('render_page_description("保存済み選手をSQLiteから読み込み', source)

    def test_success_message_has_scoped_high_contrast_style_and_escapes_html(self):
        source = Path("app.py").read_text(encoding="utf-8")
        block = css_block(source, ".pp-success-message")
        self.assertIn("color:#075f3b", block)
        self.assertIn("background:rgba(133,225,177,.38)", block)
        self.assertIn("border-left:5px solid #168a54", block)
        self.assertEqual(
            app.success_message_html("3件 <保存> & 完了"),
            '<div class="pp-success-message">3件 &lt;保存&gt; &amp; 完了</div>',
        )
        self.assertIn('render_success_message(f"{len(players)}人の選手を生成し', source)
        self.assertNotIn('.stApp [data-testid="stAlert"] {color:', source)

    def test_main_defense_position_has_distinct_emphasis(self):
        source = Path("app.py").read_text(encoding="utf-8")
        block = css_block(source, ".pp-defense-pos.main")
        self.assertIn("background:#dff3ff", block)
        self.assertIn("box-shadow:inset 4px 0 0 #0b8fe0", block)

    def test_profile_help_matches_visible_profile_and_generation_info(self):
        source = Path("app.py").read_text(encoding="utf-8")
        expected = "氏名、年齢、投打、国籍、出身地、体格を確認します。生成条件は「生成情報」から確認できます。"
        self.assertIn(f'"プロフィール": "{expected}"', source)
        self.assertNotIn("年齢、国籍、出身地、体格、生成カテゴリを確認します。", source)
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

    def test_defense_table_always_renders_six_positions_with_split_rank_and_value(self):
        player = {"role": "野手", "position": "一塁手", "seed": 1, "abilities": {"走力": app.ability(50), "肩力": app.ability(50), "守備力": app.ability(56), "捕球": app.ability(50)}, "sub_positions": []}
        html = app.render_defense_usage_left(player)
        self.assertEqual(html.count('class="pp-defense-pos'), 6)
        self.assertIn('class="pp-defense-rank"', html)
        self.assertIn('class="pp-defense-num"', html)

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
        self.assertIn(">◎</span><span class=\"pp-defense-num\">73</span>", html)
        self.assertIn("二</span><span", html)
        self.assertIn(">○</span><span class=\"pp-defense-num\">58</span>", html)
        self.assertIn("三</span><span", html)
        self.assertIn(">△</span><span class=\"pp-defense-num\">51</span>", html)
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
        self.assertIn(">○</span><span class=\"pp-defense-num\">52</span>", html)


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

    def test_pitch_display_names_are_shortened(self):
        expected = {
            "シンキングツーシーム": "Sツーシーム",
            "シンキングスプリット": "Sスプリット",
            "サークルチェンジ": "Cチェンジ",
            "シンキングファスト": "Sファスト",
            "ドロップカーブ": "Dカーブ",
            "ナックルカーブ": "Nカーブ",
            "パワーカーブ": "Pカーブ",
            "ツーシームファスト": "ツーシーム",
            "シンキングスプリット": "Sスプリット",
            "超スローボール": "超スロー",
            "123456789": "1234567…",
        }
        for formal, display in expected.items():
            with self.subTest(formal=formal):
                self.assertEqual(app.pitch_display_name(formal), display)

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
    @staticmethod
    def breaking(movement, direction="1", name="球種A", **extra):
        return {"kind": "breaking", "direction_code": direction, "name": name, "movement": movement, **extra}

    def test_fixed_frame_ball_straight_marker_and_wrap(self):
        svg = app.render_pitch_chart_svg([])
        self.assertIn('viewBox="0 0 280 210"', svg)
        self.assertIn('<rect x="5" y="5" width="270" height="200"', svg)
        self.assertIn('<circle cx="140" cy="66"', svg)
        self.assertEqual(svg.count('class="straight-marker"'), 1)
        source = Path("app.py").read_text(encoding="utf-8")
        wrap = css_block(source, ".pp-chart-wrap")
        for expected in ("height:286px", "min-height:286px", "max-height:286px", "overflow:hidden"):
            self.assertIn(expected, wrap)

    def test_first_and_second_pitch_share_the_same_block_color(self):
        svg = app.render_pitch_chart_svg([
            self.breaking(1, "2", "球種A"),
            self.breaking(1, "2", "球種B", is_second_pitch=True, slot=2),
        ])
        self.assertEqual(svg.count('fill="#ff8b25" stroke="#dd5f12"'), 3)  # straight + two breaking balls
        self.assertNotIn('fill="#19a9ef"', svg)

    def lane(self, direction, movement=3, lane_index=0, is_left=False, name="球種"):
        return app.PitchChartLane(direction, lane_index, name, name, movement, is_left)

    def test_straight_area_uses_at_most_two_horizontal_markers(self):
        with_second = app.render_pitch_chart_svg([
            {"kind": "second_fastball", "name": "ツーシームファスト"},
            {"kind": "second_fastball", "name": "ムービングファスト"},
        ])
        self.assertEqual(app.render_pitch_chart_svg([]).count('class="straight-marker"'), 1)
        self.assertEqual(with_second.count('class="straight-marker"'), 2)
        self.assertIn('data-center-x="133"', with_second)
        self.assertIn('data-center-x="147"', with_second)
        self.assertIn('x="132" y="40" text-anchor="end"', with_second)
        self.assertIn('x="148" y="40" text-anchor="start"', with_second)
        self.assertEqual(with_second.count('class="straight-label"'), 2)
        self.assertIn("ツーシーム", with_second)
        self.assertNotIn("ムービング", with_second)
        self.assertNotIn('class="pitch-block"', with_second)

    def test_center_marker_is_baseball_not_star(self):
        svg = app.render_pitch_chart_svg([])
        self.assertIn('class="pitch-center-ball"', svg)
        self.assertIn('<circle cx="140" cy="66" r="12"', svg)
        self.assertEqual(svg.count('stroke="#e64d4d"'), 2)
        self.assertNotIn("★", svg)

    def test_draw_order_is_straight_ball_blocks_labels(self):
        svg = app.render_pitch_chart_svg([self.breaking(2)])
        self.assertLess(svg.index('class="pitch-straight-area"'), svg.index('class="pitch-gauge-segment"'))
        self.assertLess(svg.index('class="pitch-gauge-segment"'), svg.index('class="pitch-center-ball"'))
        self.assertLess(svg.index('class="pitch-center-ball"'), svg.index('class="pitch-label"'))

    def test_movement_normalization_and_orange_block_count(self):
        cases = [(1, 1), (3, 3), (7, 7), (8, 7), (0, 0), (-2, 0), ("bad", 0)]
        for movement, expected in cases:
            with self.subTest(movement=movement):
                svg = app.render_pitch_chart_svg([self.breaking(movement)])
                self.assertEqual(svg.count('class="pitch-gauge-segment"'), 30)
                self.assertEqual(svg.count('class="pitch-gauge-tip"'), 5)
                self.assertEqual(svg.count('data-active="true"'), expected)
                self.assertEqual(svg.count('data-active="false"'), 35 - expected)

    def test_independent_lane_geometry_has_clear_origins_and_no_guides(self):
        svg = app.render_pitch_chart_svg([])
        self.assertNotIn('class="pitch-guide"', svg)
        self.assertEqual(set(app.PITCH_GAUGE_GEOMETRY), set("12345"))
        self.assertEqual(svg.count('class="pitch-gauge-segment"'), 30)
        self.assertEqual(svg.count('class="pitch-gauge-tip"'), 5)
        self.assertEqual(svg.count('fill="#35b5ef"'), 35)
        self.assertNotIn('class="pitch-label"', svg)

    def test_same_direction_uses_two_independent_lanes_and_ignores_third(self):
        balls = [
            self.breaking(2, "3", "球種A", slot=1),
            self.breaking(4, "3", "球種B", slot=2, is_second_pitch=True),
            self.breaking(7, "3", "球種C", slot=3, is_second_pitch=True),
        ]
        lanes = app.build_pitch_chart_lanes(balls, False)
        self.assertEqual(len(lanes), 2)
        first = app.pitch_gauge_segment_positions("3", 0, False, True)
        second = app.pitch_gauge_segment_positions("3", 1, False, True)
        self.assertEqual((first[0][0], second[0][0]), (135.5, 144.5))
        svg = app.render_pitch_chart_svg(balls)
        self.assertEqual(svg.count('class="paired-pitch-segment"'), 12)
        self.assertEqual(svg.count('class="paired-pitch-tip"'), 2)
        self.assertNotIn('class="pitch-gauge-segment" data-direction="3"', svg)
        self.assertNotIn("球種C", svg)

    def test_all_second_lanes_have_non_touching_block_centers(self):
        for direction in "12345":
            first = app.pitch_gauge_segment_positions(direction, 0, False, True)[0]
            second = app.pitch_gauge_segment_positions(direction, 1, False, True)[0]
            distance = ((first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2) ** 0.5
            edge_gap = distance - app.PAIRED_SEGMENT_HEIGHT
            self.assertAlmostEqual(edge_gap, app.PAIRED_LANE_GAP, places=3)

    def test_diagonal_second_lane_has_at_least_one_block_width_of_separation(self):
        for direction in ("2", "4"):
            first = app.pitch_gauge_segment_positions(direction, 0, False, True)[0]
            second = app.pitch_gauge_segment_positions(direction, 1, False, True)[0]
            distance = ((first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2) ** 0.5
            edge_gap = distance - app.PAIRED_SEGMENT_HEIGHT
            self.assertAlmostEqual(edge_gap, app.PAIRED_LANE_GAP, places=3)

    def test_labels_are_fixed_and_all_segments_stay_in_svg(self):
        expected_labels = {
            "1": (255, 96, "end"), "2": (242, 160, "end"), "3": (140, 200, "middle"),
            "4": (38, 160, "start"), "5": (25, 96, "start"),
        }
        for direction in "12345":
            self.assertEqual(app.pitch_gauge_label_geometry(direction, 0, False), expected_labels[direction])
            label_x, label_y, anchor = expected_labels[direction]
            self.assertGreaterEqual(label_x, 25 if anchor == "start" else 5)
            self.assertLessEqual(label_x, 255 if anchor == "end" else 275)
            self.assertGreaterEqual(label_y, 5)
            self.assertLessEqual(label_y, 200)
            for lane_index in (0, 1):
                for x, y, _angle in app.pitch_gauge_segment_positions(direction, lane_index, False):
                    self.assertGreaterEqual(x - 9, 5)
                    self.assertLessEqual(x + 9, 275)
                    self.assertGreaterEqual(y - 9, 5)
                    self.assertLessEqual(y + 9, 205)

    def test_labels_follow_lane_end_and_stay_in_svg(self):
        one = app.render_pitch_chart_svg([self.breaking(1, "1", "スライダー")])
        seven = app.render_pitch_chart_svg([self.breaking(7, "1", "スライダー")])
        label_pattern = r'<text class="pitch-label"[^>]+x="([0-9.]+)" y="([0-9.]+)" text-anchor="([^"]+)"'
        self.assertEqual(re.findall(label_pattern, one), re.findall(label_pattern, seven))

    def test_left_pitcher_mirrors_side_and_diagonal_but_not_center(self):
        for direction in ("1", "2", "4", "5"):
            right = app.pitch_gauge_segment_positions(direction, 0, False)
            left = app.pitch_gauge_segment_positions(direction, 0, True)
            self.assertEqual([round(280 - x, 5) for x, _y, _a in right], [round(x, 5) for x, _y, _a in left])
            self.assertEqual([(180 - a) % 360 for _x, _y, a in right], [a for _x, _y, a in left])
            rx, ry, ra = app.pitch_gauge_label_geometry(direction, 0, False)
            lx, ly, la = app.pitch_gauge_label_geometry(direction, 0, True)
            self.assertEqual((lx, ly), (280 - rx, ry))
            self.assertNotEqual(la, ra)
        self.assertEqual(app.pitch_gauge_segment_positions("3", 0, False), app.pitch_gauge_segment_positions("3", 0, True))

    def test_fixed_segment_geometry_and_tip_shape(self):
        svg = app.render_pitch_chart_svg([])
        self.assertEqual(app.PITCH_GAUGE_SEGMENT_LENGTH, 12)
        self.assertEqual(app.PITCH_GAUGE_SEGMENT_THICKNESS, 9)
        self.assertEqual(app.PITCH_GAUGE_SEGMENT_GAP, 1)
        self.assertGreater(app.PITCH_GAUGE_SEGMENT_LENGTH, app.PITCH_GAUGE_SEGMENT_THICKNESS)
        self.assertIn('<polygon points="-6,-4.5 2,-4.5 7,0 2,4.5 -6,4.5"', svg)
        angles = {app.PITCH_GAUGE_GEOMETRY[code]["angle"] for code in "12345"}
        self.assertEqual(angles, {0, 45, 90, 135, 180})

    def test_segment_coordinates_and_label_do_not_depend_on_movement(self):
        positions = app.pitch_gauge_segment_positions("2", 0, False)
        self.assertEqual(len(positions), 7)
        one = app.render_pitch_chart_svg([self.breaking(1, "2", "カーブ")])
        seven = app.render_pitch_chart_svg([self.breaking(7, "2", "カーブ")])
        transforms = r'transform="(translate\([^"]+\) rotate\([^"]+\))"'
        self.assertEqual(re.findall(transforms, one)[:35], re.findall(transforms, seven)[:35])

    def test_direction_three_centers_and_splits_only_when_second_pitch_exists(self):
        centered = app.pitch_gauge_segment_positions("3", 0, False)
        split_first = app.pitch_gauge_segment_positions("3", 0, False, True)
        split_second = app.pitch_gauge_segment_positions("3", 1, False, True)
        self.assertEqual({x for x, _y, _a in centered}, {140})
        self.assertEqual({x for x, _y, _a in split_first}, {135.5})
        self.assertEqual({x for x, _y, _a in split_second}, {144.5})
        self.assertEqual(centered, app.pitch_gauge_segment_positions("3", 0, True))
        self.assertEqual(app.pitch_gauge_label_geometry("3", 0, False), (140, 200, "middle"))
        self.assertEqual(app.pitch_gauge_label_geometry("3", 0, False, True), (134, 200, "end"))
        self.assertEqual(app.pitch_gauge_label_geometry("3", 1, False, True), (146, 200, "start"))

    def test_second_pitch_gauge_is_fixed_seven_steps_with_active_color_count(self):
        for movement, expected in ((1, 1), (3, 3), (7, 7), (0, 0), ("bad", 0)):
            svg = app.render_pitch_chart_svg([
                self.breaking(4, "1", "スライダー"),
                self.breaking(movement, "1", "Hスライダー", is_second_pitch=True, slot=2),
            ])
            active = re.findall(r'class="paired-pitch-(?:segment|tip)" data-direction="1" data-lane="1"[^>]+data-active="true"', svg)
            inactive = re.findall(r'class="paired-pitch-(?:segment|tip)" data-direction="1" data-lane="1"[^>]+data-active="false"', svg)
            self.assertEqual(len(active), expected)
            self.assertEqual(len(inactive), 7 - expected)
            self.assertEqual(svg.count('class="paired-pitch-segment"'), 12)
            self.assertEqual(svg.count('class="paired-pitch-tip"'), 2)
            self.assertIn('<polygon points="-5,-3.5 1.5,-3.5 6,0 1.5,3.5 -5,3.5"', svg)
        self.assertEqual(app.PAIRED_SEGMENT_WIDTH, 10)
        self.assertEqual(app.PAIRED_SEGMENT_HEIGHT, 7)
        self.assertEqual(app.PAIRED_SEGMENT_GAP, 1)
        self.assertEqual(app.PAIRED_SEGMENT_COUNT, 7)

    def test_paired_lanes_use_identical_geometry_and_independent_active_counts(self):
        for first_movement, second_movement in ((7, 1), (1, 7), (3, 5)):
            with self.subTest(first=first_movement, second=second_movement):
                svg = app.render_pitch_chart_svg([
                    self.breaking(first_movement, "2", "カーブ"),
                    self.breaking(second_movement, "2", "Dカーブ", is_second_pitch=True, slot=2),
                ])
                self.assertNotIn('class="pitch-gauge-segment" data-direction="2"', svg)
                self.assertNotIn('class="pitch-gauge-tip" data-direction="2"', svg)
                for lane, expected in ((0, first_movement), (1, second_movement)):
                    lane_elements = re.findall(
                        rf'class="paired-pitch-(?:segment|tip)" data-direction="2" data-lane="{lane}"[^>]+', svg,
                    )
                    self.assertEqual(len(lane_elements), 7)
                    self.assertEqual(sum('data-active="true"' in element for element in lane_elements), expected)
                self.assertEqual(svg.count(f'points="{app.PAIRED_ARROW_POINTS}"'), 2)

    def test_fixed_label_rectangles_do_not_overlap_for_same_direction_lanes(self):
        def estimated_label_width(text):
            return sum(12 if unicodedata.east_asian_width(character) in {"W", "F", "A"} else 7 for character in text)

        def label_rect(direction, lane_index):
            x, y, anchor = app.pitch_gauge_label_geometry(direction, lane_index, False, direction == "3")
            width = estimated_label_width("長球種名AB12")
            left = x - width if anchor == "end" else x - width / 2 if anchor == "middle" else x
            return left - 3, y - 14, left + width + 3, y + 2

        def overlaps(first, second):
            return first[0] < second[2] and second[0] < first[2] and first[1] < second[3] and second[1] < first[3]

        rectangles = [label_rect(direction, lane_index) for direction in "12345" for lane_index in (0, 1)]
        for index, first in enumerate(rectangles):
            self.assertGreaterEqual(first[0], 5)
            self.assertLessEqual(first[2], 275)
            self.assertGreaterEqual(first[1], 5)
            self.assertLessEqual(first[3], 205)
            for second in rectangles[index + 1:]:
                self.assertFalse(overlaps(first, second))

        self.assertEqual(estimated_label_width("SFF"), 21)
        self.assertEqual(estimated_label_width("カーブ"), 36)

    def test_straight_markers_are_compact_and_close_to_center_ball(self):
        single = app.render_pitch_chart_svg([])
        double = app.render_pitch_chart_svg([
            {"kind": "second_fastball", "name": "ツーシームファスト"},
            {"kind": "second_fastball", "name": "ムービングファスト"},
        ])
        self.assertIn('data-center-x="140" data-center-y="49"><polygon points="136,52 140,46 144,52"', single)
        self.assertIn('data-center-x="133"', double)
        self.assertIn('data-center-x="147"', double)
        self.assertEqual(double.count('class="straight-marker"'), 2)
        self.assertNotIn("ムービング", double)

    def test_fixed_visual_samples_a_to_e_render_expected_lanes(self):
        samples = {
            "A": ([self.breaking(4, "1", "スライダー"), self.breaking(3, "2", "カーブ"), self.breaking(5, "3", "フォーク")], False, 3),
            "B": ([self.breaking(4, "1", "スライダー"), self.breaking(2, "1", "Hスライダー", is_second_pitch=True), self.breaking(3, "3", "フォーク"), self.breaking(2, "3", "Vスライダー", is_second_pitch=True)], False, 4),
            "C": ([self.breaking(5, "1", "カットボール"), self.breaking(2, "2", "カーブ"), self.breaking(4, "3", "SFF"), self.breaking(3, "4", "シンカー")], True, 4),
            "D": ([{"kind": "second_fastball", "name": "ツーシームファスト"}, self.breaking(3, "1", "スライダー"), self.breaking(4, "3", "フォーク")], False, 2),
            "E": ([self.breaking(3, code, f"球種{code}") for code in "12345"], False, 5),
        }
        for name, (balls, is_left, expected_lanes) in samples.items():
            with self.subTest(sample=name):
                lanes = app.build_pitch_chart_lanes(balls, is_left)
                self.assertEqual(len(lanes), expected_lanes)
                svg = app.render_pitch_chart_svg(balls, "左投左打" if is_left else "右投右打")
                self.assertNotIn('class="pitch-guide"', svg)
                self.assertNotIn("★", svg)


if __name__ == "__main__":
    unittest.main()
