"""Verify wallet entry, local code rendering, and private image display."""
import base64
from io import BytesIO
from uuid import uuid4

import requests
from PIL import Image

from browser_harness import Browser, browser_test_password, main, wait_for


def run(base, site, driver, firefox, _temporary):
    account = requests.post(f"{base}/api/user/register/", json={
        "username": f"wallet-{uuid4().hex[:8]}", "password": browser_test_password(),
    }, timeout=5)
    account.raise_for_status()
    token = account.json()["access"]
    browser = Browser(driver, firefox)
    try:
        browser.navigate(f"{site}/login")
        browser.execute("localStorage.setItem('access', arguments[0]);", token)
        browser.navigate(f"{site}/loyalty-wallet")
        wait_for(lambda: browser.click("Add loyalty card"))
        browser.change(".loyalty-fields input", "Fixture Market")
        browser.change(".loyalty-fields label:nth-child(2) input", "Weekend card")
        browser.change(".loyalty-fields label:nth-child(3) input", "MEM-001234")
        browser.change(".loyalty-fields select", "code128")
        assert not browser.click("Save card")
        browser.execute("document.querySelector('.loyalty-panel form input[type=checkbox]').click();")
        assert browser.click("Save card")
        wait_for(lambda: browser.execute("return !!document.querySelector('.loyalty-grid article');"))
        assert browser.execute("return !document.body.textContent.includes('MEM-001234');")
        browser.execute("document.querySelector('.loyalty-card-title button').click();")
        wait_for(lambda: browser.execute("return document.querySelector('.loyalty-card-title button').getAttribute('aria-pressed') === 'true';"))
        assert browser.click("Favorites only")
        browser.change(".loyalty-search input", "weekend")
        wait_for(lambda: browser.execute("return document.querySelector('.loyalty-grid article')?.textContent.includes('Fixture Market');"))
        browser.change(".loyalty-search input", "no such store")
        wait_for(lambda: browser.execute("return document.body.textContent.includes('No cards match');"))
        browser.change(".loyalty-search input", "")

        assert browser.click("Show card Fixture Market")
        wait_for(lambda: browser.execute("""
            const canvas = document.querySelector('dialog[open] canvas:not([hidden])');
            const bytes = canvas?.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
            return canvas?.width > 200 && bytes.some((value, index) => index % 4 !== 3 && value === 0)
                && document.querySelector('dialog .loyalty-identifier').textContent === 'MEM-001234';
        """))
        buffer = BytesIO()
        Image.new("RGB", (80, 42), "white").save(buffer, format="PNG")
        browser.execute("""
            const controls = document.querySelector('.loyalty-image-controls');
            controls.open = true;
            const input = controls.querySelector('input[type=file]');
            const selection = new DataTransfer();
            selection.items.add(new File([Uint8Array.from(atob(arguments[0]), c => c.charCodeAt(0))],
                'fixture.png', {type:'image/png'}));
            input.files = selection.files;
            input.dispatchEvent(new Event('change', {bubbles:true}));
        """, base64.b64encode(buffer.getvalue()).decode())
        assert not browser.click("Save image")
        browser.execute("document.querySelector('.loyalty-image-controls input[type=checkbox]').click();")
        assert browser.click("Save image")
        wait_for(lambda: browser.click("Show original image"))
        wait_for(lambda: browser.execute("return document.querySelector('.loyalty-original')?.naturalWidth === 80;"))
        assert browser.execute("return document.querySelector('.loyalty-original').src.startsWith('blob:');")
        assert browser.click("Edit card")
        browser.change(".loyalty-fields select", "qrcode")
        assert not browser.click("Save card")
        browser.execute("document.querySelector('.loyalty-panel form input[type=checkbox]').click();")
        assert browser.click("Save card")
        wait_for(lambda: browser.execute("return document.querySelector('.loyalty-grid').textContent.includes('QR code');"))
        assert browser.click("Show card Fixture Market")
        wait_for(lambda: browser.execute("""
            const canvas = document.querySelector('dialog[open] .loyalty-qr:not([hidden])');
            return canvas?.width > 0 && canvas.width === canvas.height;
        """))
        browser.send_key("\ue00c")
        wait_for(lambda: browser.execute("return !document.querySelector('dialog[open]') && !document.body.textContent.includes('MEM-001234');"))

        browser.execute("""
            const frame = document.createElement('iframe'); frame.id = 'loyalty-mobile';
            frame.width = '320'; frame.height = '700'; frame.src = '/loyalty-wallet'; document.body.append(frame);
        """)
        wait_for(lambda: browser.execute("""
            const doc = document.querySelector('#loyalty-mobile').contentDocument;
            const button = doc.querySelector('.loyalty-grid .dash-primary'); if (button) button.click(); return !!button;
        """))
        wait_for(lambda: browser.execute("""
            const doc = document.querySelector('#loyalty-mobile').contentDocument;
            const dialog = doc.querySelector('dialog[open]');
            return !!dialog && dialog.getBoundingClientRect().width <= 320
                && !!dialog.querySelector('canvas:not([hidden])');
        """))
        assert browser.click("Delete card Fixture Market")
        assert browser.click("Confirm delete")
        wait_for(lambda: browser.execute("return document.body.textContent.includes('Add a loyalty card to get started');"))
        print("Passed private listing, format confirmation, local barcode and QR display, favorites, search, image upload, deletion and 320px layout.")
    finally:
        browser.close()


if __name__ == "__main__":
    main(run)
