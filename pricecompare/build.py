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
    promos     [[description, last day, qty, total in agorot, get, percent, min basket in agorot]]
               deals open to every customer (see promos.py); total is 0 for percent /
               buy-get deals, min basket is 0 when the deal has no purchase minimum
    sprices    one list per store, aligned with `stores`, flattened pairs of
               (product index delta, promo index), sorted by product index
"""

import json
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config, generic, promos
from .parse import matches_region, normalize_barcode, parse_prices
from .sources import Bina, Carrefour, Cerberus, Shufersal

log = logging.getLogger("pricecompare")

MAX_STALE = timedelta(days=3)  # older prices are dropped rather than shown as current
LOCAL_TZ = ZoneInfo("Asia/Jerusalem")  # promotion times are local


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


def _store_promos(source, files, store_id):
    """Promotions of one store; a missing or broken promo file only costs the deals."""
    fetch = files.get(store_id)
    if not fetch:
        log.warning("%s store %s: no PromoFull file", source.chain["key"], store_id)
        return []
    try:
        return list(promos.parse_promos(fetch()))
    except Exception:
        log.exception("%s store %s: promotions failed", source.chain["key"], store_id)
        return []


def collect_chain(source, region):
    """Return (all region stores, [(store dict, [items], [promos])] for those with a price file)."""
    key = source.chain["key"]
    try:
        stores = {s["store_id"]: s for s in source.stores() if matches_region(s, region)}
        stores = list(stores.values())
        log.info("%s: %d stores in %s", key, len(stores), region["name"])
        if not stores:
            return [], []
        files = source.latest_price_files([s["store_id"] for s in stores])
        try:
            promo_files = source.latest_promo_files([s["store_id"] for s in stores])
        except Exception:
            log.exception("%s: listing promotions failed", key)
            promo_files = {}
        out = []
        for store in stores:
            fetch = files.get(store["store_id"])
            if not fetch:
                log.warning("%s store %s: no PriceFull file", key, store["store_id"])
                continue
            items = list(parse_prices(fetch()))
            deals = _store_promos(source, promo_files, store["store_id"]) if items else []
            log.info("%s store %s (%s): %d items, %d promotions", key, store["store_id"], store["name"], len(items), len(deals))
            if items:
                out.append((store, items, deals))
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


MAX_DEALS = 3  # per product and store


def match_promos(items, deals, prices, now):
    """{barcode: [deal]} for the store's deals that really lower the price.

    A deal is (description, last day, qty, total in agorot, get, percent, min basket in agorot).
    `prices` is the store's {barcode: regular price}; deals on products the
    store doesn't price, or that cost as much as the regular price, are dropped.
    """
    by_code = {it["code"]: it["barcode"] for it in items if it["barcode"]}
    out = defaultdict(dict)
    for deal in deals:
        if not promos.is_active(deal, now):
            continue
        key = (deal["desc"], promos.last_day(deal["end"]).isoformat(), deal["qty"],
               round((deal["total"] or 0) * 100), deal["get"], deal["pct"] or 0,
               round(deal.get("min_basket", 0) * 100))
        for code in deal["codes"]:
            bc = by_code.get(code) or normalize_barcode(code)
            regular = prices.get(bc)
            if not regular:
                continue
            unit = promos.unit_price(deal, regular)
            if 0 < unit <= regular - 0.01:
                out[bc][key] = unit
    return {bc: [k for k, _ in sorted(found.items(), key=lambda kv: kv[1])[:MAX_DEALS]]
            for bc, found in out.items()}


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
    table = [tuple(d) for d in old.get("promos", [])]
    sprices = old.get("sprices") or [[] for _ in old.get("stores", [])]
    out = {}
    now = datetime.now(timezone.utc)
    today = datetime.now(LOCAL_TZ).date().isoformat()
    for store, flat, gp, sp in zip(old.get("stores", []), old.get("prices", []), gprices, sprices):
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
        deals, i = defaultdict(list), 0
        for k in range(0, len(sp), 2):
            i += sp[k]
            deal = table[sp[k + 1]]
            if deal[1] >= today:
                deals[codes[i]].append(deal)
        out[store["id"]] = {
            "store": store,
            "prices": prices,
            "generics": {gkeys[g]: (p / 100, name) for g, p, name in gp},
            "promos": dict(deals),
            "product_info": {codes[i]: old["products"][i] for i in range(len(codes)) if codes[i] in prices},
        }
    return out


def build(region=config.REGION, workers=6, previous=None):
    sources = list(_sources())
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda s: (s, collect_chain(s, region)), sources))

    _merge_internal_codes([items for _, (_, chain_stores) in results for _, items, _ in chain_stores])
    asof = datetime.now(timezone.utc).isoformat(timespec="minutes")
    previous = previous or {}

    names = defaultdict(Counter)
    makers = defaultdict(Counter)
    info = {}
    stores, store_prices, store_generics, store_promos = [], [], [], []
    now = datetime.now(LOCAL_TZ).replace(tzinfo=None)
    for source, (region_stores, chain_stores) in results:
        fresh = {store["store_id"] for store, _, _ in chain_stores}
        for store, items, deals in chain_stores:
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
            store_promos.append(match_promos(items, deals, prices, now))

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
            store_promos.append(old.get("promos", {}))
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

    table, tindex, spacked = [], {}, []
    for deals in store_promos:
        flat, prev = [], 0
        for i, bc in sorted((index[bc], bc) for bc in deals if bc in index):
            for deal in deals[bc]:
                if deal not in tindex:
                    tindex[deal] = len(table)
                    table.append(deal)
                flat += [i - prev, tindex[deal]]
                prev = i
        spacked.append(flat)

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
        "promos": [list(d) for d in table],
        "sprices": spacked,
    }


def main(out_path):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    data = build(previous=_load_previous(out_path) if os.path.exists(out_path) else None)
    if not data["stores"]:
        log.error("no stores collected, keeping the previous data file")
        sys.exit(1)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    log.info("wrote %s: %d stores, %d products, %d generic products, %d promotions",
             out_path, len(data["stores"]), len(data["products"]), len(data["generics"]), len(data["promos"]))
