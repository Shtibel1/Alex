"""Parsing of the XML files published under the Price Transparency Law.

Chains follow the same schema loosely: tag case differs (StoreID / StoreId /
STOREID), files may be gzip'ed, zipped or plain, and the encoding is UTF-8 or UTF-16.
Everything here normalises tag names to lower case.
"""

import gzip
import io
import re
import zipfile
import xml.etree.ElementTree as ET


def decode(data: bytes) -> str:
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    elif data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            data = z.read(z.namelist()[0])
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = data.decode("utf-16")
    else:
        text = data.decode("utf-8-sig", errors="replace")
    # ElementTree refuses a str that still carries an encoding declaration
    # that disagrees with it, so drop the declaration.
    return re.sub(r"^\s*<\?xml[^>]*\?>", "", text)


def _children(elem):
    return {child.tag.lower(): (child.text or "").strip() for child in elem}


def _iter_tag(root, tag):
    for elem in root.iter():
        if elem.tag.lower() == tag:
            yield elem


def parse_stores(data: bytes):
    """Yield dicts with store_id, name, address, city from a Stores file."""
    root = ET.fromstring(decode(data))
    for store in _iter_tag(root, "store"):
        f = _children(store)
        if not f.get("storeid"):
            continue
        yield {
            "store_id": normalize_store_id(f["storeid"]),
            "name": " ".join(f.get("storename", "").split()),
            "address": " ".join(f.get("address", "").split()),
            "city": f.get("city", ""),
        }


def normalize_store_id(value: str) -> str:
    value = value.strip()
    return str(int(value)) if value.isdigit() else value


def normalize_barcode(code: str):
    """Return a cross-chain comparable barcode, or None for internal codes.

    Chains use short internal codes for produce, bakery etc.; only real
    EAN/UPC barcodes identify the same product in different chains.
    """
    code = code.strip().lstrip("0")
    if not code.isdigit() or len(code) < 7:
        return None
    return code


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_prices(data: bytes):
    """Yield one dict per priced item from a PriceFull file.

    `barcode` is the cross-chain barcode, or None for the chain's internal
    codes (produce, meat, bakery); those still count for generic products.
    """
    root = ET.fromstring(decode(data))
    for item in _iter_tag(root, "item"):
        f = _children(item)
        price = _to_float(f.get("itemprice"))
        if not price or price <= 0:
            continue
        code = f.get("itemcode", "").strip()
        yield {
            "code": code.lstrip("0"),
            "barcode": normalize_barcode(code),
            "name": " ".join((f.get("itemname") or f.get("itemnm") or "").split()),
            "manufacturer": " ".join(f.get("manufacturername", f.get("manufacturename", "")).split()),
            "quantity": _to_float(f.get("quantity")),
            "unit": " ".join(f.get("unitqty", "").split()),
            "weighted": f.get("bisweighted", "0") == "1",
            "price": price,
        }


def file_store_and_time(filename: str):
    """Extract (store_id, timestamp) from a price file name.

    Handles both PriceFull<chain>-<sub>-<store>-<yyyymmdd>-<hhmm[ss]>.gz and
    the shorter PriceFull<chain>-<store>-<yyyymmddhhmm>.gz (Keshet).
    """
    stem = re.sub(r"\.(gz|xml|zip)$", "", filename.split("/")[-1], flags=re.I)
    parts = stem.split("-")
    for i, part in enumerate(parts):
        if i >= 2 and part.isdigit() and len(part) >= 8:
            return normalize_store_id(parts[i - 1]), "".join(parts[i:])
        if i == 1 and part.isdigit() and len(part) >= 8:
            return None, None
    return None, None


def matches_region(store, region) -> bool:
    if store["city"] in region["city_codes"]:
        return True
    haystack = " ".join((store["name"], store["address"], store["city"]))
    return any(name in haystack for name in region["names"])
