"""Exercise the simulator using Django and isolated market quote fixtures."""
import os
import sys
from uuid import uuid4

import requests

from statement_wizard import Browser, ROOT, main, serve, wait_for


def configure_provider():
    from django.utils import timezone

    from api.services import portfolio_quotes
    from api.views import stocks

    def quote_data(path, **_):
        stamp = int(timezone.now().timestamp())
        return {"chart": {"result": [{
            "meta": {"symbol": path.rsplit("/", 1)[-1], "regularMarketPrice": 160,
                     "regularMarketTime": stamp, "currency": "USD", "exchangeTimezoneName": "UTC"},
            "timestamp": [stamp],
            "indicators": {"quote": [{"close": [160]}]},
        }]}}
    portfolio_quotes._finance_data = quote_data
    stocks._finance_data = quote_data


def seed_watchlist(temporary, username):
    os.environ["DJANGO_SETTINGS_MODULE"] = "backend.settings"
    sys.path.insert(0, str(ROOT / "backend"))
    import django
    from django.conf import settings
    from django.utils import timezone

    settings.DATABASES["default"] = {"ENGINE": "django.db.backends.sqlite3", "NAME": temporary + "/test.sqlite3"}
    django.setup()
    from django.contrib.auth import get_user_model
    from api.models import Stock

    owner = get_user_model().objects.get(username=username)
    Stock.objects.create(user=owner, name="Apple Inc.", ticker="AAPL", quantity=0, price_per_share=0, purchase_date=timezone.now())


def run(api, site, driver, firefox, temporary):
    username = f"portfolio-browser-{uuid4().hex[:8]}"
    account = requests.post(f"{api}/api/user/register/", json={
        "username": username, "password": uuid4().hex,
    }, timeout=5)
    account.raise_for_status()
    seed_watchlist(temporary, username)
    browser = Browser(driver, firefox)
    try:
        browser.navigate(f"{site}/login")
        browser.execute("localStorage.setItem('access', arguments[0]);", account.json()["access"])
        browser.navigate(f"{site}/stocks")
        wait_for(lambda: browser.execute("return !!document.querySelector('.stock-chart a[href*=\"ticker=AAPL\"]');"))
        browser.execute("document.querySelector('.stock-chart a[href*=\"ticker=AAPL\"]').click();")
        wait_for(lambda: browser.execute("return !!document.querySelector('.portfolio-create');"))
        browser.change(".portfolio-create input", "Test positions")
        assert browser.click("Create portfolio")
        wait_for(lambda: browser.execute("return document.querySelector('dialog[open] fieldset input')?.value === 'AAPL';"))
        assert browser.execute("return document.querySelector('#portfolio-watchlist option').value === 'AAPL';")
        browser.change(".portfolio-dialog fieldset label:nth-of-type(3) input", "2")
        browser.change(".portfolio-dialog fieldset label:nth-of-type(4) input", "100")
        assert browser.click("Record simulated trade")
        wait_for(lambda: browser.execute("""
            const dashboard = document.querySelector('.portfolio-kpis');
            return dashboard?.textContent.includes('320.00') &&
                !!document.querySelector('.recharts-pie') && !!document.querySelector('.portfolio-trades tbody tr');
        """))
        assert browser.execute("return document.querySelector('.portfolio-freshness').textContent.includes('Oldest usable quote');")
        assert browser.click("Simulate sell")
        wait_for(lambda: browser.execute("return document.querySelector('dialog[open] select')?.value === 'sell';"))
        browser.change(".portfolio-dialog fieldset label:nth-of-type(3) input", "3")
        browser.change(".portfolio-dialog fieldset label:nth-of-type(4) input", "150")
        assert browser.click("Record simulated trade")
        wait_for(lambda: browser.execute("return document.querySelector('dialog [role=alert]')?.textContent.includes('exceeds');"))
        browser.change(".portfolio-dialog fieldset label:nth-of-type(3) input", "1")
        browser.change(".portfolio-dialog fieldset label:nth-of-type(5) input", "1")
        assert browser.click("Record simulated trade")
        wait_for(lambda: browser.execute("""
            return document.querySelector('.portfolio-kpis')?.textContent.includes('49.00') &&
                document.querySelectorAll('.portfolio-trades tbody tr').length === 2 &&
                !!document.querySelector('.portfolio-charts .recharts-line-curve');
        """))
        browser.execute("document.querySelector('.portfolio-chart-data summary').click();")
        assert browser.execute("return document.querySelector('.portfolio-chart-data[open] tbody').textContent.includes('49.00');")

        assert browser.click("Simulate trade")
        wait_for(lambda: browser.execute("return !!document.querySelector('dialog[open]');"))
        browser.send_key("\ue00c")
        wait_for(lambda: browser.execute("return !document.querySelector('dialog[open]');"))

        browser.execute("""
            const frame = document.createElement('iframe');
            frame.id = 'portfolio-mobile';
            frame.style.cssText = 'width:390px;height:740px;border:0';
            frame.src = '/portfolios';
            document.body.append(frame);
        """)
        wait_for(lambda: browser.execute("""
            const frame = document.querySelector('#portfolio-mobile');
            const doc = frame.contentDocument;
            const table = doc.querySelector('.portfolio-holdings')?.parentElement;
            return table && frame.contentWindow.innerWidth === 390 && doc.documentElement.scrollWidth <= 390 &&
                table.scrollWidth > table.clientWidth && !!doc.querySelector('.portfolio-charts svg.recharts-surface');
        """))
        print("Passed watchlist entry, portfolio creation, simulated buy/sell, oversell rejection, charts, trade history, freshness, Escape and 390 px layout.")
    finally:
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        serve(*sys.argv[2:], configure=configure_provider)
    else:
        main(run, server_script=__file__)
