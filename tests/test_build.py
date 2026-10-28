import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from pricecompare.build import LOCAL_TZ, _load_previous, _merge_internal_codes, _size


class BuildHelpersTest(unittest.TestCase):
    def test_size_formats_quantities_and_omits_single_unit(self):
        self.assertEqual(_size({"quantity": 500, "unit": "גרם"}), "500 גרם")
        self.assertEqual(_size({"quantity": 1.5, "unit": "ליטר"}), "1.5 ליטר")
        self.assertEqual(_size({"quantity": 1, "unit": "יח'"}), "")
        self.assertEqual(_size({"quantity": 1, "unit": "יחידות"}), "")
        self.assertEqual(_size({"quantity": 0, "unit": "גרם"}), "")
        self.assertEqual(_size({"quantity": 250, "unit": ""}), "")

    def test_merge_internal_codes_links_unique_suffix_with_shared_tokens(self):
        store_a = [
            {
                "code": "7290000121093",
                "barcode": "7290000121093",
                "name": "חלב תנובה 3% קרטון 1 ליטר",
                "weighted": False,
            }
        ]
        store_b = [
            {
                "code": "121093",
                "barcode": None,
                "name": "חלב תנובה 3% 1 ליטר",
                "weighted": False,
            },
            {
                "code": "121093",
                "barcode": None,
                "name": "חלב תנובה משקל",
                "weighted": True,
            },
            {
                "code": "121093",
                "barcode": None,
                "name": "שוקו יטבתה",
                "weighted": False,
            },
        ]
        _merge_internal_codes([store_a, store_b])
        self.assertEqual(store_b[0]["barcode"], "7290000121093")
        self.assertIsNone(store_b[1]["barcode"])
        self.assertIsNone(store_b[2]["barcode"])

    def test_merge_internal_codes_skips_ambiguous_suffixes(self):
        known = [
            {
                "code": "7290000121093",
                "barcode": "7290000121093",
                "name": "חלב תנובה 3%",
                "weighted": False,
            },
            {
                "code": "7290009121093",
                "barcode": "7290009121093",
                "name": "חלב תנובה 1%",
                "weighted": False,
            },
        ]
        target = [
            {
                "code": "121093",
                "barcode": None,
                "name": "חלב תנובה בקרטון",
                "weighted": False,
            }
        ]
        _merge_internal_codes([known, target])
        self.assertIsNone(target[0]["barcode"])

    def test_load_previous_unpacks_delta_prices_and_drops_stale_stores(self):
        now = datetime.now(timezone.utc)
        fresh_asof = (now - timedelta(hours=6)).isoformat(timespec="minutes")
        stale_asof = (now - timedelta(days=5)).isoformat(timespec="minutes")
        tomorrow = (datetime.now(LOCAL_TZ).date() + timedelta(days=1)).isoformat()
        yesterday = (datetime.now(LOCAL_TZ).date() - timedelta(days=1)).isoformat()

        bundle = {
            "generated": fresh_asof,
            "products": [
                ["7290000000011", "מוצר א", "יצרן א", "500 גרם", 0],
                ["7290000000028", "מוצר ב", "יצרן ב", "1 ליטר", 0],
                ["7290000000035", "מוצר ג", "יצרן ג", "200 גרם", 0],
            ],
            "generics": [
                ["tomato", "עגבנייה", "ירקות", "ק״ג"],
            ],
            "promos": [
                ["2 ב-15", tomorrow, 2, 1500, 0, 0, 0],
                ["מבצע שפג", yesterday, 1, 500, 0, 0, 0],
            ],
            "stores": [
                {"id": "shufersal-1", "chain": "shufersal", "name": "חדרה", "address": "הרברט סמואל", "items": 2, "asof": fresh_asof},
                {"id": "ramilevy-2", "chain": "ramilevy", "name": "חדרה ישן", "address": "שדרות חופים", "items": 1, "asof": stale_asof},
            ],
            "prices": [
                [0, 990, 2, 1450],
                [1, 1200],
            ],
            "gprices": [
                [[0, 690, "עגבנייה חממה"]],
                [],
            ],
            "sprices": [
                [0, 0, 2, 1],
                [],
            ],
        }

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as f:
            json.dump(bundle, f, ensure_ascii=False)
            path = f.name

        try:
            loaded = _load_previous(path)
        finally:
            os.remove(path)

        self.assertIn("shufersal-1", loaded)
        self.assertNotIn("ramilevy-2", loaded)

        st = loaded["shufersal-1"]
        self.assertEqual(st["prices"], {"7290000000011": 9.9, "7290000000035": 14.5})
        self.assertEqual(st["generics"], {"tomato": (6.9, "עגבנייה חממה")})
        self.assertEqual(
            st["promos"],
            {"7290000000011": [("2 ב-15", tomorrow, 2, 1500, 0, 0, 0)]},
        )


if __name__ == "__main__":
    unittest.main()
