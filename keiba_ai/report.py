"""分析結果のレンダリング(テキスト / Markdown / JSON)。"""
from __future__ import annotations

import dataclasses
import json
import unicodedata

from .analysis.darkhorse import summarize_reasons
from .models import RaceAnalysis

BAR_WIDTH = 40


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _pad(text: str, width: int, align: str = "left") -> str:
    gap = max(0, width - _width(text))
    if align == "right":
        return " " * gap + text
    if align == "center":
        return " " * (gap // 2) + text + " " * (gap - gap // 2)
    return text + " " * gap


def _bar(pct: float, width: int = BAR_WIDTH) -> str:
    filled = int(round(width * max(0.0, min(100.0, pct)) / 100.0))
    return "█" * filled + "░" * (width - filled)


def _odds(e) -> str:
    return f"{e.horse.odds:.1f}倍" if e.horse.odds else "--"


def _pop(e) -> str:
    return f"{e.horse.popularity}人気" if e.horse.popularity else "--"


# --------------------------------------------------------------------------
# テキストレポート
# --------------------------------------------------------------------------
def render_text(a: RaceAnalysis) -> str:
    r = a.race
    out: list[str] = []
    line = "=" * 78
    out.append(line)
    date = r.date.strftime("%Y-%m-%d") if r.date else "日付不明"
    out.append(f" {r.headline()}")
    out.append(
        f" {date} {r.start_time}発走 / {r.course_label()} / 馬場:{r.condition or '不明'}"
        f" / 天候:{r.weather or '不明'} / {r.field_size or len(a.evaluations)}頭"
    )
    if r.class_name or r.weight_rule:
        out.append(f" 条件: {r.class_name} {r.weight_rule}".rstrip())
    if r.race_id:
        out.append(f" race_id: {r.race_id}")
    out.append(line)

    # --- 1. 荒れる可能性 --------------------------------------------------
    steady = round(100.0 - a.chaos_pct, 1)
    out.append("")
    out.append("【1】荒れる可能性")
    out.append(f"  判定: {a.chaos_label}")
    out.append(f"  波乱度  {a.chaos_pct:5.1f}%  [{_bar(a.chaos_pct)}]")
    out.append(f"    ├ 上位人気(1〜6番人気)で決着する確率 ... {steady:5.1f}%")
    out.append(f"    └ 7番人気以下が3着以内に絡む確率     ... {a.chaos_pct:5.1f}%")
    out.append("")
    out.append("  内訳(基準値 48.0% からの増減):")
    for f in sorted(a.chaos_factors, key=lambda f: -abs(f.delta)):
        out.append(f"    {f.delta:+6.1f}  {_pad(f.name, 24)} {f.detail}")

    # --- 2. 穴馬筆頭候補 --------------------------------------------------
    out.append("")
    out.append(f"【2】穴馬筆頭候補({len(a.dark_horses)}頭)")
    if not a.dark_horses:
        out.append("  条件を満たす穴馬候補は見当たらない。")
    for i, e in enumerate(a.dark_horses, 1):
        h = e.horse
        out.append("")
        out.append(
            f"  ◆ 穴{i}  {h.umaban:>2}番 {h.name}  ({_pop(e)} / 単勝{_odds(e)} / {h.jockey})"
        )
        out.append(
            f"      穴指数 {e.dark_index:5.1f}   能力スコア {e.ability:5.1f}   "
            f"市場評価 {e.market:5.1f}   乖離 {e.gap:+5.1f}   脚質 {e.style}"
        )
        out.append("      根拠:")
        for reason in summarize_reasons(e, r, a.pace, a.bias):
            out.append(f"        ・{reason}")

    # --- 3. 想定ペースと展開 ------------------------------------------------
    out.append("")
    out.append("【3】想定ペース・展開")
    out.append(f"  {a.pace.label}(逃げ{a.pace.nige_count}頭 / 先行{a.pace.senko_count}頭 "
               f"/ 先行圧力{a.pace.pressure:.1f} / 前後有利度 {a.pace.front_advantage:+.2f})")
    out.append(f"  {a.pace.comment}")
    if a.pace.key_horses:
        out.append(f"  ハナ・前受け候補: {'、'.join(a.pace.key_horses)}")

    # --- 4. 馬場傾向の反映 ---------------------------------------------------
    out.append("")
    out.append("【4】馬場傾向の反映")
    out.append(f"  入力: {a.bias.raw or '(なし)'}")
    out.append(f"  解釈: {a.bias.describe()}")

    # --- 5. 本命・対抗 --------------------------------------------------------
    out.append("")
    out.append("【5】本命・対抗(能力7.5:市場2.5の総合力)")
    marks = ["◎ 本命", "○ 対抗"]
    for mark, e in zip(marks, a.favorites_pick):
        out.append(f"  {mark}  {e.horse.umaban:>2}番 {e.horse.name}"
                   f"  ({_pop(e)} / 単勝{_odds(e)} / 能力{e.ability:.1f} / 脚質{e.style})")
        for reason in e.top_reasons(2):
            out.append(f"        ・{reason}")

    # --- 6. 危険な人気馬 -------------------------------------------------------
    out.append("")
    out.append("【6】危険な人気馬")
    if not a.dangerous_favorites:
        out.append("  上位人気に強い減点材料は見当たらない。")
    for e in a.dangerous_favorites:
        out.append(f"  ✕ {e.horse.umaban:>2}番 {e.horse.name}"
                   f"  ({_pop(e)} / 単勝{_odds(e)} / 能力{e.ability:.1f} / 乖離{e.gap:+.1f})")
        for risk in e.top_risks(2):
            out.append(f"        ・{risk}")

    # --- 7. 全頭評価 ------------------------------------------------------------
    out.append("")
    out.append("【7】全頭評価一覧")
    out.append("  ※ 能力=馬柱から算出した能力スコア / 市場=単勝オッズを同じ尺度に換算した値")
    out.append("  ※ 乖離=能力-市場(プラスなら過小評価) / 穴指数=乖離と能力から求めた穴馬度")
    header = (
        _pad("馬番", 5) + _pad("馬名", 20) + _pad("人気", 8) + _pad("単勝", 10)
        + _pad("能力", 7, "right") + _pad("市場", 7, "right")
        + _pad("乖離", 7, "right") + _pad("穴指数", 9, "right") + "  脚質"
    )
    out.append("  " + header)
    out.append("  " + "-" * _width(header))
    for e in sorted(a.evaluations, key=lambda e: -e.dark_index):
        h = e.horse
        mark = "取消" if h.scratched else ""
        out.append(
            "  "
            + _pad(f"{h.umaban}", 5)
            + _pad(h.name[:12] + mark, 20)
            + _pad(_pop(e), 8)
            + _pad(_odds(e), 10)
            + _pad(f"{e.ability:.1f}", 7, "right")
            + _pad(f"{e.market:.1f}", 7, "right")
            + _pad(f"{e.gap:+.1f}", 7, "right")
            + _pad(f"{e.dark_index:.1f}", 9, "right")
            + "  " + e.style
        )

    # --- 8. 買い目 ----------------------------------------------------------------
    out.append("")
    out.append("【8】推奨買い目(参考)")
    for plan in a.bets:
        out.append(f"  ・{plan.kind}: {plan.detail}")
        if plan.note:
            out.append(f"      {plan.note}")

    # --- 9. 注意 -----------------------------------------------------------------
    if a.warnings:
        out.append("")
        out.append("【9】データ上の注意")
        for w in a.warnings:
            out.append(f"  ! {w}")

    out.append("")
    out.append("-" * 78)
    out.append("※ 本出力は公開データの統計的処理による参考情報であり、的中を保証するものではありません。")
    out.append("※ 馬券の購入は20歳以上。余裕資金の範囲で、自己責任でお楽しみください。")
    out.append(f"※ 生成日時: {a.generated_at.strftime('%Y-%m-%d %H:%M:%S')}")
    return "\n".join(out)


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------
def render_markdown(a: RaceAnalysis) -> str:
    r = a.race
    steady = round(100.0 - a.chaos_pct, 1)
    out = [f"# {r.headline()}", ""]
    date = r.date.strftime("%Y-%m-%d") if r.date else "日付不明"
    out.append(f"- 開催: {date} {r.start_time} / {r.course_label()} / 馬場 {r.condition or '不明'} / {r.field_size}頭")
    out.append(f"- 条件: {r.class_name} {r.weight_rule}".rstrip())
    out.append("")
    out.append("## 1. 荒れる可能性")
    out.append(f"**{a.chaos_pct:.1f}%**({a.chaos_label})")
    out.append("")
    out.append("| 決着イメージ | 確率 |")
    out.append("|---|---|")
    out.append(f"| 上位人気(1〜6番人気)で決着 | {steady:.1f}% |")
    out.append(f"| 7番人気以下が3着以内に絡む | {a.chaos_pct:.1f}% |")
    out.append("")
    out.append("| 要因 | 増減 | 内容 |")
    out.append("|---|---:|---|")
    for f in sorted(a.chaos_factors, key=lambda f: -abs(f.delta)):
        out.append(f"| {f.name} | {f.delta:+.1f} | {f.detail} |")

    out.append("")
    out.append(f"## 2. 穴馬筆頭候補({len(a.dark_horses)}頭)")
    for i, e in enumerate(a.dark_horses, 1):
        out.append("")
        out.append(f"### 穴{i} {e.horse.umaban}番 {e.horse.name}({_pop(e)} / 単勝{_odds(e)})")
        out.append(f"- 穴指数 **{e.dark_index:.1f}** / 能力 {e.ability:.1f} / 市場 {e.market:.1f} / 乖離 {e.gap:+.1f} / 脚質 {e.style}")
        for reason in summarize_reasons(e, r, a.pace, a.bias):
            out.append(f"- {reason}")

    out.append("")
    out.append("## 3. 想定ペース・展開")
    out.append(f"{a.pace.label}(逃げ{a.pace.nige_count}頭 / 先行{a.pace.senko_count}頭 / 前後有利度 {a.pace.front_advantage:+.2f})")
    out.append("")
    out.append(a.pace.comment)

    out.append("")
    out.append("## 4. 馬場傾向の反映")
    out.append(f"- 入力: {a.bias.raw or '(なし)'}")
    out.append(f"- 解釈: {a.bias.describe()}")

    out.append("")
    out.append("## 5. 本命・対抗")
    for mark, e in zip(["◎", "○"], a.favorites_pick):
        out.append(f"- {mark} {e.horse.umaban}番 {e.horse.name}({_pop(e)} / 能力 {e.ability:.1f} / {e.style})")

    out.append("")
    out.append("## 6. 危険な人気馬")
    if not a.dangerous_favorites:
        out.append("該当なし。")
    for e in a.dangerous_favorites:
        out.append(f"- ✕ {e.horse.umaban}番 {e.horse.name}({_pop(e)} / 乖離 {e.gap:+.1f}): "
                   + " / ".join(e.top_risks(2)))

    out.append("")
    out.append("## 7. 全頭評価")
    out.append("| 馬番 | 馬名 | 人気 | 単勝 | 能力 | 市場 | 乖離 | 穴指数 | 脚質 |")
    out.append("|---:|---|---:|---:|---:|---:|---:|---:|---|")
    for e in sorted(a.evaluations, key=lambda e: -e.dark_index):
        out.append(
            f"| {e.horse.umaban} | {e.horse.name} | {_pop(e)} | {_odds(e)} | "
            f"{e.ability:.1f} | {e.market:.1f} | {e.gap:+.1f} | {e.dark_index:.1f} | {e.style} |"
        )

    out.append("")
    out.append("## 8. 推奨買い目(参考)")
    for plan in a.bets:
        out.append(f"- **{plan.kind}**: {plan.detail}  \n  {plan.note}")

    if a.warnings:
        out.append("")
        out.append("## 9. データ上の注意")
        for w in a.warnings:
            out.append(f"- {w}")

    out.append("")
    out.append("---")
    out.append("※ 公開データの統計的処理による参考情報です。的中を保証するものではありません。20歳未満の馬券購入は禁止されています。")
    return "\n".join(out)


# --------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------
def render_json(a: RaceAnalysis) -> str:
    def horse_dict(e):
        return {
            "umaban": e.horse.umaban,
            "waku": e.horse.waku,
            "name": e.horse.name,
            "horse_id": e.horse.horse_id,
            "jockey": e.horse.jockey,
            "odds": e.horse.odds,
            "popularity": e.horse.popularity,
            "scratched": e.horse.scratched,
            "style": e.style,
            "style_confidence": e.style_confidence,
            "ability": e.ability,
            "market": e.market,
            "gap": round(e.gap, 1),
            "dark_index": e.dark_index,
            "implied_prob": round(e.implied_prob, 5),
            "components": e.components,
            "adjustments": [{"name": n, "delta": d} for n, d in e.adjustments],
            "reasons": [r.text for r in sorted(e.reasons, key=lambda r: -r.weight)],
            "risks": [r.text for r in sorted(e.risks, key=lambda r: -r.weight)],
        }

    payload = {
        "race": {**dataclasses.asdict(a.race),
                 "date": a.race.date.isoformat() if a.race.date else None},
        "generated_at": a.generated_at.isoformat(),
        "chaos": {
            "upset_probability_pct": a.chaos_pct,
            "favorites_decide_pct": round(100.0 - a.chaos_pct, 1),
            "label": a.chaos_label,
            "definition": "3着以内に単勝7番人気以下の馬が1頭以上入る確率",
            "factors": [dataclasses.asdict(f) for f in a.chaos_factors],
        },
        "bias": {**dataclasses.asdict(a.bias), "description": a.bias.describe()},
        "pace": dataclasses.asdict(a.pace),
        "dark_horses": [
            {**horse_dict(e), "grounds": summarize_reasons(e, a.race, a.pace, a.bias)}
            for e in a.dark_horses
        ],
        "favorites": [horse_dict(e) for e in a.favorites_pick],
        "dangerous_favorites": [horse_dict(e) for e in a.dangerous_favorites],
        "all_horses": [horse_dict(e) for e in a.by_umaban()],
        "bets": [dataclasses.asdict(b) for b in a.bets],
        "warnings": a.warnings,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


RENDERERS = {"text": render_text, "markdown": render_markdown, "json": render_json}


def render(a: RaceAnalysis, fmt: str = "text") -> str:
    return RENDERERS[fmt](a)
