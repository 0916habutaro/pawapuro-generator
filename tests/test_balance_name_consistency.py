import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from generator import foreign_names


# 名前グループID → 表示国籍（generator/foreign_names.py の対応表の一部を固定したもの）
GROUP_NATIONALITIES = {
    0: frozenset({"アメリカ"}),
    71: frozenset({"ドミニカ共和国"}),
    3: frozenset({"韓国"}),
}


@pytest.fixture
def master():
    return app.MasterData(names={"日本": {"姓": ["山田"], "名": ["太郎"]}}, places={}, abilities=[])


@pytest.fixture
def group_mapping(monkeypatch):
    monkeypatch.setattr(app, "name_group_display_nationalities", lambda: GROUP_NATIONALITIES)


def foreign_player(**overrides):
    player = {"name": "Delfo Polanco", "nationality": "ドミニカ共和国", "birthplace": "サントドミンゴ", "name_group_id": 71, "name_group_name": "Dominican"}
    return pd.Series({**player, **overrides})


def test_foreign_player_name_matches_nationality(master, group_mapping):
    player = foreign_player()
    assert app.name_matches_nationality(player["name"], player["nationality"], master, player["birthplace"], player["name_group_id"], player["name_group_name"])
    assert app.player_name_matches_nationality(player, master)


def test_foreign_name_group_with_other_nationality_is_inconsistent(master, group_mapping):
    assert not app.player_name_matches_nationality(foreign_player(nationality="韓国"), master)


def test_name_group_id_zero_is_treated_as_foreign_when_group_name_exists(master, group_mapping):
    # ID 0 は「U.S. (Modern)」と DB の既定値の両方に使われるため、グループ名の有無で判定する
    player = foreign_player(name="Nolan Richards", nationality="アメリカ", name_group_id=0, name_group_name="U.S. (Modern)")
    assert app.player_name_matches_nationality(player, master)


def test_japanese_player_without_group_name_uses_names_master(master, group_mapping):
    player = pd.Series({"name": "山田 太郎", "nationality": "日本", "birthplace": None, "name_group_id": 0, "name_group_name": ""})
    assert app.foreign_name_group(player["name_group_id"], player["name_group_name"]) is None
    assert app.player_name_matches_nationality(player, master)


def test_name_type_shows_name_group_name_for_foreign_player(master, group_mapping):
    assert app.player_name_type(foreign_player(), master) == "Dominican"


def test_consistency_table_counts_foreign_player_as_consistent(master, group_mapping):
    df = pd.DataFrame([foreign_player().to_dict()])
    assert app.inconsistency_count(df, master, "name") == 0
    table = app.consistency_table(df, master, "name")
    assert table.loc[0, "名前種別"] == "Dominican"
    assert bool(table.loc[0, "整合性"]) is True


@pytest.mark.skipif(not foreign_names.imported_db_ready(), reason="外国人名DB（data/imported/foreign_names.sqlite）が無い環境")
def test_real_name_group_mapping_contains_dominican_group():
    mapping = foreign_names.name_group_display_nationalities()
    assert "ドミニカ共和国" in mapping.get(71, frozenset())
