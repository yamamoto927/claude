"""出馬表(race.netkeiba.com/race/shutuba.html)のパーサ。"""
from __future__ import annotations

import datetime as dt
import re

from ..models import Horse, RaceInfo, to_float, to_int
from .client import make_soup

SHUTUBA_URL = "https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
ODDS_API_URL = (
    "https://race.netkeiba.com/api/api_get_jra_odds.html"
    "?type=1&locale=ja&race_id={race_id}"
)

#: race_id 5〜6桁目の競馬場コード
VENUE_CODES = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
    "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
}

CLASS_KEYWORDS = [
    ("G1", ("G1", "GI", "Ｇ１", "J.G1")),
    ("G2", ("G2", "GII", "Ｇ２", "J.G2")),
    ("G3", ("G3", "GIII", "Ｇ３", "J.G3")),
    ("L", ("(L)", "リステッド")),
    ("OP", ("オープン", "OP")),
    ("3勝", ("3勝クラス", "３勝クラス", "1600万下")),
    ("2勝", ("2勝クラス", "２勝クラス", "1000万下")),
    ("1勝", ("1勝クラス", "１勝クラス", "500万下")),
    ("未勝利", ("未勝利",)),
    ("新馬", ("新馬", "メイクデビュー")),
]

WEIGHT_RULES = ("ハンデ", "別定", "定量", "馬齢")


def shutuba_url(race_id: str) -> str:
    return SHUTUBA_URL.format(race_id=race_id)


def odds_api_url(race_id: str) -> str:
    return ODDS_API_URL.format(race_id=race_id)


def classify(text: str) -> str:
    """テキストからクラス(格)を判定する。"""
    for label, keys in CLASS_KEYWORDS:
        if any(k in text for k in keys):
            return label
    return ""


def _norm_condition(text: str) -> str:
    text = text.strip()
    return {"稍": "稍重", "不": "不良"}.get(text, text)


def _venue_from_race_id(race_id: str) -> str:
    return VENUE_CODES.get(race_id[4:6], "") if len(race_id) >= 6 else ""


def _parse_race_header(soup, race_id: str) -> RaceInfo:
    info = RaceInfo(race_id=race_id, url=shutuba_url(race_id) if race_id else "")

    name_el = soup.select_one(".RaceName")
    if name_el:
        info.name = name_el.get_text(" ", strip=True)
        grade_el = name_el.select_one("span[class*=Icon_GradeType]")
        if grade_el:
            info.grade = classify(grade_el.get_text(strip=True)) or classify(
                " ".join(grade_el.get("class", []))
            )
            info.name = re.sub(r"\s*" + re.escape(grade_el.get_text(strip=True)) + r"\s*$", "", info.name).strip()

    num_el = soup.select_one(".RaceNum")
    if num_el:
        info.race_no = to_int(num_el.get_text(strip=True))

    data01 = soup.select_one(".RaceData01")
    if data01:
        text = data01.get_text(" ", strip=True)
        m = re.search(r"(\d{1,2}:\d{2})発走", text)
        if m:
            info.start_time = m.group(1)
        m = re.search(r"(芝|ダ|ダート|障)\s*(\d{3,4})m", text)
        if m:
            info.surface = {"ダート": "ダ"}.get(m.group(1), m.group(1))
            info.distance = int(m.group(2))
        m = re.search(r"\((左|右|直線|直)", text)
        if m:
            info.direction = {"直": "直線"}.get(m.group(1), m.group(1))
        m = re.search(r"天候\s*[:：]\s*(\S+?)(?:\s|/|$)", text)
        if m:
            info.weather = m.group(1)
        m = re.search(r"馬場\s*[:：]\s*(\S+)", text)
        if m:
            info.condition = _norm_condition(re.sub(r"[^良稍重不良]", "", m.group(1)) or m.group(1))

    data02 = soup.select_one(".RaceData02")
    if data02:
        spans = [s.get_text(strip=True) for s in data02.find_all("span")]
        text = " ".join(spans)
        for s in spans:
            if s in VENUE_CODES.values():
                info.venue = s
            elif "サラ系" in s or "系" in s and "歳" in s:
                info.class_name = s
            elif s in WEIGHT_RULES or any(w in s for w in WEIGHT_RULES):
                info.weight_rule = next(w for w in WEIGHT_RULES if w in s)
            elif s.startswith("(") and s.endswith(")"):
                info.restrictions.append(s)
            elif re.fullmatch(r"\d+頭", s):
                info.field_size = to_int(s)
        if not info.grade:
            info.grade = classify(text)
        if not info.class_name:
            info.class_name = text

    info.venue = info.venue or _venue_from_race_id(race_id)

    m = re.search(r"kaisai_date=(\d{8})", str(soup))
    if m:
        info.date = dt.datetime.strptime(m.group(1), "%Y%m%d").date()
    else:
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", soup.get_text(" ", strip=True))
        if m:
            info.date = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    if not info.grade and info.name:
        info.grade = classify(info.name)
    return info


def _cell(row, *selectors):
    for sel in selectors:
        el = row.select_one(sel)
        if el is not None:
            return el
    return None


def _parse_horse_row(row) -> Horse | None:
    tds = row.find_all("td", recursive=False) or row.find_all("td")
    if not tds:
        return None

    link = _cell(row, 'td.HorseInfo a[href*="/horse/"]', 'a[href*="/horse/"]')
    if link is None:
        return None
    name = link.get_text(strip=True)
    m = re.search(r"/horse/(\w+)", link.get("href", ""))
    horse_id = m.group(1) if m else ""

    waku_td = next((t for t in tds if any(re.fullmatch(r"Waku\d", c) for c in t.get("class", []))), None)
    uma_td = next((t for t in tds if any(re.fullmatch(r"Umaban\d+", c) for c in t.get("class", []))), None)
    waku = to_int(waku_td.get_text(strip=True)) if waku_td else (to_int(tds[0].get_text(strip=True)) if tds else None)
    umaban = to_int(uma_td.get_text(strip=True)) if uma_td else (to_int(tds[1].get_text(strip=True)) if len(tds) > 1 else None)
    if umaban is None:
        return None

    barei_td = next((t for t in tds if "Barei" in t.get("class", [])), None)
    sex, age = "", None
    weight_carried = None
    if barei_td is not None:
        barei = barei_td.get_text(strip=True)
        m = re.match(r"([牡牝セせん騸]+)\s*(\d+)", barei)
        if m:
            sex, age = m.group(1), int(m.group(2))
        idx = tds.index(barei_td)
        if idx + 1 < len(tds):
            weight_carried = to_float(tds[idx + 1].get_text(strip=True))

    jockey_el = _cell(row, 'td.Jockey a', 'a[href*="/jockey/"]')
    trainer_el = _cell(row, 'td.Trainer a', 'a[href*="/trainer/"]')
    stable_el = _cell(row, 'td.Trainer span.Label1', 'td.Trainer span')

    weight_td = next((t for t in tds if "Weight" in t.get("class", [])), None)
    horse_weight = horse_weight_diff = None
    if weight_td is not None:
        wtext = weight_td.get_text(strip=True)
        m = re.match(r"(\d+)\s*\(([-+]?\d+)\)", wtext)
        if m:
            horse_weight, horse_weight_diff = int(m.group(1)), int(m.group(2))
        else:
            horse_weight = to_int(wtext)

    odds_el = _cell(row, 'span[id^="odds-"]', "td.Popular span", "td.Txt_R.Popular")
    ninki_el = _cell(row, 'span[id^="ninki-"]', "td.Popular_Ninki span", "td.Popular_Ninki")
    odds = to_float(odds_el.get_text(strip=True)) if odds_el else None
    popularity = to_int(ninki_el.get_text(strip=True)) if ninki_el else None

    row_text = row.get_text(" ", strip=True)
    scratched = ("取消" in row_text or "除外" in row_text
                 or any("Cancel" in c for c in row.get("class", [])))

    return Horse(
        umaban=umaban,
        name=name,
        horse_id=horse_id,
        waku=waku,
        sex=sex,
        age=age,
        weight_carried=weight_carried,
        jockey=jockey_el.get_text(strip=True) if jockey_el else "",
        trainer=trainer_el.get_text(strip=True) if trainer_el else "",
        stable=stable_el.get_text(strip=True) if stable_el else "",
        horse_weight=horse_weight,
        horse_weight_diff=horse_weight_diff,
        odds=odds,
        popularity=popularity,
        scratched=scratched,
    )


def parse_shutuba(
    html: str, race_id: str = "", parser: str | None = None
) -> tuple[RaceInfo, list[Horse]]:
    """出馬表 HTML から (レース情報, 出走馬リスト) を返す。"""
    soup = make_soup(html, parser)
    info = _parse_race_header(soup, race_id)

    rows = soup.select("tr.HorseList")
    if not rows:
        table = soup.select_one("table.Shutuba_Table, table.ShutubaTable, table.RaceTable01")
        rows = table.select("tr")[1:] if table else []

    horses: list[Horse] = []
    for row in rows:
        horse = _parse_horse_row(row)
        if horse is not None:
            horses.append(horse)
    horses.sort(key=lambda h: h.umaban)

    live = [h for h in horses if not h.scratched]
    info.field_size = len(live) or info.field_size
    return info, horses


def parse_odds_api(payload: dict) -> dict[int, tuple[float, int | None]]:
    """オッズ API の JSON から {馬番: (単勝オッズ, 人気)} を作る。

    出馬表 HTML のオッズは JavaScript で描画されるため空のことがある。
    その穴埋めに使う。
    """
    result: dict[int, tuple[float, int | None]] = {}
    odds = (payload.get("data") or {}).get("odds") or {}
    tansho = odds.get("1") or {}
    for key, value in tansho.items():
        umaban = to_int(key)
        if umaban is None or not isinstance(value, (list, tuple)) or not value:
            continue
        o = to_float(value[0])
        ninki = to_int(value[2]) if len(value) > 2 else None
        if o:
            result[umaban] = (o, ninki)
    return result
