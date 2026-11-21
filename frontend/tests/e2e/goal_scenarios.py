"""Exercise live goal scenario comparisons against Django in Firefox."""
import sys
from uuid import uuid4

import requests

from statement_wizard import Browser, browser_test_password, main, serve, wait_for


def run(api, site, driver, firefox, _temporary):
    account = requests.post(f"{api}/api/user/register/", json={
        "username": f"goal-scenario-{uuid4().hex}", "password": browser_test_password(),
    }, timeout=5)
    account.raise_for_status()
    token = account.json()["access"]

    def call(method, path, **kwargs):
        response = requests.request(method, api + path, headers={"Authorization": f"Bearer {token}"}, timeout=5, **kwargs)
        response.raise_for_status()
        return response.json()

    goal = call("POST", "/api/goals/", json={
        "name": "Travel fund", "target_amount": "1000.00", "currency": "EUR", "monthly_contribution": "100.00",
        "target_date": "2099-12-31",
    })
    endpoint = f"/api/goals/{goal['id']}/"
    posted = call("POST", endpoint + "contributions/", json={"kind": "contribution", "amount": "100.00"})
    browser = Browser(driver, firefox)

    def comparison(text):
        return browser.execute("""
            const latest = document.querySelector('[aria-label="Latest estimate"] .goals-scenario-result');
            return latest?.textContent.includes(arguments[0]);
        """, text)

    def fill(name, value):
        browser.change(f'input[name="{name}"]', value)

    try:
        browser.navigate(f"{site}/login")
        browser.execute("localStorage.setItem('access', arguments[0]);", token)
        browser.navigate(f"{site}/goals")
        wait_for(lambda: browser.execute("return !!document.querySelector('.goals-action-link');"))
        browser.execute("document.querySelector('.goals-action-link').click();")
        wait_for(lambda: comparison("Same time"))
        browser.execute("""document.querySelector('input[aria-label="Monthly contribution slider"]').focus();""")
        browser.send_key("\ue014")
        assert browser.execute("return document.querySelector('[name=monthly_contribution]').value === '101';")

        fill("monthly_contribution", "200")
        fill("one_time_contribution", "100")
        fill("expense_reduction", "50")
        fill("target_amount", "1200")
        wait_for(lambda: comparison("5 months sooner"))
        assert browser.execute("""
            const plans = document.querySelector('.goals-scenario-plans');
            return plans.textContent.includes('250.00') && plans.textContent.includes('200.00');
        """)
        browser.change(".goals-scenario-field select", "custom")
        fill_date = 'input[type="date"]'
        browser.change(fill_date, "2099-01-31")
        wait_for(lambda: browser.execute("""return document.querySelector('[aria-label="Latest estimate"]')?.textContent.includes("Jan 31, 2099");"""))
        wait_for(lambda: browser.execute("return document.querySelectorAll('.goals-scenario-chart .recharts-line-curve').length === 2;"))
        browser.execute("document.querySelector('.goals-scenario-stack details summary').click();")
        assert browser.execute("return document.querySelector('.goals-scenario-table tbody tr').textContent.includes('16.67%');")

        browser.change('.goals-scenario-save input', "Lower expenses")
        assert browser.click("Save scenario")
        wait_for(lambda: browser.execute("return document.querySelector('.goals-scenario-saved')?.textContent.includes('Lower expenses');"))
        assert browser.click("Reset")
        wait_for(lambda: comparison("Same time"))
        assert browser.click("Load")
        wait_for(lambda: comparison("5 months sooner"))
        assert browser.execute("return document.querySelector('[name=target_amount]').value === '1200.00';")

        browser.execute("""
            const frame = document.createElement('iframe');
            frame.id = 'scenario-mobile';
            frame.style.cssText = 'width:320px;height:680px;border:0';
            frame.src = window.location.pathname;
            document.body.append(frame);
        """)
        wait_for(lambda: browser.execute("""
            const doc = document.querySelector('#scenario-mobile').contentDocument;
            return !!doc?.querySelector('.goals-scenario-chart .recharts-line-curve');
        """))
        assert browser.execute("""
            const doc = document.querySelector('#scenario-mobile').contentDocument;
            return doc.documentElement.scrollWidth <= 320 && doc.querySelector('.goals-scenario-chart').clientWidth > 0;
        """)
        assert call("GET", endpoint) == posted["goal"]
        ledger = call("GET", endpoint + "contributions/")
        assert ledger["count"] == 1 and ledger["results"][0] == posted["entry"]
        saved, = call("GET", endpoint + "scenarios/")
        assert saved["name"] == "Lower expenses" and saved["changes"]["target_date"] == "2099-01-31"
        print("Passed live sliders, forecast chart, save/load/reset, goal ledger isolation, and 320 px layout.")
    finally:
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        serve(*sys.argv[2:])
    else:
        main(run_browser=run, server_script=__file__)
