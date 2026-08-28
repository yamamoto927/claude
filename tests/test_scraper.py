import datetime as dt

from conftest import FIXTURES, fixture

from keiba_ai.scraper.client import HTML_PARSER, NetkeibaClient, decode_html
from keiba_ai.scraper.horse import parse_horse_results
from keiba_ai.scraper.shutuba import parse_odds_api, parse_shutuba


def test_decode_html_handles_euc_jp():
    raw = '<html><head><meta charset="EUC-JP"></head><body>馬場:良</body></html>'.encode("euc-jp")
    assert "馬場:良" in decode_html(raw)


def test_decode_html_falls_back_without_meta():
    assert decode_html("東京11R".encode("utf-8")) == "東京11R"


def test_parse_shutuba_race_header():
    race, _ = parse_shutuba(fixture("shutuba_sample.html"), "202605020711")
    assert race.name == "サンプルステークス"
    assert race.grade == "G3"
    assert race.race_no == 11
    assert race.venue == "東京"
    assert race.surface == "芝"
    assert race.distance == 1800
    assert race.direction == "左"
    assert race.condition == "稍重"      # 「稍」を正規化
    assert race.weather == "晴"
    assert race.start_time == "15:45"
    assert race.weight_rule == "ハンデ"
    assert race.date == dt.date(2026, 5, 17)


def test_parse_shutuba_horses():
    _, horses = parse_shutuba(fixture("shutuba_sample.html"), "202605020711")
    assert [h.umaban for h in horses] == [1, 3, 5, 7, 8]

    first = horses[0]
    assert first.name == "サンプルアロー"
    assert first.horse_id == "2021104321"
    assert first.waku == 1
    assert (first.sex, first.age) == ("牡", 5)
    assert first.weight_carried == 55.0
    assert first.jockey == "田中太郎"
    assert first.trainer == "山田一郎"
    assert first.stable == "美浦"
    assert (first.horse_weight, first.horse_weight_diff) == (482, 4)
    assert first.odds == 12.4
    assert first.popularity == 4

    assert horses[2].sex == "セ"
    assert horses[1].horse_weight_diff == -6


def test_parse_shutuba_marks_scratched_horse():
    race, horses = parse_shutuba(fixture("shutuba_sample.html"), "202605020711")
    cancelled = [h for h in horses if h.scratched]
    assert [h.name for h in cancelled] == ["モックスター"]
    assert race.field_size == 4      # 取消を除いた頭数


def test_parse_odds_api():
    payload = {"data": {"odds": {"1": {"01": ["12.4", "12.6", "4"], "03": ["3.8", "3.9", "1"]}}}}
    assert parse_odds_api(payload) == {1: (12.4, 4), 3: (3.8, 1)}


def test_parse_horse_results_columns():
    runs = parse_horse_results(fixture("horse_results.html"))
    assert len(runs) == 3
    latest = runs[0]
    assert latest.date == dt.date(2026, 4, 12)
    assert latest.venue == "東京"
    assert latest.race_name == "サンプル記念"
    assert latest.grade == "G3"
    assert latest.field_size == 16
    assert latest.finish == 3
    assert latest.surface == "芝"
    assert latest.distance == 1800
    assert latest.condition == "良"
    assert latest.time_sec == 105.8
    assert latest.margin == 0.2
    assert latest.corners == [5, 5, 4]
    assert (latest.pace_first, latest.pace_last) == (36.5, 34.9)
    assert latest.last3f == 34.2
    assert (latest.horse_weight, latest.horse_weight_diff) == (482, 4)
    assert latest.prize == 1000.0


def test_parse_horse_results_derived_values():
    runs = parse_horse_results(fixture("horse_results.html"))
    latest = runs[0]
    # 16頭立て3着 -> 1 - 2/15
    assert round(latest.finish_rate, 3) == round(1 - 2 / 15, 3)
    assert latest.agari_edge == 0.7            # 34.9 - 34.2
    assert round(latest.early_position_rate, 3) == round(4 / 15, 3)


def test_parse_horse_results_skips_cancelled_race():
    runs = parse_horse_results(fixture("horse_results.html"))
    cancelled = runs[2]
    assert cancelled.finish is None
    assert cancelled.finish_note == "中止"
    assert cancelled.valid is False
    assert cancelled.condition == "不良"
    assert cancelled.surface == "ダ"


def test_parse_horse_results_limit():
    assert len(parse_horse_results(fixture("horse_results.html"), limit=2)) == 2


def test_html_parser_fallback_gives_same_result():
    """lxml が無い環境でも標準の html.parser で同じ結果になる。"""
    html = fixture("shutuba_sample.html")
    race_a, horses_a = parse_shutuba(html, "202605020711", parser=HTML_PARSER)
    race_b, horses_b = parse_shutuba(html, "202605020711", parser="html.parser")
    assert (race_a.name, race_a.distance, race_a.condition) == (race_b.name, race_b.distance, race_b.condition)
    assert [(h.umaban, h.name, h.odds, h.jockey) for h in horses_a] == \
           [(h.umaban, h.name, h.odds, h.jockey) for h in horses_b]

    runs_a = parse_horse_results(fixture("horse_results.html"), parser=HTML_PARSER)
    runs_b = parse_horse_results(fixture("horse_results.html"), parser="html.parser")
    assert [(r.date, r.finish, r.last3f, r.grade) for r in runs_a] == \
           [(r.date, r.finish, r.last3f, r.grade) for r in runs_b]


def test_offline_client_reads_saved_html(tmp_path):
    url = "https://race.netkeiba.com/race/shutuba.html?race_id=202605020711"
    target = tmp_path / NetkeibaClient.slug(url)
    target.write_bytes(fixture("shutuba_sample.html").encode("utf-8"))
    client = NetkeibaClient(cache_dir=None, offline_dir=tmp_path, sleep=0)
    assert "サンプルステークス" in client.get(url)
