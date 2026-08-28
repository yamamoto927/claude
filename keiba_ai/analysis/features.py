"""1頭ごとの能力スコアリング。

「馬柱から読み取れる能力」と「オッズが示す市場評価」を別々に数値化し、
その差(＝過小評価の度合い)を穴指数の土台にする。
"""
from __future__ import annotations

import math

from ..models import (
    UNKNOWN_STYLE, Horse, HorseEvaluation, PaceForecast, PastRun, RaceInfo,
    Reason, TrackBias,
)
from .pace import style_value

RECENCY = [1.0, 0.82, 0.66, 0.52, 0.40, 0.30]
WET = ("稍重", "重", "不良")


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _weighted(values: list[tuple[float, float]]) -> float | None:
    """[(値, 重み)] の加重平均。"""
    total = sum(w for _, w in values)
    return sum(v * w for v, w in values) / total if total > 0 else None


def _subset_score(runs: list[PastRun], baseline: float = 50.0) -> tuple[float, int]:
    """部分集合の着順成績を 0〜100 に。サンプルが少ないほど 50 に寄せる。"""
    rates = [r.finish_rate for r in runs if r.finish_rate is not None]
    if not rates:
        return baseline, 0
    mean = sum(rates) / len(rates)
    shrink = len(rates) / (len(rates) + 1.5)
    return _clamp(50.0 + shrink * 90.0 * (mean - 0.5)), len(rates)


def _agari_residual(run: PastRun) -> float | None:
    """位置取りを補正した「純粋な末脚の速さ」。正なら優秀。"""
    edge = run.agari_edge
    pos = run.early_position_rate
    if edge is None:
        return None
    expected = 0.9 * (pos if pos is not None else 0.5)
    return round(edge - expected, 3)


def _pace_of(run: PastRun) -> float | None:
    """走破レースのペース。正=ハイペース、負=スローペース(秒)。"""
    if run.pace_first is None or run.pace_last is None:
        return None
    return round(run.pace_last - run.pace_first, 2)


# --------------------------------------------------------------------------
# 能力の構成要素
# --------------------------------------------------------------------------
def ability_components(horse: Horse, race: RaceInfo, condition: str) -> dict[str, float]:
    recent = horse.recent[:6]
    level = race.level

    # --- 近走成績(クラス補正つき) --------------------------------------
    pairs = []
    for run, w in zip(recent, RECENCY):
        rate = run.finish_rate
        if rate is None:
            continue
        pairs.append((rate + 0.055 * (run.level - level), w))
    form = _clamp(50.0 + 95.0 * ((_weighted(pairs) or 0.5) - 0.5)) if pairs else 45.0

    # --- ベストパフォーマンス(能力の天井) -------------------------------
    peaks = [
        (r.finish_rate or 0) + 0.075 * (r.level - level)
        for r in recent
        if r.finish_rate is not None
    ]
    best = _clamp(50.0 + 95.0 * (max(peaks) - 0.5)) if peaks else 45.0

    # --- 末脚(位置取り補正後) -------------------------------------------
    ag = [(res, w) for res, w in
          ((_agari_residual(r), w) for r, w in zip(recent, RECENCY)) if res is not None]
    agari = _clamp(50.0 + 30.0 * (_weighted(ag) or 0.0)) if ag else 50.0

    # --- 距離適性 --------------------------------------------------------
    dist_runs = [
        r for r in recent + horse.recent[6:12]
        if r.surface == race.surface and r.distance and race.distance
        and abs(r.distance - race.distance) <= 200
    ]
    fit_distance, n_dist = _subset_score(dist_runs)

    # --- コース適性 ------------------------------------------------------
    course_runs = [
        r for r in horse.recent[:12]
        if r.venue == race.venue and r.surface == race.surface
    ]
    fit_course, n_course = _subset_score(course_runs)

    # --- 馬場状態適性 ----------------------------------------------------
    if condition in WET:
        cond_runs = [r for r in horse.recent[:12] if r.condition in WET and r.surface == race.surface]
    else:
        cond_runs = [r for r in horse.recent[:12] if r.condition == "良" and r.surface == race.surface]
    fit_condition, n_cond = _subset_score(cond_runs)

    # --- クラス格 --------------------------------------------------------
    levels = [r.level for r in recent[:3]]
    class_edge = (sum(levels) / len(levels) - level) if levels else 0.0
    class_fit = _clamp(50.0 + 13.0 * class_edge)

    return {
        "form": round(form, 1),
        "best": round(best, 1),
        "agari": round(agari, 1),
        "fit_distance": round(fit_distance, 1),
        "fit_course": round(fit_course, 1),
        "fit_condition": round(fit_condition, 1),
        "class_fit": round(class_fit, 1),
        "n_distance": n_dist,
        "n_course": n_course,
        "n_condition": n_cond,
    }


BASE_WEIGHTS = {
    "form": 0.26,
    "best": 0.18,
    "agari": 0.16,
    "fit_distance": 0.13,
    "fit_course": 0.10,
    "fit_condition": 0.10,
    "class_fit": 0.07,
}


# --------------------------------------------------------------------------
# 状況補正(休養・斤量・クラス替わりなど)
# --------------------------------------------------------------------------
def situational_adjustments(
    horse: Horse, race: RaceInfo, comps: dict[str, float]
) -> tuple[list[tuple[str, float]], list[Reason], list[Reason]]:
    adjustments: list[tuple[str, float]] = []
    merits: list[Reason] = []
    risks: list[Reason] = []
    recent = horse.recent
    last = horse.last_run

    def add(name: str, delta: float, text: str, *, risk: bool = False, weight: float | None = None) -> None:
        adjustments.append((name, round(delta, 2)))
        r = Reason(text, abs(delta) if weight is None else weight)
        (risks if risk else merits).append(r)

    # --- 休養明け / ローテーション ---------------------------------------
    rest = horse.rest_days(race.date)
    if rest is not None:
        fresh_ok = any(
            r.finish is not None and r.finish <= 3
            for r, prev in zip(recent, recent[1:])
            if r.date and prev.date and (r.date - prev.date).days >= 90
        )
        if rest >= 365:
            add("長期休養明け", -6.0, f"{rest}日ぶりの実戦。長期離脱明けで仕上がりに不安。", risk=True)
        elif rest >= 180:
            add("休み明け", -4.0 if not fresh_ok else -1.5,
                f"{rest}日の休み明け。" + ("休養明けでも走る実績はある。" if fresh_ok else "叩き台の可能性。"),
                risk=not fresh_ok)
        elif rest >= 90:
            add("休み明け", -2.0 if not fresh_ok else 0.5,
                f"{rest}日ぶり。" + ("休養明けの実績あり。" if fresh_ok else "実戦間隔が開いた。"),
                risk=not fresh_ok)
        elif 21 <= rest <= 70:
            add("順調", 1.0, f"中{rest//7}週前後の順調なローテーション。")
        elif rest <= 13:
            add("連闘・詰まった間隔", -1.5, f"前走から{rest}日。反動が心配な詰まった使い方。", risk=True)

        if len(recent) >= 2 and recent[0].date and recent[1].date:
            prev_gap = (recent[0].date - recent[1].date).days
            if prev_gap >= 90 and rest <= 70:
                add("叩き2走目", 2.5, "休み明けを一度使われた上積みが見込める2走目。")

    # --- 斤量 ------------------------------------------------------------
    if horse.weight_carried and last and last.weight_carried:
        diff = horse.weight_carried - last.weight_carried
        if abs(diff) >= 0.5:
            delta = max(-3.0, min(3.0, -diff * 1.2))
            add("斤量変化", delta,
                f"斤量は前走{last.weight_carried:g}kg → 今回{horse.weight_carried:g}kg({diff:+g}kg)。",
                risk=diff > 0)
    if race.weight_rule == "ハンデ" and horse.weight_carried and horse.weight_carried <= 54.0:
        add("ハンデ恵まれ", 1.5, f"ハンデ戦で{horse.weight_carried:g}kgは恵まれた印象。")

    # --- 馬体重 ----------------------------------------------------------
    if horse.horse_weight_diff is not None and abs(horse.horse_weight_diff) >= 16:
        add("馬体重の大幅増減", -2.0,
            f"馬体重{horse.horse_weight_diff:+d}kgと大きく変動。", risk=True)

    # --- クラス替わり ------------------------------------------------------
    if recent:
        max_level = max(r.level for r in recent[:4])
        if race.level > max_level + 0.5:
            add("昇級初戦", -3.5, f"実質的な昇級戦(前走クラス {recent[0].grade or '条件戦'})。相手強化。", risk=True)
        elif max_level - race.level >= 1.0:
            good = any(r.level >= race.level + 1 and (r.finish_rate or 0) >= 0.6 for r in recent[:4])
            add("相手弱化", 3.0 if good else 1.5,
                f"格上のクラス({max(recent[:4], key=lambda r: r.level).grade})を経験。相手関係は楽になる。")

    # --- 距離延長・短縮 ---------------------------------------------------
    if last and last.distance and race.distance:
        diff = race.distance - last.distance
        has_record = comps["n_distance"] >= 1
        if abs(diff) >= 400 and not has_record:
            add("距離大幅変化", -2.0,
                f"前走{last.distance}m → 今回{race.distance}m({diff:+d}m)で当該距離の実績なし。", risk=True)
        elif abs(diff) >= 400:
            add("距離変化", -0.5, f"前走から{diff:+d}mの距離変化。")
    if comps["n_distance"] == 0 and race.distance:
        add("当該距離未経験", -1.5, f"{race.surface}{race.distance}m前後の出走歴がなく適性は未知数。", risk=True)
    if comps["n_course"] == 0 and race.venue:
        add("当該コース未経験", -0.8, f"{race.venue}{race.surface}は初出走。")

    # --- 騎手 --------------------------------------------------------------
    if last and last.jockey and horse.jockey:
        if last.jockey == horse.jockey:
            if (last.finish_rate or 0) >= 0.7:
                add("継続騎乗", 1.5, f"{horse.jockey}騎手が前走に続いて継続騎乗。手の内を知る。")
        else:
            add("乗り替わり", -0.5, f"{last.jockey} → {horse.jockey} へ乗り替わり。")

    # --- 前走の内容(着順に表れない部分) ------------------------------------
    if last and last.valid:
        residual = _agari_residual(last)
        rate = last.finish_rate or 0.0
        pace = _pace_of(last)
        pos = last.early_position_rate

        if residual is not None and residual >= 0.45 and rate < 0.55:
            add("前走は着順以上の内容", 4.0,
                f"前走({last.label()})は位置取りを考慮した実質上がりがメンバー平均比{residual:+.2f}秒。"
                "脚は使えており、着順ほど負けていない。", weight=4.5)
        if last.margin is not None and 0 < last.margin <= 0.4 and rate < 0.6:
            add("前走僅差", 1.5, f"前走は勝ち馬から{last.margin:.1f}秒差の僅差。展開ひとつで着順は入れ替わる。")
        if pace is not None and pos is not None:
            if pace <= -0.8 and pos >= 0.6 and rate >= 0.6:
                add("スロー克服", 3.0,
                    f"前走は前半{last.pace_first}-後半{last.pace_last}のスローペースを後方から差して好走。価値が高い。",
                    weight=3.5)
            if pace >= 0.8 and pos <= 0.3 and rate >= 0.6:
                add("ハイペース粘り", 3.0,
                    f"前走は{last.pace_first}-{last.pace_last}のハイペースを前々で粘っての好走。地力を示した。",
                    weight=3.5)
            if pace <= -1.0 and pos <= 0.2 and rate >= 0.8:
                add("前走は展開に恵まれた", -3.0,
                    f"前走は{last.pace_first}-{last.pace_last}のスローを楽に先行しての好走。展開の利があった可能性。",
                    risk=True, weight=3.0)
        if last.popularity and last.finish and last.popularity <= 3 and rate < 0.4:
            add("前走人気を裏切り", -1.0,
                f"前走は{last.popularity}番人気{last.finish}着と評価を裏切っている。", risk=True)

    # --- 安定感・実績 --------------------------------------------------------
    board = [r for r in recent[:5] if r.finish is not None and r.finish <= 5]
    if len(board) >= 4:
        add("安定感", 1.5, "近5走のうち4度以上で5着以内。大きく崩れない。")
    heavy = [r for r in horse.recent[:12] if r.level >= 8 and r.finish is not None and r.finish <= 5]
    if heavy and race.level < 8:
        add("重賞実績", 2.0, f"重賞({heavy[0].grade} {heavy[0].race_name})で{heavy[0].finish}着の実績。")

    return adjustments, merits, risks


# --------------------------------------------------------------------------
# 馬場傾向 / 展開による補正
# --------------------------------------------------------------------------
def context_adjustments(
    horse: Horse,
    race: RaceInfo,
    comps: dict[str, float],
    style: str,
    style_conf: float,
    bias: TrackBias,
    pace: PaceForecast,
    field_size: int,
) -> tuple[list[tuple[str, float]], list[Reason], list[Reason]]:
    adjustments: list[tuple[str, float]] = []
    merits: list[Reason] = []
    risks: list[Reason] = []

    def add(name, delta, text, *, risk=False, weight=None):
        if abs(delta) < 0.25:
            return
        adjustments.append((name, round(delta, 2)))
        r = Reason(text, abs(delta) if weight is None else weight)
        (risks if risk else merits).append(r)

    # 展開(6割)と当日の馬場傾向(4割)を合成した「実効的な前後有利」
    effective_front = 0.6 * pace.front_advantage + 0.4 * bias.front * bias.confidence
    sv = style_value(style)
    if style != UNKNOWN_STYLE:
        delta = effective_front * sv * 7.0 * max(0.4, style_conf)
        if delta > 0:
            add("展開・馬場が味方", delta,
                f"脚質は{style}。{pace.label}想定"
                + (f"＋馬場も{'前残り' if bias.front > 0 else '差し有利'}傾向" if abs(bias.front) >= 0.2 else "")
                + "で、この馬の位置取りは有利に働く。", weight=delta + 1.0)
        elif delta < 0:
            add("展開・馬場が逆風", delta,
                f"脚質は{style}。{pace.label}想定で展開が向きにくい。", risk=True, weight=-delta + 0.5)

    # 枠順 × 内外バイアス
    if horse.umaban and field_size > 1 and abs(bias.inner) >= 0.15:
        draw_pos = (horse.umaban - 1) / (field_size - 1)
        delta = bias.inner * (1 - 2 * draw_pos) * 5.0 * bias.confidence
        side = "内" if bias.inner > 0 else "外"
        mine = "内" if draw_pos < 0.5 else "外"
        add("枠順×馬場", delta,
            f"{side}有利の馬場に対して{horse.umaban}番({mine}枠寄り)。"
            + ("枠の利を活かせる。" if delta > 0 else "枠は割引材料。"),
            risk=delta < 0)

    # 時計(高速/タフ)への適性
    if abs(bias.speed) >= 0.15:
        sharpness = (comps["agari"] - 50.0) / 50.0        # 上がりの速さ
        stamina = (comps["fit_condition"] - 50.0) / 50.0  # 当日馬場状態への実績
        delta = bias.speed * sharpness * 4.0 * bias.confidence
        delta += (-bias.speed) * stamina * 3.0 * bias.confidence
        if bias.speed > 0:
            add("高速馬場適性", delta,
                "高速決着想定。切れる脚を使えるタイプで、時計勝負は歓迎。" if delta > 0
                else "高速決着想定だが、瞬発力勝負では分が悪い。", risk=delta < 0)
        else:
            add("タフな馬場適性", delta,
                "時計のかかる馬場で、消耗戦への適性が高い。" if delta > 0
                else "時計のかかる馬場は本来の持ち味を削がれる。", risk=delta < 0)

    return adjustments, merits, risks


# --------------------------------------------------------------------------
# 総合
# --------------------------------------------------------------------------
def evaluate_horse(
    horse: Horse,
    race: RaceInfo,
    bias: TrackBias,
    pace: PaceForecast,
    style_info: tuple[str, float, float | None],
    condition: str,
    field_size: int,
) -> HorseEvaluation:
    style, style_conf, _ = style_info
    comps = ability_components(horse, race, condition)
    base = sum(comps[k] * w for k, w in BASE_WEIGHTS.items())

    adj_s, merit_s, risk_s = situational_adjustments(horse, race, comps)
    adj_c, merit_c, risk_c = context_adjustments(
        horse, race, comps, style, style_conf, bias, pace, field_size
    )
    adjustments = adj_s + adj_c
    ability = _clamp(base + sum(d for _, d in adjustments))

    if not horse.recent:
        ability = 45.0
        merit_s.append(Reason("出走歴のデータが無く、能力は暫定値(45)で評価している。", 0.1))

    ev = HorseEvaluation(
        horse=horse,
        ability=round(ability, 1),
        style=style,
        style_confidence=style_conf,
        components=comps,
        adjustments=adjustments,
        reasons=merit_s + merit_c,
        risks=risk_s + risk_c,
    )
    ev.components["base"] = round(base, 1)
    return ev


def apply_market_scores(evaluations: list[HorseEvaluation]) -> None:
    """単勝オッズを「市場が示唆する能力スコア」に換算する。

    オッズ(対数支持率)の分布を、そのレースの能力スコアの平均・標準偏差に
    合わせて写像する。こうすると ``ability - market`` が
    「市場評価に対して能力がどれだけ上回っているか」を素直に表す。
    生の対数オッズをそのまま 0〜100 に伸ばすと分散が能力側より遥かに大きく、
    単に人気薄なだけの馬が上位に来てしまうため、この正規化が要になる。
    """
    live = [e for e in evaluations if not e.horse.scratched and e.horse.odds]
    if len(live) < 2:
        for e in evaluations:
            e.market, e.implied_prob = e.ability, 0.0
        return

    raw = {id(e): 1.0 / e.horse.odds for e in live}
    total = sum(raw.values())
    for e in live:
        e.implied_prob = raw[id(e)] / total

    logs = [math.log(e.implied_prob) for e in live]
    mu_l = sum(logs) / len(logs)
    sd_l = math.sqrt(sum((x - mu_l) ** 2 for x in logs) / len(logs)) or 1.0

    abilities = [e.ability for e in live]
    mu_a = sum(abilities) / len(abilities)
    sd_a = math.sqrt(sum((x - mu_a) ** 2 for x in abilities) / len(abilities))
    sd_a = max(5.0, sd_a)

    for e in live:
        z = (math.log(e.implied_prob) - mu_l) / sd_l
        e.market = round(_clamp(mu_a + z * sd_a), 1)
    for e in evaluations:
        if e not in live:
            e.market, e.implied_prob = e.ability, 0.0
