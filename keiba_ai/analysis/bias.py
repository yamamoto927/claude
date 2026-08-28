"""ユーザーが入力する「当日の馬場傾向」を数値化する。

自然文(例:「内有利で前残り、時計はかなり速い」)を
``TrackBias(inner=+0.8, front=+0.8, speed=+1.0)`` のような連続値に変換する。

* 3軸: ``inner``(内外) / ``front``(前後) / ``speed``(時計)
* いずれも -1.0 〜 +1.0
* 「かなり」「やや」などの修飾語は、直後のキーワードだけに掛かる
"""
from __future__ import annotations

import re

from ..models import TrackBias

Effects = list[tuple[str, float]]

#: (正規表現, [(軸, 値), ...])。具体的な表現ほど先に置く。
RULES: list[tuple[str, Effects]] = [
    # --- 複合表現 -------------------------------------------------------
    (r"外[のがはも]?差し[がはも]?(決ま|有利|届|伸び)", [("inner", -0.8), ("front", -0.5)]),
    (r"大外一気", [("inner", -0.5), ("front", -0.8)]),
    (r"内(を)?先行(が)?有利", [("inner", 0.7), ("front", 0.7)]),
    (r"イン(を)?突", [("inner", 0.7)]),
    (r"内[がはも]?荒れ", [("inner", -0.8)]),
    (r"内[がはも]?伸びな", [("inner", -0.7)]),
    (r"前[がはも]?止まらな", [("front", 0.9)]),
    (r"前[がはも]?止ま[るり]", [("front", -0.8)]),
    (r"前[がはも]?崩れ", [("front", -0.8)]),
    # --- 内外 -----------------------------------------------------------
    (r"最内", [("inner", 0.9)]),
    (r"内ラチ", [("inner", 0.9)]),
    (r"ラチ沿い", [("inner", 0.8)]),
    (r"(内|イン|内枠)[がはも]?(有利|良[いく]|伸び|決ま|残)", [("inner", 0.8)]),
    (r"(外|外枠)[がはも]?(有利|良[いく]|伸び|決ま)", [("inner", -0.8)]),
    (r"(内|イン|内枠)[がはも]?(不利|悪い)", [("inner", -0.8)]),
    (r"(外|外枠)[がはも]?不利", [("inner", 0.6)]),
    (r"四分どころ", [("inner", -0.4)]),
    (r"内目", [("inner", 0.4)]),
    (r"外目", [("inner", -0.4)]),
    # --- 脚質 -----------------------------------------------------------
    (r"前残り", [("front", 0.8)]),
    (r"逃げ[がはも]?(有利|残|決ま)", [("front", 0.9)]),
    (r"先行[がはも]?(有利|残|決ま)", [("front", 0.7)]),
    (r"前[がはも]?(有利|残)", [("front", 0.8)]),
    (r"(差し|捲り|マクリ)[がはも]?(有利|決ま|届|利く)", [("front", -0.8)]),
    (r"(追込|追い込み)[がはも]?(有利|決ま|届)", [("front", -0.9)]),
    (r"後方一気", [("front", -0.8)]),
    (r"末脚勝負", [("front", -0.6)]),
    (r"上がり勝負", [("front", -0.4), ("speed", 0.5)]),
    (r"差し", [("front", -0.5)]),
    (r"追込", [("front", -0.6)]),
    (r"先行", [("front", 0.5)]),
    (r"逃げ", [("front", 0.6)]),
    # --- 時計 -----------------------------------------------------------
    (r"超高速", [("speed", 1.0)]),
    (r"高速馬場", [("speed", 0.9)]),
    (r"時計[がはも]?[^。、\s]{0,4}(速|早)い", [("speed", 0.8)]),
    (r"時計[がはも]?[^。、\s]{0,4}かか", [("speed", -0.8)]),
    (r"(軽|かる)い馬場", [("speed", 0.7)]),
    (r"レコード", [("speed", 0.8)]),
    (r"時計[がはも]?[^。、\s]{0,4}遅い", [("speed", -0.7)]),
    (r"タフな?馬場", [("speed", -0.8)]),
    (r"(重|おも)い馬場", [("speed", -0.7)]),
    (r"荒れ馬場", [("speed", -0.6), ("inner", -0.4)]),
    (r"消耗戦", [("speed", -0.6)]),
    (r"パワー", [("speed", -0.6)]),
    (r"道悪", [("speed", -0.7)]),
    (r"洋芝", [("speed", -0.4)]),
    (r"タフ", [("speed", -0.6)]),
]

#: 馬場状態そのものの指定
CONDITION_WORDS = [
    ("不良", "不良"), ("重馬場", "重"), ("稍重", "稍重"), ("やや重", "稍重"), ("良馬場", "良"),
]

#: 強弱の修飾語(直前 8 文字以内にあれば効く)
INTENSIFIERS = [
    ("極端", 1.4), ("強烈", 1.35), ("かなり", 1.25), ("非常に", 1.25), ("とても", 1.2),
    ("やや", 0.6), ("少し", 0.6), ("若干", 0.55), ("わずか", 0.5), ("多少", 0.6),
    ("気持ち", 0.5),
]

AXES = ("inner", "front", "speed")


def _intensity(text: str, start: int, end: int) -> float:
    """直前 8 文字＋マッチ範囲内に修飾語があれば、その係数を返す。"""
    window = text[max(0, start - 8):end]
    for word, factor in INTENSIFIERS:
        if word in window:
            return factor
    return 1.0


def parse_bias_text(text: str, confidence: float = 1.0) -> TrackBias:
    """自然文の馬場傾向メモを ``TrackBias`` に変換する。"""
    bias = TrackBias(raw=text or "", confidence=max(0.0, min(1.0, confidence)))
    if not text:
        return bias

    normalized = text.replace("、", " ").replace("。", " ").replace("　", " ")
    mask = list(normalized)   # 二重カウント防止のため、消費した文字を空白に置き換える
    hits: dict[str, list[float]] = {a: [] for a in AXES}

    for pattern, effects in RULES:
        for m in re.finditer(pattern, "".join(mask)):
            scale = _intensity(normalized, m.start(), m.end())
            for axis, value in effects:
                hits[axis].append(max(-1.0, min(1.0, value * scale)))
                bias.notes.append(f"「{m.group(0)}」→ {axis} {value * scale:+.2f}")
            for i in range(m.start(), m.end()):
                mask[i] = " "

    for axis, values in hits.items():
        if not values:
            continue
        mean = sum(values) / len(values)
        boost = 1.0 + 0.15 * (len(values) - 1)     # 同方向の表現が重なれば強める
        setattr(bias, axis, round(max(-1.0, min(1.0, mean * boost)), 3))

    for word, cond in CONDITION_WORDS:
        if word in normalized:
            bias.condition_override = cond
            break

    # 数値の直接指定: "inner=0.5" など
    for axis in AXES:
        m = re.search(rf"{axis}\s*=\s*([-+]?\d*\.?\d+)", normalized)
        if m:
            setattr(bias, axis, max(-1.0, min(1.0, float(m.group(1)))))
            bias.notes.append(f"{axis} を明示指定 {m.group(1)}")
    return bias


def build_bias(
    text: str | None = None,
    inner: float | None = None,
    front: float | None = None,
    speed: float | None = None,
    condition: str | None = None,
    confidence: float = 1.0,
) -> TrackBias:
    """自然文と数値指定をマージして ``TrackBias`` を作る(数値指定が優先)。"""
    bias = parse_bias_text(text or "", confidence=confidence)
    if inner is not None:
        bias.inner = max(-1.0, min(1.0, inner))
    if front is not None:
        bias.front = max(-1.0, min(1.0, front))
    if speed is not None:
        bias.speed = max(-1.0, min(1.0, speed))
    if condition:
        bias.condition_override = condition
    return bias


_SCALE_CHOICES = {
    "inner": ["外有利", "やや外有利", "フラット", "やや内有利", "内有利"],
    "front": ["差し・追込有利", "やや差し有利", "フラット", "やや前有利", "前残り"],
    "speed": ["時計がかかる", "やや時計がかかる", "標準", "やや高速", "高速馬場"],
}
_SCALE_VALUES = [-0.8, -0.4, 0.0, 0.4, 0.8]
_CONFIDENCE = {"1": 0.4, "2": 0.7, "3": 1.0}


def prompt_bias(input_fn=input, output_fn=print) -> TrackBias:
    """対話形式で馬場傾向を聞き取る。"""
    output_fn("=== 当日の馬場傾向を入力してください ===")
    output_fn("例: 「内有利で前残り、時計はかなり速い」「外差しが決まる荒れ馬場」")
    output_fn("空欄のまま Enter を押すと選択式に切り替わります。")
    text = input_fn("馬場傾向 > ").strip()
    if text:
        bias = parse_bias_text(text)
        cf = input_fn("この傾向の確信度 [1:低 2:中 3:高](既定3) > ").strip()
        bias.confidence = _CONFIDENCE.get(cf, 1.0)
        output_fn(f"→ 解釈: {bias.describe()}")
        return bias

    bias = TrackBias()
    titles = {"inner": "内外の伸び", "front": "有利な脚質", "speed": "時計の出方"}
    for axis, labels in _SCALE_CHOICES.items():
        output_fn(f"\n[{titles[axis]}]")
        for i, label in enumerate(labels, 1):
            output_fn(f"  {i}. {label}")
        ans = input_fn("番号(既定3) > ").strip()
        idx = int(ans) - 1 if ans.isdigit() and 1 <= int(ans) <= 5 else 2
        setattr(bias, axis, _SCALE_VALUES[idx])
        bias.notes.append(f"{titles[axis]}: {labels[idx]}")
    cond = input_fn("\n馬場状態(良/稍重/重/不良、空欄ならサイトの値を使用) > ").strip()
    if cond:
        bias.condition_override = cond
    cf = input_fn("確信度 [1:低 2:中 3:高](既定3) > ").strip()
    bias.confidence = _CONFIDENCE.get(cf, 1.0)
    bias.raw = " / ".join(bias.notes)
    output_fn(f"→ 解釈: {bias.describe()}")
    return bias
