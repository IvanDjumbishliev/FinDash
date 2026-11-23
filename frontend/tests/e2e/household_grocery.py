"""Exercise a shared grocery list with two authenticated browser sessions."""
from uuid import uuid4

import requests

from browser_harness import Browser, browser_test_password, main, wait_for
from grocery_optimizer import seed_catalog


def run(base, site, driver, firefox, temporary, second_driver):
    seed_catalog(temporary)

    def account(prefix):
        username = f"{prefix}-{uuid4().hex[:8]}"
        response = requests.post(f"{base}/api/user/register/", json={
            "username": username, "password": browser_test_password(),
        }, timeout=5)
        response.raise_for_status()
        return username, response.json()["access"]

    _, owner_token = account("household-owner")
    member_name, member_token = account("household-member")
    owner = Browser(driver, firefox)
    member = Browser(second_driver, firefox)
    try:
        for browser, token in ((owner, owner_token), (member, member_token)):
            browser.navigate(f"{site}/login")
            browser.execute("localStorage.setItem('access', arguments[0]);", token)
        owner.navigate(f"{site}/grocery")
        wait_for(lambda: owner.execute("return !!document.querySelector('.grocery-sidebar form input');"))
        owner.change(".grocery-sidebar form input", "Family shop")
        assert owner.click("Create shared list")
        wait_for(lambda: owner.execute("return !!document.querySelector('.household-add');"))
        owner.change(".household-add input", "Milk")
        owner.change(".household-add select", "l")
        assert owner.click("Add product")
        wait_for(lambda: owner.execute("return !!document.querySelector('.household-item');"))
        owner.change(".household-invite input", member_name)
        assert owner.click("Invite user")
        wait_for(lambda: owner.execute("return document.querySelector('.household-members').textContent.includes('Invited');"))

        member.navigate(f"{site}/grocery")
        wait_for(lambda: member.click("Accept invitation"))
        wait_for(lambda: member.execute("return !!document.querySelector('.household-item');"))
        member.change(".household-item input", "2")
        assert member.click("Save quantity")
        wait_for(lambda: member.execute("return Number(document.querySelector('.household-item input')?.value) === 2;"))
        wait_for(lambda: member.click("Optimize unpurchased items"))
        wait_for(lambda: member.execute("return document.querySelector('.grocery-results')?.textContent.includes('4.00');"))
        assert member.click("Mark purchased")
        wait_for(lambda: owner.execute("""
            return document.querySelector('.household-item').textContent.includes('Purchased by ' + arguments[0]);
        """, member_name))
        assert owner.click(f"Remove {member_name}")
        wait_for(lambda: member.execute("""
            return document.body.textContent.includes('your access was removed') && !document.querySelector('.household-item');
        """))
        print("Passed shared creation, invitation, member edit, optimizer, purchase attribution and live revocation.")
    finally:
        owner.close()
        member.close()


if __name__ == "__main__":
    main(run, second_browser=True)
