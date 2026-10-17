"""日本人の名（下の名前）の出やすさと、名を選ぶ乱数の分離（日本人の名前_改修指示.md）。

正式な判定は scripts/validate_team_mode.py の「日本人の名前」の節（球団生成300球団の日本人）。
ここでは、段の分け方と名の数、名が重みどおりに出ること、共通の乱数が改修前（名53個の rng.choice）と同じだけ進むこと、
名の一覧を変えても名前以外が変わらないこと、PYTHONHASHSEED によらないこと、一覧にない名が出ないこと、
名前の判定（集合にした版）が改修前と同じ結果になることを確かめる。
"""
from __future__ import annotations

import copy
import json
import os
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path

import app

APP_DIR = Path(__file__).resolve().parents[1]
MASTER = app.load_master_data()
GIVEN = MASTER.names["日本"]["名"]
SURNAME_MASTER = app.load_japanese_surname_master()
# 改修前の名の一覧（今の一覧の先頭53個がそのまま改修前の一覧）
LEGACY_GIVEN = GIVEN[:app.JAPANESE_GIVEN_NAME_LEGACY_COUNT]


def tier_counts() -> Counter:
    return Counter(app.japanese_given_name_tiers(GIVEN))


def test_given_name_list():
    assert len(GIVEN) == 9999
    assert len(set(GIVEN)) == len(GIVEN)
    assert "潮吹" not in GIVEN
    assert LEGACY_GIVEN[:3] == ["蓮", "大和", "翔"] and LEGACY_GIVEN[-1] == "琥太郎"


def test_tier_counts_and_shares():
    counts = tier_counts()
    assert counts == {"定番": 111, "よくある字": 924, "その他": 8501, "控えめ": 463}
    weights = app.load_japanese_given_name_weight_config()["重み"]
    total = sum(counts[tier] * weights[tier] for tier in counts)
    shares = {tier: round(100 * counts[tier] * weights[tier] / total, 1) for tier in counts}
    assert shares == {"定番": 36.0, "よくある字": 36.0, "その他": 27.6, "控えめ": 0.5}


def test_tier_rules():
    tiers = dict(zip(GIVEN, app.japanese_given_name_tiers(GIVEN)))
    assert tiers["翔太"] == "定番"
    assert tiers["悠介"] == "よくある字"  # 悠・介 とも定番の名前に使われている字
    assert tiers["翔太郎"] == "よくある字"
    assert tiers["恵"] == "控えめ"  # 1字（名指しにもある）
    assert tiers["静香"] == "控えめ"  # 名指し
    assert tiers["一"] == "控えめ"  # 定番にない1字
    assert tiers["龍之介"] == "その他"
    # 表の定番にあっても一覧にない名前は無視する（その字も「よくある字」の決め方に使わない）
    assert app.japanese_given_name_tiers(["翔太", "悠介", "未登録の名"]) == ["定番", "その他", "その他"]


def test_names_follow_weights():
    tier_of = dict(zip(GIVEN, app.japanese_given_name_tiers(GIVEN)))
    rng = random.Random(20261017)
    names = [app.choose_japanese_name(rng, MASTER.names, "東京都", SURNAME_MASTER).split(" ", 1)[1] for _ in range(30000)]
    assert all(name in tier_of for name in names)
    shares = {tier: 100 * count / len(names) for tier, count in Counter(tier_of[name] for name in names).items()}
    for tier, expected in {"定番": 36.0, "よくある字": 36.0, "その他": 27.6, "控えめ": 0.5}.items():
        assert abs(shares.get(tier, 0.0) - expected) < 1.5, (tier, shares)
    assert Counter(names).most_common(1)[0][1] / len(names) < 0.008


def test_common_rng_advances_like_legacy_choice():
    for seed in range(1, 200):
        rng = random.Random(seed)
        legacy = random.Random(seed)
        app.choose_japanese_name(rng, MASTER.names, "大阪府", SURNAME_MASTER)
        app.choose_japanese_surname("大阪府", legacy, SURNAME_MASTER)
        legacy.choice(LEGACY_GIVEN)  # 改修前の名の選び方
        assert rng.getstate() == legacy.getstate()


def test_given_name_list_does_not_change_anything_but_name():
    small = copy.deepcopy(MASTER)
    small.names = copy.deepcopy(MASTER.names)
    small.names["日本"]["名"] = list(LEGACY_GIVEN)
    compared = 0
    for category in ("架空球団用", "ドラフト候補用"):
        for role in ("投手", "野手"):
            for seed in range(1, 31):
                full = app.generate_player(role, category, MASTER, seed=seed, used_names=set())
                legacy = app.generate_player(role, category, small, seed=seed, used_names=set())
                if full["nationality"] != "日本":
                    assert full == legacy
                    continue
                ignore = {"name", "skin_color"}
                assert {k: v for k, v in full.items() if k not in ignore} == {k: v for k, v in legacy.items() if k not in ignore}
                assert full["name"].split(" ")[0] == legacy["name"].split(" ")[0]
                assert full["name"].split(" ")[1] in GIVEN
                compared += 1
    assert compared > 100


HASH_SCRIPT = r"""
import json, random, sys
sys.path.insert(0, sys.argv[1])
import app
master = app.load_master_data()
surnames = app.load_japanese_surname_master()
print("RESULT:" + json.dumps([app.choose_japanese_name(random.Random(seed), master.names, "北海道", surnames) for seed in range(300)], ensure_ascii=False))
"""


def test_names_do_not_depend_on_hash_seed():
    results = []
    for hash_seed in ("0", "123"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONIOENCODING": "utf-8"}
        out = subprocess.run([sys.executable, "-c", HASH_SCRIPT, str(APP_DIR)], env=env, capture_output=True, text=True, encoding="utf-8", check=True).stdout
        results.append(json.loads(next(line for line in out.splitlines() if line.startswith("RESULT:"))[len("RESULT:"):]))
    assert results[0] == results[1]


def legacy_name_matches_entry(name, entry):
    surnames, given_names = entry.get("姓", []), entry.get("名", [])
    return any(name.startswith(f"{s} ") for s in surnames) and any(name.endswith(f" {g}") for g in given_names)


def test_name_matching_same_as_before():
    entry = MASTER.names["日本"]
    cases = ["佐藤 翔太", "佐藤 潮吹", "佐藤  翔太", "佐藤翔太", "翔太 佐藤", "佐藤 翔太 佐藤 翔太", "鈴木 翔", "鈴木 翔太郎", " 翔太", "佐藤 ", ""]
    cases += [f"{random.Random(i).choice(entry['姓'])} {random.Random(i + 1).choice(GIVEN)}" for i in range(200)]
    for name in cases:
        assert app.name_matches_entry(name, entry) == legacy_name_matches_entry(name, entry), name
    foreign = {"姓": ["Smith", "De La Cruz"], "名": ["John", "Juan Carlos"]}
    for name in ("Smith John", "De La Cruz Juan Carlos", "Smith Juan Carlos", "De La Cruz John", "Smith Carlos", "La Cruz John"):
        assert app.name_matches_entry(name, foreign) == legacy_name_matches_entry(name, foreign), name
    assert app.japanese_name_matches_surname_master("佐藤 翔太", MASTER)
    assert not app.japanese_name_matches_surname_master("佐藤 潮吹", MASTER)
