"""Verify warranty, receipt and proof flows against an isolated Django database."""
import base64
import os
import sys
from datetime import timedelta
from io import BytesIO
from uuid import uuid4

import requests
from PIL import Image

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
    from api.models import Receipt, ReceiptItem

    owner = get_user_model().objects.get(username=username)
    receipt = Receipt.objects.create(
        owner=owner, merchant="Fixture Electronics", currency="EUR", source="upload", total="120",
        purchased_at=timezone.now() - timedelta(days=2), fingerprint="vault-fixture", image_digest="vault-fixture",
    )
    ReceiptItem.objects.create(receipt=receipt, original_description="Fixture Camera", normalized_name="fixture camera", line_total="120")
    return receipt.pk


def run(base, site, driver, firefox, temporary):
    username = f"vault-{uuid4().hex[:8]}"
    account = requests.post(f"{base}/api/user/register/", json={
        "username": username, "password": browser_test_password(),
    }, timeout=5)
    account.raise_for_status()
    receipt = seed(temporary, username)
    browser = Browser(driver, firefox)
    try:
        browser.navigate(f"{site}/login")
        browser.execute("localStorage.setItem('access', arguments[0]);", account.json()["access"])
        browser.navigate(f"{site}/warranties")
        wait_for(lambda: browser.click("Add manual warranty"))
        browser.change(".warranty-fields input:nth-child(1)", "Manual Blender")
        browser.change(".warranty-fields label:nth-child(2) input", "Test Merchant")
        browser.change(".warranty-fields input[type=date]", "2024-01-31")
        browser.change(".warranty-fields input[type=number]", "1")
        assert browser.click("Save warranty")
        wait_for(lambda: browser.execute("""
            const card = document.querySelector('.warranty-grid article');
            return card?.textContent.includes('Manual Blender') && card.querySelector('[data-status=expired]');
        """))
        browser.change(".warranty-filters input", "Test merchant")
        assert browser.click("Search warranties")
        wait_for(lambda: browser.execute("return !!document.querySelector('.warranty-grid article');"))
        browser.change(".warranty-filters select", "active")
        wait_for(lambda: browser.execute("return document.body.textContent.includes('No warranties match');"))

        browser.navigate(f"{site}/receipts/history?receipt={receipt}")
        wait_for(lambda: browser.execute("""return !!document.querySelector('.receipt-saved-items a[href^="/warranties"]');"""))
        browser.execute("""document.querySelector('.receipt-saved-items a[href^="/warranties"]').click();""")
        wait_for(lambda: browser.execute("""
            return document.querySelector('form fieldset')?.textContent.includes('From confirmed receipt');
        """))
        browser.change(".warranty-fields input[type=number]", "12")
        browser.change('.warranty-fields input[placeholder="30, 7, 1"]', "7, 0")
        assert browser.click("Save warranty")
        wait_for(lambda: browser.execute("""
            return [...document.querySelectorAll('.warranty-grid article')].some(card =>
                card.textContent.includes('Fixture Camera') && card.textContent.includes('From confirmed receipt')
                && card.textContent.includes('0, 7 before expiry'));
        """))

        file = BytesIO()
        Image.new("RGB", (30, 60), "white").save(file, format="PNG")
        browser.execute("""
            const target = document.querySelector('[aria-label="Upload proof for Fixture Camera"]');
            const transfer = new DataTransfer();
            transfer.items.add(new File([Uint8Array.from(atob(arguments[0]), char => char.charCodeAt(0))],
                'camera-proof.png', {type:'image/png'}));
            target.files = transfer.files;
            target.dispatchEvent(new Event('change', {bubbles:true}));
        """, base64.b64encode(file.getvalue()).decode())
        wait_for(lambda: browser.execute("return document.body.textContent.includes('Download proof');"))
        browser.execute("""
            const click = HTMLAnchorElement.prototype.click;
            HTMLAnchorElement.prototype.click = function () {
                if (this.download === 'purchase-proof.png') window.proofDownload = this.href.startsWith('blob:');
                else return click.call(this);
            };
        """)
        assert browser.click("Download proof")
        wait_for(lambda: browser.execute("return window.proofDownload === true;"))
        wait_for(lambda: browser.click("Remove proof"))
        wait_for(lambda: browser.execute("return !document.body.textContent.includes('Download proof');"))
        browser.change(".warranty-filters input", "Fixture Camera")
        assert browser.click("Search warranties")
        wait_for(lambda: browser.execute("return document.querySelector('.warranty-grid')?.children.length === 1;"))
        assert browser.click("Edit warranty")
        browser.change('input[placeholder="30, 7, 1"]', "14")
        assert browser.click("Save warranty")
        wait_for(lambda: browser.execute("return document.querySelector('.warranty-grid').textContent.includes('14 before expiry');"))
        assert browser.click("Delete warranty")
        assert browser.click("Confirm delete warranty and proof")
        wait_for(lambda: browser.execute("return document.body.textContent.includes('No warranties match');"))
        browser.execute("""
            const frame = document.createElement('iframe'); frame.id = 'warranty-mobile';
            frame.width = '320'; frame.height = '740'; frame.src = '/warranties'; document.body.append(frame);
        """)
        wait_for(lambda: browser.execute("""
            const doc = document.querySelector('#warranty-mobile').contentDocument;
            return !!doc.querySelector('.warranty-grid article') && doc.documentElement.scrollWidth <= 320;
        """))
        print("Passed manual warranty, filters, receipt link, proof upload/download/deletion, edits and 320px layout.")
    finally:
        browser.close()


if __name__ == "__main__":
    main(run)
