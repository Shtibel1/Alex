"""Downloaders for the chains' price portals.

Every source exposes the same methods:
    stores()                 -> list of store dicts (see parse.parse_stores)
    latest_price_files(ids)  -> {store_id: downloader} for the newest PriceFull
    latest_promo_files(ids)  -> {store_id: downloader} for the newest PromoFull
"""

import html
import re
import time
from datetime import datetime, timedelta

import requests

from .parse import file_store_and_time, parse_stores

TIMEOUT = 120
HEADERS = {"User-Agent": "Mozilla/5.0 (price-compare; +https://github.com/shtibel1/alex)"}


def _get(session, url, **kwargs):
    """GET with a few retries; the portals are slow and occasionally time out."""
    for attempt in range(4):
        try:
            r = session.get(url, timeout=TIMEOUT, **kwargs)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))


def _post(session, url, **kwargs):
    for attempt in range(4):
        try:
            r = session.post(url, timeout=TIMEOUT, **kwargs)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))


def _latest(names):
    """Newest file name per store id."""
    best = {}
    for name in names:
        store_id, stamp = file_store_and_time(name)
        if store_id is None:
            continue
        if store_id not in best or stamp > best[store_id][0]:
            best[store_id] = (stamp, name)
    return {store_id: name for store_id, (_, name) in best.items()}


class Shufersal:
    BASE = "https://prices.shufersal.co.il/FileObject/UpdateCategory"
    CAT_PRICEFULL, CAT_PROMOFULL, CAT_STORES = 2, 4, 5

    def __init__(self, chain):
        self.chain = chain
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _links(self, cat, store_id=0):
        r = _get(self.session, self.BASE, params={"catID": cat, "storeId": store_id})
        return [html.unescape(u) for u in re.findall(r'href="(https://pricesprodpublic[^"]+)"', r.text)]

    def stores(self):
        url = self._links(self.CAT_STORES)[0]
        return list(parse_stores(_get(self.session, url).content))

    def latest_price_files(self, store_ids):
        return self._latest_files(self.CAT_PRICEFULL, store_ids)

    def latest_promo_files(self, store_ids):
        return self._latest_files(self.CAT_PROMOFULL, store_ids)

    def _latest_files(self, cat, store_ids):
        out = {}
        for store_id in store_ids:
            links = self._links(cat, store_id)
            by_name = {u.split("?")[0].rsplit("/", 1)[-1]: u for u in links}
            latest = _latest(by_name).get(store_id)
            if latest:
                url = by_name[latest]
                out[store_id] = lambda url=url: _get(self.session, url).content
        return out


class Cerberus:
    BASE = "https://url.publishedprices.co.il"

    def __init__(self, chain):
        self.chain = chain
        self.session = None
        self.token = None

    def _login(self):
        if self.session:
            return
        s = requests.Session()
        s.headers.update(HEADERS)
        r = _get(s, f"{self.BASE}/login")
        token = re.search(r'name="csrftoken" content="([^"]+)"', r.text).group(1)
        r = _post(s, f"{self.BASE}/login/user", data={
            "r": "", "username": self.chain["user"], "password": "",
            "Submit": "Sign in", "csrftoken": token,
        })
        self.token = re.search(r'name="csrftoken" content="([^"]+)"', r.text).group(1)
        self.session = s

    def _list(self, search):
        self._login()
        r = _post(self.session, f"{self.BASE}/file/json/dir", data={
            "sEcho": 1, "iDisplayStart": 0, "iDisplayLength": 100000,
            "sSearch": search, "cd": "/", "csrftoken": self.token,
        })
        return [row["name"] for row in r.json().get("aaData", [])]

    def _download(self, name):
        return _get(self.session, f"{self.BASE}/file/d/{name}").content

    def stores(self):
        names = sorted(n for n in self._list("Stores") if n.lower().startswith("stores"))
        return list(parse_stores(self._download(names[-1]))) if names else []

    def latest_price_files(self, store_ids):
        return self._latest_files("PriceFull", store_ids)

    def latest_promo_files(self, store_ids):
        return self._latest_files("PromoFull", store_ids)

    def _latest_files(self, prefix, store_ids):
        latest = _latest(n for n in self._list(prefix) if n.lower().startswith(prefix.lower()))
        return {
            sid: (lambda name=latest[sid]: self._download(name))
            for sid in store_ids if sid in latest
        }


class Carrefour:
    BASE = "https://prices.carrefour.co.il"
    DAYS_BACK = 3  # right after midnight the new day's folder is almost empty

    def __init__(self, chain):
        self.chain = chain
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._days = {}

    def _listing(self, day=None):
        """(date folder, [file names]) for a day (YYYYMMDD), default today."""
        if day not in self._days:
            text = _get(self.session, f"{self.BASE}/", params={"date": day} if day else None).text
            folder = re.search(r"const path = '(\d{8})'", text)
            self._days[day] = (folder.group(1) if folder else "", re.findall(r'"name":"([^"]+)"', text))
        return self._days[day]

    def _recent_days(self):
        folder, _ = self._listing()
        today = datetime.strptime(folder, "%Y%m%d") if folder else datetime.now()
        for back in range(self.DAYS_BACK + 1):
            yield None if back == 0 else (today - timedelta(days=back)).strftime("%Y%m%d")

    def stores(self):
        for day in self._recent_days():
            folder, names = self._listing(day)
            stores = sorted(n for n in names if n.startswith("Stores"))
            if stores:
                return list(parse_stores(_get(self.session, f"{self.BASE}/{folder}/{stores[-1]}").content))
        return []

    def latest_price_files(self, store_ids):
        return self._latest_files("PriceFull", store_ids)

    def latest_promo_files(self, store_ids):
        return self._latest_files("PromoFull", store_ids)

    def _latest_files(self, prefix, store_ids):
        out = {}
        for day in self._recent_days():
            missing = [sid for sid in store_ids if sid not in out]
            if not missing:
                break
            folder, names = self._listing(day)
            latest = _latest(n for n in names if n.startswith(prefix))
            for sid in missing:
                if sid in latest:
                    url = f"{self.BASE}/{folder}/{latest[sid]}"
                    out[sid] = lambda url=url: _get(self.session, url).content
        return out


class Bina:
    """Chains hosted by Bina Projects (<prefix>.binaprojects.com)."""

    FILE_TYPES = {"stores": 1, "pricefull": 4, "promofull": 5}

    def __init__(self, chain):
        self.chain = chain
        self.base = f"https://{chain['prefix']}.binaprojects.com"
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _list(self, file_type, store_id=""):
        r = _get(self.session, f"{self.base}/MainIO_Hok.aspx", params={
            "_": self.chain["chain_id"], "wReshet": "הכל",
            "WFileType": self.FILE_TYPES[file_type], "WDate": "", "WStore": store_id,
        })
        return [row["FileNm"] for row in r.json()]

    def _download(self, name):
        r = _get(self.session, f"{self.base}/Download.aspx", params={"FileNm": name})
        return _get(self.session, r.json()[0]["SPath"]).content

    def stores(self):
        names = sorted(n for n in self._list("stores") if n.lower().startswith("stores"))
        return list(parse_stores(self._download(names[-1]))) if names else []

    def latest_price_files(self, store_ids):
        return self._latest_files("pricefull", store_ids)

    def latest_promo_files(self, store_ids):
        return self._latest_files("promofull", store_ids)

    def _latest_files(self, file_type, store_ids):
        out = {}
        for store_id in store_ids:
            latest = _latest(self._list(file_type, store_id)).get(store_id)
            if latest:
                out[store_id] = lambda name=latest: self._download(name)
        return out
