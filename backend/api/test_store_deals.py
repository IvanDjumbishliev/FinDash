from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pymupdf
from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.test import APIClient


class BrochureDealTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()

    def test_lidl_dated_brochures_exclude_expired_and_upcoming_weeks(self):
        from api.views.deals import lidl_flyer_is_current

        today = date(2026, 11, 20)
        self.assertFalse(lidl_flyer_is_current("12-11-18-11-weekly", today))
        self.assertFalse(lidl_flyer_is_current("23-11-29-11-weekly", today))
        self.assertTrue(lidl_flyer_is_current("19-11-25-11-weekly", today))
        self.assertTrue(lidl_flyer_is_current("28-12-03-01-weekly", date(2027, 1, 1)))

    @patch("api.views.deals.requests.get")
    def test_lidl_returns_named_priced_products_largest_discount_first(self, get):
        with pymupdf.open() as document:
            page = document.new_page(width=600, height=800)
            page.insert_text((65, 120), "Butter")
            page.insert_text((65, 140), "-10%")
            page.insert_text((65, 160), "2.99 EUR")
            page.insert_text((360, 120), "Milk")
            page.insert_text((360, 140), "-35%")
            page.insert_text((360, 160), "1.29 EUR")
            pdf = document.tobytes()

        get.side_effect = [
            Mock(text="/bg/broshura/weekly/view/flyer/page/1"),
            Mock(json=lambda: {"flyer": {"pdfUrl": "https://example.com/current.pdf"}}),
            Mock(content=pdf),
        ]
        response = self.client.get("/api/deals/lidl/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [
                (deal["name"], deal["price"], deal["discount_percent"])
                for deal in response.data
            ],
            [("Milk", "1,29 €", 35), ("Butter", "2,99 €", 10)],
        )
        for deal in response.data:
            self.assertTrue(deal["image_url"].startswith("data:image/jpeg;base64,"))

    @patch("api.views.deals.fantastico_page_offers")
    @patch("api.views.deals.requests.get")
    def test_fantastico_uses_the_active_brochure_and_returns_products(
        self, get, extract
    ):
        current_url = "https://online.flippingbook.com/view/current/"
        listing = Mock(
            url="https://www.fantastico.bg/special-offers",
            text=(
                '<div class="brochure-switch" data-url="https://online.flippingbook.com/view/old/"></div>'
                f'<div class="brochure-switch active" data-url="{current_url}"></div>'
            ),
        )
        flipbook = Mock(
            text="""
            var initialPolicies = [
                {"PathPrefix": "/current/", "KeyId": "key", "Policy": "policy", "Signature": "signature"}
            ];
            ContentRoot: 'https://example.com/current/',
            TotalPages: 1
        """
        )
        page = Mock(content=b"brochure image")
        get.side_effect = [listing, flipbook, page]
        extract.return_value = [
            {
                "name": "Краве масло",
                "price": "2,99 €",
                "image_url": "data:image/jpeg;base64,AA==",
                "store": "Fantastico",
                "discount_percent": 30,
            }
        ]

        response = self.client.get("/api/deals/fantastico/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, extract.return_value)
        self.assertEqual(get.call_args_list[1].args, (current_url,))
        self.assertEqual(
            get.call_args_list[2].args,
            (
                "https://example.com/current/common/pages/html5substrates/page0001_1.webp",
            ),
        )
        extract.assert_called_once_with(page.content)

    @patch("api.views.deals.subprocess.run")
    def test_bulgarian_ocr_preserves_product_names_and_normalizes_euro(self, run):
        from PIL import Image
        from api.views.deals import recognize_flyer_lines

        run.return_value = SimpleNamespace(
            stderr=b"",
            stdout=(
                "block_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n"
                "1\t1\t1\t12\t20\t50\t20\t95\tКраве\n"
                "1\t1\t1\t65\t20\t50\t20\t95\tмасло\n"
                "2\t1\t1\t14\t95\t42\t20\t95\t2,99\n"
                "2\t1\t1\t65\t95\t14\t20\t95\tЕ\n"
            ).encode(),
        )
        lines = recognize_flyer_lines(Image.new("RGB", (160, 160)))
        self.assertEqual([text for _, text in lines], ["Краве масло", "2,99 €"])
