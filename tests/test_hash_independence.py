"""文字列のハッシュ（PYTHONHASHSEED）の値によらず、同じseedなら同じ選手・同じ球団ができることを確かめる。

集合（set）を順番に回しながら乱数を引くと、起動のたびに結果が変わる。そうした処理が入り込んでいないかを、
PYTHONHASHSEED を変えた別プロセスで作った結果を比べて確かめる。
"""
import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent

HASH_SEEDS = ("0", "1", "2", "12345")
PLAYER_SEEDS = 200  # 6区分 × seed 1〜200（ドラフト候補用の野手も200人）
TEAM_SEEDS = (1, 2, 3)

DUMP_SCRIPT = r"""
import hashlib, json, logging, sys
sys.path.insert(0, sys.argv[1])
import app
n, team_seeds = int(sys.argv[2]), json.loads(sys.argv[3])
master = app.load_master_data()
fp = lambda value: hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
result = {}
for category in app.CATEGORIES:
    for role in ("投手", "野手"):
        result[f"{category}|{role}"] = [
            fp(app.generate_player(role, category, master, seed=seed, used_names=set())) for seed in range(1, n + 1)
        ]
result["team"] = [fp({k: v for k, v in app.generate_team(seed, master=master).items() if k != "elapsed_seconds"}) for seed in team_seeds]
print("RESULT:" + json.dumps(result))
"""


class HashIndependenceTest(unittest.TestCase):
    def test_same_result_for_any_hash_seed(self):
        procs = {}
        for hash_seed in HASH_SEEDS:
            env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONUTF8": "1"}
            procs[hash_seed] = subprocess.Popen(
                [sys.executable, "-c", DUMP_SCRIPT, str(APP_DIR), str(PLAYER_SEEDS), json.dumps(list(TEAM_SEEDS))],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env, cwd=str(APP_DIR),
            )
        results = {}
        for hash_seed, proc in procs.items():
            out, err = proc.communicate()
            self.assertEqual(proc.returncode, 0, f"PYTHONHASHSEED={hash_seed} で異常終了:\n{err[-2000:]}")
            line = next(line for line in out.splitlines() if line.startswith("RESULT:"))
            results[hash_seed] = json.loads(line[len("RESULT:"):])
        base = results[HASH_SEEDS[0]]
        for hash_seed in HASH_SEEDS[1:]:
            for key, values in base.items():
                diff = [i + 1 for i, (a, b) in enumerate(zip(values, results[hash_seed][key])) if a != b]
                self.assertEqual(diff, [], f"PYTHONHASHSEED={hash_seed} で {key} の seed/球団 {diff[:10]} が PYTHONHASHSEED={HASH_SEEDS[0]} と違う")


if __name__ == "__main__":
    unittest.main()
