"""Test the browser wizard and real Django API without touching the app database."""
from pathlib import Path
from uuid import uuid4

import pymupdf
import requests

from browser_harness import Browser, browser_test_password, main, wait_for


def run(base, site, driver, firefox, temporary):
    account = requests.post(f"{base}/api/user/register/", json={
        "username": f"statement-test-{uuid4().hex[:8]}", "password": browser_test_password(),
    }, timeout=5)
    assert account.status_code == 201
    token = account.json()["access"]
    headers = {"Authorization": f"Bearer {token}"}

    def transactions():
        result = requests.get(f"{base}/api/transactions/", headers=headers, timeout=5)
        assert result.ok
        data = result.json()
        return data if isinstance(data, list) else data["results"]

    browser = Browser(driver, firefox)
    try:
        browser.post(f"{browser.prefix}/window/rect", width=1024, height=900)
        browser.navigate(site + "/login")
        browser.execute("localStorage.setItem('access', arguments[0]);", token)
        browser.navigate(site + "/")
        wait_for(lambda: browser.click("Upload statement"))
        assert browser.step("Upload")
        assert browser.execute("return document.activeElement.id === 'statement-step-title';")
        browser.tab()
        assert browser.execute("return document.activeElement.id === 'statement-upload';")

        browser.drop("unsupported.xlsx", "synthetic fixture")
        assert browser.execute("return document.querySelector('.statement-wizard [role=alert]').textContent.includes('Unsupported format');")
        browser.drop("synthetic.csv",
                     "Booked;Counterparty;Net;CCY;Reference\n"
                     "21.11.2026;Synthetic Boutique;-37,25;EUR;SX1111\n"
                     "21.11.2026;Synthetic-Boutique;-37,25;EUR;SX1111\n")
        assert browser.execute("return document.querySelector('.statement-drop output').textContent.includes('synthetic.csv');")

        # Hold the genuine preview request briefly so Parse progress is observable.
        browser.execute("""
            const open = XMLHttpRequest.prototype.open;
            const send = XMLHttpRequest.prototype.send;
            XMLHttpRequest.prototype.open = function (method, url, ...rest) {
                this.delayPreview = url.endsWith('/bank-statement/preview/');
                return open.call(this, method, url, ...rest);
            };
            XMLHttpRequest.prototype.send = function (...args) {
                if (this.delayPreview) setTimeout(() => send.apply(this, args), 600);
                else return send.apply(this, args);
            };
        """)
        assert browser.click("Preview statement")
        assert browser.step("Parse")
        assert browser.execute("return !!document.querySelector('.statement-wizard progress');")
        assert transactions() == []
        wait_for(lambda: browser.execute("return !!document.querySelector('#statement-column-mapping:not([hidden])');"))
        for field, column in (("date", "Booked"), ("description", "Counterparty"), ("amount", "Net")):
            browser.change(f'[name="mapping-{field}"]', column)
        assert browser.click("Retry parsing")
        wait_for(lambda: browser.step("Review"))
        assert browser.execute("return document.querySelectorAll('.statement-table tbody tr').length === 2;")
        assert browser.execute("return document.querySelector('.statement-table').innerText.includes('Possible duplicate');")
        assert transactions() == []

        browser.change('[name="merchant-1"]', "Corrected Boutique")
        browser.change('[name="category-1"]', "groceries")
        assert not browser.click("Review import totals")
        assert browser.click("Save corrections")
        wait_for(lambda: browser.execute("return document.querySelector('.statement-table').innerText.includes('Manual correction');"))
        browser.execute("document.querySelector('.statement-table tbody tr:nth-child(2) input[type=checkbox]').click();")
        assert not browser.click("Approve selected")
        assert browser.click("Exclude selected")
        wait_for(lambda: browser.execute("return document.querySelector('.statement-table').innerText.includes('Excluded');"))
        assert browser.click("Review import totals")
        assert browser.step("Confirm")
        assert browser.execute("""
            return [...document.querySelectorAll('.statement-totals dd')].map(el => el.textContent).join(',') === '2,1,1,1';
        """)
        assert transactions() == []
        assert browser.click("Back to review")
        assert browser.step("Review")
        assert browser.click("Review import totals")
        # Route the first confirmation to a missing endpoint, then retry the same batch.
        browser.execute("""
            const open = XMLHttpRequest.prototype.open;
            let failOnce = true;
            XMLHttpRequest.prototype.open = function (method, url, ...rest) {
                if (failOnce && url.endsWith('/confirm/')) {
                    failOnce = false;
                    url += 'synthetic-failure/';
                }
                return open.call(this, method, url, ...rest);
            };
        """)
        assert browser.click("Confirm import")
        wait_for(lambda: browser.execute("return document.querySelector('.statement-wizard [role=alert]')?.textContent.includes('Retry this same preview');"))
        assert transactions() == []
        browser.execute("""[...document.querySelectorAll('button')].find(
            button => button.textContent.trim() === 'Retry confirmation').focus();""")
        browser.send_key("\ue007")
        wait_for(lambda: browser.step("Complete"))
        assert browser.execute("""
            return [...document.querySelectorAll('.statement-totals dd')].map(el => el.textContent).join(',') === '1,1,0';
        """)
        (saved,) = transactions()
        assert saved["merchant"] == "Corrected Boutique" and saved["category"] == "groceries"

        batch = requests.get(f"{base}/api/bank-statement/imports/", headers=headers, timeout=5).json()["results"][0]
        second = requests.post(f"{base}/api/bank-statement/imports/{batch['id']}/confirm/", headers=headers, json={}, timeout=5)
        assert second.ok and second.json()["imported_count"] == 1
        assert len(transactions()) == 1
        stats = requests.get(f"{base}/api/transaction-stats/", headers=headers, timeout=5)
        assert stats.json() == [{"category": "groceries", "amount": 37.25}]
        assert browser.click("Done")
        wait_for(lambda: browser.execute("return document.querySelector('.transactions-table')?.innerText.includes('37.25');"))

        # The existing file-picker route still works for local PDF parsing.
        pdf_path = Path(temporary) / "synthetic.pdf"
        with pymupdf.open() as pdf:
            sheet = pdf.new_page()
            sheet.insert_text((35, 40), "Date;Description;Debit;Credit;Currency")
            sheet.insert_text((35, 57), "22.11.2026;Synthetic PDF;15,50;;EUR")
            pdf.save(pdf_path)
        assert browser.click("Upload statement")
        element = browser.post(f"{browser.prefix}/element", using="css selector", value="#statement-upload")
        file_id = next(iter(element.values()))
        browser.post(f"{browser.prefix}/element/{file_id}/value", text=str(pdf_path))
        assert browser.click("Preview statement")
        wait_for(lambda: browser.step("Review"))
        assert len(transactions()) == 1
        assert browser.click("Close")

        # A frame gives an exact mobile viewport even on Firefox's minimum window size.
        browser.execute("""
            const frame = document.createElement('iframe');
            frame.id = 'statement-mobile';
            frame.style.cssText = 'width:390px;border:0';
            frame.src = '/';
            document.body.append(frame);
        """)
        wait_for(lambda: browser.execute("return !!document.querySelector('#statement-mobile')?.contentDocument?.querySelector('.input_box button');"))
        browser.execute("document.querySelector('#statement-mobile').contentDocument.querySelector('.input_box button').click();")
        wait_for(lambda: browser.execute("return document.querySelector('#statement-mobile').contentDocument.querySelector('dialog')?.open;"))
        browser.execute("""
            const frame = document.querySelector('#statement-mobile');
            const win = frame.contentWindow;
            const transfer = new win.DataTransfer();
            transfer.items.add(new win.File([arguments[0]], 'mobile.csv', {type: 'text/csv'}));
            frame.contentDocument.querySelector('.statement-drop').dispatchEvent(
                new win.DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: transfer}));
        """, "Date,Description,Amount,Currency\n23.11.2026,Synthetic mobile preview,-7,EUR\n")
        browser.execute("document.querySelector('#statement-mobile').contentDocument.querySelector('.statement-wizard button[type=submit]').click();")
        wait_for(lambda: browser.execute("return !!document.querySelector('#statement-mobile')?.contentDocument?.querySelector('.statement-table tbody tr');"))
        assert browser.execute("""
            const frame = document.querySelector('#statement-mobile');
            const dialog = frame.contentDocument.querySelector('dialog');
            return frame.contentWindow.innerWidth === 390 && dialog.scrollWidth <= dialog.clientWidth;
        """)
        print("Passed keyboard entry, drag-and-drop, parse progress and retry, editable review, confirmation, idempotency, analytics, PDF preview and 390 px layout.")
    finally:
        browser.close()


if __name__ == "__main__":
    main(run)
