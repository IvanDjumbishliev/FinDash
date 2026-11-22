"""Exercise dashboard customization, paired financial data, and mobile navigation."""
from uuid import uuid4

import requests

from browser_harness import Browser, browser_test_password, main, wait_for


def run(api, site, driver, firefox, _temporary):
    account = requests.post(f"{api}/api/user/register/", json={
        "username": f"dashboard-{uuid4().hex[:8]}", "password": browser_test_password(),
    }, timeout=5)
    account.raise_for_status()
    token = account.json()["access"]
    item = requests.post(f"{api}/api/transactions/", headers={"Authorization": f"Bearer {token}"}, json={
        "amount": "120.00", "category": "general", "currency": "EUR", "particulars": "Synthetic income",
    }, timeout=5)
    item.raise_for_status()
    browser = Browser(driver, firefox)
    try:
        browser.navigate(f"{site}/login")
        browser.execute("localStorage.setItem('access', arguments[0]);", token)
        browser.navigate(site)
        wait_for(lambda: browser.execute("""
            return document.querySelector('[aria-label="Monthly cash flow"]')?.textContent.includes('120.00');
        """))
        browser.execute("document.querySelector('.theme-toggle').click();")
        assert browser.execute("""
            return document.documentElement.dataset.theme === 'dark' &&
                document.querySelector('[aria-label="Monthly cash flow"]').textContent.includes('120.00');
        """)
        assert browser.click("Customize dashboard")
        browser.execute("""
            document.querySelector('input[value=monthly]').click();
            document.querySelector('input[value=portfolio]').click();
        """)
        assert browser.click("Save layout")
        wait_for(lambda: browser.execute("return !!document.querySelector('[aria-label=\x22Virtual portfolio\x22]');"))
        browser.navigate(site)
        wait_for(lambda: browser.execute("return !!document.querySelector('[aria-label=\x22Virtual portfolio\x22]');"))
        assert browser.execute("""
            const requests = performance.getEntriesByType('resource').map(entry => new URL(entry.name))
                .filter(url => url.pathname === '/api/dashboard/');
            const sections = requests.at(-1)?.searchParams.get('sections').split(',') || [];
            return sections.includes('portfolio') && !sections.includes('monthly') &&
                !document.querySelector('[aria-label="Monthly cash flow"]');
        """)
        browser.execute("document.querySelector('.nav-menu-trigger').focus();")
        browser.send_key("\ue007")
        assert browser.execute("return document.querySelector('.nav-menu-trigger').getAttribute('aria-expanded') === 'true';")
        browser.send_key("\ue00c")
        assert browser.execute("""
            return document.activeElement === document.querySelector('.nav-menu-trigger') &&
                document.activeElement.getAttribute('aria-expanded') === 'false';
        """)
        browser.execute("""
            const frame = document.createElement('iframe');
            frame.style.cssText = 'width:320px;height:680px;border:0';
            frame.id = 'dash-mobile';
            frame.src = '/';
            document.body.append(frame);
        """)
        wait_for(lambda: browser.execute("""
            const doc = document.querySelector('#dash-mobile').contentDocument;
            return !!doc?.querySelector('.nav-menu-trigger') && !!doc.querySelector('[aria-label="Virtual portfolio"]');
        """))
        assert browser.execute("""
            const doc = document.querySelector('#dash-mobile').contentDocument;
            doc.querySelector('.nav-menu-trigger').click();
            return doc.documentElement.scrollWidth <= 320;
        """)
        wait_for(lambda: browser.execute("""
            const doc = document.querySelector('#dash-mobile').contentDocument;
            const menu = doc.querySelector('.nav-menu');
            const bounds = menu.getBoundingClientRect();
            return !menu.hidden && bounds.width > 0 && bounds.x >= 0 && bounds.right <= 320;
        """))
        browser.execute("""
            const link = document.querySelector('[aria-label="Financial overview"] a[href="/transactions"]');
            link.focus();
        """)
        browser.send_key("\ue007")
        wait_for(lambda: browser.execute("""
            return location.pathname === '/transactions' && document.activeElement.id === 'main-content';
        """))
        print("Passed real dashboard data, widget persistence, selected API sections, and keyboard and mobile navigation.")
    finally:
        browser.close()


if __name__ == "__main__":
    main(run)
