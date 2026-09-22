import unittest

from pricecompare import generic


def item(name, price, weighted=True, quantity=1.0, unit="קילוגרם"):
    return {"name": name, "price": price, "weighted": weighted, "quantity": quantity, "unit": unit}


def matches(items):
    return {key: sorted(n for _, n in found) for key, found in generic.match_store(items).items()}


class GenericTest(unittest.TestCase):
    def test_fresh_chicken_breast_excludes_frozen_ground_and_turkey(self):
        m = matches([
            item("חזה עוף טרי ארוז", 39.9),
            item("חזה עוף ארוז קפוא", 35.9),
            item("חזה עוף טחון עטרה", 39.9),
            item("חזה הודו טרי", 44.9),
            item("פילה לברק בסט פיש קפ", 34.9),  # name cut short: "קפ" = frozen
        ])
        self.assertEqual(m["chicken-breast"], ["חזה עוף טרי ארוז"])
        self.assertIn("חזה עוף ארוז קפוא", m["chicken-breast-frozen"])
        self.assertNotIn("fish-sea-bass", m)

    def test_produce_must_start_with_the_name_and_be_sold_by_weight(self):
        m = matches([
            item("עגבניה", 5.9),
            item("רוטב עגבניות שרי", 15.1, weighted=False, quantity=400, unit="גרם"),
            item("בננה", 9.9),
            item("משקה חלב בננה", 6.4, weighted=False, quantity=250, unit="מיליליטר"),
        ])
        self.assertEqual(m["veg-tomato"], ["עגבניה"])
        self.assertEqual(m["fruit-banana"], ["בננה"])
        self.assertNotIn("veg-tomato-cherry", m)

    def test_eggs_need_size_and_count_and_skip_premium(self):
        m = matches([
            item("12 ביצי משק טריות L לסר", 14.24, weighted=False, unit="יחידות"),
            item("ביצים 12 יח בינוני", 13.13, weighted=False, unit="יחידות"),
            item("ביצים אומגה3 12יחידות L", 23.9, weighted=False, unit="יחידות"),
            item("ביצים 30יח ענק XL", 38.5, weighted=False, unit="יחידות"),
            item("אטריות ביצים 500", 9.9, weighted=False, quantity=500, unit="גרם"),
        ])
        self.assertEqual(m["eggs-l-12"], ["12 ביצי משק טריות L לסר"])
        self.assertEqual(m["eggs-m-12"], ["ביצים 12 יח בינוני"])
        self.assertNotIn("eggs-l-30", m)

    def test_pick_cheapest_but_ignore_implausibly_cheap(self):
        stores = [
            {"veg-tomato": [(6.9, "עגבניה"), (5.9, "עגבניה ארוזה")]},
            {"veg-tomato": [(1.0, "עגבניה (שגיאה)"), (7.9, "עגבניה")]},
            {"veg-tomato": [(6.9, "עגבניה")]},
        ]
        picked = generic.pick_prices(stores)
        self.assertEqual(picked[0]["veg-tomato"], (5.9, "עגבניה ארוזה"))
        self.assertEqual(picked[1]["veg-tomato"], (7.9, "עגבניה"))


if __name__ == "__main__":
    unittest.main()
