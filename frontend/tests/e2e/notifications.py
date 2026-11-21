"""Exercise the notification center against the authenticated Django API in Firefox."""
import sys
from datetime import datetime, timezone
from uuid import uuid4

import requests

from statement_wizard import Browser, main, serve, wait_for


def run(api, site, driver, firefox, _temporary):
    def account():
        response = requests.post(f"{api}/api/user/register/", json={
            "username": f"inbox-{uuid4().hex}", "password": uuid4().hex,
        }, timeout=5)
        response.raise_for_status()
        return response.json()["access"]

    def call(method, route, token, **kwargs):
        response = requests.request(
            method, f"{api}/api/{route}", headers={"Authorization": f"Bearer {token}"}, timeout=5, **kwargs,
        )
        response.raise_for_status()
        return response.json()

    owner, other = account(), account()
    now = datetime.now(timezone.utc)
    call("POST", "budgets/", owner, json={
        "period": now.date().replace(day=1).isoformat(), "category": "groceries",
        "amount": "100.00", "currency": "EUR", "alert_thresholds": [50],
    })
    call("POST", "reports/", other, json={"month": now.strftime("%Y-%m"), "currency": "EUR"})
    assert call("GET", "notifications/", other)["unread_count"] == 1

    browser = Browser(driver, firefox)
    try:
        browser.navigate(f"{site}/login")
        browser.execute("localStorage.setItem('access', arguments[0]);", owner)
        browser.navigate(f"{site}/notifications")
        wait_for(lambda: browser.execute("return document.querySelector('.notification-page')?.textContent.includes('caught up');"))
        browser.execute("""
            let connected = false;
            Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => connected });
            window.restoreInboxNetwork = () => { connected = true; window.dispatchEvent(new Event('online')); };
            window.dispatchEvent(new Event('offline'));
        """)
        wait_for(lambda: browser.execute("return document.querySelector('.notification-page')?.textContent.includes('offline');"))
        call("POST", "transactions/", owner, json={
            "timestamp": now.isoformat(), "amount": "-60.00", "category": "groceries",
            "particulars": "Synthetic groceries", "currency": "EUR",
        })
        notification = call("GET", "notifications/", owner)["results"][0]
        wrong_owner = requests.patch(f"{api}/api/notifications/{notification['id']}/",
                                     headers={"Authorization": f"Bearer {other}"}, json={"read": True}, timeout=5)
        assert wrong_owner.status_code == 404
        assert browser.execute("return !document.querySelector('.notification-badge');")
        browser.execute("window.restoreInboxNetwork();")
        wait_for(lambda: browser.execute("return document.querySelector('.notification-badge')?.textContent === '1';"))
        wait_for(lambda: browser.execute("return document.querySelector('.notification-page .notification-item');"))
        assert browser.execute("return !document.querySelector('.notification-page .notification-list').textContent.includes('Financial reports');")

        browser.execute("document.querySelector('.notification-bell').focus();")
        browser.send_key("\ue007")
        assert browser.execute("return document.querySelector('.notification-bell').getAttribute('aria-expanded') === 'true';")
        browser.tab()
        assert browser.execute("return document.activeElement.textContent.includes('Mark all as read');")
        browser.send_key("\ue00c")
        assert browser.execute("""
            return document.activeElement.matches('.notification-bell') &&
                document.activeElement.getAttribute('aria-expanded') === 'false';
        """)

        browser.change(".notification-filters select", "financial_report")
        wait_for(lambda: browser.execute("return document.querySelector('.notification-page').textContent.includes('No notifications match');"))
        browser.change(".notification-filters select", "budget_threshold")
        wait_for(lambda: browser.execute("return !!document.querySelector('.notification-page .notification-item');"))
        assert browser.click("Mark read")
        wait_for(lambda: browser.execute("return !document.querySelector('.notification-badge');"))
        wait_for(lambda: browser.click("Mark unread"))
        wait_for(lambda: browser.execute("return document.querySelector('.notification-badge')?.textContent === '1';"))
        wait_for(lambda: browser.click("Mark all as read"))
        wait_for(lambda: browser.execute("return !document.querySelector('.notification-badge');"))

        browser.execute("document.querySelector('.notification-page a[href=\x22/notifications/settings\x22]').click();")
        wait_for(lambda: browser.execute("return !!document.querySelector('input[aria-label=\x22Unusual spending\x22]');"))
        browser.execute("document.querySelector('input[aria-label=\x22Unusual spending\x22]').click();")
        assert browser.click("Save settings")
        wait_for(lambda: browser.execute("return document.querySelector('.notification-settings-footer').textContent.includes('settings saved');"))
        assert not call("GET", "notifications/preferences/", owner)["categories"]["unusual_spending"]
        assert call("GET", "notifications/preferences/", other)["categories"]["unusual_spending"]

        browser.execute("""
            const frame = document.createElement('iframe');
            frame.id = 'inbox-mobile';
            frame.style.cssText = 'width:320px;height:680px;border:0';
            frame.src = '/notifications';
            document.body.append(frame);
        """)
        wait_for(lambda: browser.execute("""
            return !!document.querySelector('#inbox-mobile').contentDocument?.querySelector('.notification-item');
        """))
        browser.execute("document.querySelector('#inbox-mobile').contentDocument.querySelector('.notification-bell').click();")
        wait_for(lambda: browser.execute("""
            const doc = document.querySelector('#inbox-mobile').contentDocument;
            return !doc.querySelector('.notification-popover').hidden;
        """))
        assert browser.execute("""
            const doc = document.querySelector('#inbox-mobile').contentDocument;
            const bounds = doc.querySelector('.notification-popover').getBoundingClientRect();
            return doc.documentElement.scrollWidth <= 320 && bounds.width > 0 && bounds.x >= 0 && bounds.right <= 320;
        """)

        browser.execute("""
            const previous = localStorage.getItem('access');
            localStorage.setItem('access', arguments[0]);
            window.dispatchEvent(new StorageEvent('storage', {key:'access', oldValue:previous, newValue:arguments[0]}));
        """, other)
        wait_for(lambda: browser.execute("return document.querySelector('.notification-badge')?.textContent === '1';"))
        browser.execute("document.querySelector('.notification-bell').click();")
        wait_for(lambda: browser.execute("""
            const popover = document.querySelector('.notification-popover');
            return popover?.textContent.includes('Financial reports') && !popover.textContent.includes('Budget thresholds');
        """))
        print("Passed private delivery, offline reconnect, keyboard interaction, filters, read state, settings, and 320 px layout.")
    finally:
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        serve(*sys.argv[2:])
    else:
        main(run_browser=run, server_script=__file__)
