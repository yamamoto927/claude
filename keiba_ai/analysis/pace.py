"""脚質判定とレース展開(ペース)予想。"""
from __future__ import annotations

from ..models import (
    NIGE, OIKOMI, SASHI, SENKO, STYLE_VALUE, UNKNOWN_STYLE,
    Horse, PaceForecast, RaceInfo,
)

#: 直近走をどれだけ重く見るか
STYLE_WEIGHTS = [1.0, 0.85, 0.7, 0.55, 0.4]


def detect_style(horse: Horse, lookback: int = 5) -> tuple[str, float, float | None]:
    """脚質を (脚質名, 確信度0-1, 平均位置取り0-1) で返す。

    位置取りは 0.0=最前方、1.0=最後方。通過順が取れない馬は「不明」。
    """
    samples: list[tuple[float, float, bool]] = []
    for run, weight in zip(horse.recent[:lookback], STYLE_WEIGHTS):
        pos = run.early_position_rate
        if pos is None:
            continue
        led = bool(run.corners and run.corners[0] == 1)
        samples.append((pos, weight, led))
    if not samples:
        return UNKNOWN_STYLE, 0.0, None

    total_w = sum(w for _, w, _ in samples)
    avg = sum(p * w for p, w, _ in samples) / total_w
    led_ratio = sum(w for _, w, led in samples if led) / total_w

    if led_ratio >= 0.34 or avg <= 0.10:
        style = NIGE
    elif avg <= 0.35:
        style = SENKO
    elif avg <= 0.68:
        style = SASHI
    else:
        style = OIKOMI

    # サンプル数と位置のばらつきから確信度を決める
    spread = max(p for p, _, _ in samples) - min(p for p, _, _ in samples)
    confidence = min(1.0, len(samples) / 4.0) * (1.0 - min(0.6, spread * 0.7))
    return style, round(max(0.15, confidence), 2), round(avg, 3)


def forecast_pace(horses: list[Horse], race: RaceInfo, styles: dict[int, tuple[str, float, float | None]]) -> PaceForecast:
    """出走各馬の脚質構成からペースと前後有利を予想する。"""
    live = [h for h in horses if not h.scratched]
    n = len(live) or 1

    nige = [h for h in live if styles.get(h.umaban, (UNKNOWN_STYLE,))[0] == NIGE]
    senko = [h for h in live if styles.get(h.umaban, (UNKNOWN_STYLE,))[0] == SENKO]

    # 逃げ馬1頭 = 1.0、先行馬 = 0.35 として「前に行きたい圧力」を測る
    pressure = len(nige) + 0.35 * len(senko)
    # 頭数の影響を均すため 16 頭立て換算にする
    pressure_norm = pressure * (16.0 / n)

    if len(nige) == 0 and pressure_norm >= 5.0:
        label, front_adv = "平均ペース", -0.1
        comment = ("明確な逃げ馬は不在だが先行タイプが多く、ハナ争いは起こりそう。"
                   "隊列が決まるまでに脚を使う馬が出る。")
    elif len(nige) == 0 and pressure_norm >= 3.0:
        label, front_adv = "ややスロー", 0.45
        comment = "明確な逃げ馬が不在。先手を取った馬がそのまま運べる形になりやすい。"
    elif len(nige) == 0:
        label, front_adv = "スローペース濃厚", 0.75
        comment = "明確な逃げ馬が不在。先手を取った馬がそのまま楽に運ぶ形になりやすく、前残りを警戒。"
    elif len(nige) == 1 and pressure_norm < 3.2:
        label, front_adv = "ややスロー", 0.45
        comment = f"逃げ馬は{nige[0].name}のみ。ハナを主張する馬が少なく、隊列は落ち着きそう。"
    elif pressure_norm < 5.0:
        label, front_adv = "平均ペース", 0.0
        comment = "先行争いは適度。極端な展開にはなりにくく、力どおりの決着になりやすい。"
    elif pressure_norm < 6.8:
        label, front_adv = "ややハイペース", -0.45
        comment = "同型が複数。前がやり合う可能性が高く、中団以降から差してくる馬に出番がある。"
    else:
        label, front_adv = "ハイペース濃厚", -0.8
        comment = "逃げ・先行タイプが密集。潰し合いから展開が向く差し・追込勢を重視したい。"

    # 短距離は前が止まりにくく、長距離は落ち着きやすい
    if race.distance:
        if race.distance <= 1200:
            front_adv += 0.15
        elif race.distance >= 2400:
            front_adv += 0.1
    if race.surface == "ダ":
        front_adv += 0.15   # ダートは総じて前有利
    front_adv = max(-1.0, min(1.0, front_adv))

    return PaceForecast(
        label=label,
        nige_count=len(nige),
        senko_count=len(senko),
        pressure=round(pressure_norm, 2),
        front_advantage=round(front_adv, 2),
        comment=comment,
        key_horses=[f"{h.umaban} {h.name}" for h in nige + senko][:5],
    )


def style_value(style: str) -> float:
    return STYLE_VALUE.get(style, 0.0)
