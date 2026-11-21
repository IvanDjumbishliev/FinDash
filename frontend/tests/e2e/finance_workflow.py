"""Sign in, record spending, and manage the matching monthly budget through the UI."""
from uuid import uuid4

import requests

from browser_harness import Browser, browser_test_password, main, wait_for


def run(api, site, driver, firefox, _temporary):
    username = f"finance-test-{uuid4().hex[:8]}"
    password = browser_test_password()
    account = requests.post(f"{api}/api/user/register/", json={
        "username": username, "password": password,
    }, timeout=5)
    account.raise_for_status()

    browser = Browser(driver, firefox)

    def click_link(path):
        assert browser.execute("""
            const link = document.querySelector(`nav a[href="${arguments[0]}"]`);
            if (link) link.click();
            return Boolean(link);
        """, path)

    def editor(name, value):
        browser.change(f'.budget-dialog[open] [name="{name}"]', value)

    def progress(percent):
        return browser.execute("""
            return document.querySelector('.budget-cards [role="progressbar"]')
                ?.getAttribute('aria-valuenow') === arguments[0];
        """, str(percent))

    try:
        browser.navigate(f"{site}/transactions")
        wait_for(lambda: browser.execute("return location.pathname === '/login';"))
        browser.execute("window.alert = (message) => { window.testAlert = message; };")
        browser.change('input[placeholder="Username"]', username)
        browser.change('input[placeholder="Password"]', "deliberately-invalid")
        assert browser.click("Login")
        wait_for(lambda: browser.execute("return location.pathname === '/login' && window.testAlert?.includes('Authentication failed');"))
        browser.change('input[placeholder="Password"]', password)
        assert browser.click("Login")
        wait_for(lambda: browser.execute("return location.pathname === '/' && !!document.querySelector('nav a[href=\x22/transactions\x22]');"))

        click_link("/transactions")
        wait_for(lambda: browser.execute("return !!document.querySelector('.transaction-form');"))
        browser.change("#amount", "-25.00")
        browser.change("#category", "groceries")
        browser.change("#currency", "EUR")
        browser.change("#description", "Synthetic grocery purchase")
        assert browser.click("Submit")
        wait_for(lambda: browser.execute("""
            return [...document.querySelectorAll('.transaction-item')].some(
                row => row.textContent.includes('Synthetic grocery purchase') && row.textContent.includes('-25.00 EUR'));
        """))

        # Fail the first budget overview request while letting the retry use the real API.
        browser.execute("""
            const originalOpen = XMLHttpRequest.prototype.open;
            let failNext = true;
            XMLHttpRequest.prototype.open = function(method, url, ...options) {
                const path = new URL(url, location.origin).pathname;
                if (failNext && method === 'GET' && path === '/api/budgets/overview/') {
                    failNext = false;
                    url = url.replace('/api/budgets/overview/', '/api/budgets/browser-test-unavailable/');
                }
                return originalOpen.call(this, method, url, ...options);
            };
        """)
        click_link("/budgets")
        wait_for(lambda: browser.execute("return !!document.querySelector('.budget-error [role=alert]');"))
        assert browser.click("Retry overview")
        wait_for(lambda: browser.execute("return !!document.querySelector('.budget-empty');"))

        assert browser.click("New budget")
        editor("category", "groceries")
        editor("amount", "-1")
        editor("currency", "EUR")
        assert browser.click("Save budget")
        wait_for(lambda: browser.execute("""
            return document.querySelector('.budget-dialog [role="alert"]')?.textContent.includes('Enter a positive amount');
        """))
        editor("amount", "100")
        assert browser.click("Save budget")
        wait_for(lambda: progress(25))

        assert browser.click("Edit")
        editor("amount", "50")
        assert browser.click("Save budget")
        wait_for(lambda: progress(50))
        assert browser.click("Edit")
        assert browser.click("Archive budget")
        wait_for(lambda: browser.execute("return document.querySelector('.budget-feedback[role=status]')?.textContent === 'Budget archived.';"))

        token = browser.execute("return localStorage.getItem('access');")
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(f"{api}/api/budgets/", headers=headers, timeout=5)
        response.raise_for_status()
        archived, = response.json()
        assert archived["archived"] and archived["actual_spending"] == "25.00"
        response = requests.get(f"{api}/api/transactions/", headers=headers, timeout=5)
        response.raise_for_status()
        transaction, = response.json()
        assert transaction["particulars"] == "Synthetic grocery purchase"
        print("Passed login, transaction creation, budget API error and retry, validation, edit, and archive.")
    finally:
        browser.close()


if __name__ == "__main__":
    main(run)
