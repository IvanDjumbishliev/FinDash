"""Check My Deals controls and the authenticated optimizer handoff."""
import os
import sys
from datetime import timedelta
from uuid import uuid4

import requests

from browser_harness import Browser, ROOT, browser_test_password, main, wait_for


def seed(temporary, username):
    os.environ["DJANGO_SETTINGS_MODULE"] = "backend.settings"
    sys.path.insert(0, str(ROOT / "backend"))
    import django
    from django.conf import settings

    settings.DATABASES["default"] = {"ENGINE": "django.db.backends.sqlite3", "NAME": temporary + "/test.sqlite3"}
    django.setup()
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from api.models import GroceryCatalogRefresh, GroceryOffer, ProductPreference, Receipt, ReceiptItem, ShoppingPersonalization
    from api.services.receipts import SOFIA

    owner = get_user_model().objects.get(username=username)
    now = timezone.now()
    day = timezone.localdate(now, SOFIA)
    ShoppingPersonalization.objects.create(owner=owner, automatic_enabled=True)
    preference = ProductPreference.objects.create(owner=owner, name="Milk", normalized_name="milk", favorite=False)
    GroceryCatalogRefresh.objects.create(retailer="lidl", last_attempt_at=now, last_success_at=now, status="success")
    GroceryCatalogRefresh.objects.create(retailer="kaufland", last_attempt_at=now,
                                         last_success_at=now - timedelta(days=3), status="unavailable")
    GroceryOffer.objects.create(
        retailer="lidl", product_name="Milk 1 L", normalized_name="milk", fingerprint="personal-deal",
        price="2.00", currency="EUR", brand="Dairy", quantity="1", measurement_unit="l", pack_count=1,
        starts_on=day, expires_on=day + timedelta(days=1), last_successful_update=now,
        availability_status="advertised", discount_percent=20,
    )
    for offset in (1, 3, 5):
        receipt = Receipt.objects.create(
            owner=owner, merchant="Test Market", currency="EUR", source="upload", total="6",
            image_digest=str(offset), fingerprint=str(offset), purchased_at=now - timedelta(days=offset),
        )
        ReceiptItem.objects.create(receipt=receipt, original_description="Milk", normalized_name="milk",
                                   brand="Dairy", unit="l", quantity="2", line_total="6")
    return preference.pk


def run(api, site, driver, firefox, temporary):
    username = f"my-deals-{uuid4().hex[:8]}"
    account = requests.post(f"{api}/api/user/register/", json={
        "username": username, "password": browser_test_password(),
    }, timeout=5)
    account.raise_for_status()
    token = account.json()["access"]
    headers = {"Authorization": f"Bearer {token}"}
    browser = Browser(driver, firefox)
    try:
        browser.navigate(f"{site}/login")
        browser.execute("localStorage.setItem('access', arguments[0]);", token)
        browser.navigate(f"{site}/my-deals")
        wait_for(lambda: browser.execute("return document.body.textContent.includes('No active product preferences');"))
        assert browser.execute("return document.body.textContent.includes('Retailer data is unavailable');")
        preference = seed(temporary, username)
        browser.navigate(f"{site}/my-deals")
        wait_for(lambda: browser.execute("return !!document.querySelector('.my-deal-card');"))
        assert browser.execute("""
            const result = document.querySelector('.my-deals-results');
            return result.textContent.includes('Stale data') && result.textContent.includes('Data unavailable')
                && result.textContent.includes('1.00') && result.textContent.includes('below that receipt price');
        """)
        browser.change(".my-deals-results select", "BGN")
        wait_for(lambda: browser.execute("return document.querySelector('.my-deals-results').textContent.includes('No matching deals');"))
        browser.change(".my-deals-results select", "EUR")
        wait_for(lambda: browser.execute("return !!document.querySelector('.my-deal-card');"))
        assert browser.execute("""
            const summary = document.querySelector('.my-deal-explanation summary');
            summary.focus(); return document.activeElement === summary;
        """)
        browser.send_key("\ue007")
        assert browser.execute("return document.querySelector('.my-deal-explanation').open;")
        assert browser.execute("""
            [...document.querySelectorAll('.my-deals-filters button')].find(el => el.textContent.includes('Price drops')).click();
            return !!document.querySelector('.my-deal-card');
        """)
        assert browser.execute("""
            [...document.querySelectorAll('.my-deals-filters button')].find(el => el.textContent.includes('Offers expiring soon')).click();
            return !!document.querySelector('.my-deal-card');
        """)
        assert browser.click("Save favorite")
        wait_for(lambda: browser.execute("return document.querySelector('.my-deal-actions')?.textContent.includes('Favorited');"))
        wait_for(lambda: browser.execute("""
            const checkbox = document.querySelector('.my-deals-stores input');
            if (checkbox && !checkbox.disabled) { checkbox.click(); return true; }
            return false;
        """))
        wait_for(lambda: browser.execute("return document.querySelector('.my-deals-stores input')?.checked;"))
        wait_for(lambda: browser.execute("""
            const checkbox = document.querySelector('.my-deals-alert-toggle input');
            if (checkbox && !checkbox.disabled) { checkbox.click(); return true; }
            return false;
        """))
        wait_for(lambda: browser.execute("return document.querySelector('.my-deals-alert-toggle input')?.checked;"))
        wait_for(lambda: browser.click("Add to shopping list"))
        wait_for(lambda: browser.execute("return document.querySelector('.my-deal-actions').textContent.includes('In shopping list');"))
        browser.execute("""document.querySelector('.my-deals-hero a[href="/grocery"]').click();""")
        wait_for(lambda: browser.execute("""
            return document.querySelector('.grocery-edit-main input')?.value === 'Milk 1 L'
                && document.querySelector('.grocery-stepper input')?.value === '1';
        """))
        assert browser.click("Optimize basket")
        wait_for(lambda: browser.execute("return document.querySelector('.grocery-results')?.textContent.includes('2.00');"))

        browser.execute("""document.querySelector('.grocery-hero a[href="/my-deals"]').click();""")
        wait_for(lambda: browser.click("Mute Milk"))
        wait_for(lambda: browser.execute("return document.body.textContent.includes('No active product preferences');"))
        updated = requests.get(f"{api}/api/grocery/my-products/", headers=headers, timeout=5).json()
        assert any(row["id"] == preference and row["muted"] for row in updated["products"])
        result = requests.patch(f"{api}/api/grocery/my-products/{preference}/", headers=headers,
                                json={"muted": False}, timeout=5)
        result.raise_for_status()
        browser.navigate(f"{site}/my-deals")
        wait_for(lambda: browser.execute("return !!document.querySelector('.my-deal-card');"))
        browser.execute("""
            const frame = document.createElement('iframe'); frame.id = 'deals-mobile';
            frame.width = '320'; frame.height = '750'; frame.src = '/my-deals'; document.body.append(frame);
        """)
        wait_for(lambda: browser.execute("""
            const doc = document.querySelector('#deals-mobile').contentDocument;
            return !!doc.querySelector('.my-deal-card') && doc.documentElement.scrollWidth <= 320;
        """))
        print("Passed catalog states, price and expiry filters, keyboard explanation, favorites, settings, mute, optimizer handoff and 320px layout.")
    finally:
        browser.close()


if __name__ == "__main__":
    main(run)
