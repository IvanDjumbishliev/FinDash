"""Exercise the simulator using Django and isolated market quote fixtures."""
import os
import sys
from datetime import timedelta
from urllib.parse import unquote
from uuid import uuid4

import requests

from browser_harness import Browser, browser_test_password, ROOT, main, serve, wait_for


def configure_provider():
    from django.utils import timezone

    from api.services import portfolio_quotes
    from api.views import stocks

    def quote_data(path, **params):
        stamp = int(timezone.now().timestamp())
        if "period1" in params:
            symbol = unquote(path.rsplit("/", 1)[-1])
            prices = [100, 110, 120] if symbol == "AAPL" else [200, 210, 220]
            return {"chart": {"result": [{
                "meta": {"symbol": symbol, "currency": "USD", "exchangeTimezoneName": "UTC",
                         "longName": "Apple Inc.", "sector": "Technology"},
                "timestamp": [stamp - offset * 86400 for offset in (3, 2, 1)],
                "indicators": {"quote": [{"close": prices}]},
            }]}}
        return {"chart": {"result": [{
            "meta": {"symbol": path.rsplit("/", 1)[-1], "regularMarketPrice": 160,
                     "regularMarketTime": stamp, "currency": "USD", "exchangeTimezoneName": "UTC",
                     "fullExchangeName": "NasdaqGS", "regularMarketDayLow": 157, "regularMarketDayHigh": 162,
                     "fiftyTwoWeekLow": 95, "fiftyTwoWeekHigh": 180, "regularMarketVolume": 12000},
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
        "username": username, "password": browser_test_password(),
    }, timeout=5)
    account.raise_for_status()
    seed_watchlist(temporary, username)
    browser = Browser(driver, firefox)
    try:
        browser.navigate(f"{site}/login")
        browser.execute("localStorage.setItem('access', arguments[0]);", account.json()["access"])
        browser.navigate(f"{site}/stocks")
        wait_for(lambda: browser.execute("return !!document.querySelector('.stock-chart a[href*=\"ticker=AAPL\"]');"))
        assert browser.execute("""
            const card = document.querySelector('.stock-chart');
            return card.textContent.includes('NasdaqGS') &&
                card.textContent.includes('160.00 USD') &&
                card.textContent.includes('Last reported') &&
                card.textContent.includes('52-week range') &&
                card.textContent.includes('12,000');
        """)
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
        from django.utils import timezone
        from api.models import VirtualTrade

        for offset, side in ((3, "buy"), (1, "sell")):
            VirtualTrade.objects.filter(portfolio__owner__username=username, side=side).update(
                timestamp=timezone.now() - timedelta(days=offset)
            )
        browser.execute("document.querySelector('.portfolio-advanced summary').click();")
        wait_for(lambda: browser.execute("""
            return document.querySelector('.portfolio-advanced .portfolio-analytics-charts')?.textContent.includes('Historical valuation') &&
                document.querySelector('.portfolio-advanced .portfolio-analytics-distribution')?.textContent.includes('Technology');
        """))
        browser.change(".portfolio-advanced label:nth-of-type(2) select", "^GSPC")
        wait_for(lambda: browser.execute("""
            return document.querySelector('.portfolio-analytics-charts')?.textContent.includes('rebased on') &&
                document.querySelectorAll('.portfolio-analytics-charts section:nth-child(2) .recharts-line-curve').length === 2;
        """))
        browser.execute("""
            const makeURL = URL.createObjectURL.bind(URL);
            URL.createObjectURL = (blob) => {
                blob.text().then((text) => { window.analyticsCSV = text; });
                return makeURL(blob);
            };
            const oldClick = HTMLAnchorElement.prototype.click;
            HTMLAnchorElement.prototype.click = function() {
                if (this.download?.endsWith('.csv')) window.analyticsFilename = this.download;
                else oldClick.call(this);
            };
        """)
        assert browser.click("Export analytics CSV")
        wait_for(lambda: browser.execute("""
            return window.analyticsCSV?.startsWith('date,value,contributions,withdrawals,daily_return') &&
                window.analyticsCSV.includes('^GSPC') && window.analyticsFilename?.endsWith('.csv');
        """))
        print("Passed watchlist entry, portfolio creation, simulated buy/sell, oversell rejection, charts, trade history, freshness, Escape, 390 px layout, benchmark selection and analytics CSV export.")
    finally:
        browser.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        serve(*sys.argv[2:], configure=configure_provider)
    else:
        main(run, server_script=__file__)
