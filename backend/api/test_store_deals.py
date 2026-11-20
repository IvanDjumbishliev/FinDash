import json
from html import escape
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.test import APIClient


class BrochureDealTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()

    @patch("api.views.deals.time", return_value=100)
    @patch("api.views.deals.requests.get")
    def test_lidl_serves_current_products_with_official_photos(self, get, now):
        product = {
            "fullTitle": "Краве масло",
            "storeStartDate": 90,
            "storeEndDate": 110,
            "imageList_V1": [{"image": "/assets/butter.png"}],
            "price": {"price": 2.99, "oldPrice": 3.99, "displayedCurrency": "€"},
        }
        expired = {**product, "storeEndDate": 99, "fullTitle": "Изтекла оферта"}
        future = {**product, "storeStartDate": 101, "fullTitle": "Бъдеща оферта"}
        get.return_value = Mock(text="".join(
            f'<div data-grid-data="{escape(json.dumps(tile), quote=True)}"></div>'
            for tile in (product, expired, future)
        ))
        response = self.client.get("/api/deals/lidl/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [{
            "name": "Краве масло",
            "price": "2,99 €",
            "image_url": "https://www.lidl.bg/assets/butter.png",
            "store": "Lidl",
            "discount_percent": 25,
            "price_note": "",
        }])

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
                {"PathPrefix": "://example.com/current/", "KeyId": "key", "Policy": "policy", "Signature": "signature"}
            ];
            ContentRoot: 'https://example.com/current/',
            TotalPages: 1
        """
        )
        pager = Mock(json=lambda: {"pages": {"defaults": {"width": 581, "height": 836}, "1": {}}})
        search_text = "€|бр.\x02100\x02200\x020\x02112\x0253"
        search = Mock(content=search_text.encode())
        page = Mock(content=b"brochure image")
        get.side_effect = [listing, flipbook, pager, search, page]
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
            [call.args[0] for call in get.call_args_list[2:]],
            [
                "https://example.com/current/common/pager.json",
                "https://example.com/current/flash/search/search0001.xml",
                "https://example.com/current/common/pages/html5substrates/page0001_2.webp",
            ],
        )
        extract.assert_called_once_with(search_text, page.content, 581, 836)

    def test_fantastico_pairs_searchable_product_words_with_price_and_photo(self):
        from io import BytesIO

        from PIL import Image

        from api.views.deals import fantastico_page_offers

        # Coordinates are in tenths of the brochure page units.
        text = "\n".join(
            "\x02".join(map(str, (*row[:3], 0, *row[3:])))
            for row in [
                ("Краве", 900, 2800, 112, 250),
                ("масло", 1170, 2800, 112, 260),
                ("2.99", 900, 3100, 503, "195\x04600"),
                ("€|бр.", 1150, 3420, 112, 140),
                ("-25%", 1150, 3540, 160, 230),
            ]
        )
        with BytesIO() as image:
            Image.new("RGB", (581, 836), "orange").save(image, "PNG")
            offers = fantastico_page_offers(text, image.getvalue(), 581, 836)

        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["name"], "Краве масло")
        self.assertEqual(offers[0]["price"], "2,99 €")
        self.assertEqual(offers[0]["discount_percent"], 25)
        self.assertTrue(offers[0]["image_url"].startswith("data:image/jpeg;base64,"))
