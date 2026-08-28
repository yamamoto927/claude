"""netkeiba への HTTP アクセス層。

* 文字コード(EUC-JP)の自動判別
* レスポンスのローカルキャッシュ
* リクエスト間ウェイト(既定 1.0 秒)
* 保存済み HTML を使うオフラインモード

netkeiba は個人利用の範囲を超えた自動収集を禁じている。既定のウェイトを
短縮しないこと、取得したデータを再配布しないことを利用者の責任で守ること。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

_CHARSET_RE = re.compile(rb"charset\s*=\s*[\"']?([\w\-]+)", re.I)
_ENCODING_CANDIDATES = ("euc-jp", "utf-8", "cp932")


class FetchError(RuntimeError):
    """ページ取得に失敗した。"""


def decode_html(raw: bytes) -> str:
    """netkeiba のページを文字化けさせずに文字列化する。"""
    declared = None
    m = _CHARSET_RE.search(raw[:4096])
    if m:
        declared = m.group(1).decode("ascii", "ignore").lower()
        if declared in ("euc_jp", "eucjp", "x-euc-jp"):
            declared = "euc-jp"
        if declared in ("shift_jis", "sjis", "x-sjis", "windows-31j"):
            declared = "cp932"
    order = ([declared] if declared else []) + [
        e for e in _ENCODING_CANDIDATES if e != declared
    ]
    for enc in order:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("euc-jp", errors="replace")


class NetkeibaClient:
    """netkeiba の GET を担当する薄いクライアント。"""

    def __init__(
        self,
        cache_dir: str | os.PathLike[str] | None = ".cache/keiba_ai",
        sleep: float = 1.0,
        timeout: float = 20.0,
        offline_dir: str | os.PathLike[str] | None = None,
        save_dir: str | os.PathLike[str] | None = None,
        use_cache: bool = True,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.sleep = max(0.0, sleep)
        self.timeout = timeout
        self.offline_dir = Path(offline_dir) if offline_dir else None
        self.save_dir = Path(save_dir) if save_dir else None
        self.use_cache = use_cache
        self._last_request = 0.0
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept-Language": "ja,en;q=0.8",
                "Referer": "https://race.netkeiba.com/",
            }
        )
        for d in (self.cache_dir, self.save_dir):
            if d:
                d.mkdir(parents=True, exist_ok=True)

    # -- 内部ヘルパ ------------------------------------------------------
    @staticmethod
    def slug(url: str) -> str:
        """URL から人間にも読めるファイル名を作る。"""
        p = urlparse(url)
        base = (p.netloc + p.path).replace("/", "_").strip("_")
        query = p.query.replace("&", "_").replace("=", "-")
        name = f"{base}{'_' + query if query else ''}"
        name = re.sub(r"[^A-Za-z0-9._\-]", "_", name)[:120]
        digest = hashlib.sha1(url.encode()).hexdigest()[:8]
        return f"{name}.{digest}.html"

    def _offline_read(self, url: str) -> str | None:
        if not self.offline_dir:
            return None
        cand = self.offline_dir / self.slug(url)
        if cand.exists():
            return decode_html(cand.read_bytes())
        # ハッシュ無しの手動保存ファイルも探す(例: horse_2019105283.html)
        stem = self.slug(url).split(".")[0]
        for path in self.offline_dir.glob("*.html"):
            if stem in path.stem or path.stem in stem:
                return decode_html(path.read_bytes())
        return None

    def _cache_path(self, url: str) -> Path | None:
        return self.cache_dir / self.slug(url) if self.cache_dir else None

    # -- 公開 API --------------------------------------------------------
    def get(self, url: str, *, ttl: float = 900.0) -> str:
        """URL を取得して文字列で返す。

        オフラインディレクトリ → キャッシュ → ネットワークの順に探す。
        ``ttl`` はキャッシュの有効秒数(出馬表のオッズは変動するため短め)。
        """
        offline = self._offline_read(url)
        if offline is not None:
            log.debug("offline hit: %s", url)
            return offline
        if self.offline_dir is not None:
            raise FetchError(
                f"オフラインモードですが {self.offline_dir} に該当 HTML がありません: {url}"
            )

        cache = self._cache_path(url)
        if self.use_cache and cache and cache.exists():
            age = time.time() - cache.stat().st_mtime
            if age < ttl:
                log.debug("cache hit (%.0fs): %s", age, url)
                return decode_html(cache.read_bytes())

        wait = self.sleep - (time.time() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        log.info("GET %s", url)
        try:
            resp = self._session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:  # pragma: no cover - 通信依存
            raise FetchError(f"{url} の取得に失敗しました: {exc}") from exc
        finally:
            self._last_request = time.time()
        if resp.status_code != 200:
            raise FetchError(f"{url} が HTTP {resp.status_code} を返しました")

        raw = resp.content
        if cache and self.use_cache:
            cache.write_bytes(raw)
        if self.save_dir:
            (self.save_dir / self.slug(url)).write_bytes(raw)
        return decode_html(raw)

    def get_json(self, url: str, *, ttl: float = 300.0) -> dict:
        """JSON API を叩く(オッズ API 用)。"""
        text = self.get(url, ttl=ttl)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise FetchError(f"{url} の JSON 解析に失敗しました: {exc}") from exc
