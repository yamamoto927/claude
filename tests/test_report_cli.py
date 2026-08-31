import json

import conftest  # noqa: F401
import pytest

from keiba_ai.analysis.engine import analyze_race
from keiba_ai.analysis.bias import parse_bias_text
from keiba_ai.cli import main
from keiba_ai.pipeline import extract_race_id
from keiba_ai.report import render
from keiba_ai.sample_data import build_sample


@pytest.fixture(scope="module")
def analysis():
    race, horses = build_sample()
    return analyze_race(race, horses, parse_bias_text("内有利で前残り、時計は速い"))


def test_sample_data_is_complete():
    race, horses = build_sample()
    assert len(horses) == 16
    assert race.distance == 1800
    assert all(h.past_runs for h in horses)
    assert sorted(h.popularity for h in horses) == list(range(1, 17))


def test_text_report_has_all_sections(analysis):
    text = render(analysis, "text")
    for heading in ["【1】荒れる可能性", "【2】穴馬筆頭候補", "【3】想定ペース・展開",
                    "【4】馬場傾向の反映", "【5】本命・対抗", "【6】危険な人気馬",
                    "【7】全頭評価一覧", "【8】推奨買い目"]:
        assert heading in text
    assert "20歳以上" in text


def test_text_report_shows_complementary_probabilities(analysis):
    text = render(analysis, "text")
    assert f"{analysis.chaos_pct:5.1f}%" in text
    assert f"{round(100 - analysis.chaos_pct, 1):5.1f}%" in text


def test_markdown_report(analysis):
    md = render(analysis, "markdown")
    assert md.startswith("# ")
    assert "## 1. 荒れる可能性" in md
    assert "| 馬番 | 馬名 |" in md


def test_json_report_is_valid(analysis):
    payload = json.loads(render(analysis, "json"))
    assert payload["chaos"]["upset_probability_pct"] == analysis.chaos_pct
    assert (payload["chaos"]["upset_probability_pct"]
            + payload["chaos"]["favorites_decide_pct"]) == pytest.approx(100.0)
    assert len(payload["all_horses"]) == 16
    assert payload["dark_horses"] and payload["dark_horses"][0]["grounds"]
    assert payload["bias"]["inner"] > 0
    assert payload["race"]["date"] == "2026-05-17"


def test_dark_horses_are_actually_unpopular(analysis):
    for e in analysis.dark_horses:
        assert (e.horse.popularity or 0) >= 5 or (e.horse.odds or 0) >= 9.0


def test_dark_horse_count_matches_verdict(analysis):
    expected = 3 if analysis.chaos_pct >= 50 else 1
    assert len(analysis.dark_horses) == expected


def test_dangerous_favorites_are_not_also_picks(analysis):
    dangerous = {id(e) for e in analysis.dangerous_favorites}
    assert not any(id(e) in dangerous for e in analysis.favorites_pick)


def _all_plans():
    """堅い〜大波乱まで、全ての買い目分岐を実際に組ませる。"""
    from keiba_ai.analysis.betting import build_bets
    from keiba_ai.analysis.darkhorse import (
        compute_dark_index, pick_dangerous_favorites, pick_dark_horses, pick_favorites,
    )
    from keiba_ai.analysis.features import apply_market_scores, evaluate_horse
    from keiba_ai.analysis.pace import detect_style
    from keiba_ai.models import PaceForecast, TrackBias

    race, horses = build_sample()
    evs = [
        evaluate_horse(h, race, TrackBias(), PaceForecast(), detect_style(h), "良", len(horses))
        for h in horses
    ]
    apply_market_scores(evs)
    mean_ability = compute_dark_index(evs)
    dangerous = pick_dangerous_favorites(evs)
    favorites = pick_favorites(evs, 2, exclude=dangerous)
    out = []
    for chaos in (20.0, 42.9, 43.0, 59.9, 60.0, 85.0):
        darks = pick_dark_horses(evs, 3 if chaos >= 50 else 1, mean_ability)
        out.extend(build_bets(chaos, favorites, darks, evs, dangerous))
    return out


def test_bet_plans_never_repeat_a_horse_within_a_column():
    for plan in _all_plans():
        for column in plan.groups:
            assert len(column) == len(set(column)), f"{plan.kind}: {plan.detail}"


def test_flow_bets_never_put_the_axis_among_its_partners():
    """流し・フォーメーションの軸(1列目)が相手側に混ざっていないこと。"""
    for plan in _all_plans():
        if len(plan.groups) < 2:
            continue
        axis = set(plan.groups[0])
        for column in plan.groups[1:]:
            assert not (axis & set(column)), f"{plan.kind}: {plan.detail}"


def test_bet_plan_detail_matches_its_groups():
    for plan in _all_plans():
        for column in plan.groups:
            for umaban in column:
                assert str(umaban) in plan.detail


def test_every_chaos_level_produces_bets():
    from keiba_ai.analysis.betting import build_bets
    assert _all_plans()
    assert build_bets(70.0, [], [], []) == []      # 出走馬が居なければ空


@pytest.mark.parametrize("value,expected", [
    ("202605021711", "202605021711"),
    ("https://race.netkeiba.com/race/shutuba.html?race_id=202605021711", "202605021711"),
    ("https://race.netkeiba.com/race/result.html?race_id=202605021711&rf=race_list", "202605021711"),
])
def test_extract_race_id(value, expected):
    assert extract_race_id(value) == expected


def test_extract_race_id_rejects_garbage():
    with pytest.raises(ValueError):
        extract_race_id("東京11R")


def test_cli_sample_run(capsys):
    assert main(["--sample", "--bias", "内有利で前残り"]) == 0
    out = capsys.readouterr().out
    assert "穴馬筆頭候補" in out
    assert "サンプルデータ" in out


def test_cli_json_output(capsys):
    assert main(["--sample", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["pace"]["label"]
    assert payload["bias"]["description"]


def test_cli_writes_file(tmp_path, capsys):
    dest = tmp_path / "out.md"
    assert main(["--sample", "--markdown", "-o", str(dest)]) == 0
    assert "## 2. 穴馬筆頭候補" in dest.read_text(encoding="utf-8")


def test_cli_numeric_bias_flags(capsys):
    assert main(["--sample", "--bias-inner", "-0.7", "--bias-front", "-0.5", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["bias"]["inner"] == -0.7
    assert payload["bias"]["front"] == -0.5


def test_cli_requires_a_target(capsys):
    assert main([]) == 2
    assert "race_id" in capsys.readouterr().err
