import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


class SpecialCellHtmlTest(unittest.TestCase):
    def test_rank_classes_by_rank_group(self):
        expected = {
            "A": "rank-ab",
            "B": "rank-ab",
            "C": "rank-cde",
            "D": "rank-cde",
            "E": "rank-cde",
            "F": "rank-fg",
            "G": "rank-fg",
        }
        for rank, css_class in expected.items():
            with self.subTest(rank=rank):
                html = app.special_cell_html(f"対左投手{rank}")
                self.assertIn("pp-special-ranked", html)
                self.assertIn(css_class, html)
                self.assertIn("pp-special-rank-badge", html)
                self.assertIn(f">{rank}</span>", html)

    def test_unranked_special_has_no_rank_badge(self):
        html = app.special_cell_html("広角打法")
        self.assertNotIn("pp-special-ranked", html)
        self.assertNotIn("pp-special-rank-badge", html)
        self.assertIn("pp-special-name", html)

    def test_mixed_special_uses_mixed_class_and_single_name(self):
        html = app.special_cell_html("投打躍動", "mixed")
        self.assertIn("pp-special mixed", html)
        self.assertEqual(html.count("pp-special-name"), 1)
        self.assertEqual(html.count("投打躍動"), 2)

    def test_long_special_is_compressed_not_shrunk(self):
        # A-1：文字の高さは全マス同じ。自然な幅（全角1em）を上限にSVGの幅だけ縮めて横圧縮する
        short = app.special_cell_html("広角打法")
        long = app.special_cell_html("スーパーウルトラ混合能力", "mixed")
        size = app.SPECIAL_NAME_FONT_PX
        self.assertIn(f'font-size="{size}"', short)
        self.assertIn(f'font-size="{size}"', long)
        self.assertIn(f'style="width:min(100%, {12 * size}px); height:', long)
        self.assertIn('preserveAspectRatio="none"', long)
        self.assertIn('lengthAdjust="spacingAndGlyphs"', long)
        self.assertNotIn("xlong", long)
        self.assertNotIn("--n:", long)

    def test_two_and_three_letter_specials_are_spread_to_four_letters(self):
        size = app.SPECIAL_NAME_FONT_PX
        for name in ["盗塁", "満塁男", "盗塁C"]:
            with self.subTest(name=name):
                html = app.special_cell_html(name)
                self.assertIn(f'textLength="{4 * size}" lengthAdjust="spacing"', html)
        self.assertIn('lengthAdjust="spacingAndGlyphs"', app.special_cell_html("広角打法"))

    def test_ranked_special_name_and_badge_are_separate(self):
        html = app.special_cell_html("ケガしにくさF")
        self.assertIn(">ケガしにくさ</text>", html)
        self.assertIn('<span class="pp-special-rank-badge">F</span>', html)

    def test_fit_text_width_counts_full_and_half_width(self):
        self.assertEqual(app.text_em_width("対ストレート○"), 7)
        self.assertAlmostEqual(app.text_em_width("Kim"), 0.630 + 0.338 + 0.819)
        self.assertAlmostEqual(app.text_em_width("í"), app.text_em_width("i"))
        html = app.fit_text_svg("Rodríguez", 40, align="start")
        width = round(app.text_em_width("Rodríguez") * 40, 1)
        self.assertIn(f'viewBox="0 0 {width:g} 50"', html)
        self.assertIn('x="0"', html)
        self.assertEqual(app.fit_text_svg("", 40), "")


if __name__ == "__main__":
    unittest.main()
