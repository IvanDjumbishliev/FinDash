"""Exercise the receipt UI with isolated Django storage and synthetic OCR."""
import base64
import sys
from io import BytesIO
from uuid import uuid4

import requests
from PIL import Image

from browser_harness import Browser, browser_test_password, main, serve, wait_for


FIXTURE = """Sample Market
23.11.2026 13:40
Receipt no 2345
2 x 1.00 Milk 2.00
Discount -0.50
Bread 1.75
TOTAL 3.25 EUR
"""


def configure_ocr():
    from api.services import receipts

    first_scan = True

    def recognize(image):
        nonlocal first_scan
        if first_scan:
            first_scan = False
            with Image.open(BytesIO(image)) as rotated:
                assert rotated.size == (98, 54)
        return FIXTURE

    receipts.recognize_receipt = recognize


def run(base, site, driver, firefox, _temporary):
    account = requests.post(f"{base}/api/user/register/", json={
        "username": f"receipts-{uuid4().hex[:8]}", "password": browser_test_password(),
    }, timeout=5)
    account.raise_for_status()
    token = account.json()["access"]
    headers = {"Authorization": f"Bearer {token}"}

    def count():
        response = requests.get(f"{base}/api/receipts/", headers=headers, timeout=5)
        response.raise_for_status()
        return response.json()["count"]

    buffer = BytesIO()
    Image.new("RGB", (54, 98), "white").save(buffer, "PNG")
    png = base64.b64encode(buffer.getvalue()).decode()
    buffer = BytesIO()
    Image.new("RGB", (54, 98), "gray").save(buffer, "PNG")
    camera_png = base64.b64encode(buffer.getvalue()).decode()

    def step(title):
        return browser.execute("return document.querySelector('#receipt-step-title')?.textContent === arguments[0];", title)

    def upload(filename):
        browser.execute("""
            const transfer = new DataTransfer();
            transfer.items.add(new File([Uint8Array.from(atob(arguments[0]), c => c.charCodeAt(0))],
                arguments[1], { type: 'image/png' }));
            document.querySelector('.receipt-drop').dispatchEvent(new DragEvent('drop', {
               bubbles: true, cancelable: true, dataTransfer: transfer
            }));
        """, png, filename)

    browser = Browser(driver, firefox)
    try:
        browser.post(f"{browser.prefix}/window/rect", width=1100, height=900)
        browser.navigate(f"{site}/login")
        browser.execute("localStorage.setItem('access', arguments[0]);", token)
        browser.navigate(site)
        wait_for(lambda: browser.execute("const menu = document.querySelector('.nav-menu-trigger'); if (menu) menu.click(); return !!menu;"))
        assert browser.execute("""document.querySelector('.nav-menu a[href="/receipts"]').click(); return true;""")
        wait_for(lambda: step("Add receipt photos"))
        upload("unsupported.pdf")
        assert browser.execute("return document.querySelector('.receipt-panel [role=alert]').textContent.includes('Choose a JPEG');")
        upload("synthetic.png")
        wait_for(lambda: browser.execute("return document.querySelector('.receipt-photo img')?.naturalWidth === 54;"))
        browser.execute("""document.querySelector('[aria-label="Rotate photo 1 clockwise"]').click();""")
        assert browser.execute("return document.querySelector('.receipt-photo img').style.transform.includes('90deg');")
        assert browser.click("Extract receipt")
        wait_for(lambda: step("Review receipt"))
        assert count() == 0
        assert browser.execute("""
            return document.activeElement.id === 'receipt-step-title'
                && document.querySelector('input[name=merchant]').value === 'Sample Market'
                && document.querySelector('.receipt-item-review') !== null
                && document.querySelector('input[name=discounts]').value === '0.50'
                && document.querySelector('.receipt-total-panel').textContent.includes('match the printed total');
        """)
        assert browser.click("Cancel import")
        assert count() == 0 and step("Add receipt photos")
        upload("synthetic.png")
        assert browser.click("Extract receipt")
        wait_for(lambda: step("Review receipt"))
        browser.change('input[name="receipt-item-line_total-0"]', "1.25")
        assert browser.execute("return document.querySelector('.receipt-total-panel').textContent.includes('totals differ');")
        browser.change('input[name="receipt-item-line_total-0"]', "1.50")
        browser.change('input[name="receipt-item-original_description-0"]', "Reviewed milk")
        browser.change('input[name="receipt-item-category-0"]', "Dairy")
        assert browser.click("Continue to confirmation")
        assert step("Confirm import") and count() == 0
        browser.execute("""
            const open = XMLHttpRequest.prototype.open;
            let failOnce = true;
            XMLHttpRequest.prototype.open = function (method, url, ...rest) {
                if (failOnce && url.endsWith('/receipts/confirm/')) {
                    failOnce = false;
                    url += 'test-failure/';
                }
                return open.call(this, method, url, ...rest);
            };
        """)
        assert browser.click("Save receipt")
        wait_for(lambda: browser.execute("return !!document.querySelector('.receipt-panel [role=alert]');"))
        assert count() == 0
        assert browser.click("Save receipt")
        wait_for(lambda: step("Receipt saved"))
        saved = requests.get(f"{base}/api/receipts/", headers=headers, timeout=5).json()["results"]
        assert len(saved) == 1 and saved[0]["items"][0]["original_description"] == "Reviewed milk"
        assert saved[0]["items"][0]["category"] == "Dairy"
        assert browser.click("Scan another receipt")
        upload("synthetic.png")
        assert browser.click("Extract receipt")
        wait_for(lambda: step("Receipt already saved"))
        assert count() == 1

        browser.execute("""
            const iframe = document.createElement('iframe');
            iframe.id = 'receipt-mobile';
            iframe.width = '320'; iframe.height = '780'; iframe.src = '/receipts';
            document.body.append(iframe);
        """)
        wait_for(lambda: browser.execute("return !!document.querySelector('#receipt-mobile').contentDocument?.querySelector('#receipt-camera');"))
        assert browser.execute("""
            const doc = document.querySelector('#receipt-mobile').contentDocument;
            const camera = doc.querySelector('#receipt-camera');
            const gallery = doc.querySelector('#receipt-gallery');
            const buttons = [...doc.querySelectorAll('.receipt-drop button')];
            let opened = '';
            for (const field of [camera, gallery]) field.addEventListener('click', (event) => {
                opened = field.id; event.preventDefault();
            });
            buttons[0].click();
            if (opened !== 'receipt-camera' || camera.getAttribute('capture') !== 'environment') return false;
            buttons[1].click();
            return opened === 'receipt-gallery' && gallery.multiple && !gallery.hasAttribute('capture')
                && doc.documentElement.scrollWidth <= 320;
        """)
        assert browser.execute("""
            const doc = document.querySelector('#receipt-mobile').contentDocument;
            const win = doc.defaultView;
            const bytes = Uint8Array.from(atob(arguments[0]), c => c.charCodeAt(0));
            function select(id, name) {
                const field = doc.querySelector(id);
                const transfer = new win.DataTransfer();
                transfer.items.add(new win.File([bytes], name, {type:'image/png'}));
                field.files = transfer.files;
                field.dispatchEvent(new win.Event('change', {bubbles:true}));
            }
            select('#receipt-camera', 'camera.png');
            return true;
        """, camera_png)
        wait_for(lambda: browser.execute("""
            return document.querySelector('#receipt-mobile').contentDocument
                .querySelector('.receipt-filename')?.textContent === 'camera.png';
        """))
        assert browser.execute("""
            const doc = document.querySelector('#receipt-mobile').contentDocument;
            const gallery = doc.querySelector('#receipt-gallery');
            const win = doc.defaultView;
            const transfer = new win.DataTransfer();
            transfer.items.add(new win.File([Uint8Array.from(atob(arguments[0]), c => c.charCodeAt(0))], 'gallery.png', {type:'image/png'}));
            gallery.files = transfer.files;
            gallery.dispatchEvent(new win.Event('change', {bubbles:true}));
            return true;
        """, png)
        wait_for(lambda: browser.execute("""
            const doc = document.querySelector('#receipt-mobile').contentDocument;
            return [...doc.querySelectorAll('.receipt-filename')].map(node => node.textContent).join(',') === 'camera.png,gallery.png'
                && doc.documentElement.scrollWidth <= 320;
        """))
        assert browser.execute("""
            const doc = document.querySelector('#receipt-mobile').contentDocument;
            doc.querySelector('.receipt-panel button[type=submit]').click();
            return true;
        """)
        wait_for(lambda: browser.execute("""
            const doc = document.querySelector('#receipt-mobile').contentDocument;
            return doc.querySelector('#receipt-step-title')?.textContent === 'Review receipt'
                && doc.querySelector('.receipt-panel').textContent.includes('Possible duplicate')
                && doc.documentElement.scrollWidth <= 320;
        """))
        assert count() == 1
        print("Passed desktop drop, rotation, edits, totals, cancel, explicit save, duplicate handling and 320px camera/gallery inputs.")
    finally:
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        serve(sys.argv[2], int(sys.argv[3]), configure_ocr)
    else:
        main(run, __file__)
