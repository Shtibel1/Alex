"""Collect the region's stores and prices into one compact JSON file.

Output layout (kept small so the web page can load it in one request):
    generated  ISO timestamp
    region     region name
    chains     {chain key: chain display name}
    stores     [{id, chain, name, address, items}]
    products   [[barcode, name, manufacturer, size, weighted]]
    prices     one list per store, aligned with `stores`, flattened pairs of
               (product index delta, price in agorot), sorted by product index
"""

import json
import logging
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import config
from .parse import matches_region, parse_prices
from .sources import Carrefour, Cerberus, Shufersal

log = logging.getLogger("pricecompare")


def _sources():
    yield Shufersal(config.SHUFERSAL)
    yield Carrefour(config.CARREFOUR)
    for chain in config.CERBERUS:
        yield Cerberus(chain)


def _size(item):
    q, unit = item["quantity"], item["unit"]
    if not unit or not q or (q == 1 and "יח" in unit):
        return ""
    return f"{q:g} {unit}"


def collect_chain(source, region):
    """Return [(store dict, [items])] for the chain's stores in the region."""
    key = source.chain["key"]
    try:
        stores = [s for s in source.stores() if matches_region(s, region)]
        log.info("%s: %d stores in %s", key, len(stores), region["name"])
        if not stores:
            return []
        files = source.latest_price_files([s["store_id"] for s in stores])
        out = []
        for store in stores:
            fetch = files.get(store["store_id"])
            if not fetch:
                log.warning("%s store %s: no PriceFull file", key, store["store_id"])
                continue
            items = list(parse_prices(fetch()))
            log.info("%s store %s (%s): %d items", key, store["store_id"], store["name"], len(items))
            if items:
                out.append((store, items))
        return out
    except Exception:  # one broken portal must not sink the whole update
        log.exception("%s: failed", key)
        return []


def build(region=config.REGION, workers=6):
    sources = list(_sources())
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda s: (s, collect_chain(s, region)), sources))

    names = defaultdict(Counter)
    makers = defaultdict(Counter)
    info = {}
    stores, store_prices = [], []
    for source, chain_stores in results:
        for store, items in chain_stores:
            prices = {}
            for item in items:
                bc = item["barcode"]
                names[bc][item["name"]] += 1
                if re.search(r"[A-Za-zא-ת]", item["manufacturer"]):
                    makers[bc][item["manufacturer"]] += 1
                info.setdefault(bc, item)
                prices[bc] = item["price"]
            stores.append({
                "id": f"{source.chain['key']}-{store['store_id']}",
                "chain": source.chain["key"],
                "name": store["name"],
                "address": store["address"],
                "items": len(prices),
            })
            store_prices.append(prices)

    barcodes = sorted(names, key=lambda bc: (-sum(names[bc].values()), bc))
    index = {bc: i for i, bc in enumerate(barcodes)}
    products = []
    for bc in barcodes:
        item = info[bc]
        name = names[bc].most_common(1)[0][0]
        maker = makers[bc].most_common(1)[0][0] if makers[bc] else ""
        products.append([bc, name, maker, _size(item), int(item["weighted"])])

    packed = []
    for prices in store_prices:
        flat, prev = [], 0
        for i, price in sorted((index[bc], p) for bc, p in prices.items()):
            flat += [i - prev, round(price * 100)]
            prev = i
        packed.append(flat)

    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "region": region["name"],
        "chains": {s.chain["key"]: s.chain["name"] for s in sources},
        "stores": stores,
        "products": products,
        "prices": packed,
    }


def main(out_path):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    data = build()
    if not data["stores"]:
        log.error("no stores collected, keeping the previous data file")
        sys.exit(1)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    log.info("wrote %s: %d stores, %d products", out_path, len(data["stores"]), len(data["products"]))
