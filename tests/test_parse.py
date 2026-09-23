import gzip
import io
import unittest
import zipfile

from pricecompare.parse import (
    file_store_and_time, matches_region, normalize_barcode, parse_prices, parse_stores,
)
from pricecompare.config import REGION

PRICES = """<?xml version="1.0" encoding="utf-8"?>
<Root><ChainId>1</ChainId><Items Count="3">
  <Item><ItemCode>07290000066318</ItemCode><ItemName>במבה 80 גרם</ItemName>
    <ManufacturerName>אסם</ManufacturerName><Quantity>80.00</Quantity><UnitQty>גרם</UnitQty>
    <bIsWeighted>0</bIsWeighted><ItemPrice>4.90</ItemPrice></Item>
  <Item><ItemCode>3329</ItemCode><ItemName>עגבניות</ItemName><ItemPrice>6.90</ItemPrice></Item>
  <Item><ItemCode>7290000000001</ItemCode><ItemName>מוצר בחינם</ItemName><ItemPrice>0</ItemPrice></Item>
</Items></Root>"""

STORES = """<Root><SubChains><SubChain><Stores>
  <Store><StoreID>044</StoreID><StoreName>חדרה</StoreName><Address>השלום 1</Address><City>6500</City></Store>
  <Store><StoreID>001</StoreID><StoreName>ירושלים</StoreName><Address>יפו 1</Address><City>3000</City></Store>
  <Store><StoreID>022</StoreID><StoreName>חדרה צפוני</StoreName><Address>unknown</Address><City>0</City></Store>
</Stores></SubChain></SubChains></Root>"""


class ParseTest(unittest.TestCase):
    def test_prices_keep_priced_items_and_flag_internal_codes(self):
        items = list(parse_prices(gzip.compress(PRICES.encode())))
        self.assertEqual([i["barcode"] for i in items], ["7290000066318", None])
        self.assertEqual(items[0]["price"], 4.9)
        self.assertEqual(items[0]["manufacturer"], "אסם")
        self.assertEqual(items[1]["code"], "3329")

    def test_utf16_stores_and_region_filter(self):
        stores = list(parse_stores(b"\xff\xfe" + STORES.encode("utf-16-le")))
        self.assertEqual([s["store_id"] for s in stores], ["44", "1", "22"])
        self.assertEqual([s["store_id"] for s in stores if matches_region(s, REGION)], ["44", "22"])

    def test_zipped_file(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("Stores.xml", STORES)
        self.assertEqual(len(list(parse_stores(buf.getvalue()))), 3)

    def test_file_names(self):
        self.assertEqual(file_store_and_time("PriceFull7290058140886-001-044-20260922-120023.gz"), ("44", "20260922120023"))
        self.assertEqual(file_store_and_time("PriceFull7290785400000-025-202609220010.gz"), ("25", "202609220010"))

    def test_barcodes(self):
        self.assertEqual(normalize_barcode("0072900001"), "72900001")
        self.assertIsNone(normalize_barcode("3329"))


if __name__ == "__main__":
    unittest.main()
