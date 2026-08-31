"""netkeiba からデータを集めて分析にかけるまでの一連の処理。"""
from __future__ import annotations

import logging
import re

from .analysis.engine import analyze_race
from .models import Horse, RaceAnalysis, RaceInfo, TrackBias
from .scraper import (
    FetchError, NetkeibaClient, horse_url, parse_horse_results, parse_odds_api,
    parse_shutuba, shutuba_url,
)
from .scraper.shutuba import odds_api_url

log = logging.getLogger(__name__)


def extract_race_id(value: str) -> str:
    """URL でも race_id でも受け取れるようにする。"""
    value = value.strip()
    m = re.search(r"race_id=(\d+)", value)
    if m:
        return m.group(1)
    m = re.fullmatch(r"\d{10,14}", value)
    if m:
        return value
    raise ValueError(f"race_id を判別できません: {value!r}")


def fetch_race(
    client: NetkeibaClient,
    race_id: str,
    max_past: int = 10,
    fetch_form: bool = True,
) -> tuple[RaceInfo, list[Horse], list[str]]:
    """出馬表・オッズ・各馬の馬柱を取得する。

    戻り値の3番目は、取得に失敗した項目の警告メッセージ。
    """
    warnings: list[str] = []
    html = client.get(shutuba_url(race_id), ttl=600)
    race, horses = parse_shutuba(html, race_id)
    if not horses:
        raise FetchError(
            f"出馬表を解析できませんでした(race_id={race_id})。"
            "race_id が正しいか、出馬表が公開済みかを確認してください。"
        )

    # 出馬表のオッズは JS 描画のため空のことがある → API で補う
    if not all(h.odds for h in horses if not h.scratched):
        try:
            data = client.get_json(odds_api_url(race_id), ttl=180)
            live_odds = parse_odds_api(data)
            for h in horses:
                if h.umaban in live_odds:
                    h.odds, ninki = live_odds[h.umaban][0], live_odds[h.umaban][1]
                    h.popularity = ninki or h.popularity
        except (FetchError, ValueError) as exc:
            warnings.append(f"オッズ API を取得できなかった: {exc}")

    # 人気が空なら単勝オッズから振り直す
    if not any(h.popularity for h in horses):
        ranked = sorted([h for h in horses if h.odds], key=lambda h: h.odds)
        for i, h in enumerate(ranked, 1):
            h.popularity = i

    if fetch_form:
        for h in horses:
            if h.scratched or not h.horse_id:
                continue
            try:
                page = client.get(horse_url(h.horse_id), ttl=86400)
                h.past_runs = parse_horse_results(page, limit=max_past)
            except FetchError as exc:
                warnings.append(f"{h.name} の戦績取得に失敗: {exc}")
    return race, horses, warnings


def analyze(
    race_id: str,
    bias: TrackBias | None = None,
    client: NetkeibaClient | None = None,
    max_past: int = 10,
    fetch_form: bool = True,
) -> RaceAnalysis:
    """race_id を渡すだけで分析結果を返す高水準 API。"""
    client = client or NetkeibaClient()
    race, horses, warnings = fetch_race(client, race_id, max_past, fetch_form)
    analysis = analyze_race(race, horses, bias)
    analysis.warnings = warnings + analysis.warnings
    return analysis
