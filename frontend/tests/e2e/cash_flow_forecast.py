"""Exercise forecast controls and charts against Django in Firefox."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import requests

from statement_wizard import Browser, browser_test_password, main, wait_for


def account(api):
    result = requests.post(f"{api}/api/user/register/", json={
        "username": f"cash-flow-test-{uuid4().hex[:8]}", "password": browser_test_password(),
    }, timeout=5)
    result.raise_for_status()
    return result.json()["access"]


def run(api, site, driver, firefox, _temporary):
    token = account(api)
    empty_token = account(api)
    headers = {"Authorization": f"Bearer {token}"}
    today = datetime.now(UTC).date()
    entries = [
        (today - timedelta(weeks=week), str(-(12 + week % 7)), f"Variable expense {week}")
        for week in range(1, 21)
    ] + [
        (today - timedelta(days=days), "450.00", "Forecast payroll")
        for days in (7, 21, 35, 49, 63)
    ] + [
        (today - timedelta(days=days), "-9.00", "Forecast streaming")
        for days in (6, 13, 20, 27, 34, 41)
    ]
    for day, amount, label in entries:
        result = requests.post(f"{api}/api/transactions/", headers=headers, json={
            "amount": amount, "category": "general", "particulars": label,
            "timestamp": f"{day.isoformat()}T12:00:00Z", "currency": "USD",
        }, timeout=5)
        result.raise_for_status()

    browser = Browser(driver, firefox)
    try:
        browser.navigate(f"{site}/login")
        browser.execute("localStorage.setItem('access', arguments[0]);", token)
        browser.navigate(f"{site}/forecast")
        wait_for(lambda: browser.execute("""
            return document.querySelectorAll('.forecast-chart-plot svg.recharts-surface').length === 3 &&
                !!document.querySelector('.forecast-path .recharts-area-area');
        """))
        assert browser.execute("""
            return document.querySelector('nav a[href="/forecast"]') &&
                document.querySelector('.forecast-chart-actual .recharts-bar') &&
                document.querySelector('.forecast-chart-future .recharts-line-curve').getAttribute('stroke-dasharray') === '6 4' &&
                document.querySelector('.forecast-payments').textContent.includes('Forecast streaming');
        """)

        browser.execute("document.querySelector('input[value=\"30\"]').focus();")
        browser.send_key("\ue014")
        wait_for(lambda: browser.execute("return document.querySelector('.forecast-kpis')?.textContent.includes('Over 60 days');"))
        browser.send_key("\ue014")
        wait_for(lambda: browser.execute("return document.querySelector('.forecast-kpis')?.textContent.includes('Over 90 days');"))
        before = browser.execute("return document.querySelectorAll('.forecast-payments li').length;")
        browser.execute("document.querySelector('.forecast-payments button').click();")
        wait_for(lambda: browser.execute("return document.querySelectorAll('.forecast-payments li').length > arguments[0];", before))

        browser.change("#forecast-balance", "1.005")
        assert browser.click("Apply balance")
        wait_for(lambda: browser.execute("return document.querySelector('#forecast-balance').getAttribute('aria-invalid') === 'true';"))
        browser.execute("""
            const oldOpen = XMLHttpRequest.prototype.open;
            const oldHeader = XMLHttpRequest.prototype.setRequestHeader;
            const oldSend = XMLHttpRequest.prototype.send;
            XMLHttpRequest.prototype.open = function(method, url, ...options) {
                if (url.includes('/api/forecast/cash-flow/')) window.forecastURL = this.forecastURL = url;
                return oldOpen.call(this, method, url, ...options);
            };
            XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
                if (name.toLowerCase() === 'x-starting-balance') window.balanceHeader = value;
                return oldHeader.call(this, name, value);
            };
            XMLHttpRequest.prototype.send = function(...args) {
                if (this.forecastURL && window.failForecast) {
                    window.failForecast = false;
                    throw new Error('Synthetic temporary outage');
                }
                return oldSend.apply(this, args);
            };
        """)
        browser.change("#forecast-balance", "1250,50")
        assert browser.click("Apply balance")
        wait_for(lambda: browser.execute("return document.querySelector('#forecast-path-title')?.textContent.includes('Estimated balance trajectory');"))
        assert browser.execute("return window.balanceHeader === '1250.50' && !window.forecastURL.includes('1250');")
        assert browser.execute("""
            return document.querySelector('.forecast-path .recharts-area-area') &&
                document.querySelector('.forecast-path .forecast-range').textContent.includes('End of forecast range');
        """)
        browser.execute("document.querySelector('.forecast-path summary').click();")
        assert browser.execute("return document.querySelectorAll('.forecast-path details[open] tbody tr').length === 91;")
        browser.execute("document.querySelector('.forecast-assumptions summary').click();")
        assert browser.execute("return document.querySelector('.forecast-assumptions[open]').textContent.includes('complete weeks');")

        browser.execute("window.failForecast = true; document.querySelector('input[value=\"30\"]').click();")
        wait_for(lambda: browser.execute("return !!document.querySelector('.forecast-failure');"))
        assert browser.click("Try again")
        wait_for(lambda: browser.execute("return document.querySelector('.forecast-kpis')?.textContent.includes('Over 30 days');"))
        assert browser.click("Remove")
        wait_for(lambda: browser.execute("return document.querySelector('#forecast-path-title')?.textContent.includes('cumulative cash flow');"))

        browser.execute("""
            const frame = document.createElement('iframe');
            frame.id = 'forecast-mobile';
            frame.style.cssText = 'width:390px;height:740px;border:0';
            frame.src = '/forecast';
            document.body.append(frame);
        """)
        wait_for(lambda: browser.execute("""
            const frame = document.querySelector('#forecast-mobile');
            const doc = frame.contentDocument;
            const actual = doc.querySelector('.forecast-chart-actual');
            const future = doc.querySelector('.forecast-chart-future');
            return frame.contentWindow.innerWidth === 390 && doc.documentElement.scrollWidth <= 390 &&
                actual && future && actual.getBoundingClientRect().bottom <= future.getBoundingClientRect().top &&
                !!doc.querySelector('.forecast-path svg.recharts-surface');
        """))

        browser.change("#forecast-balance", "500")
        assert browser.click("Apply balance")
        wait_for(lambda: browser.execute("return document.querySelector('#forecast-path-title')?.textContent.includes('Estimated balance');"))
        browser.change(".forecast-scenario-fields fieldset:nth-child(5) input", "25")
        browser.change(".forecast-scenario-fields fieldset:nth-child(6) input", "600")
        assert browser.click("Compare scenario")
        wait_for(lambda: browser.execute("""
            return document.querySelector('.forecast-scenario-comparison')?.textContent.includes('75.00') &&
                document.querySelectorAll('.forecast-scenario-comparison .recharts-line-curve').length === 2;
        """))
        browser.change(".forecast-saved-scenarios input", "Purchase test")
        assert browser.click("Save scenario")
        wait_for(lambda: browser.execute("return document.querySelector('.forecast-saved-scenarios ul')?.textContent.includes('Purchase test');"))
        assert browser.click("Reset scenario")
        wait_for(lambda: browser.execute("return !document.querySelector('.forecast-scenario-comparison');"))
        assert browser.click("Load Purchase test")
        wait_for(lambda: browser.execute("return document.querySelector('.forecast-scenario-comparison')?.textContent.includes('75.00');"))
        browser.change(".forecast-scenario-fields fieldset:nth-child(5) input", "50")
        wait_for(lambda: browser.execute("return document.querySelector('.forecast-scenario-comparison')?.textContent.includes('50.00');"))
        assert browser.click("Delete Purchase test")
        wait_for(lambda: browser.execute("return document.querySelector('.forecast-saved-scenarios').textContent.includes('No scenarios saved yet.');"))

        browser.execute("localStorage.setItem('access', arguments[0]);", empty_token)
        browser.navigate(f"{site}/forecast")
        wait_for(lambda: browser.execute("return !!document.querySelector('.forecast-insufficient');"))
        assert browser.execute("""
            return document.querySelector('.forecast-kpis').textContent.includes('Scheduled income') &&
                !document.querySelector('.forecast-path svg.recharts-surface');
        """)
        print("Passed historical and projected charts, daily band, keyboard horizons, private balance, recurring payments, retry, sparse state, 390 px layout, and scenario comparison, save, reset, load, live edits, and deletion.")
    finally:
        browser.close()


if __name__ == "__main__":
    main(run)
