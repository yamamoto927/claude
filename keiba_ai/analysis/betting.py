"""荒れ度と評価に応じた買い目の組み立て。

同じ馬が「軸」と「相手」の両方に並ぶ、ボックスに同じ馬が二度出る、といった
成立しない買い目を作らないよう、列ごとに使用済みの馬を除きながら組み立てる。
"""
from __future__ import annotations

from ..models import BetPlan, HorseEvaluation
from .darkhorse import composite


def _tag(e: HorseEvaluation) -> str:
    return f"{e.horse.umaban}{e.horse.name}"


def _tags(evs: list[HorseEvaluation]) -> str:
    return "、".join(_tag(e) for e in evs)


def _numbers(evs: list[HorseEvaluation]) -> list[int]:
    return [e.horse.umaban for e in evs]


def _take(pool: list[HorseEvaluation], exclude: list[HorseEvaluation], n: int) -> list[HorseEvaluation]:
    """``pool`` から ``exclude`` の馬を除いて先頭 ``n`` 頭を取る。"""
    blocked = {id(e) for e in exclude}
    out: list[HorseEvaluation] = []
    for e in pool:
        if id(e) in blocked or any(id(e) == id(o) for o in out):
            continue
        out.append(e)
        if len(out) >= n:
            break
    return out


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

    if chaos < 43:
        # --- 堅い: 本命を軸に確度を取る -----------------------------------
        partners = _take(ranked, [honmei], 3)
        plans.append(BetPlan(
            "単勝・複勝", _tag(honmei),
            "堅い決着想定。軸の信頼度が高く、シンプルな券種で確度を取りに行く形。",
            groups=[[honmei.horse.umaban]]))
        plans.append(BetPlan(
            "馬連 流し", f"{_tag(honmei)} → {_tags(partners)}",
            "相手は上位評価3頭に絞る。",
            groups=[[honmei.horse.umaban], _numbers(partners)]))
        third = _take(darks, [honmei], 3)
        if third:
            plans.append(BetPlan(
                "3連複 フォーメーション",
                f"1列目 {_tag(honmei)} / 2列目 {_tags(partners)} / 3列目 {_tags(third)}",
                "配当妙味は3列目の穴馬で確保する。",
                groups=[[honmei.horse.umaban], _numbers(partners), _numbers(third)]))

    elif chaos < 60:
        # --- 中間: 人気と伏兵を混ぜる --------------------------------------
        box = [honmei] + _take(ranked, [honmei], 2) + _take(darks, [honmei], 1)
        box = _take(box, [], len(box))          # 念のため重複を落とす
        plans.append(BetPlan(
            "馬連 ボックス", _tags(box),
            "人気と伏兵を混ぜた中穴狙い。",
            groups=[_numbers(box)]))
        partners = _take(ranked, [honmei], 3)
        third = _take(darks, [honmei], 3) or _take(ranked, [honmei] + partners, 3)
        plans.append(BetPlan(
            "3連複 フォーメーション",
            f"1列目 {_tag(honmei)} / 2列目 {_tags(partners)} / 3列目 {_tags(third)}",
            "軸1頭固定＋穴を3列目に置いて期待値を取る。",
            groups=[[honmei.horse.umaban], _numbers(partners), _numbers(third)]))
        if darks:
            wide_partners = _take(ranked, [darks[0]], 3)
            plans.append(BetPlan(
                "ワイド 流し", f"{_tag(darks[0])} → {_tags(wide_partners)}",
                "穴馬の複勝圏内をワイドで拾う保険。",
                groups=[[darks[0].horse.umaban], _numbers(wide_partners)]))

    else:
        # --- 波乱: 穴馬を軸に据える ----------------------------------------
        axis = darks[0] if darks else honmei
        partners = _take(ranked, [axis], 3)
        plans.append(BetPlan(
            "ワイド 流し", f"{_tag(axis)} → {_tags(partners)}",
            "波乱想定。穴馬を軸に、人気サイドとの組み合わせで的中率を確保。",
            groups=[[axis.horse.umaban], _numbers(partners)]))

        first = _take(darks, [], 2) or [honmei]
        second = _take(ranked, first, 3)
        # 3列目は手広く。1列目と重ならなければ2列目と重なってよい(組み合わせは自動で除かれる)
        third = _take(ranked, first, 8)
        plans.append(BetPlan(
            "3連複 フォーメーション",
            f"1列目 {_tags(first)} / 2列目 {_tags(second)} / 3列目 {_tags(third)}",
            "穴馬を1列目に据えた高配当狙い。",
            groups=[_numbers(first), _numbers(second), _numbers(third)]))

        head = _take(ranked, first, 1)
        if head:
            plans.append(BetPlan(
                "馬単・3連単 少点数",
                f"{_tags(first)} → {_tags(head)} 方向",
                "穴馬の勝ち切りまで見込む場合の上積み。点数は資金に応じて絞ること。",
                groups=[_numbers(first), _numbers(head)]))
    return plans
