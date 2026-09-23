"""Product thumbnails, packed into sprite sheets next to data.json.

The price files carry no images. Rami Levy's image server is keyed by barcode
and covers most products sold in several chains, so thumbnails come from there.
Generic fresh products get an emoji icon instead (see generic.ICONS): the
packaged look-alikes were too often wrong (tomato paste for tomatoes).

Thumbnails are cached on disk and packed into sheets of SHEET x SHEET cells,
most popular products first, so a search for everyday items touches only a few
small files. Output:
    web/img/s<N>.jpg     sprite sheets
    web/img/index.json   {"cell": px, "grid": SHEET, "map": {barcode: [sheet, cell]}}
"""

import io
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor

import requests
from PIL import Image

log = logging.getLogger("pricecompare")

SOURCE = "https://img.rami-levy.co.il/product/{}/small.jpg"
CELL = 64          # px per thumbnail
SHEET = 10         # cells per row/column
MIN_STORES = 3     # only products sold in at least this many stores get a photo
QUALITY = 72


def _popularity(data):
    pop = [0] * len(data["products"])
    for flat in data["prices"]:
        i = 0
        for k in range(0, len(flat), 2):
            i += flat[k]
            pop[i] += 1
    return pop


class ThumbCache:
    """Downloaded thumbnails on disk; remembers misses so they aren't refetched."""

    def __init__(self, folder):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)
        self.missing_path = os.path.join(folder, "missing.txt")
        try:
            with open(self.missing_path) as f:
                self.missing = set(f.read().split())
        except OSError:
            self.missing = set()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "Mozilla/5.0 (price-compare)"
        self.session.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=32))

    def path(self, code):
        return os.path.join(self.folder, f"{code}.jpg")

    def has(self, code):
        return os.path.exists(self.path(code))

    def fetch(self, code):
        if self.has(code) or code in self.missing:
            return self.has(code)
        try:
            r = self.session.get(SOURCE.format(code), timeout=30)
        except requests.RequestException:
            return False  # transient: try again next run
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
            self.missing.add(code)
            return False
        try:
            im = Image.open(io.BytesIO(r.content)).convert("RGB")
        except OSError:
            self.missing.add(code)
            return False
        im.thumbnail((CELL, CELL), Image.LANCZOS)
        cell = Image.new("RGB", (CELL, CELL), "white")
        cell.paste(im, ((CELL - im.width) // 2, (CELL - im.height) // 2))
        cell.save(self.path(code), quality=90)
        return True

    def save_missing(self):
        with open(self.missing_path, "w") as f:
            f.write("\n".join(sorted(self.missing)))


def build_images(data_path, out_dir, cache_dir, workers=16):
    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)
    products = data["products"]
    pop = _popularity(data)
    cache = ThumbCache(cache_dir)

    wanted = [i for i in sorted(range(len(products)), key=lambda i: -pop[i]) if pop[i] >= MIN_STORES]
    codes = [products[i][0] for i in wanted]
    log.info("fetching up to %d thumbnails", len(codes))
    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(cache.fetch, codes))
    cache.save_missing()
    entries = [c for c in codes if cache.has(c)]

    os.makedirs(out_dir, exist_ok=True)
    for old in os.listdir(out_dir):
        if re.fullmatch(r"s\d+\.jpg", old):
            os.remove(os.path.join(out_dir, old))
    per_sheet = SHEET * SHEET
    mapping = {}
    for n in range(0, len(entries), per_sheet):
        sheet = Image.new("RGB", (CELL * SHEET, CELL * SHEET), "white")
        for cell, code in enumerate(entries[n:n + per_sheet]):
            with Image.open(cache.path(code)) as im:
                sheet.paste(im, ((cell % SHEET) * CELL, (cell // SHEET) * CELL))
            mapping[code] = [n // per_sheet, cell]
        sheet.save(os.path.join(out_dir, f"s{n // per_sheet}.jpg"), quality=QUALITY, optimize=True, progressive=True)

    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"cell": CELL, "grid": SHEET, "map": mapping}, f, separators=(",", ":"))
    sheets = (len(entries) + per_sheet - 1) // per_sheet
    log.info("wrote %d thumbnails in %d sheets", len(entries), sheets)
