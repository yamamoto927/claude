import datetime as dt

import conftest  # noqa: F401

from keiba_ai.analysis.chaos import BASE_RATE, compute_chaos
from keiba_ai.analysis.darkhorse import compute_dark_index
from keiba_ai.analysis.engine import CHAOS_THRESHOLD, analyze_race
from keiba_ai.analysis.features import apply_market_scores, evaluate_horse
from keiba_ai.analysis.pace import detect_style, forecast_pace
from keiba_ai.models import (
    NIGE, OIKOMI, Horse, HorseEvaluation, PaceForecast, PastRun, RaceInfo, TrackBias,
)

RACE_DATE = dt.date(2026, 5, 17)


def make_race(**kw) -> RaceInfo:
    base = dict(
        race_id="202605021711", name="テストS", grade="OP", venue="東京", race_no=11,
        date=RACE_DATE, surface="芝", distance=1800, condition="良", field_size=10,
    )
    base.update(kw)
    return RaceInfo(**base)


def make_run(days_ago, finish, field=16, corner=8, last3f=34.5,
             pace=(36.0, 35.0), distance=1800, venue="東京", condition="良",
             surface="芝", grade="OP", jockey="騎手A", weight=55.0):
    return PastRun(
        date=RACE_DATE - dt.timedelta(days=days_ago),
        venue=venue, race_name="前哨戦", grade=grade, field_size=field,
        umaban=corner, odds=10.0, popularity=5, finish=finish, jockey=jockey,
        weight_carried=weight, surface=surface, distance=distance,
        condition=condition, margin=0.3, corners=[corner, corner],
        pace_first=pace[0], pace_last=pace[1], last3f=last3f,
    )


def make_horse(umaban=1, odds=10.0, popularity=5, runs=None, **kw):
    return Horse(
        umaban=umaban, name=f"馬{umaban}", horse_id=f"H{umaban}", waku=umaban,
        weight_carried=55.0, jockey="騎手A", odds=odds, popularity=popularity,
        past_runs=runs if runs is not None else [make_run(30 * i + 30, 3) for i in range(5)],
        **kw,
    )


# ---------------------------------------------------------------- 脚質判定
def test_detect_style_front_runner():
    horse = make_horse(runs=[make_run(30 * i + 30, 2, corner=1) for i in range(4)])
    style, conf, pos = detect_style(horse)
    assert style == NIGE
    assert conf > 0.5
    assert pos < 0.1


def test_detect_style_closer():
    horse = make_horse(runs=[make_run(30 * i + 30, 4, field=16, corner=15) for i in range(4)])
    style, _, pos = detect_style(horse)
    assert style == OIKOMI
    assert pos > 0.8


def test_detect_style_without_corner_data():
    run = make_run(30, 3)
    run.corners = []
    assert detect_style(make_horse(runs=[run]))[0] == "不明"


# ---------------------------------------------------------------- ペース予想
def test_pace_is_slow_without_front_runners():
    horses = [make_horse(i, runs=[make_run(30, 5, corner=14)]) for i in range(1, 11)]
    styles = {h.umaban: detect_style(h) for h in horses}
    pace = forecast_pace(horses, make_race(), styles)
    assert pace.nige_count == 0
    assert pace.front_advantage > 0.5
    assert "スロー" in pace.label


def test_pace_is_high_with_many_front_runners():
    horses = [make_horse(i, runs=[make_run(30, 5, corner=1)]) for i in range(1, 11)]
    styles = {h.umaban: detect_style(h) for h in horses}
    pace = forecast_pace(horses, make_race(), styles)
    assert pace.nige_count >= 4
    assert pace.front_advantage < 0
    assert "ハイペース" in pace.label


def test_pace_is_average_when_many_stalkers_but_no_pacesetter():
    """逃げ宣言馬が不在でも、先行タイプが密集していればスローとは見ない。"""
    horses = [make_horse(i, runs=[make_run(30, 5, corner=5)]) for i in range(1, 11)]
    styles = {h.umaban: detect_style(h) for h in horses}
    pace = forecast_pace(horses, make_race(), styles)
    assert pace.nige_count == 0
    assert pace.senko_count == 10
    assert pace.label == "平均ペース"


# ---------------------------------------------------------------- 能力スコア
def _evaluate(horse, race=None, bias=None, pace=None, condition="良", field=10):
    race = race or make_race()
    pace = pace or PaceForecast()
    return evaluate_horse(horse, race, bias or TrackBias(), pace,
                          detect_style(horse), condition, field)


def test_ability_rewards_better_recent_form():
    strong = _evaluate(make_horse(runs=[make_run(30 * i + 30, 1) for i in range(5)]))
    weak = _evaluate(make_horse(runs=[make_run(30 * i + 30, 14) for i in range(5)]))
    assert strong.ability > weak.ability
    assert 0 <= weak.ability <= 100


def test_long_layoff_is_penalised():
    fresh = make_horse(runs=[make_run(35, 3), make_run(80, 3), make_run(130, 4)])
    rusty = make_horse(runs=[make_run(400, 3), make_run(445, 3), make_run(495, 4)])
    assert _evaluate(rusty).ability < _evaluate(fresh).ability
    assert any("休養" in name or "休み明け" in name for name, _ in _evaluate(rusty).adjustments)


def test_class_step_up_is_penalised():
    horse = make_horse(runs=[make_run(30 * i + 30, 2, grade="1勝") for i in range(4)])
    up = _evaluate(horse, race=make_race(grade="G2"))
    assert any(name == "昇級初戦" for name, _ in up.adjustments)


def test_position_adjusted_agari_does_not_punish_front_runners():
    """逃げ馬は上がりが平凡でも、位置取り補正で不当に減点されない。"""
    leader = make_horse(runs=[make_run(30 * i + 30, 3, corner=1, last3f=35.0) for i in range(4)])
    closer = make_horse(runs=[make_run(30 * i + 30, 3, field=16, corner=15, last3f=34.1)
                              for i in range(4)])
    assert abs(_evaluate(leader).components["agari"] - _evaluate(closer).components["agari"]) < 12


def test_bias_shifts_scores_in_expected_direction():
    front = make_horse(1, runs=[make_run(30 * i + 30, 3, corner=1) for i in range(4)])
    neutral = _evaluate(front)
    helped = _evaluate(front, bias=TrackBias(front=0.8),
                       pace=PaceForecast(front_advantage=0.5))
    hurt = _evaluate(front, bias=TrackBias(front=-0.8),
                     pace=PaceForecast(front_advantage=-0.5))
    assert helped.ability > neutral.ability > hurt.ability


def test_draw_bias_favours_inner_horses():
    runs = [make_run(30 * i + 30, 4) for i in range(4)]
    inner = _evaluate(make_horse(1, runs=runs), bias=TrackBias(inner=0.8), field=16)
    outer = _evaluate(make_horse(16, runs=runs), bias=TrackBias(inner=0.8), field=16)
    assert inner.ability > outer.ability


def test_horse_without_form_gets_provisional_score():
    ev = _evaluate(make_horse(runs=[]))
    assert ev.ability == 45.0
    assert any("暫定" in r.text for r in ev.reasons)


# ---------------------------------------------------------------- 市場評価
def test_market_scores_match_ability_dispersion():
    evs = []
    for i, odds in enumerate([2.0, 4.0, 8.0, 16.0, 32.0, 64.0], start=1):
        ev = HorseEvaluation(horse=make_horse(i, odds=odds, popularity=i))
        ev.ability = 50.0 + i          # 意図的にばらけさせる
        evs.append(ev)
    apply_market_scores(evs)

    abilities = [e.ability for e in evs]
    markets = [e.market for e in evs]
    mean_a = sum(abilities) / len(abilities)
    mean_m = sum(markets) / len(markets)
    assert abs(mean_a - mean_m) < 1.0          # 平均が揃っている
    # 人気順に市場評価が単調減少する
    assert markets == sorted(markets, reverse=True)
    assert abs(sum(e.implied_prob for e in evs) - 1.0) < 1e-9


def test_market_score_without_odds_falls_back_to_ability():
    evs = [HorseEvaluation(horse=make_horse(1, odds=None))]
    evs[0].ability = 61.0
    apply_market_scores(evs)
    assert evs[0].market == 61.0


# ---------------------------------------------------------------- 穴指数
def test_dark_index_rewards_undervalued_horses():
    evs = []
    for i in range(1, 5):
        ev = HorseEvaluation(horse=make_horse(i))
        ev.ability, ev.market = 60.0, 60.0
        evs.append(ev)
    evs[0].ability = 75.0      # 能力は高いが人気がない
    evs[0].market = 45.0
    compute_dark_index(evs)
    assert evs[0].dark_index > evs[1].dark_index
    assert all(0 <= e.dark_index <= 100 for e in evs)


# ---------------------------------------------------------------- 荒れ度
def _chaos_for(odds_list, race=None, bias=None):
    race = race or make_race(field_size=len(odds_list))
    evs = []
    for i, odds in enumerate(odds_list, start=1):
        ev = HorseEvaluation(horse=make_horse(i, odds=odds, popularity=i))
        ev.ability = 60.0
        evs.append(ev)
    apply_market_scores(evs)
    compute_dark_index(evs)
    return compute_chaos(evs, race, bias or TrackBias(), PaceForecast())


def test_dominant_favorite_lowers_chaos():
    solid, _, _ = _chaos_for([1.2, 6.0, 12.0, 20.0, 40.0, 60.0, 80.0, 100.0])
    wide, _, _ = _chaos_for([6.5, 7.0, 8.0, 9.0, 11.0, 13.0, 15.0, 18.0])
    assert solid < wide
    assert 12.0 <= solid <= 88.0 and 12.0 <= wide <= 88.0


def test_handicap_and_wet_track_raise_chaos():
    flat, _, _ = _chaos_for([2.0, 5.0, 8.0, 15.0, 30.0, 50.0])
    rough, _, _ = _chaos_for(
        [2.0, 5.0, 8.0, 15.0, 30.0, 50.0],
        race=make_race(weight_rule="ハンデ", condition="不良", field_size=6),
        bias=TrackBias(condition_override="不良"),
    )
    assert rough > flat


def test_chaos_factors_sum_to_result():
    chaos, label, factors = _chaos_for([2.0, 5.0, 8.0, 15.0, 30.0, 50.0])
    assert abs(chaos - (BASE_RATE + sum(f.delta for f in factors))) < 0.11
    assert label


# ---------------------------------------------------------------- 全体
def test_analyze_race_outputs_one_dark_horse_when_solid():
    """堅いと判定したレースでは穴馬候補は1頭。"""
    horses = [make_horse(1, odds=1.1, popularity=1,
                         runs=[make_run(30 * i + 30, 1) for i in range(5)])]
    horses += [
        make_horse(i, odds=20.0 * i, popularity=i,
                   runs=[make_run(30 * j + 30, 10) for j in range(5)])
        for i in range(2, 9)
    ]
    a = analyze_race(make_race(grade="G1", field_size=8), horses)
    assert a.chaos_pct < CHAOS_THRESHOLD
    assert len(a.dark_horses) == 1


def test_analyze_race_outputs_three_dark_horses_when_wide_open():
    horses = []
    for i in range(1, 17):
        finish = 2 if i % 2 else 9
        horses.append(make_horse(i, odds=6.0 + i * 1.5, popularity=i,
                                 runs=[make_run(30 * j + 30, finish, corner=i)
                                       for j in range(5)]))
    a = analyze_race(make_race(weight_rule="ハンデ", field_size=16), horses)
    assert a.chaos_pct >= CHAOS_THRESHOLD
    assert len(a.dark_horses) == 3
    assert all((e.horse.popularity or 0) >= 5 or (e.horse.odds or 0) >= 9 for e in a.dark_horses)


def test_analysis_warns_when_odds_missing():
    horses = [make_horse(i, odds=None, popularity=None) for i in range(1, 7)]
    a = analyze_race(make_race(field_size=6), horses)
    assert any("オッズ" in w for w in a.warnings)


def test_scratched_horses_are_excluded_from_picks():
    horses = [make_horse(i, odds=3.0 * i, popularity=i) for i in range(1, 9)]
    horses[0].scratched = True
    a = analyze_race(make_race(field_size=8), horses)
    picked = a.dark_horses + a.favorites_pick + a.dangerous_favorites
    assert all(not e.horse.scratched for e in picked)


def test_bias_input_changes_the_analysis():
    horses = [
        make_horse(i, odds=4.0 + i * 2, popularity=i,
                   runs=[make_run(30 * j + 30, 4, corner=1 if i <= 4 else 14)
                         for j in range(4)])
        for i in range(1, 13)
    ]
    race = make_race(field_size=12)
    front_bias = analyze_race(race, horses, TrackBias(front=0.9))
    closer_bias = analyze_race(race, horses, TrackBias(front=-0.9))

    def ability(analysis, umaban):
        return next(e.ability for e in analysis.evaluations if e.horse.umaban == umaban)

    # 1番は逃げ・先行タイプ、12番は後方タイプ
    assert ability(front_bias, 1) > ability(closer_bias, 1)
    assert ability(closer_bias, 12) > ability(front_bias, 12)
    # 馬場傾向の説明が結果に残る
    assert "前残り" in front_bias.bias.describe()
    assert "差し有利" in closer_bias.bias.describe()
