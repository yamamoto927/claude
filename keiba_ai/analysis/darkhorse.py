"""穴馬の抽出と根拠づくり、危険な人気馬の抽出。"""
from __future__ import annotations

from ..models import HorseEvaluation, PaceForecast, RaceInfo, TrackBias

#: 穴馬とみなす下限(単勝オッズ or 人気)
DARK_MIN_ODDS = 9.0
DARK_MIN_POPULARITY = 5


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def compute_dark_index(evaluations: list[HorseEvaluation]) -> float:
    """穴指数(0〜100)を各馬に付与し、出走馬の平均能力を返す。

    「能力に対して人気が無い」ほど高くなるが、能力そのものが低い馬が
    上位に来ないよう、レース内での能力の相対位置も加味する。
    """
    live = [e for e in evaluations if not e.horse.scratched]
    mean_ability = sum(e.ability for e in live) / len(live) if live else 50.0
    for e in evaluations:
        if e.horse.scratched:
            e.dark_index = 0.0
            continue
        e.dark_index = round(
            _clamp(50.0 + 1.8 * e.gap + 0.30 * (e.ability - mean_ability)), 1
        )
    return mean_ability


def is_dark_candidate(e: HorseEvaluation) -> bool:
    if e.horse.scratched:
        return False
    odds = e.horse.odds or 0.0
    pop = e.horse.popularity or 99
    return odds >= DARK_MIN_ODDS or pop >= DARK_MIN_POPULARITY


def pick_dark_horses(
    evaluations: list[HorseEvaluation], limit: int, mean_ability: float = 50.0
) -> list[HorseEvaluation]:
    """穴指数の高い順に最大 ``limit`` 頭を返す。

    人気薄というだけの馬を拾わないよう、能力がレース平均から大きく
    離れていないことを条件に加える。
    """
    pool = [
        e for e in evaluations
        if is_dark_candidate(e) and e.ability >= mean_ability - 4.0
    ]
    pool.sort(key=lambda e: (-e.dark_index, -e.ability))
    picked = [e for e in pool if e.dark_index >= 56.0 or e.gap >= 4.0][:limit]
    if picked:
        return picked
    fallback = [e for e in evaluations if is_dark_candidate(e)]
    fallback.sort(key=lambda e: (-e.dark_index, -e.ability))
    return fallback[:1]


def composite(e: HorseEvaluation) -> float:
    """総合力。能力を主、市場(＝調教や厩舎情報など数値化できない材料の代理)を従とする。"""
    return 0.75 * e.ability + 0.25 * e.market


def pick_favorites(
    evaluations: list[HorseEvaluation],
    limit: int = 2,
    exclude: list[HorseEvaluation] | None = None,
) -> list[HorseEvaluation]:
    """本命・対抗を選ぶ。「危険な人気馬」と判定した馬は外す。"""
    banned = {id(e) for e in (exclude or [])}
    live = [e for e in evaluations if not e.horse.scratched and id(e) not in banned]
    live.sort(key=lambda e: -composite(e))
    return live[:limit]


def pick_dangerous_favorites(evaluations: list[HorseEvaluation]) -> list[HorseEvaluation]:
    """人気の割に評価できない馬(＝馬券の軸にしづらい馬)。"""
    out = []
    for e in evaluations:
        if e.horse.scratched or (e.horse.popularity or 99) > 4:
            continue
        risk_weight = sum(-d for _, d in e.adjustments if d < 0)
        if -e.gap >= 8.0 or risk_weight >= 6.0:
            out.append(e)
    out.sort(key=lambda e: (e.horse.popularity or 99, e.gap))
    return out[:3]


def summarize_reasons(
    e: HorseEvaluation, race: RaceInfo, pace: PaceForecast, bias: TrackBias
) -> list[str]:
    """穴馬としての根拠を、データを引用した文章で組み立てる。"""
    lines: list[str] = []
    h = e.horse
    c = e.components

    odds_txt = f"単勝{h.odds:.1f}倍" if h.odds else "オッズ不明"
    pop_txt = f"{h.popularity}番人気" if h.popularity else "人気不明"
    lines.append(
        f"市場評価{e.market:.0f}に対して能力スコア{e.ability:.0f}。"
        f"{pop_txt}({odds_txt})という評価は{abs(e.gap):.0f}ポイント"
        f"{'低すぎる' if e.gap > 0 else '高い'}。"
    )

    # 構成要素のうち突出しているものを引用する
    labels = {
        "form": "近走の着順内容", "best": "ベストパフォーマンス", "agari": "位置取り補正後の上がり",
        "fit_distance": f"{race.surface}{race.distance}m前後の距離適性",
        "fit_course": f"{race.venue}{race.surface}のコース実績",
        "fit_condition": f"{bias.condition_override or race.condition}馬場での実績",
        "class_fit": "経験クラスの格",
    }
    highlights = sorted(
        ((k, c[k]) for k in labels if k in c), key=lambda kv: -kv[1]
    )[:2]
    for key, val in highlights:
        if val >= 62:
            lines.append(f"{labels[key]}が{val:.0f}と高い。")

    lines.extend(e.top_reasons(3))

    risks = e.top_risks(1)
    if risks:
        lines.append(f"[注意] {risks[0]}")
    # 重複を除いて返す
    seen, out = set(), []
    for line in lines:
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out
