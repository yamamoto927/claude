"""データモデル定義。

スクレイピング層と分析層のあいだで受け渡すデータ構造をここに集約する。
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any


# --------------------------------------------------------------------------
# 脚質
# --------------------------------------------------------------------------
NIGE = "逃げ"
SENKO = "先行"
SASHI = "差し"
OIKOMI = "追込"
UNKNOWN_STYLE = "不明"

#: 脚質を -1.0(後方) 〜 +1.0(前方) の数直線に写像したもの
STYLE_VALUE = {
    NIGE: 1.0,
    SENKO: 0.5,
    SASHI: -0.5,
    OIKOMI: -1.0,
    UNKNOWN_STYLE: 0.0,
}

#: クラス格付け。数字が大きいほど格上。
CLASS_LEVEL = {
    "G1": 10.0,
    "G2": 9.0,
    "G3": 8.0,
    "L": 7.5,
    "OP": 7.0,
    "3勝": 6.0,
    "2勝": 5.0,
    "1勝": 4.0,
    "未勝利": 2.0,
    "新馬": 1.0,
    "地方": 3.0,
    "不明": 4.5,
}


def class_level(name: str) -> float:
    """クラス名から格付けスコアを引く。"""
    return CLASS_LEVEL.get(name, CLASS_LEVEL["不明"])


# --------------------------------------------------------------------------
# 過去走
# --------------------------------------------------------------------------
@dataclass
class PastRun:
    """馬柱1行ぶん(1レース)の戦績。"""

    date: dt.date | None = None
    meeting: str = ""            # 例: 2東京9
    venue: str = ""              # 例: 東京
    weather: str = ""
    race_no: int | None = None
    race_name: str = ""
    grade: str = ""              # G1 / G2 / G3 / L / OP / 3勝 ...
    field_size: int | None = None
    waku: int | None = None
    umaban: int | None = None
    odds: float | None = None
    popularity: int | None = None
    finish: int | None = None    # 着順(中止・除外などは None)
    finish_note: str = ""        # 中止 / 除外 / 失格 など
    jockey: str = ""
    weight_carried: float | None = None
    surface: str = ""            # 芝 / ダ / 障
    distance: int | None = None
    condition: str = ""          # 良 / 稍重 / 重 / 不良
    time_sec: float | None = None
    margin: float | None = None  # 着差(秒)。勝ち馬は負値。
    corners: list[int] = field(default_factory=list)   # 通過順
    pace_first: float | None = None  # レース前半3F
    pace_last: float | None = None   # レース後半3F
    last3f: float | None = None      # 自身の上がり3F
    horse_weight: int | None = None
    horse_weight_diff: int | None = None
    prize: float = 0.0

    # -- 派生値 ---------------------------------------------------------
    @property
    def valid(self) -> bool:
        """着順が確定している(＝評価に使える)走りかどうか。"""
        return self.finish is not None and self.field_size not in (None, 0)

    @property
    def finish_rate(self) -> float | None:
        """着順を 1.0(1着) 〜 0.0(最下位) に正規化したもの。"""
        if not self.valid or self.field_size is None or self.field_size <= 1:
            return None
        return 1.0 - (self.finish - 1) / (self.field_size - 1)

    @property
    def agari_edge(self) -> float | None:
        """レース平均(後半3F)に対する上がり3Fの優位。正なら速い。"""
        if self.last3f is None or self.pace_last is None:
            return None
        return round(self.pace_last - self.last3f, 2)

    @property
    def early_position_rate(self) -> float | None:
        """道中の前後位置。0.0=最前、1.0=最後方。"""
        if not self.corners or not self.field_size:
            return None
        head = self.corners[:2] if len(self.corners) >= 2 else self.corners[:1]
        avg = sum(head) / len(head)
        return min(1.0, max(0.0, (avg - 1) / max(1, self.field_size - 1)))

    @property
    def level(self) -> float:
        return class_level(self.grade or "不明")

    def label(self) -> str:
        d = self.date.strftime("%y/%m/%d") if self.date else "??"
        place = f"{self.venue}{self.surface}{self.distance or ''}"
        res = f"{self.finish}着" if self.finish else (self.finish_note or "-")
        return f"{d} {place} {self.race_name} {res}"


# --------------------------------------------------------------------------
# 出走馬
# --------------------------------------------------------------------------
@dataclass
class Horse:
    """出馬表1行 + 過去走。"""

    umaban: int
    name: str
    horse_id: str = ""
    waku: int | None = None
    sex: str = ""
    age: int | None = None
    weight_carried: float | None = None
    jockey: str = ""
    trainer: str = ""
    stable: str = ""                     # 美浦 / 栗東 / 地方 など
    horse_weight: int | None = None
    horse_weight_diff: int | None = None
    odds: float | None = None
    popularity: int | None = None
    scratched: bool = False              # 取消・除外
    past_runs: list[PastRun] = field(default_factory=list)

    @property
    def recent(self) -> list[PastRun]:
        """新しい順に並べた有効な過去走。"""
        runs = [r for r in self.past_runs if r.valid]
        runs.sort(key=lambda r: r.date or dt.date.min, reverse=True)
        return runs

    @property
    def last_run(self) -> PastRun | None:
        runs = sorted(self.past_runs, key=lambda r: r.date or dt.date.min, reverse=True)
        return runs[0] if runs else None

    def rest_days(self, race_date: dt.date | None) -> int | None:
        """前走からの間隔(日)。"""
        last = self.last_run
        if last is None or last.date is None or race_date is None:
            return None
        return (race_date - last.date).days


# --------------------------------------------------------------------------
# レース情報
# --------------------------------------------------------------------------
@dataclass
class RaceInfo:
    race_id: str = ""
    name: str = ""
    grade: str = ""              # G1 / G2 / G3 / L / OP / 3勝 / ...
    venue: str = ""
    race_no: int | None = None
    date: dt.date | None = None
    start_time: str = ""
    surface: str = ""            # 芝 / ダ / 障
    distance: int | None = None
    direction: str = ""          # 左 / 右 / 直線
    condition: str = ""          # 良 / 稍重 / 重 / 不良
    weather: str = ""
    field_size: int | None = None
    class_name: str = ""         # サラ系3歳以上 1勝クラス など
    weight_rule: str = ""        # 定量 / ハンデ / 別定 / 馬齢
    restrictions: list[str] = field(default_factory=list)
    url: str = ""

    @property
    def level(self) -> float:
        return class_level(self.grade or "不明")

    def headline(self) -> str:
        parts = [f"{self.venue}{self.race_no}R" if self.race_no else self.venue, self.name]
        if self.grade:
            parts.append(f"({self.grade})")
        return " ".join(p for p in parts if p)

    def course_label(self) -> str:
        return f"{self.surface}{self.distance or '?'}m{self.direction}"


# --------------------------------------------------------------------------
# 馬場傾向(ユーザー入力)
# --------------------------------------------------------------------------
@dataclass
class TrackBias:
    """当日の馬場傾向。すべて -1.0 〜 +1.0 の連続値で保持する。"""

    inner: float = 0.0     # +1: 内(イン)有利 / -1: 外有利
    front: float = 0.0     # +1: 前残り     / -1: 差し・追込有利
    speed: float = 0.0     # +1: 高速馬場   / -1: 時計を要するタフな馬場
    condition_override: str = ""   # 馬場状態を上書き(良/稍重/重/不良)
    confidence: float = 1.0        # 0.0〜1.0。傾向の確信度
    notes: list[str] = field(default_factory=list)
    raw: str = ""

    @property
    def is_empty(self) -> bool:
        return abs(self.inner) < 0.05 and abs(self.front) < 0.05 and abs(self.speed) < 0.05

    @property
    def strength(self) -> float:
        """傾向の極端さ(0.0〜1.0)。荒れ度の判定に使う。"""
        return min(1.0, (abs(self.inner) + abs(self.front) + abs(self.speed)) / 2.0) * self.confidence

    def describe(self) -> str:
        if self.is_empty:
            return "馬場傾向の入力なし(ニュートラルとして扱う)"
        bits = []
        if abs(self.inner) >= 0.05:
            bits.append(f"{'内有利' if self.inner > 0 else '外有利'}({self.inner:+.2f})")
        if abs(self.front) >= 0.05:
            bits.append(f"{'前残り' if self.front > 0 else '差し有利'}({self.front:+.2f})")
        if abs(self.speed) >= 0.05:
            bits.append(f"{'高速馬場' if self.speed > 0 else '時計のかかる馬場'}({self.speed:+.2f})")
        if self.condition_override:
            bits.append(f"馬場状態={self.condition_override}")
        bits.append(f"確信度{self.confidence:.0%}")
        return " / ".join(bits)


# --------------------------------------------------------------------------
# 展開・評価・分析結果
# --------------------------------------------------------------------------
@dataclass
class PaceForecast:
    label: str = "平均ペース"
    nige_count: int = 0
    senko_count: int = 0
    pressure: float = 0.0
    front_advantage: float = 0.0   # +1: 前有利 / -1: 差し有利
    comment: str = ""
    key_horses: list[str] = field(default_factory=list)


@dataclass
class Reason:
    text: str
    weight: float = 0.0

    def __str__(self) -> str:  # pragma: no cover - 表示用
        return self.text


@dataclass
class HorseEvaluation:
    horse: Horse
    ability: float = 50.0          # 能力スコア 0〜100
    market: float = 50.0           # 市場評価スコア 0〜100 (オッズ由来)
    dark_index: float = 50.0       # 穴指数 0〜100
    style: str = UNKNOWN_STYLE
    style_confidence: float = 0.0
    components: dict[str, float] = field(default_factory=dict)
    adjustments: list[tuple[str, float]] = field(default_factory=list)
    reasons: list[Reason] = field(default_factory=list)
    risks: list[Reason] = field(default_factory=list)
    implied_prob: float = 0.0      # オッズから求めた支持率

    @property
    def gap(self) -> float:
        """能力 - 市場評価。プラスなら過小評価。"""
        return self.ability - self.market

    def top_reasons(self, n: int = 4) -> list[str]:
        return [r.text for r in sorted(self.reasons, key=lambda r: -r.weight)[:n]]

    def top_risks(self, n: int = 3) -> list[str]:
        return [r.text for r in sorted(self.risks, key=lambda r: -r.weight)[:n]]


@dataclass
class ChaosFactor:
    name: str
    delta: float
    detail: str


@dataclass
class BetPlan:
    kind: str
    detail: str
    note: str = ""
    #: 券種の「列」ごとの馬番。流しなら [軸, 相手]、ボックスなら [全頭]、
    #: フォーメーションなら [1列目, 2列目, 3列目]。detail はこれを整形したもの。
    groups: list[list[int]] = field(default_factory=list)


@dataclass
class RaceAnalysis:
    race: RaceInfo
    bias: TrackBias
    pace: PaceForecast
    evaluations: list[HorseEvaluation]
    chaos_pct: float
    chaos_label: str
    chaos_factors: list[ChaosFactor]
    dark_horses: list[HorseEvaluation]
    favorites_pick: list[HorseEvaluation]      # 本命・対抗
    dangerous_favorites: list[HorseEvaluation]
    bets: list[BetPlan]
    warnings: list[str] = field(default_factory=list)
    generated_at: dt.datetime = field(default_factory=dt.datetime.now)

    def by_umaban(self) -> list[HorseEvaluation]:
        return sorted(self.evaluations, key=lambda e: e.horse.umaban)


# --------------------------------------------------------------------------
# 小さなパースユーティリティ(モデル層で共有)
# --------------------------------------------------------------------------
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def to_float(text: Any) -> float | None:
    if text is None:
        return None
    m = _NUM_RE.search(str(text).replace(",", ""))
    return float(m.group()) if m else None


def to_int(text: Any) -> int | None:
    v = to_float(text)
    return int(v) if v is not None else None
