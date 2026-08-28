"""「荒れる可能性」の算出。

ここでの“荒れる”の定義:
    **3着以内に単勝7番人気以下の馬が1頭以上入ること**

JRA 全体でのこの発生率はおおむね 48% 前後。これを基準値(base)として、
レースごとの材料で加減算する。
"""
from __future__ import annotations

import math

from ..models import ChaosFactor, HorseEvaluation, PaceForecast, RaceInfo, TrackBias

BASE_RATE = 48.0

CONTEXT_ADJ_NAMES = {"展開・馬場が味方", "展開・馬場が逆風", "枠順×馬場", "高速馬場適性", "タフな馬場適性"}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _entropy(probs: list[float]) -> float:
    probs = [p for p in probs if p > 0]
    if len(probs) < 2:
        return 0.0
    h = -sum(p * math.log(p) for p in probs)
    return h / math.log(len(probs))


def compute_chaos(
    evaluations: list[HorseEvaluation],
    race: RaceInfo,
    bias: TrackBias,
    pace: PaceForecast,
) -> tuple[float, str, list[ChaosFactor]]:
    live = [e for e in evaluations if not e.horse.scratched]
    ranked = sorted(
        [e for e in live if e.horse.popularity],
        key=lambda e: e.horse.popularity,
    ) or sorted(live, key=lambda e: -(e.horse.odds or 0))
    n = len(live) or 1
    factors: list[ChaosFactor] = []

    # 1) 1番人気のオッズ -----------------------------------------------
    fav_odds = ranked[0].horse.odds if ranked and ranked[0].horse.odds else None
    if fav_odds:
        delta = _clamp((math.log(fav_odds) - math.log(2.8)) * 22.0, -20.0, 20.0)
        factors.append(ChaosFactor(
            "1番人気の信頼度", round(delta, 1),
            f"1番人気{ranked[0].horse.name}は単勝{fav_odds:.1f}倍。"
            + ("抜けた存在で堅く収まりやすい。" if delta <= -8 else
               "人気馬が抜けきっておらず波乱の余地がある。" if delta >= 8 else
               "標準的な支持を集めている。")))

    # 2) オッズ分布の割れ方 ---------------------------------------------
    probs = [e.implied_prob for e in live if e.implied_prob > 0]
    if len(probs) >= 4:
        h = _entropy(probs)
        delta = _clamp((h - 0.88) * 120.0, -12.0, 12.0)
        factors.append(ChaosFactor(
            "オッズ分布", round(delta, 1),
            f"支持率のエントロピーは{h:.3f}。"
            + ("人気が上位数頭に集中している。" if delta <= -4 else
               "人気が広く割れており混戦模様。" if delta >= 4 else "標準的な分布。")))

    # 3) 上位人気の不安材料 ----------------------------------------------
    top = ranked[:3]
    risk_points = 0.0
    risk_texts: list[str] = []
    for e in top:
        neg = sum(-d for name, d in e.adjustments if d < 0)
        risk_points += neg
        if neg >= 3.0 and e.risks:
            risk_texts.append(f"{e.horse.popularity}番人気{e.horse.name}: {e.top_risks(1)[0]}")
    delta = _clamp(risk_points * 0.9 - 3.0, -4.0, 16.0)
    factors.append(ChaosFactor(
        "上位人気の不安材料", round(delta, 1),
        ("／".join(risk_texts) if risk_texts else "上位人気に目立った減点材料は見当たらない。")))

    # 4) 上位人気の能力が市場評価に追いついているか -----------------------
    gaps = [e.gap for e in top]
    if gaps:
        avg_gap = sum(gaps) / len(gaps)
        delta = _clamp(-avg_gap * 0.55, -8.0, 12.0)
        factors.append(ChaosFactor(
            "人気馬の実力評価", round(delta, 1),
            f"上位3頭の能力スコア－市場評価の平均は{avg_gap:+.1f}。"
            + ("人気に見合う実力がある。" if avg_gap >= 0 else "人気先行の面がある。")))

    # 5) 頭数 --------------------------------------------------------------
    delta = _clamp((n - 12) * 0.85, -5.0, 5.0)
    factors.append(ChaosFactor("頭数", round(delta, 1), f"{n}頭立て。"
                               + ("多頭数で紛れが生じやすい。" if delta > 1 else
                                  "少頭数で紛れは少ない。" if delta < -1 else "標準的な頭数。")))

    # 6) レース条件 ---------------------------------------------------------
    cond_delta = 0.0
    notes: list[str] = []
    if race.weight_rule == "ハンデ":
        cond_delta += 4.0
        notes.append("ハンデ戦は実力差が詰まりやすい")
    if race.grade in ("未勝利", "新馬"):
        cond_delta += 2.0
        notes.append("能力が固まっていないクラス")
    elif race.grade in ("1勝", "2勝"):
        cond_delta += 1.5
        notes.append("条件戦は力量差が小さい")
    elif race.grade in ("G1", "G2"):
        cond_delta -= 2.5
        notes.append("上級条件は地力が反映されやすい")
    if race.surface == "障":
        cond_delta += 5.0
        notes.append("障害戦はアクシデントの影響が大きい")
    if race.surface == "ダ" and race.distance and race.distance <= 1300:
        cond_delta += 2.0
        notes.append("ダート短距離は枠・展開の影響が大きい")
    if race.surface == "芝" and race.distance and race.distance <= 1200:
        cond_delta += 1.5
        notes.append("芝短距離はスタートと枠順の紛れが大きい")
    if cond_delta:
        factors.append(ChaosFactor("レース条件", round(_clamp(cond_delta, -6, 10), 1),
                                   "／".join(notes) or "特記なし"))

    # 7) 馬場状態 -----------------------------------------------------------
    cond = bias.condition_override or race.condition
    if cond in ("重", "不良"):
        factors.append(ChaosFactor("馬場状態", 5.0, f"{cond}馬場。適性差が大きく人気薄の台頭余地がある。"))
    elif cond == "稍重":
        factors.append(ChaosFactor("馬場状態", 2.0, "稍重。わずかに適性差が出る。"))

    # 8) 馬場傾向と人気馬の相性 ---------------------------------------------
    if bias.strength >= 0.15 and top:
        ctx = []
        for e in top:
            ctx.append(sum(d for name, d in e.adjustments if name in CONTEXT_ADJ_NAMES))
        avg_ctx = sum(ctx) / len(ctx)
        delta = _clamp(-avg_ctx * 1.1, -6.0, 9.0)
        factors.append(ChaosFactor(
            "馬場傾向と人気馬の相性", round(delta, 1),
            f"入力された馬場傾向({bias.describe()})に対し、上位人気3頭の適合度は平均{avg_ctx:+.1f}。"
            + ("人気馬に向く馬場。" if avg_ctx > 0.5 else
               "人気馬にとって不向きな馬場で、伏兵の台頭余地がある。" if avg_ctx < -0.5 else
               "大きな有利不利はない。")))

    # 9) 展開の極端さ ---------------------------------------------------------
    if abs(pace.front_advantage) >= 0.6:
        factors.append(ChaosFactor(
            "展開", round(3.0 * abs(pace.front_advantage), 1),
            f"{pace.label}。展開が極端になると人気どおりに決まりにくい。"))

    # 10) 有力な伏兵の数 -------------------------------------------------------
    mean_ability = (sum(e.ability for e in live) / len(live)) if live else 50.0
    dark_pool = [e for e in live
                 if (e.horse.popularity or 99) >= 5 and e.gap >= 5.0
                 and e.ability >= mean_ability]
    if dark_pool:
        delta = _clamp(len(dark_pool) * 2.4, 0.0, 9.0)
        names = "、".join(f"{e.horse.umaban}{e.horse.name}" for e in dark_pool[:3])
        factors.append(ChaosFactor("伏兵の層", round(delta, 1),
                                   f"能力が人気を上回る人気薄が{len(dark_pool)}頭({names}など)。"))

    total = BASE_RATE + sum(f.delta for f in factors)
    chaos = round(_clamp(total, 12.0, 88.0), 1)
    return chaos, chaos_label(chaos), factors


def chaos_label(pct: float) -> str:
    if pct < 30:
        return "堅い(上位人気での決着濃厚)"
    if pct < 43:
        return "やや堅い(人気サイド中心)"
    if pct < 57:
        return "標準(中穴まで警戒)"
    if pct < 72:
        return "波乱含み(穴馬にチャンスあり)"
    return "大波乱警戒(人気総崩れも)"
