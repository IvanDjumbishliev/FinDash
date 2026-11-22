"""Exercise the product library with private synthetic receipt history."""
from datetime import timedelta
from uuid import uuid4

import requests

from browser_harness import Browser, ROOT, browser_test_password, main, wait_for


def seed_receipts(temporary, username):
    import os
    import sys

    os.environ["DJANGO_SETTINGS_MODULE"] = "backend.settings"
    sys.path.insert(0, str(ROOT / "backend"))
    import django
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    settings.DATABASES["default"] = {"ENGINE": "django.db.backends.sqlite3", "NAME": temporary + "/test.sqlite3"}
    django.setup()
    from api.models import GroceryCatalogRefresh, GroceryOffer, Receipt, ReceiptItem
    from api.services.receipts import SOFIA

    owner = get_user_model().objects.get(username=username)
    now = timezone.now()
    today = timezone.localdate(now, SOFIA)
    GroceryCatalogRefresh.objects.create(retailer="lidl", last_attempt_at=now, last_success_at=now, status="success")
    GroceryOffer.objects.create(
        retailer="lidl", product_name="milk", normalized_name="milk", fingerprint="alert-test",
        price="2.00", currency="EUR", quantity=1, measurement_unit="l", pack_count=1,
        starts_on=today, expires_on=today + timedelta(days=1), last_successful_update=now, availability_status="advertised",
    )
    for day in (1, 3, 5):
        receipt = Receipt.objects.create(owner=owner, merchant="Fixture Market", normalized_merchant="fixture market",
                                         currency="EUR", purchased_at=timezone.now() - timedelta(days=day), total="4.00",
                                         fingerprint=str(day), image_digest=str(day), source="upload")
        for food in ("milk", "bread"):
            ReceiptItem.objects.create(receipt=receipt, original_description=food, normalized_name=food, line_total="2.00")


def run(base, site, driver, firefox, temporary):
    username = f"products-{uuid4().hex[:8]}"
    account = requests.post(f"{base}/api/user/register/", json={
        "username": username, "password": browser_test_password(),
    }, timeout=5)
    account.raise_for_status()
    seed_receipts(temporary, username)
    browser = Browser(driver, firefox)
    try:
        browser.navigate(f"{site}/login")
        browser.execute("localStorage.setItem('access', arguments[0]);", account.json()["access"])
        browser.navigate(f"{site}/my-products")
        wait_for(lambda: browser.execute("return document.body.textContent.includes('Turn on receipt-based suggestions');"))
        assert browser.click("Add a product")
        browser.change(".product-editor input", "Carrots")
        assert browser.click("Add product")
        wait_for(lambda: browser.click("Edit Carrots"))
        browser.execute("""
            const editor = document.querySelector('.product-editor');
            [...editor.querySelectorAll('label')].find(label => label.textContent.includes('Mute product')).querySelector('input').click();
        """)
        assert browser.click("Save product")
        wait_for(lambda: browser.execute("return document.querySelector('.product-list').textContent.includes('Muted');"))
        browser.execute("document.querySelector('.product-settings-fields input').click();")
        assert browser.click("Save shopping settings")
        wait_for(lambda: browser.click("Approve milk"))
        wait_for(lambda: browser.execute("""
            return [...document.querySelectorAll('.product-layout .product-list h3')].filter(el => el.textContent.trim() === 'milk').length === 1
                && document.querySelector('.product-layout').textContent.includes('From receipts');
        """))
        browser.execute("""
            [...document.querySelectorAll('.product-deal-settings label')]
                .find(label => label.textContent.includes('Enable in-app deal alerts')).querySelector('input').click();
        """)
        assert browser.click("Save shopping settings")
        wait_for(lambda: browser.click("Edit milk"))
        browser.execute("""
            [...document.querySelectorAll('.product-editor label')]
                .find(label => label.textContent.includes('Allow deal alerts')).querySelector('input').click();
        """)
        assert browser.click("Save product")
        wait_for(lambda: browser.click("Track expiry"))
        wait_for(lambda: browser.execute("return document.body.textContent.includes('Expiry tracked');"))
        from django.contrib.auth import get_user_model
        from api.services.deal_alerts import evaluate_deal_alerts

        owner = get_user_model().objects.get(username=username)
        assert evaluate_deal_alerts(owner) == 1
        browser.navigate(f"{site}/notifications")
        wait_for(lambda: browser.execute("""
            const alert = document.querySelector('.notification-deal-details');
            return alert?.textContent.includes('milk') && alert.textContent.includes('Lidl')
                && alert.textContent.includes('2.00') && alert.textContent.includes('favorited product');
        """))
        browser.navigate(f"{site}/my-products")
        wait_for(lambda: browser.execute("return document.body.textContent.includes('Reject bread');"))
        assert browser.click("Reject bread")
        wait_for(lambda: browser.execute("return document.querySelector('.product-layout').textContent.includes('Excluded');"))
        assert browser.click("Clear inferred preferences")
        assert browser.click("Clear inferred products")
        wait_for(lambda: browser.execute("""
            const library = document.querySelector('.product-layout').querySelector('.product-list');
            return library.textContent.includes('Carrots') && library.children.length === 1;
        """))
        browser.execute("""
            const frame = document.createElement('iframe');
            frame.id = 'products-mobile';
            frame.src = '/my-products';
            frame.width = '320'; frame.height = '700';
            document.body.append(frame);
        """)
        wait_for(lambda: browser.execute("""
            const doc = document.querySelector('#products-mobile').contentDocument;
            return doc.querySelector('.product-list')?.textContent.includes('Carrots') && doc.documentElement.scrollWidth <= 320;
        """))
        print("Passed manual save, mute, consent, approval, rejection, clearing inferred preferences, per-product alerts, expiry tracking, inbox details and 320px layout.")
    finally:
        browser.close()


if __name__ == "__main__":
    main(run)
