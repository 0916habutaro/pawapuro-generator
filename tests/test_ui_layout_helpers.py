import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

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
            "S": "#f3b400",
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
            {"kind": "breaking", "direction_code": "3", "name": "SFF", "movement": 3, "is_second_pitch": False, "slot": 1},
            {"kind": "breaking", "direction_code": "3", "name": "フォーク", "movement": 4, "is_second_pitch": True, "slot": 2},
        ])
        labels = re.findall(r'<text x="([0-9.]+)" y="[0-9.]+" text-anchor="(end|start)"[^>]*>(SFF|フォーク)</text>', html)
        self.assertEqual(len(labels), 2)
        anchors = {label: anchor for _x, anchor, label in labels}
        xs = {label: float(x) for x, _anchor, label in labels}
        self.assertEqual(anchors["SFF"], "end")
        self.assertEqual(anchors["フォーク"], "start")
        self.assertEqual(xs["SFF"], 126)
        self.assertEqual(xs["フォーク"], 154)
        self.assertIn('<text x="126" y="192" text-anchor="end"', html)
        self.assertIn('<text x="154" y="192" text-anchor="start"', html)
        self.assertNotIn('<text x="128" y="202"', html)
        self.assertNotIn('<text x="152" y="202"', html)

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

    def test_left_pitcher_mirrors_direction_one_label(self):
        ball = [{"kind": "breaking", "direction_code": "1", "name": "スライダー", "movement": 3}]
        right = app.render_pitch_chart_svg(ball, "右投右打")
        left = app.render_pitch_chart_svg(ball, "左投左打")
        self.assertIn('<text x="260" y="86" text-anchor="end"', right)
        self.assertIn('<text x="20" y="86" text-anchor="start"', left)
        self.assertNotIn('<text x="250" y="72"', right)
        self.assertNotIn('<text x="30" y="72"', left)

    def test_second_fastball_uses_first_fixed_lane_and_short_name(self):
        html = app.render_pitch_chart_svg([
            {"kind": "second_fastball", "name": "ツーシームファスト"},
            {"kind": "second_fastball", "name": "ムービングファスト"},
        ])
        self.assertIn('<text x="140" y="25" text-anchor="middle"', html)
        self.assertIn('<text x="140" y="42" text-anchor="middle" fill="#126bb0" font-size="12"', html)
        self.assertIn('<rect x="135" y="47" width="4" height="8" rx="1" fill="#ff9b19"/>', html)
        self.assertIn('<rect x="142" y="47" width="4" height="8" rx="1" fill="#ff9b19"/>', html)
        self.assertNotIn('<text x="140" y="43" text-anchor="middle" fill="#126bb0" font-size="13"', html)
        self.assertNotIn('<rect x="134" y="48" width="5" height="10"', html)
        self.assertIn("ツーシーム", html)
        self.assertNotIn("ムービング", html)

    def test_pitch_display_names_are_shortened(self):
        expected = {
            "サークルチェンジ": "Cチェンジ",
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

    def test_pitch_chart_draw_order_keeps_labels_in_front(self):
        svg = app.render_pitch_chart_svg([
            {"kind": "breaking", "direction_code": "1", "name": "スライダー", "movement": 3},
        ])
        self.assertLess(svg.index('<line x1="140" y1="66"'), svg.index('<rect x="80" y="57"'))
        self.assertLess(svg.index('<rect x="80" y="57"'), svg.index('<circle cx="140" cy="66"'))
        self.assertLess(svg.index('<circle cx="140" cy="66"'), svg.index('width="8" height="8"'))
        self.assertLess(svg.index('width="8" height="8"'), svg.index('>スライダー</text>'))

    def test_pitch_chart_straight_bars_use_compact_fixed_geometry(self):
        svg = app.render_pitch_chart_svg([])
        self.assertIn('<rect x="80" y="57" width="43" height="6" rx="3"', svg)
        self.assertIn('<rect x="157" y="57" width="43" height="6" rx="3"', svg)
        self.assertNotIn('<rect x="78" y="59" width="46" height="7"', svg)
        self.assertNotIn('<rect x="156" y="59" width="46" height="7"', svg)

    def test_direction_pitch_labels_use_12px_font(self):
        svg = app.render_pitch_chart_svg([
            {"kind": "breaking", "direction_code": "1", "name": "スライダー", "movement": 1},
        ])
        self.assertIn('font-size="16" font-weight="900">ストレート</text>', svg)
        self.assertIn('font-size="12" font-weight="900">スライダー</text>', svg)

    def test_short_block_progression_stays_closer_to_center(self):
        regular = app.block_points(140, 66, 250, 92, -1, 7)
        shortened = app.block_points(140, 66, 250, 92, -1, 7, start_t=0.20, step_t=0.075)
        self.assertEqual(len(regular), 7)
        self.assertEqual(len(shortened), 7)
        self.assertLess(shortened[-1][0], regular[-1][0])
        self.assertLess(shortened[-1][1], regular[-1][1])
        self.assertAlmostEqual(regular[-1][0], 241.390204, places=5)
        self.assertAlmostEqual(regular[-1][1], 81.744523, places=5)
        self.assertAlmostEqual(shortened[-1][0], 221.590204, places=5)
        self.assertAlmostEqual(shortened[-1][1], 77.064523, places=5)
        self.assertEqual(app.block_points(140, 66, 250, 92, -1, 0), [])


if __name__ == "__main__":
    unittest.main()
