"""Exercise the grocery page with an isolated catalog and the real API."""
import os
import sys
from datetime import timedelta
from uuid import uuid4

import requests

from browser_harness import Browser, browser_test_password, ROOT, main, wait_for


def seed_catalog(temporary):
    os.environ["DJANGO_SETTINGS_MODULE"] = "backend.settings"
    sys.path.insert(0, str(ROOT / "backend"))
    import django
    from django.conf import settings
    from django.utils import timezone

    settings.DATABASES["default"] = {"ENGINE": "django.db.backends.sqlite3", "NAME": temporary + "/test.sqlite3"}
    django.setup()
    from api.models import GroceryCatalogRefresh, GroceryOffer
    from api.services.grocery_catalog import normalized

    now = timezone.now()
    for retailer, prices in [("lidl", ["2.00", "5.00"]), ("kaufland", ["5.00", "2.00"])]:
        GroceryCatalogRefresh.objects.create(retailer=retailer, last_success_at=now, last_attempt_at=now, status="success")
        for index, (title, price) in enumerate(zip(("Milk 1 l", "Eggs 6 pcs"), prices)):
            GroceryOffer.objects.create(
                retailer=retailer, fingerprint=str(index), product_name=title, normalized_name=normalized(title),
                price=price, currency="EUR", source_url="https://example.com/offers",
                starts_on=now.date() - timedelta(days=2), expires_on=now.date() + timedelta(days=2),
                last_successful_update=now, availability_status="advertised",
            )


def run(api, site, driver, firefox, temporary):
    seed_catalog(temporary)
    account = requests.post(f"{api}/api/user/register/", json={
        "username": f"grocery-test-{uuid4().hex[:8]}", "password": browser_test_password(),
    }, timeout=5)
    account.raise_for_status()
    browser = Browser(driver, firefox)
    try:
        browser.navigate(f"{site}/login")
        browser.execute("localStorage.setItem('access', arguments[0]);", account.json()["access"])
        browser.navigate(f"{site}/grocery")
        wait_for(lambda: browser.execute("return !!document.querySelector('.grocery-empty');"))
        for index, term in enumerate(("Milk", "Eggs"), 1):
            browser.execute("document.querySelector('#grocery-search-input').focus();")
            browser.change("#grocery-search-input", term)
            wait_for(lambda: browser.execute("return !!document.querySelector('.grocery-suggestions li');"))
            browser.send_key("\ue015")
            browser.send_key("\ue007")
            wait_for(lambda: browser.execute("return document.querySelectorAll('.grocery-edit-item').length === arguments[0];", index))

        browser.execute("document.querySelector('[aria-label=\"Increase quantity for item 1\"]').click();")
        assert browser.execute("return document.querySelector('.grocery-stepper input').value === '1.25';")
        browser.execute("document.querySelector('[aria-label=\"Decrease quantity for item 1\"]').click();")
        browser.execute("document.querySelector('.grocery-retailer-options label:last-child input').click();")
        assert browser.click("Optimize basket")
        wait_for(lambda: browser.execute("""
            const results = document.querySelector('.grocery-results');
            return results && results.textContent.includes('4.00') && results.textContent.includes('3.00') &&
                results.textContent.includes('Observed') && results.textContent.includes('Store inventory is unverified');
        """))
        assert browser.execute("return document.querySelectorAll('.grocery-table-scroll th[scope=col]').length === 3;")
        browser.execute("document.querySelector('.grocery-check input').click();")
        wait_for(lambda: browser.execute("return !!document.querySelector('.grocery-check.checked');"))

        browser.change(".grocery-sidebar form input", "Weekly groceries")
        assert browser.click("Save list")
        wait_for(lambda: browser.execute("return !!document.querySelector('[aria-label=\"Load Weekly groceries\"]');"))
        browser.execute("document.querySelector('[aria-label=\"Remove item 1\"]').click();")
        assert browser.execute("return document.querySelectorAll('.grocery-edit-item').length === 1 && !document.querySelector('.grocery-results');")
        browser.execute("document.querySelector('[aria-label=\"Load Weekly groceries\"]').click();")
        wait_for(lambda: browser.execute("return document.querySelectorAll('.grocery-edit-item').length === 2;"))
        browser.change("#grocery-search-input", "Coffee")
        assert browser.click("Add item")
        assert browser.click("Optimize basket")
        wait_for(lambda: browser.execute("return document.querySelector('.grocery-results')?.textContent.includes('Unmatched in this basket: Coffee');"))

        browser.execute("""
            const frame = document.createElement('iframe');
            frame.id = 'grocery-mobile';
            frame.style.cssText = 'width:390px;height:740px;border:0';
            frame.src = '/grocery';
            document.body.append(frame);
        """)
        wait_for(lambda: browser.execute("""
            return !!document.querySelector('#grocery-mobile').contentDocument?.querySelector('[aria-label="Load Weekly groceries"]');
        """))
        browser.execute("document.querySelector('#grocery-mobile').contentDocument.querySelector('[aria-label=\"Load Weekly groceries\"]').click();")
        browser.execute("document.querySelector('#grocery-mobile').contentDocument.querySelector('.grocery-primary').click();")
        wait_for(lambda: browser.execute("""
            const frame = document.querySelector('#grocery-mobile');
            const doc = frame.contentDocument;
            const table = doc.querySelector('.grocery-table-scroll');
            return frame.contentWindow.innerWidth === 390 && doc.documentElement.scrollWidth <= 390 &&
                table && table.scrollWidth > table.clientWidth && !!doc.querySelector('.grocery-check input');
        """))
        print("Passed keyboard autocomplete, list edits, retailer filters, measured totals, checklist, save/load, unmatched warning and 390 px layout.")
    finally:
        browser.close()


if __name__ == "__main__":
    main(run)
