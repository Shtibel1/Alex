"""Parsing of PromoFull files into simple, comparable offers.

Chains publish promotions in two layouts:

* Grouped (Shufersal, Rami Levy, Carrefour, Bina chains and most others):
  Promotion > Groups > Group > PromotionItems > PromotionItem, where every item
  carries its own RewardType, MinQty, DiscountRate and DiscountedPrice.
  A single group is a plain deal; two groups are "buy the first group, get a
  discount on the second" (1+1, 2+1, the second at half price).
* Flat (Keshet and other older feeds): the reward fields sit on the Promotion
  itself and the items are listed under PromotionItems > Item.

Only these kinds of deal are kept; everything else (coupons, club and credit
card deals, discounts on the whole basket, gifts of a different product) is skipped:

    unit price    "ב־9.90"         qty=1, total=9.90
    X for Y       "3 ב־20"         qty=3, total=20
    percent off   "20% הנחה"       qty=1, pct=20
    buy X get Y   "2+1", "השני ב־50%"  qty=X, get=Y, pct=discount on the Y units

Some deals only apply when the whole purchase passes an amount ("מעל 75");
that amount is kept as min_basket.
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from .parse import _iter_tag, decode

# RewardType values in the grouped layout.
G_PRICE = {"3"}           # DiscountedPrice is the unit price
G_MULTI = {"1", "10"}     # DiscountedPrice is the price of MinQty units
G_PERCENT = {"2"}         # DiscountRate percent off
G_CONDITION = {"0"}       # the "buy" side of a two-group deal
# RewardType values in the flat layout.
F_MULTI = {"1"}
F_PERCENT = {"2"}
F_BUY_GET = {"9"}

# Chains write "0", "0 - כלל הלקוחות" for everyone; anything else is a club,
# credit card or employee deal.
_ALL_CUSTOMERS = re.compile(r"0(\s*-\s*כלל הלקוחות)?")


def _text(elem, tag):
    for child in elem:
        if child.tag.lower() == tag:
            return (child.text or "").strip()
    return ""


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _when(date_value, hour_value, default_hour):
    """Combine '2026-09-28' or '2026-09-28T02:59:00.000' with an hour field."""
    date = (date_value or "")[:10]
    hour = (hour_value or "")[:5] or (date_value or "")[11:16] or default_hour
    try:
        return datetime.strptime(f"{date} {hour}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _code(value):
    code = (value or "").strip().lstrip("0")
    return code or None


def _pct(rate):
    """Discount percent; the flat layout writes 100% as 10000."""
    rate = _num(rate)
    if rate is None:
        return None
    if rate > 100:
        rate /= 100
    return rate if 0 < rate <= 100 else None


def _offer(qty=1, total=None, get=0, pct=None):
    return {"qty": qty, "total": total, "get": get, "pct": pct}


def _single_group_offer(items):
    """Offer for a one-group deal, from its first item (all items share the reward)."""
    it = items[0]
    rt = _text(it, "rewardtype")
    qty = _num(_text(it, "minqty")) or 1
    price = _num(_text(it, "discountedprice"))
    if _text(it, "bisweighted") == "1":
        return None  # per-kg deals on items sold by weight
    if rt in G_PRICE or (rt in G_MULTI and qty <= 1):
        return _offer(total=price) if price and price > 0 else None
    if rt in G_MULTI:
        if qty != int(qty) or not price or price <= 0:
            return None
        return _offer(qty=int(qty), total=price)
    if rt in G_PERCENT and qty <= 1:
        pct = _pct(_text(it, "discountrate"))
        return _offer(pct=pct) if pct and pct < 100 else None
    return None


def _two_group_offer(buy, get):
    """Buy the first group's MinQty, get the second group's MinQty at a discount."""
    if not all(_text(it, "rewardtype") in G_CONDITION for it in buy):
        return None
    x = _num(_text(buy[0], "minqty")) or 1
    y = _num(_text(get[0], "minqty")) or 1
    pct = _pct(_text(get[0], "discountrate"))
    if not pct or x != int(x) or y != int(y) or not (1 <= x <= 10 and 1 <= y <= 10):
        return None
    return _offer(qty=int(x), get=int(y), pct=pct)


def _grouped(promo):
    groups = []
    for group in _iter_tag(promo, "group"):
        items = [it for it in _iter_tag(group, "promotionitem") if _code(_text(it, "itemcode"))]
        # A group of only "0000000000000" is a basket-total condition ("מעל 75");
        # its amount is picked up by _min_basket.
        if items:
            groups.append(items)
    if len(groups) == 1:
        codes = [_code(_text(it, "itemcode")) for it in groups[0]]
        return _single_group_offer(groups[0]), codes
    if len(groups) == 2:
        buy, get = groups
        # Only deals where the free/discounted unit is the same product.
        get_codes = {_code(_text(it, "itemcode")) for it in get}
        codes = [c for c in (_code(_text(it, "itemcode")) for it in buy) if c in get_codes]
        return _two_group_offer(buy, get), codes
    return None, []


def _flat(promo):
    if _text(promo, "isweightedpromo") == "1":
        return None, []
    items = list(_iter_tag(promo, "item"))
    codes = [c for c in (_code(_text(it, "itemcode")) for it in items) if c]
    rt = _text(promo, "rewardtype")
    qty = _num(_text(promo, "minqty")) or 1
    price = _num(_text(promo, "discountedprice"))
    if qty != int(qty):
        return None, []
    if rt in F_MULTI and price and price > 0:
        return _offer(qty=int(qty), total=price), codes
    if rt in F_PERCENT and qty <= 1:
        pct = _pct(_text(promo, "discountrate"))
        return (_offer(pct=pct) if pct and pct < 100 else None), codes
    if rt in F_BUY_GET and 2 <= qty <= 11:
        pct = _pct(_text(promo, "discountrate"))
        return (_offer(qty=int(qty) - 1, get=1, pct=pct) if pct else None), codes
    return None, []


def _min_basket(promo):
    amounts = [_num((e.text or "").strip()) for e in promo.iter()
               if e.tag.lower() in ("minpurchaseamount", "minpurchaseamnt")]
    return max([a for a in amounts if a] or [0])


def _open_to_all(promo):
    clubs = [(c.text or "").strip() for c in _iter_tag(promo, "clubid")]
    return bool(clubs) and all(_ALL_CUSTOMERS.fullmatch(c) for c in clubs)


def parse_promos(data: bytes):
    """Yield one dict per usable promotion in a PromoFull file.

    Keys: desc, start, end (datetimes), codes (item codes without leading
    zeros), min_basket (0 when none), and the offer: qty, total, get, pct.
    """
    root = ET.fromstring(decode(data))
    for promo in _iter_tag(root, "promotion"):
        # The coupon flag is a direct child in the grouped layout and sits under
        # AdditionalRestrictions in the flat one.
        coupon = any((e.text or "").strip() == "1" for e in _iter_tag(promo, "additionaliscoupon"))
        if coupon or not _open_to_all(promo):
            continue
        is_grouped = any(True for _ in _iter_tag(promo, "group"))
        offer, codes = _grouped(promo) if is_grouped else _flat(promo)
        if not offer or not codes:
            continue
        start = _when(_text(promo, "promotionstartdatetime") or _text(promo, "promotionstartdate"),
                      _text(promo, "promotionstarthour"), "00:00")
        end = _when(_text(promo, "promotionenddatetime") or _text(promo, "promotionenddate"),
                    _text(promo, "promotionendhour"), "23:59")
        if not end:
            continue
        yield {
            "desc": " ".join(_text(promo, "promotiondescription").split()),
            "start": start,
            "end": end,
            "codes": codes,
            "min_basket": _min_basket(promo),
            **offer,
        }


def is_active(promo, now):
    return (promo["start"] is None or promo["start"] <= now) and now <= promo["end"]


def last_day(end):
    """The last shopping day: a deal that ends at 02:59 ended the evening before."""
    return (end - timedelta(hours=6)).date() if end.hour < 6 else end.date()


def unit_price(offer, regular):
    """Effective price of one unit under the offer, given the regular price."""
    if offer["get"]:
        paid = offer["qty"] * regular + offer["get"] * regular * (1 - offer["pct"] / 100)
        return paid / (offer["qty"] + offer["get"])
    if offer["total"]:
        return offer["total"] / offer["qty"]
    return regular * (1 - offer["pct"] / 100)
