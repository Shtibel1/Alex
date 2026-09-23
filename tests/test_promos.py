import gzip
import unittest
from datetime import datetime

from pricecompare.build import match_promos
from pricecompare.promos import last_day, parse_promos, unit_price


def grouped(desc, groups, club="0 - כלל הלקוחות", coupon="0", end="2026-10-03T02:59:00.000", min_basket=""):
    """A promotion in the grouped layout; groups are lists of item tuples
    (code, reward type, min qty, discount rate, discounted price, weighted)."""
    xml_groups = "".join(
        f"<Group><GroupID>{n}</GroupID><MinPurchaseAmount>{min_basket if n == 1 else ''}</MinPurchaseAmount>"
        f"<PromotionItems>" + "".join(
            f"<PromotionItem><ItemCode>{c}</ItemCode><RewardType>{rt}</RewardType><MinQty>{q}</MinQty>"
            f"<DiscountRate>{rate}</DiscountRate><DiscountedPrice>{price}</DiscountedPrice>"
            f"<bIsWeighted>{w}</bIsWeighted></PromotionItem>"
            for c, rt, q, rate, price, w in items) + "</PromotionItems></Group>"
        for n, items in enumerate(groups, 1))
    return (f"<Promotion><PromotionID>1</PromotionID><PromotionDescription>{desc}</PromotionDescription>"
            f"<PromotionStartDateTime>2026-09-01T00:00:00.000</PromotionStartDateTime>"
            f"<PromotionEndDateTime>{end}</PromotionEndDateTime><PromotionStartHour>00:00:00.000</PromotionStartHour>"
            f"<PromotionEndHour>{end[11:]}</PromotionEndHour><ClubID>{club}</ClubID>"
            f"<AdditionalIsCoupon>{coupon}</AdditionalIsCoupon><Groups>{xml_groups}</Groups></Promotion>")


def flat(desc, reward, min_qty, price="", rate="", club="0", codes=("7290000066318",)):
    items = "".join(f"<Item><ItemCode>{c}</ItemCode><ItemType>1</ItemType><IsGiftItem>0</IsGiftItem></Item>" for c in codes)
    return (f"<Promotion><PromotionId>9</PromotionId><PromotionDescription>{desc}</PromotionDescription>"
            f"<PromotionStartDate>2026-09-01</PromotionStartDate><PromotionStartHour>00:00:00</PromotionStartHour>"
            f"<PromotionEndDate>2026-09-28</PromotionEndDate><PromotionEndHour>23:59:00</PromotionEndHour>"
            f"<RewardType>{reward}</RewardType><AdditionalRestrictions><AdditionalIsCoupon>0</AdditionalIsCoupon>"
            f"</AdditionalRestrictions><MinQty>{min_qty}</MinQty><DiscountedPrice>{price}</DiscountedPrice>"
            f"<DiscountRate>{rate}</DiscountRate><PromotionItems Count=\"1\">{items}</PromotionItems>"
            f"<Clubs><ClubId>{club}</ClubId></Clubs></Promotion>")


def parse(*promos):
    xml = "<Root><Promotions>" + "".join(promos) + "</Promotions></Root>"
    return list(parse_promos(gzip.compress(xml.encode())))


def offer(p):
    return (p["qty"], p["total"], p["get"], p["pct"])


BAMBA = "7290000066318"


class GroupedTest(unittest.TestCase):
    def test_unit_price(self):
        [p] = parse(grouped("במבה ב4.90", [[(BAMBA, 3, "1.00", "20", "4.90", 0)]]))
        self.assertEqual(offer(p), (1, 4.9, 0, None))
        self.assertEqual(p["codes"], [BAMBA])
        self.assertEqual(p["desc"], "במבה ב4.90")

    def test_x_for_y(self):
        [p] = parse(grouped("3ב10", [[(BAMBA, 10, "3.00", "", "10.00", 0), ("07290000066325", 10, "3.00", "", "10.00", 0)]]))
        self.assertEqual(offer(p), (3, 10.0, 0, None))
        self.assertEqual(p["codes"], [BAMBA, "7290000066325"])

    def test_percent(self):
        [p] = parse(grouped("30% הנחה", [[(BAMBA, 2, "1", "30.00", "3.43", 0)]]))
        self.assertEqual(offer(p), (1, None, 0, 30.0))

    def test_buy_x_get_y(self):
        [p] = parse(grouped("2+1", [[(BAMBA, 0, "2.00", "", "", 0)], [(BAMBA, 1, "1.00", "100", "0.00", 0)]]))
        self.assertEqual(offer(p), (2, None, 1, 100.0))

    def test_second_at_half_price(self):
        [p] = parse(grouped("השני בחצי", [[(BAMBA, 0, "1", "", "", 0)], [(BAMBA, 10, "1", "50.00", "2.45", 0)]]))
        self.assertEqual(offer(p), (1, None, 1, 50.0))

    def test_basket_total_condition_is_ignored(self):
        [p] = parse(grouped("ב4.90 מעל 75", [[("0000000000000", 0, "1", "", "", 0)], [(BAMBA, 3, "1", "", "4.90", 0)]],
                            min_basket="75.00"))
        self.assertEqual(offer(p), (1, 4.9, 0, None))
        self.assertEqual(p["min_basket"], 75)
        [p] = parse(grouped("ב4.90", [[(BAMBA, 3, "1", "", "4.90", 0)]], min_basket="0.00"))
        self.assertEqual(p["min_basket"], 0)

    def test_skips_clubs_coupons_gifts_and_weighted(self):
        item = [(BAMBA, 3, "1", "", "4.90", 0)]
        self.assertEqual(parse(
            grouped("מועדון", [item], club="1 - מועדון עובדים"),
            grouped("אשראי", [item], club="(2=מועדון קרפור אשראי|2=מועדון אפליקציה)"),
            grouped("קופון", [item], coupon="1"),
            grouped("מתנה", [[(BAMBA, 2, "1", "100", "0.00", 0)]]),
            grouped("בשר לקג", [[(BAMBA, 10, "0.010", "", "79.90", 1)]]),
            grouped("סל", [[("0000000000000", 12, "1", "", "", 0)]]),
        ), [])

    def test_last_day(self):
        [p] = parse(grouped("x", [[(BAMBA, 3, "1", "", "4.90", 0)]]))
        self.assertEqual(p["end"], datetime(2026, 10, 3, 2, 59))
        self.assertEqual(str(last_day(p["end"])), "2026-10-02")
        self.assertEqual(str(last_day(datetime(2026, 9, 28, 23, 59))), "2026-09-28")


class FlatTest(unittest.TestCase):
    def test_x_for_y_and_unit_price(self):
        a, b = parse(flat("2 ב 14.90", 1, "2.00", price="14.90"), flat("ב 9.90", 1, "1.00", price="9.90"))
        self.assertEqual(offer(a), (2, 14.9, 0, None))
        self.assertEqual(offer(b), (1, 9.9, 0, None))
        self.assertEqual(str(last_day(a["end"])), "2026-09-28")

    def test_buy_get_rate_in_hundredths(self):
        [p] = parse(flat("2+1", 9, "3.00", rate="10000"))
        self.assertEqual(offer(p), (2, None, 1, 100.0))

    def test_skips_club(self):
        self.assertEqual(parse(flat("מועדון", 1, "1", price="5", club="1")), [])


class MatchTest(unittest.TestCase):
    NOW = datetime(2026, 9, 23, 12, 0)

    def deal(self, **kw):
        base = {"desc": "d", "start": datetime(2026, 9, 1), "end": datetime(2026, 10, 3, 2, 59),
                "codes": [BAMBA], "qty": 1, "total": None, "get": 0, "pct": None}
        return {**base, **kw}

    def test_unit_price(self):
        self.assertEqual(unit_price(self.deal(qty=2, total=15), 9.9), 7.5)
        self.assertAlmostEqual(unit_price(self.deal(qty=2, get=1, pct=100), 9), 6)
        self.assertAlmostEqual(unit_price(self.deal(qty=1, get=1, pct=50), 10), 7.5)
        self.assertAlmostEqual(unit_price(self.deal(pct=20), 10), 8)

    def test_keeps_real_discounts_best_first(self):
        deals = [self.deal(desc="a", total=4.5), self.deal(desc="b", qty=3, total=12), self.deal(desc="c", total=5)]
        got = match_promos([], deals, {BAMBA: 5.0}, self.NOW)
        self.assertEqual([d[0] for d in got[BAMBA]], ["b", "a"])
        self.assertEqual(got[BAMBA][0], ("b", "2026-10-02", 3, 1200, 0, 0, 0))

    def test_drops_inactive_and_unpriced(self):
        deals = [self.deal(end=datetime(2026, 9, 20)), self.deal(start=datetime(2026, 9, 30)),
                 self.deal(codes=["7290000000001"], total=1)]
        self.assertEqual(match_promos([], deals, {BAMBA: 5.0}, self.NOW), {})

    def test_internal_codes_follow_the_price_file(self):
        items = [{"code": "66318", "barcode": BAMBA}]
        got = match_promos(items, [self.deal(codes=["66318"], total=4)], {BAMBA: 5.0}, self.NOW)
        self.assertIn(BAMBA, got)


if __name__ == "__main__":
    unittest.main()
