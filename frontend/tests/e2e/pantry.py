"""Exercise pantry inventory, receipt estimates, and the shopping draft handoff."""
from uuid import uuid4

import requests

from browser_harness import Browser, browser_test_password, main, wait_for
from grocery_optimizer import seed_catalog


def run(api, site, driver, firefox, temporary):
    seed_catalog(temporary)
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from api.models import Receipt, ReceiptItem

    username = f"pantry-{uuid4().hex[:8]}"
    account = requests.post(f"{api}/api/user/register/", json={
        "username": username, "password": browser_test_password(),
    }, timeout=5)
    account.raise_for_status()
    receipt = Receipt.objects.create(
        owner=get_user_model().objects.get(username=username), merchant="Test Shop",
        purchased_at=timezone.now(), currency="BGN", total="2", source="upload",
    )
    ReceiptItem.objects.create(
        receipt=receipt, original_description="Ориз", normalized_name="ориз",
        quantity="0.25", unit="kg", line_total="2",
    )
    browser = Browser(driver, firefox)
    try:
        browser.navigate(f"{site}/login")
        browser.execute("localStorage.setItem('access', arguments[0]);", account.json()["access"])
        browser.navigate(f"{site}/receipts/history?receipt={receipt.id}")
        wait_for(lambda: browser.click("Add to pantry"))
        wait_for(lambda: browser.execute("return document.body.textContent.includes('Added to pantry as an estimate.');"))
        browser.navigate(f"{site}/pantry")
        wait_for(lambda: browser.execute("return document.querySelector('.pantry-items')?.textContent.includes('0.25 kg · Estimated');"))
        assert browser.click("Edit quantity or details")
        browser.change(".pantry-form input[type=number]", "0")
        browser.execute("document.querySelector('.pantry-check input').click();")
        browser.change(".pantry-form label:nth-child(5) input", "0.1")
        assert browser.click("Save pantry item")
        wait_for(lambda: browser.execute("""
            const items = document.querySelector('.pantry-items');
            return items?.textContent.includes('0 kg · Confirmed') && items.textContent.includes('replenishment level');
        """))
        assert browser.click("Add to shopping list")
        browser.change(".pantry-replenish input", "1")
        assert browser.click("Add to draft")
        wait_for(lambda: browser.execute("return document.body.textContent.includes('Added to your grocery basket draft.');"))
        browser.navigate(f"{site}/grocery")
        wait_for(lambda: browser.execute("""
            return [...document.querySelectorAll('.grocery-edit-item input')].some(input => input.value === 'Ориз');
        """))
        browser.navigate(f"{site}/pantry")
        wait_for(lambda: browser.click("Remove"))
        assert browser.click("Confirm removal")
        wait_for(lambda: browser.execute("return document.body.textContent.includes('Your pantry is empty');"))
        assert browser.click("Add pantry item")
        browser.change(".pantry-form input", "Яйца")
        browser.change(".pantry-form input[type=number]", "3")
        assert browser.click("Save pantry item")
        wait_for(lambda: browser.execute("return document.querySelector('.pantry-items')?.textContent.includes('3 items · Estimated');"))
        browser.execute("""
            const frame = document.createElement('iframe');
            frame.id = 'pantry-mobile';
            frame.style.cssText = 'width:320px;height:700px;border:0';
            frame.src = '/pantry';
            document.body.append(frame);
        """)
        wait_for(lambda: browser.execute("""
            const page = document.querySelector('#pantry-mobile').contentDocument;
            return !!page?.querySelector('.pantry-items') && page.documentElement.scrollWidth <= 322;
        """))
        print("Passed receipt import, estimates, confirmed consumption, replenishment, grocery draft, removal, manual entry, and 320px layout.")
    finally:
        browser.close()


if __name__ == "__main__":
    main(run)
