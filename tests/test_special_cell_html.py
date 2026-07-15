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

    def test_long_mixed_special_keeps_length_class(self):
        html = app.special_cell_html("スーパーウルトラ混合能力", "mixed")
        self.assertIn("pp-special mixed xlong", html)
        self.assertIn("pp-special-name", html)


if __name__ == "__main__":
    unittest.main()
