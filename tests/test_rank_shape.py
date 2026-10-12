"""架空球団用の日本人の、ポジション・役割ごとのランク特能の重み（`ランク特能の形_改修指示.md`）。

重みは球団生成で合わせており、正式な判定は scripts/check_fielder_speed.py・check_fielder_position.py・
check_pitcher_rank_pitches.py（球団生成300球団。共通部分は scripts/rank_shape.py）。ここでは個別生成で、
ポジション・役割ごとの重みが使われること、乱数の流れとほかの区分が変わらないことを確かめる。
"""
from __future__ import annotations

import app

MASTER = app.load_master_data()
SEEDS = range(1, 301)
FIELDER_KEYS = ("走塁_捕手", "走塁_一三", "走塁_二遊外", "盗塁_捕手", "盗塁_一三", "盗塁_二遊外", "ケガしにくさ_捕遊", "ケガしにくさ_他")
PITCHER_KEYS = ("対ピンチ_先発", "対ピンチ_救援")


def players(role: str = "野手", category: str = "架空球団用") -> list[dict]:
    return [app.generate_player(role, category, MASTER, seed=seed) for seed in SEEDS]


def domestic(role: str) -> list[dict]:
    return [player for player in players(role) if player["roster_origin"] == "domestic"]


def letter(player: dict, group: str) -> str | None:
    name = player["abilities"]["ranked_specials"].get(group)
    return name[-1] if name else None


def without_ranked(player: dict) -> dict:
    return {**player, "abilities": {k: v for k, v in player["abilities"].items() if k != "ranked_specials"}}


def test_fielder_weights_key_splits_running_by_position_group_and_injury_by_catcher_side():
    key = app.fictional_fielder_ranked_weights_key
    for group in ("走塁", "盗塁"):
        assert key(group, "捕手", "右投右打") == f"{group}_捕手"
        assert key(group, "一塁手", "左投左打") == f"{group}_一三"
        assert key(group, "三塁手", "右投右打") == f"{group}_一三"
        for position in ("二塁手", "遊撃手", "外野手"):
            assert key(group, position, "右投左打") == f"{group}_二遊外"
    for position in ("捕手", "遊撃手"):
        assert key("ケガしにくさ", position, "右投右打") == "ケガしにくさ_捕遊"
    for position in ("一塁手", "二塁手", "三塁手", "外野手"):
        assert key("ケガしにくさ", position, "右投右打") == "ケガしにくさ_他"
    assert key("チャンス", "捕手", "右投左打") == "チャンス"  # チャンスは分けない（重みだけ変えた）
    for name in (*FIELDER_KEYS, "走塁", "盗塁", "ケガしにくさ", "チャンス"):  # 分けない重みは予備として残す
        assert name in app.FICTIONAL_FIELDER_RANKED_WEIGHTS


def test_pitcher_weights_key_splits_pinch_by_role_and_keeps_injury():
    key = app.fictional_pitcher_ranked_weights_key
    assert key("対ピンチ", "先発", "右投右打") == "対ピンチ_先発"
    assert key("対ピンチ", "中継ぎ", "左投左打") == "対ピンチ_救援"
    assert key("対ピンチ", "抑え", "右投右打") == "対ピンチ_救援"
    assert key("ケガしにくさ", "先発", "右投右打") == "ケガしにくさ"  # 投手のケガしにくさは今の重みのまま
    for name in (*PITCHER_KEYS, "対ピンチ", "ケガしにくさ"):
        assert name in app.FICTIONAL_PITCHER_RANKED_WEIGHTS


def test_fielder_new_weights_are_used(monkeypatch):
    # 補正で1段ずつしか動かないので、重なりのない文字にする（G は F・E に、A は B・C にしか動かない）
    weights = dict(app.FICTIONAL_FIELDER_RANKED_WEIGHTS)
    weights.update({"走塁_捕手": {"G": 1.0}, "走塁_一三": {"D": 1.0}, "走塁_二遊外": {"A": 1.0},
                    "ケガしにくさ_捕遊": {"G": 1.0}, "ケガしにくさ_他": {"A": 1.0}})
    monkeypatch.setattr(app, "FICTIONAL_FIELDER_RANKED_WEIGHTS", weights)
    seen = {"捕手": 0, "一三": 0, "二遊外": 0}
    for player in domestic("野手"):
        part = app.FICTIONAL_FIELDER_RUN_GROUPS.get(player["position"], "二遊外")
        run = letter(player, "走塁") or "D"
        assert run in {"捕手": "EFG", "一三": "BCDEF", "二遊外": "ABC"}[part], (player["seed"], player["position"], run)
        seen[part] += 1
        injury = letter(player, "ケガしにくさ") or "D"
        assert injury in ("EFG" if player["position"] in ("捕手", "遊撃手") else "ABC"), (player["seed"], player["position"], injury)
    assert all(seen.values()), seen


def test_pitcher_new_weights_are_used(monkeypatch):
    weights = {**app.FICTIONAL_PITCHER_RANKED_WEIGHTS, "対ピンチ_先発": {"G": 1.0}, "対ピンチ_救援": {"A": 1.0}}
    monkeypatch.setattr(app, "FICTIONAL_PITCHER_RANKED_WEIGHTS", weights)
    seen = {"先発": 0, "救援": 0}
    for player in domestic("投手"):
        role = "先発" if player["position"] == "先発" else "救援"
        pinch = letter(player, "対ピンチ") or "D"
        assert pinch in ("EFG" if role == "先発" else "ABC"), (player["seed"], player["position"], pinch)
        seen[role] += 1
    assert all(seen.values()), seen


def test_new_weights_do_not_change_the_random_stream(monkeypatch):
    # 重みを変えても乱数を引く回数は変わらない（weighted_choice は重みによらず1回）。ランク特能以外と、ほかの項目のランクは同じ
    current = {role: domestic(role) for role in ("投手", "野手")}
    monkeypatch.setattr(app, "FICTIONAL_FIELDER_RANKED_WEIGHTS", {**app.FICTIONAL_FIELDER_RANKED_WEIGHTS, **{k: {"D": 1.0} for k in (*FIELDER_KEYS, "チャンス")}})
    monkeypatch.setattr(app, "FICTIONAL_PITCHER_RANKED_WEIGHTS", {**app.FICTIONAL_PITCHER_RANKED_WEIGHTS, **{k: {"D": 1.0} for k in PITCHER_KEYS}})
    changed_groups = {"投手": {"対ピンチ"}, "野手": {"走塁", "盗塁", "ケガしにくさ", "チャンス"}}
    for role in ("投手", "野手"):
        for a, b in zip(current[role], domestic(role)):
            assert without_ranked(a) == without_ranked(b), (role, a["seed"])
            ra, rb = a["abilities"]["ranked_specials"], b["abilities"]["ranked_specials"]
            for group in set(ra) | set(rb):
                if group not in changed_groups[role]:
                    assert ra.get(group) == rb.get(group), (role, a["seed"], group)


def test_other_categories_do_not_use_the_new_weights(monkeypatch):
    cases = [("投手", "ドラフト候補用"), ("野手", "ドラフト候補用"), ("投手", "助っ人外国人用"), ("野手", "助っ人外国人用")]
    current = {case: players(*case) for case in cases}
    foreign = {role: [p for p in players(role) if p["roster_origin"] != "domestic"] for role in ("投手", "野手")}
    monkeypatch.setattr(app, "FICTIONAL_FIELDER_RANKED_WEIGHTS", {**app.FICTIONAL_FIELDER_RANKED_WEIGHTS, **{k: {"G": 1.0} for k in (*FIELDER_KEYS, "チャンス")}})
    monkeypatch.setattr(app, "FICTIONAL_PITCHER_RANKED_WEIGHTS", {**app.FICTIONAL_PITCHER_RANKED_WEIGHTS, **{k: {"G": 1.0} for k in PITCHER_KEYS}})
    for case in cases:
        assert players(*case) == current[case], case
    for role in ("投手", "野手"):
        assert [p for p in players(role) if p["roster_origin"] != "domestic"] == foreign[role], role
