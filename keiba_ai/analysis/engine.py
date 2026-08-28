"""分析全体のオーケストレーション。"""
from __future__ import annotations

from ..models import Horse, RaceAnalysis, RaceInfo, TrackBias
from .betting import build_bets
from .chaos import compute_chaos
from .darkhorse import (
    compute_dark_index, pick_dangerous_favorites, pick_dark_horses, pick_favorites,
)
from .features import apply_market_scores, evaluate_horse
from .pace import detect_style, forecast_pace

#: この値以上を「荒れる」と判定する(単位: %)
CHAOS_THRESHOLD = 50.0


def analyze_race(
    race: RaceInfo,
    horses: list[Horse],
    bias: TrackBias | None = None,
) -> RaceAnalysis:
    bias = bias or TrackBias()
    condition = bias.condition_override or race.condition or "良"
    live = [h for h in horses if not h.scratched]
    field_size = len(live) or (race.field_size or len(horses))

    styles = {h.umaban: detect_style(h) for h in horses}
    pace = forecast_pace(horses, race, styles)

    evaluations = [
        evaluate_horse(h, race, bias, pace, styles[h.umaban], condition, field_size)
        for h in horses
    ]
    apply_market_scores(evaluations)
    mean_ability = compute_dark_index(evaluations)

    chaos, label, factors = compute_chaos(evaluations, race, bias, pace)

    # 荒れると判定したら3頭、堅いと判定したら1頭
    dark_limit = 3 if chaos >= CHAOS_THRESHOLD else 1
    darks = pick_dark_horses(evaluations, dark_limit, mean_ability)
    dangerous = pick_dangerous_favorites(evaluations)
    favorites = pick_favorites(evaluations, 2, exclude=dangerous)
    bets = build_bets(chaos, favorites, darks, evaluations, dangerous)

    warnings: list[str] = []
    if not any(h.odds for h in live):
        warnings.append(
            "単勝オッズを取得できていないため、市場評価は全馬同一として扱っている。"
            "荒れ度・穴指数の精度は大きく落ちる。"
        )
    no_form = [h.name for h in live if not h.recent]
    if no_form:
        warnings.append(f"過去走データが取得できなかった馬: {'、'.join(no_form)}(暫定評価)")
    if bias.is_empty:
        warnings.append("馬場傾向の入力がないため、当日の馬場補正は行っていない。")
    if not race.date:
        warnings.append("開催日を特定できず、休養間隔(ローテーション)の評価をスキップした。")

    return RaceAnalysis(
        race=race,
        bias=bias,
        pace=pace,
        evaluations=evaluations,
        chaos_pct=chaos,
        chaos_label=label,
        chaos_factors=factors,
        dark_horses=darks,
        favorites_pick=favorites,
        dangerous_favorites=dangerous,
        bets=bets,
        warnings=warnings,
    )
