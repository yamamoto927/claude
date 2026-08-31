"""荒れ度と評価に応じた買い目の組み立て。"""
from __future__ import annotations

from ..models import BetPlan, HorseEvaluation
from .darkhorse import composite


def _tag(e: HorseEvaluation) -> str:
    return f"{e.horse.umaban}{e.horse.name}"


def build_bets(
    chaos: float,
    favorites: list[HorseEvaluation],
    darks: list[HorseEvaluation],
    evaluations: list[HorseEvaluation],
    dangerous: list[HorseEvaluation] | None = None,
) -> list[BetPlan]:
    banned = {id(e) for e in (dangerous or [])}
    live = [e for e in evaluations if not e.horse.scratched]
    ranked = sorted(
        [e for e in live if id(e) not in banned], key=lambda e: -composite(e)
    ) or sorted(live, key=lambda e: -composite(e))
    plans: list[BetPlan] = []

    honmei = favorites[0] if favorites else (ranked[0] if ranked else None)
    if honmei is None:
        return plans

    top_group = [e for e in ranked[:4]]
    dark_tags = [_tag(e) for e in darks]

    if chaos < 43:
        plans.append(BetPlan(
            "単勝・複勝", f"{_tag(honmei)}",
            "堅い決着想定。軸の信頼度が高く、シンプルな券種で確度を取りに行く形。"))
        plans.append(BetPlan(
            "馬連 流し", f"{_tag(honmei)} → " + "、".join(_tag(e) for e in top_group[1:4]),
            "相手は上位評価3頭に絞る。"))
        if dark_tags:
            plans.append(BetPlan(
                "3連複 フォーメーション",
                f"1列目 {_tag(honmei)} / 2列目 " + "、".join(_tag(e) for e in top_group[1:4])
                + " / 3列目 " + "、".join(dark_tags),
                "配当妙味は3列目の穴馬で確保する。"))
    elif chaos < 60:
        plans.append(BetPlan(
            "馬連 ボックス",
            "、".join(_tag(e) for e in top_group[:3] + darks[:1]),
            "人気と伏兵を混ぜた中穴狙い。"))
        plans.append(BetPlan(
            "3連複 フォーメーション",
            f"1列目 {_tag(honmei)} / 2列目 " + "、".join(_tag(e) for e in top_group[1:4])
            + " / 3列目 " + "、".join(dark_tags or [_tag(e) for e in ranked[4:7]]),
            "軸1頭固定＋穴を3列目に置いて期待値を取る。"))
        if dark_tags:
            plans.append(BetPlan("複勝・ワイド", f"{dark_tags[0]} 絡み",
                                 "穴馬の複勝圏内をワイドで拾う保険。"))
    else:
        plans.append(BetPlan(
            "ワイド 流し",
            f"{dark_tags[0] if dark_tags else _tag(honmei)} → "
            + "、".join(_tag(e) for e in top_group[:3]),
            "波乱想定。穴馬を軸に、人気サイドとの組み合わせで的中率を確保。"))
        plans.append(BetPlan(
            "3連複 フォーメーション",
            "1列目 " + "、".join(dark_tags[:2] or [_tag(honmei)])
            + " / 2列目 " + "、".join(_tag(e) for e in top_group[:3])
            + " / 3列目 " + "、".join(
                _tag(e) for e in ranked[:8] if _tag(e) not in dark_tags[:2]),
            "穴馬を1列目に据えた高配当狙い。"))
        plans.append(BetPlan(
            "馬単・3連単 少点数",
            "、".join(dark_tags[:2]) + f" → {_tag(honmei)} 方向",
            "穴馬の勝ち切りまで見込む場合の上積み。点数は資金に応じて絞ること。"))
    return plans
