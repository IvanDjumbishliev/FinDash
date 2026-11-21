"""Exercise report previews and the real PDF endpoint in Firefox."""
import sys
from uuid import uuid4

import requests

from statement_wizard import Browser, browser_test_password, main, serve, wait_for


def configure_provider():
    from types import SimpleNamespace

    from django.conf import settings

    from api.services import report_explanation

    def unavailable(**_):
        raise TimeoutError("synthetic provider timeout")

    settings.API_KEY = "synthetic-browser-test"
    report_explanation.client = SimpleNamespace(models=SimpleNamespace(generate_content=unavailable))


def run(api, site, driver, firefox, _temporary):
    account = requests.post(f"{api}/api/user/register/", json={
        "username": f"monthly-report-test-{uuid4().hex[:8]}", "password": browser_test_password(),
    }, timeout=5)
    account.raise_for_status()
    token = account.json()["access"]
    for amount, day, label in [
        ("100.00", "2026-04-01", "Pay"),
        ("-23.75", "2026-04-03", "Test market"),
        ("-10.00", "2026-03-04", "Previous month"),
    ]:
        result = requests.post(f"{api}/api/transactions/", headers={"Authorization": f"Bearer {token}"}, json={
            "amount": amount, "category": "groceries", "particulars": label,
            "timestamp": f"{day}T12:00:00Z", "currency": "USD",
        }, timeout=5)
        result.raise_for_status()

    browser = Browser(driver, firefox)
    try:
        browser.navigate(f"{site}/login")
        browser.execute("localStorage.setItem('access', arguments[0]);", token)
        browser.navigate(f"{site}/reports")
        wait_for(lambda: browser.execute("return !!document.querySelector('.reports-form');"))
        assert browser.execute("return Boolean(document.querySelector('nav a[href=\"/reports\"]'));")
        browser.change(".reports-fields input[type=month]", "2026-04")
        browser.execute("document.querySelector('.reports-consent input').click();")
        assert browser.click("Generate report")
        wait_for(lambda: browser.execute("return !!document.querySelector('.report-preview');"))
        assert browser.execute("""
            const preview = document.querySelector('.report-preview').textContent;
            return ['23.75', '76.25', '13.75', 'Test market', 'Financial goals', 'Gemini commentary is unavailable']
                .every(value => preview.includes(value)) && !document.querySelector('.reports-consent input').checked;
        """)
        browser.execute("""
            const makeURL = URL.createObjectURL.bind(URL);
            URL.createObjectURL = (blob) => {
                blob.slice(0, 4).text().then((text) => { window.pdfData = {type: blob.type, magic: text}; });
                return makeURL(blob);
            };
            const originalClick = HTMLAnchorElement.prototype.click;
            HTMLAnchorElement.prototype.click = function() {
                if (this.download?.endsWith('.pdf')) window.pdfFilename = this.download;
                else originalClick.call(this);
            };
        """)
        assert browser.click("Export PDF")
        wait_for(lambda: browser.execute("""
            return window.pdfData?.magic === '%PDF' && window.pdfData?.type === 'application/pdf' &&
                window.pdfFilename === 'findash-report-2026-04-USD.pdf';
        """))
        assert browser.click("Clear preview")
        wait_for(lambda: browser.execute("return !!document.querySelector('.report-empty');"))
        browser.execute("""
            const frame = document.createElement('iframe');
            frame.id = 'report-mobile';
            frame.style.cssText = 'width:390px;height:740px;border:0';
            frame.src = '/reports';
            document.body.append(frame);
        """)
        wait_for(lambda: browser.execute("""
            return !!document.querySelector('#report-mobile').contentDocument?.querySelector('.reports-form');
        """))
        browser.execute("""
            const frame = document.querySelector('#report-mobile');
            const field = frame.contentDocument.querySelector('input[type=month]');
            const setter = Object.getOwnPropertyDescriptor(frame.contentWindow.HTMLInputElement.prototype, 'value').set;
            setter.call(field, '2026-04');
            field.dispatchEvent(new frame.contentWindow.Event('input', {bubbles:true}));
        """)
        browser.execute("document.querySelector('#report-mobile').contentDocument.querySelector('form button').click();")
        wait_for(lambda: browser.execute("""
            const frame = document.querySelector('#report-mobile');
            const doc = frame.contentDocument;
            const table = doc.querySelector('.report-table-scroll');
            return frame.contentWindow.innerWidth === 390 && doc.documentElement.scrollWidth <= 390 &&
                table && table.scrollWidth > table.clientWidth;
        """))
        print("Passed report navigation, calculated preview, AI fallback, PDF download, clear, and 390 px layout.")
    finally:
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        serve(*sys.argv[2:], configure=configure_provider)
    else:
        main(run, server_script=__file__)
