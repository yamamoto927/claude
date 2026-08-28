"""馬柱(db.netkeiba.com/horse/{id}/)のパーサ。

列の並びは時期によって変わるため、``thead`` の見出しテキストから
列インデックスを引く方式にしてある。
"""
from __future__ import annotations

import datetime as dt
import re

from ..models import PastRun, to_float, to_int
from .client import make_soup
from .shutuba import classify

HORSE_URL = "https://db.netkeiba.com/horse/{horse_id}/"

JRA_VENUES = {"札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"}

#: 見出しテキスト → 正規化キー
HEADER_MAP = {
    "日付": "date", "開催": "meeting", "天気": "weather", "R": "race_no",
    "レース名": "race_name", "映像": "movie", "頭数": "field_size",
    "枠番": "waku", "馬番": "umaban", "オッズ": "odds", "人気": "popularity",
    "着順": "finish", "騎手": "jockey", "斤量": "weight_carried",
    "距離": "distance", "馬場": "condition", "タイム": "time",
    "着差": "margin", "通過": "corners", "ペース": "pace", "上り": "last3f",
    "馬体重": "horse_weight", "勝ち馬": "winner", "賞金": "prize",
}


def horse_url(horse_id: str) -> str:
    return HORSE_URL.format(horse_id=horse_id)


def _norm_header(text: str) -> str:
    text = re.sub(r"\s+", "", text)
    text = text.replace("ﾀｲﾑ指数", "タイム指数").replace("厩舎ｺﾒﾝﾄ", "厩舎コメント")
    for key, norm in HEADER_MAP.items():
        if text.startswith(key):
            return norm
    return text


def _parse_date(text: str) -> dt.date | None:
    m = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", text)
    if m:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _parse_venue(meeting: str) -> str:
    """「2東京9」→「東京」。地方・海外はそのまま返す。"""
    name = re.sub(r"^\d+", "", meeting)
    name = re.sub(r"\d+$", "", name)
    return name.strip()


def _parse_time(text: str) -> float | None:
    m = re.match(r"(\d+):(\d+(?:\.\d+)?)", text.strip())
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    return to_float(text)


def _parse_distance(text: str) -> tuple[str, int | None]:
    m = re.match(r"\s*(芝|ダ|障)\s*(\d{3,4})", text)
    if m:
        return m.group(1), int(m.group(2))
    return "", to_int(text)


def _parse_condition(text: str) -> str:
    text = text.strip()
    return {"稍": "稍重", "不": "不良"}.get(text, text)


def _parse_corners(text: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", text)][:4]


def _parse_pace(text: str) -> tuple[float | None, float | None]:
    m = re.match(r"\s*(\d+\.\d+)\s*-\s*(\d+\.\d+)", text)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def _parse_horse_weight(text: str) -> tuple[int | None, int | None]:
    m = re.match(r"(\d+)\(([-+]?\d+)\)", text.replace(" ", ""))
    if m:
        return int(m.group(1)), int(m.group(2))
    return to_int(text), None


def _infer_grade(cell, race_name: str, prize: float, venue: str) -> str:
    """レース名セルからクラス(格)を推定する。"""
    grade = classify(race_name)
    if grade:
        return grade
    if cell is not None:
        for img in cell.find_all("img"):
            m = re.search(r"grade(\d)", img.get("src", ""), re.I)
            if m:
                return {"1": "G1", "2": "G2", "3": "G3"}.get(m.group(1), "OP")
        span = cell.select_one("span[class*=Icon_GradeType]")
        if span:
            g = classify(span.get_text(strip=True))
            if g:
                return g
    if venue and venue not in JRA_VENUES:
        return "地方"
    # 賞金(万円)からのおおまかな推定
    if prize >= 3000:
        return "G2"
    if prize >= 1500:
        return "G3"
    if prize >= 900:
        return "OP"
    return ""


def parse_horse_results(
    html: str, limit: int | None = None, parser: str | None = None
) -> list[PastRun]:
    """馬の全成績テーブルを ``PastRun`` のリストにする(新しい順)。"""
    soup = make_soup(html, parser)
    table = soup.select_one("table.db_h_race_results") or soup.select_one("table.nk_tb_common")
    if table is None:
        return []

    header_cells = table.select("thead th") or (table.select("tr")[0].find_all(["th", "td"]) if table.select("tr") else [])
    headers = [_norm_header(th.get_text(strip=True)) for th in header_cells]
    index = {name: i for i, name in enumerate(headers)}

    def cell(cells, key):
        i = index.get(key)
        return cells[i] if i is not None and i < len(cells) else None

    def text(cells, key) -> str:
        c = cell(cells, key)
        return c.get_text(strip=True) if c is not None else ""

    body_rows = table.select("tbody tr") or table.select("tr")[1:]
    runs: list[PastRun] = []
    for row in body_rows:
        cells = row.find_all(["td", "th"])
        if len(cells) < 5:
            continue
        date = _parse_date(text(cells, "date"))
        if date is None:
            continue

        finish_raw = text(cells, "finish")
        finish = to_int(finish_raw)
        finish_note = "" if finish is not None else finish_raw

        surface, distance = _parse_distance(text(cells, "distance"))
        pace_first, pace_last = _parse_pace(text(cells, "pace"))
        hw, hwd = _parse_horse_weight(text(cells, "horse_weight"))
        meeting = text(cells, "meeting")
        venue = _parse_venue(meeting)
        name_cell = cell(cells, "race_name")
        # レース名セルには格付けアイコンが混ざるため、リンクのテキストを優先する
        name_link = name_cell.find("a") if name_cell is not None else None
        race_name = (name_link.get_text(strip=True) if name_link is not None
                     else text(cells, "race_name"))
        prize = to_float(text(cells, "prize")) or 0.0

        runs.append(
            PastRun(
                date=date,
                meeting=meeting,
                venue=venue,
                weather=text(cells, "weather"),
                race_no=to_int(text(cells, "race_no")),
                race_name=race_name,
                grade=_infer_grade(name_cell, race_name, prize, venue),
                field_size=to_int(text(cells, "field_size")),
                waku=to_int(text(cells, "waku")),
                umaban=to_int(text(cells, "umaban")),
                odds=to_float(text(cells, "odds")),
                popularity=to_int(text(cells, "popularity")),
                finish=finish,
                finish_note=finish_note,
                jockey=text(cells, "jockey"),
                weight_carried=to_float(text(cells, "weight_carried")),
                surface=surface,
                distance=distance,
                condition=_parse_condition(text(cells, "condition")),
                time_sec=_parse_time(text(cells, "time")),
                margin=to_float(text(cells, "margin")),
                corners=_parse_corners(text(cells, "corners")),
                pace_first=pace_first,
                pace_last=pace_last,
                last3f=to_float(text(cells, "last3f")),
                horse_weight=hw,
                horse_weight_diff=hwd,
                prize=prize,
            )
        )

    runs.sort(key=lambda r: r.date or dt.date.min, reverse=True)
    return runs[:limit] if limit else runs
