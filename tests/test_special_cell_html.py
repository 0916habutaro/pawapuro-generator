import unittest

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


if __name__ == "__main__":
    unittest.main()
