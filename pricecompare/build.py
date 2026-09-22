"""Collect the region's stores and prices into one compact JSON file.

Output layout (kept small so the web page can load it in one request):
    generated  ISO timestamp
    region     region name
    chains     {chain key: chain display name}
    stores     [{id, chain, name, address, items, asof}]  asof: when its prices were published
    products   [[barcode, name, manufacturer, size, weighted]]
    prices     one list per store, aligned with `stores`, flattened pairs of
               (product index delta, price in agorot), sorted by product index
    generics   [[key, name, category, unit]]  fresh products matched by name
    gprices    one list per store: [[generic index, price in agorot, chosen item name]]
"""

import json
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from . import config, generic
from .parse import matches_region, parse_prices
from .sources import Bina, Carrefour, Cerberus, Shufersal

log = logging.getLogger("pricecompare")

MAX_STALE = timedelta(days=3)  # older prices are dropped rather than shown as current


def _sources():
    yield Shufersal(config.SHUFERSAL)
    yield Carrefour(config.CARREFOUR)
    for chain in config.CERBERUS:
        yield Cerberus(chain)
    for chain in config.BINA:
        yield Bina(chain)


def _size(item):
    q, unit = item["quantity"], item["unit"]
    if not unit or not q or (q == 1 and "יח" in unit):
        return ""
    return f"{q:g} {unit}"


def collect_chain(source, region):
    """Return (all region stores, [(store dict, [items])] for those with a price file)."""
    key = source.chain["key"]
    try:
        stores = {s["store_id"]: s for s in source.stores() if matches_region(s, region)}
        stores = list(stores.values())
        log.info("%s: %d stores in %s", key, len(stores), region["name"])
        if not stores:
            return [], []
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
        return stores, out
    except Exception:  # one broken portal must not sink the whole update
        log.exception("%s: failed", key)
        return [], []


def _tokens(name):
    return set(re.sub(r"[^A-Za-zא-ת0-9 ]", " ", name or "").split())


def _merge_internal_codes(all_items):
    """Map a chain's short internal code to the real barcode it stands for.

    Some chains list packaged goods under the last digits of the barcode
    ("121093" for 7290000121093). Accept a match only when exactly one known
    barcode ends with the code and the names share at least two words.
    """
    known = {}
    for items in all_items:
        for it in items:
            if it["barcode"]:
                known.setdefault(it["barcode"], it["name"])
    by_suffix = defaultdict(list)
    for bc in known:
        by_suffix[bc[-6:]].append(bc)
    merged = 0
    for items in all_items:
        for it in items:
            code = it["code"]
            if it["barcode"] or it["weighted"] or not (5 <= len(code) <= 7):
                continue
            cands = [bc for bc in by_suffix.get(code[-6:], []) if bc.endswith(code)
                     and len(_tokens(known[bc]) & _tokens(it["name"])) >= 2]
            if len(cands) == 1:
                it["barcode"] = cands[0]
                merged += 1
    log.info("matched %d internal codes to barcodes", merged)


def _load_previous(path):
    """Per-store prices from the previous data file, keyed by store id."""
    try:
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        return {}
    codes = [p[0] for p in old.get("products", [])]
    gkeys = [g[0] for g in old.get("generics", [])]
    gprices = old.get("gprices") or [[] for _ in old.get("stores", [])]
    out = {}
    now = datetime.now(timezone.utc)
    for store, flat, gp in zip(old.get("stores", []), old.get("prices", []), gprices):
        store = {**store, "asof": store.get("asof") or old.get("generated")}
        try:
            if now - datetime.fromisoformat(store["asof"]) > MAX_STALE:
                continue
        except (TypeError, ValueError):
            continue
        prices, i = {}, 0
        for k in range(0, len(flat), 2):
            i += flat[k]
            prices[codes[i]] = flat[k + 1] / 100
        out[store["id"]] = {
            "store": store,
            "prices": prices,
            "generics": {gkeys[g]: (p / 100, name) for g, p, name in gp},
            "product_info": {codes[i]: old["products"][i] for i in range(len(codes)) if codes[i] in prices},
        }
    return out


def build(region=config.REGION, workers=6, previous=None):
    sources = list(_sources())
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda s: (s, collect_chain(s, region)), sources))

    _merge_internal_codes([items for _, (_, chain_stores) in results for _, items in chain_stores])
    asof = datetime.now(timezone.utc).isoformat(timespec="minutes")
    previous = previous or {}

    names = defaultdict(Counter)
    makers = defaultdict(Counter)
    info = {}
    stores, store_prices, store_generics = [], [], []
    for source, (region_stores, chain_stores) in results:
        fresh = {store["store_id"] for store, _ in chain_stores}
        for store, items in chain_stores:
            prices = {}
            for item in items:
                bc = item["barcode"]
                if not bc:
                    continue
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
                "asof": asof,
            })
            store_prices.append(prices)
            store_generics.append(generic.match_store(items))

        # A store whose file isn't published yet keeps its previous prices.
        region_ids = {f"{source.chain['key']}-{s['store_id']}" for s in region_stores}
        stale_ids = {sid for sid, old in previous.items() if old["store"]["chain"] == source.chain["key"]}
        if not region_stores:
            region_ids = stale_ids  # the portal itself failed
        for sid in sorted(region_ids & stale_ids):
            if sid.split("-", 1)[1] in fresh:
                continue
            old = previous[sid]
            log.warning("%s: reusing prices from %s", sid, old["store"].get("asof", "?"))
            stores.append(dict(old["store"]))
            store_prices.append(old["prices"])
            store_generics.append({k: [v] for k, v in old["generics"].items()})
            for bc, p in old["product_info"].items():
                if bc not in info:
                    info[bc] = {"manufacturer": p[2], "quantity": None, "unit": "", "weighted": bool(p[4]), "size": p[3]}
                    names[bc][p[1]] += 1
                    if p[2]:
                        makers[bc][p[2]] += 1

    barcodes = sorted(names, key=lambda bc: (-sum(names[bc].values()), bc))
    index = {bc: i for i, bc in enumerate(barcodes)}
    products = []
    for bc in barcodes:
        item = info[bc]
        name = names[bc].most_common(1)[0][0]
        maker = makers[bc].most_common(1)[0][0] if makers[bc] else ""
        size = item["size"] if "size" in item else _size(item)
        products.append([bc, name, maker, size, int(item["weighted"])])

    packed = []
    for prices in store_prices:
        flat, prev = [], 0
        for i, price in sorted((index[bc], p) for bc, p in prices.items()):
            flat += [i - prev, round(price * 100)]
            prev = i
        packed.append(flat)

    catalog = generic.catalog()
    gindex = {key: i for i, (key, *_rest) in enumerate(catalog)}
    gpacked = [
        sorted([gindex[key], round(price * 100), name] for key, (price, name) in chosen.items() if key in gindex)
        for chosen in generic.pick_prices(store_generics)
    ]

    return {
        "generated": asof,
        "region": region["name"],
        "chains": {s.chain["key"]: s.chain["name"] for s in sources},
        "stores": stores,
        "products": products,
        "prices": packed,
        "generics": [list(g) for g in catalog],
        "gprices": gpacked,
    }


def main(out_path):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    data = build(previous=_load_previous(out_path) if os.path.exists(out_path) else None)
    if not data["stores"]:
        log.error("no stores collected, keeping the previous data file")
        sys.exit(1)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    log.info("wrote %s: %d stores, %d products, %d generic products",
             out_path, len(data["stores"]), len(data["products"]), len(data["generics"]))
