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
