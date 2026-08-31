"""ネットワークに繋がらない環境でも動作を確認するためのサンプルレース。

実在のレース・馬ではなく、動作確認用に生成した架空のデータ。
``python -m keiba_ai --sample`` から利用する。
"""
from __future__ import annotations

import datetime as dt
import random

from .models import Horse, PastRun, RaceInfo

RACE_DATE = dt.date(2026, 5, 17)

VENUES = ["東京", "中山", "阪神", "京都", "新潟"]
GRADES = ["OP", "3勝", "G3", "3勝", "OP"]


def _make_race() -> RaceInfo:
    return RaceInfo(
        race_id="202605021711",
        name="サンプルステークス",
        grade="OP",
        venue="東京",
        race_no=11,
        date=RACE_DATE,
        start_time="15:45",
        surface="芝",
        distance=1800,
        direction="左",
        condition="良",
        weather="晴",
        field_size=16,
        class_name="サラ系4歳以上 オープン",
        weight_rule="ハンデ",
        restrictions=["(国際)", "(特指)"],
        url="(サンプルデータ)",
    )


def _past_runs(
    rng: random.Random,
    *,
    strength: float,
    position: float,
    closing: float,
    runs: int,
    last_gap: int,
    distance: int,
    surface: str = "芝",
) -> list[PastRun]:
    """1頭ぶんの馬柱を生成する。

    strength: 0.0〜1.0 の地力、position: 0.0(先頭)〜1.0(最後方)、
    closing: 上がりの優秀さ(秒)。
    """
    out: list[PastRun] = []
    date = RACE_DATE - dt.timedelta(days=last_gap)
    for i in range(runs):
        field = rng.choice([12, 14, 16, 16, 18])
        noise = rng.gauss(0, 0.16)
        rate = max(0.02, min(0.99, strength + noise))
        finish = max(1, min(field, int(round((1 - rate) * (field - 1)) + 1)))
        pos = max(0.02, min(0.98, position + rng.gauss(0, 0.08)))
        corner = max(1, min(field, int(round(pos * (field - 1)) + 1)))
        pace_first = round(rng.uniform(34.5, 37.5), 1)
        pace_last = round(pace_first + rng.uniform(-1.6, 1.4), 1)
        last3f = round(pace_last - closing - 0.9 * pos + rng.gauss(0, 0.2), 1)
        dist = distance + rng.choice([-200, -100, 0, 0, 0, 100, 200])
        out.append(
            PastRun(
                date=date,
                meeting=f"{rng.randint(1, 5)}{rng.choice(VENUES)}{rng.randint(1, 12)}",
                venue=rng.choice(VENUES) if i else "東京",
                weather=rng.choice(["晴", "曇", "小雨"]),
                race_no=rng.randint(9, 12),
                race_name=f"サンプル{i + 1}",
                grade=rng.choice(GRADES),
                field_size=field,
                waku=rng.randint(1, 8),
                umaban=rng.randint(1, field),
                odds=round(max(1.5, 40 * (1 - strength) + rng.uniform(-3, 6)), 1),
                popularity=max(1, min(field, int((1 - strength) * field) + rng.randint(-1, 2))),
                finish=finish,
                jockey="サンプル騎手",
                weight_carried=round(rng.choice([54.0, 55.0, 56.0, 57.0]), 1),
                surface=surface,
                distance=dist,
                condition=rng.choice(["良", "良", "良", "稍重", "重"]),
                time_sec=round(60 + dist * 0.06 + rng.uniform(-1, 1), 1),
                margin=round(max(0.0, (finish - 1) * 0.15 + rng.uniform(0, 0.3)), 1),
                corners=[corner, corner, max(1, corner - 1), max(1, corner - 1)][: rng.choice([2, 4])],
                pace_first=pace_first,
                pace_last=pace_last,
                last3f=last3f,
                horse_weight=480 + rng.randint(-20, 20),
                horse_weight_diff=rng.randint(-8, 8),
                prize=round(max(0.0, (1 - (finish - 1) / field) * rng.uniform(0, 2200)), 1),
            )
        )
        date -= dt.timedelta(days=rng.choice([28, 35, 42, 56, 70]))
    return out


# (馬番, 馬名, 騎手, 単勝オッズ, 地力, 位置取り, 末脚, 出走数, 前走間隔, 斤量, 得意距離)
SPECS = [
    (1, "サンプルアロー", "田中", 12.4, 0.62, 0.20, 0.35, 6, 35, 55.0, 1800),
    (2, "テストブリーズ", "佐藤", 48.9, 0.46, 0.72, 0.85, 6, 42, 53.0, 1800),
    (3, "ダミーロード", "鈴木", 3.8, 0.74, 0.30, 0.30, 6, 28, 57.5, 1800),
    (4, "モックスター", "高橋", 78.3, 0.38, 0.55, 0.20, 5, 63, 54.0, 1400),
    (5, "サンプルノヴァ", "伊藤", 2.4, 0.82, 0.35, 0.40, 5, 196, 58.0, 2000),
    (6, "フィクスチャー", "渡辺", 31.5, 0.55, 0.85, 0.95, 6, 35, 52.0, 1800),
    (7, "スタブホープ", "山本", 8.9, 0.66, 0.45, 0.50, 6, 49, 56.0, 1800),
    (8, "プレースホルダ", "中村", 121.0, 0.30, 0.60, 0.15, 4, 91, 51.0, 2200),
    (9, "サンプルギア", "小林", 6.2, 0.70, 0.08, 0.10, 6, 21, 56.5, 1800),
    (10, "ラベルウィンド", "加藤", 19.8, 0.58, 0.65, 0.75, 6, 28, 54.5, 1800),
    (11, "テンプレート", "吉田", 15.2, 0.60, 0.40, 0.45, 6, 56, 55.5, 1600),
    (12, "シードバリュー", "松本", 62.0, 0.52, 0.78, 0.90, 5, 45, 52.0, 1800),
    (13, "ダミーフラッシュ", "井上", 9.7, 0.64, 0.25, 0.35, 6, 14, 56.0, 1800),
    (14, "サンプルクエスト", "木村", 27.6, 0.50, 0.50, 0.55, 6, 112, 53.5, 1800),
    (15, "モックリバー", "林", 41.3, 0.48, 0.15, 0.25, 6, 35, 53.0, 1600),
    (16, "スタブネイチャー", "清水", 88.4, 0.40, 0.70, 0.60, 5, 77, 52.0, 2000),
]


def build_sample() -> tuple[RaceInfo, list[Horse]]:
    """サンプルのレース情報と出走馬(過去走つき)を返す。"""
    rng = random.Random(20260517)
    race = _make_race()
    horses: list[Horse] = []
    ranked = sorted(SPECS, key=lambda s: s[3])
    popularity = {spec[0]: i + 1 for i, spec in enumerate(ranked)}

    for (umaban, name, jockey, odds, strength, position, closing,
         runs, gap, weight, dist) in SPECS:
        horses.append(
            Horse(
                umaban=umaban,
                waku=min(8, (umaban + 1) // 2),
                name=name,
                horse_id=f"S{umaban:04d}",
                sex=rng.choice(["牡", "牝", "セ"]),
                age=rng.randint(4, 7),
                weight_carried=weight,
                jockey=jockey,
                trainer="サンプル調教師",
                stable=rng.choice(["美浦", "栗東"]),
                horse_weight=470 + rng.randint(-15, 25),
                horse_weight_diff=rng.randint(-10, 10),
                odds=odds,
                popularity=popularity[umaban],
                past_runs=_past_runs(
                    rng, strength=strength, position=position, closing=closing,
                    runs=runs, last_gap=gap, distance=dist,
                ),
            )
        )
    return race, horses
