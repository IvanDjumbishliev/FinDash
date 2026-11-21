"""Exercise the heatmap in Firefox against a temporary Django database."""
from uuid import uuid4

import requests

from browser_harness import Browser, browser_test_password, main, wait_for


def run(api, site, driver, firefox, _temporary):
    account = requests.post(f"{api}/api/user/register/", json={
        "username": f"heatmap-test-{uuid4().hex[:8]}", "password": browser_test_password(),
    }, timeout=5)
    account.raise_for_status()
    token = account.json()["access"]
    headers = {"Authorization": f"Bearer {token}"}
    for day, amount, category, description in [
        (1, "-12.00", "groceries", "Test market"),
        (1, "-36.00", "bills", "Test electricity"),
        (2, "2.00", "groceries", "Merchant refund"),
    ]:
        response = requests.post(f"{api}/api/transactions/", headers=headers, json={
            "amount": amount, "category": category, "particulars": description, "currency": "USD",
            "timestamp": f"2024-01-{day:02}T12:00:00Z",
        }, timeout=5)
        response.raise_for_status()

    browser = Browser(driver, firefox)
    try:
        browser.navigate(f"{site}/login")
        browser.execute("localStorage.setItem('access', arguments[0]);", token)
        browser.navigate(site)
        wait_for(lambda: browser.execute("return !!document.querySelector('.heatmap-cell');"))
        browser.change("#heatmap-year", "2024")
        assert browser.click("Go")
        wait_for(lambda: browser.execute("return document.querySelectorAll('.heatmap-cell').length === 366;"))
        assert browser.execute("return document.querySelector('.heatmap-peak button').textContent.includes('48.00');")
        browser.change(".heatmap-controls select", "groceries")
        wait_for(lambda: browser.execute("return document.querySelector('.heatmap-peak button').textContent.includes('12.00');"))
        assert browser.execute("return document.querySelector('.heatmap-monthly dd').textContent.includes('10.00');")
        browser.execute("""
            const cell = document.querySelector('.heatmap-cell');
            cell.focus();
            cell.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
        """)
        wait_for(lambda: browser.execute("return document.querySelector('.heatmap-tooltip')?.textContent.includes('1 transaction');"))
        browser.send_key("\ue007")
        wait_for(lambda: browser.execute("return document.querySelector('.heatmap-transactions')?.textContent.includes('Test market');"))
        assert not browser.execute("return document.querySelector('.heatmap-transactions').textContent.includes('Test electricity');")
        browser.send_key("\ue015")
        browser.send_key("\ue007")
        wait_for(lambda: browser.execute("return document.querySelector('.heatmap-transactions')?.textContent.includes('Merchant refund');"))

        browser.execute("""
            const frame = document.createElement('iframe');
            frame.id = 'heatmap-mobile';
            frame.style.cssText = 'width:390px;border:0';
            frame.src = '/';
            document.body.append(frame);
        """)
        wait_for(lambda: browser.execute("""
            const frame = document.querySelector('#heatmap-mobile');
            const scroller = frame?.contentDocument?.querySelector('.heatmap-scroll');
            if (!scroller) return false;
            scroller.scrollLeft = 160;
            return frame.contentWindow.innerWidth === 390 &&
                scroller.scrollWidth > scroller.clientWidth && scroller.scrollLeft > 0 &&
                scroller.getBoundingClientRect().right <= 390;
        """))
        print("Passed year selection, category filtering, tooltip, keyboard drill-down, totals, and 390 px horizontal scrolling.")
    finally:
        browser.close()


if __name__ == "__main__":
    main(run)
