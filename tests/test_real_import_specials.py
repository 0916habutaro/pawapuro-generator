"""実在のHTMLの特能の読み替え（「対ランナー」は class=M なら赤特の「対ランナー×」）を確かめる。"""
import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(APP_DIR / "scripts"))

import import_real_powerpro_players as importer  # noqa: E402


class RealSpecialNameTest(unittest.TestCase):
    def test_red_tairunner_becomes_red_name(self):
        block = '<b class="P">奪三振</b><b class="PM">荒れ球</b><b class="M">対ランナー</b><b class="M">四球</b>'
        self.assertEqual(importer.parse_normal_specials(block), ["奪三振", "荒れ球", "対ランナー×", "四球"])

    def test_blue_tairunner_keeps_app_blue_name(self):
        block = '<b class="P">対ランナー○</b><b class="P">要所○</b>'
        self.assertEqual(importer.parse_normal_specials(block), ["対ランナー", "要所○"])

    def test_other_specials_are_not_renamed(self):
        for name, css in (("対ランナー", "P"), ("四球", "M"), ("寸前", "PM st9")):
            self.assertEqual(importer.normalize_special_name(name, css), name)


if __name__ == "__main__":
    unittest.main()
