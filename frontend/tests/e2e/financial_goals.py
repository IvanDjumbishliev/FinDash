"""Exercise the Financial Goals dashboard using real Django endpoints and Firefox."""
import sys
from uuid import uuid4

import requests

from statement_wizard import Browser, main, serve, wait_for


def run(api, site, driver, firefox, _temporary):
    response = requests.post(f"{api}/api/user/register/", json={
        "username": f"goals-browser-{uuid4().hex}", "password": uuid4().hex,
    }, timeout=5)
    response.raise_for_status()
    token = response.json()["access"]
    browser = Browser(driver, firefox)

    def dialog_text(text):
        return browser.execute("return document.querySelector('dialog[open]')?.textContent.includes(arguments[0]);", text)

    def notice(text):
        return browser.execute("return document.querySelector('.goals-notice')?.textContent.includes(arguments[0]);", text)

    def fill(name, value):
        browser.change(f"dialog[open] [name='{name}']", value)

    def progress(value):
        return browser.execute("""
            const bar = document.querySelector('.goals-card progress');
            return bar?.value === arguments[0] && bar.getAttribute('aria-label') === 'Progress for Emergency fund';
        """, value)

    try:
        browser.navigate(f"{site}/login")
        browser.execute("localStorage.setItem('access', arguments[0]);", token)
        browser.navigate(f"{site}/goals")
        wait_for(lambda: browser.execute("return document.querySelector('.goals-empty')?.textContent.includes('No current goals');"))
        assert browser.execute("return document.querySelector('nav a[href=\x22/goals\x22]').textContent === 'Goals';")
        assert browser.click("New goal")
        wait_for(lambda: dialog_text("Step 1 of 2"))
        assert browser.execute("return document.activeElement.name === 'name';")
        fill("name", "Emergency fund")
        fill("target_amount", "0")
        assert browser.click("Continue")
        wait_for(lambda: dialog_text("Enter a positive amount"))
        fill("target_amount", "100,00")
        assert browser.click("Continue")
        wait_for(lambda: dialog_text("Step 2 of 2"))
        assert browser.execute("return document.activeElement.name === 'target_date';")
        fill("target_date", "2099-12-31")
        fill("monthly_contribution", "invalid")
        assert browser.click("Back")
        wait_for(lambda: dialog_text("Step 1 of 2"))
        assert browser.execute("return document.querySelector('dialog [name=target_amount]').value === '100,00';")
        assert browser.click("Continue")
        wait_for(lambda: dialog_text("Step 2 of 2"))
        assert browser.click("Create goal")
        wait_for(lambda: dialog_text("Enter a positive amount, zero, or leave it blank."))
        fill("monthly_contribution", "50")
        assert browser.click("Create goal")
        wait_for(lambda: notice("Savings goal created"))
        assert progress(0)
        wait_for(lambda: browser.execute("""
            const dates = document.querySelector('.goals-dates');
            return dates?.textContent.includes('2099') && !dates.textContent.includes('Calculating') &&
                !dates.textContent.includes('Retry estimate');
        """))

        assert browser.click("Add contribution")
        fill("amount", "50.25")
        fill("note", "First deposit")
        assert browser.click("Record contribution")
        wait_for(lambda: notice("Contribution recorded"))
        assert progress(50.25)
        assert browser.execute("return document.querySelector('.goals-summary').textContent.includes('50.25');")

        assert browser.click("Add contribution")
        fill("amount", "49.75")
        assert browser.click("Record contribution")
        wait_for(lambda: notice("Goal reached"))
        assert progress(100)
        assert browser.execute("return !!document.querySelector('.goals-confetti');")

        assert browser.click("Add contribution")
        fill("kind", "withdrawal")
        fill("amount", "100.01")
        assert browser.click("Record withdrawal")
        wait_for(lambda: dialog_text("withdrawal exceeds"))
        fill("amount", "0.25")
        assert browser.click("Record withdrawal")
        wait_for(lambda: notice("Withdrawal recorded"))
        assert progress(99.75)

        assert browser.click("History")
        wait_for(lambda: dialog_text("First deposit"))
        assert dialog_text("Withdrawal")
        browser.send_key("\ue00c")
        wait_for(lambda: browser.execute("return !document.querySelector('dialog[open]') && document.activeElement.textContent.trim() === 'History';"))

        assert browser.click("Edit")
        fill("target_amount", "200")
        assert browser.click("Save changes")
        wait_for(lambda: notice("Goal updated"))
        assert browser.execute("return document.querySelector('.goals-card progress').getAttribute('aria-valuetext') === '49.88% funded';")

        browser.execute("""
            const frame = document.createElement('iframe');
            frame.id = 'goals-mobile';
            frame.style.cssText = 'width:320px;height:680px;border:0';
            frame.src = '/goals';
            document.body.append(frame);
        """)
        wait_for(lambda: browser.execute("return !!document.querySelector('#goals-mobile').contentDocument?.querySelector('.goals-card');"))
        browser.execute("""
            const doc = document.querySelector('#goals-mobile').contentDocument;
            doc.querySelector('.goals-card .goals-primary').click();
        """)
        wait_for(lambda: browser.execute("return !!document.querySelector('#goals-mobile').contentDocument.querySelector('dialog[open]');"))
        assert browser.execute("""
            const doc = document.querySelector('#goals-mobile').contentDocument;
            const bounds = doc.querySelector('dialog').getBoundingClientRect();
            return doc.documentElement.scrollWidth <= 320 && bounds.width > 0 && bounds.x >= 0 && bounds.right <= 320;
        """)

        assert browser.click("Archive")
        assert browser.click("Archive goal")
        wait_for(lambda: notice("Goal archived"))
        assert browser.click("Archived (1)")
        wait_for(lambda: browser.execute("return !!document.querySelector('.goals-card .goals-status');"))
        assert browser.click("History")
        wait_for(lambda: dialog_text("First deposit"))
        browser.send_key("\ue00c")

        headers = {"Authorization": f"Bearer {token}"}
        result = requests.get(f"{api}/api/goals/", headers=headers, timeout=5)
        result.raise_for_status()
        goal, = result.json()
        assert goal["archived"] and goal["current_amount"] == "99.75"
        history = requests.get(f"{api}/api/goals/{goal['id']}/contributions/", headers=headers, timeout=5)
        history.raise_for_status()
        entries = history.json()["results"]
        assert len(entries) == 3 and all(entry["request_id"] for entry in entries)
        print("Passed wizard validation, projections, contribution progress, celebration, withdrawal, history, editing, archive, and 320 px layout.")
    finally:
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        serve(*sys.argv[2:])
    else:
        main(run_browser=run, server_script=__file__)
