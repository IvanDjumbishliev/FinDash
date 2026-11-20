import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from xml.etree import ElementTree

import requests
from django.core.cache import cache
from django.utils.timezone import now
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)
FEEDS = (
    ("markets", "Markets", "The Guardian", "https://www.theguardian.com/business/stock-markets/rss"),
    ("banking", "Banking", "The Guardian", "https://www.theguardian.com/business/banking/rss"),
    ("money", "Personal finance", "The Guardian", "https://www.theguardian.com/money/rss"),
    ("business", "Business & economy", "BBC News", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("ecb", "Banking", "European Central Bank", "https://www.ecb.europa.eu/rss/press.html"),
    ("fed", "Banking", "Federal Reserve", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
    ("bta", "Business & economy", "БТА", "https://www.bta.bg/bg/news/economy/rss"),
    ("asia", "Markets", "Business Standard", "https://www.business-standard.com/rss/markets-106.rss"),
    ("canada", "Business & economy", "CBC News", "https://www.cbc.ca/webfeed/rss/rss-business"),
    (
        "cost-of-living",
        "Cost of living",
        "The Guardian",
        "https://www.theguardian.com/business/cost-of-living-crisis/rss",
    ),
)


def read_feed(content, category, source):
    channel = ElementTree.fromstring(content).find("channel")
    if channel is None:
        raise ValueError("RSS channel missing")

    stories = []
    for item in channel.findall("item"):
        title = " ".join(item.findtext("title", "").split())
        link = item.findtext("link", "").strip()
        try:
            url = urlsplit(link)
            published = parsedate_to_datetime(item.findtext("pubDate", ""))
        except (ValueError, OverflowError, TypeError):
            continue
        if not title or url.scheme != "https" or not url.hostname or published.tzinfo is None:
            continue
        stories.append({
            "title": title,
            "url": link,
            "source": source,
            "categories": [category],
            "published_at": published.astimezone(timezone.utc).isoformat(),
        })
    return stories


def load_feed(feed):
    identifier, category, source, url = feed
    key = f"financial-news:{identifier}"
    fresh = cache.get(key)
    if fresh is not None:
        return fresh, False

    try:
        response = requests.get(url, timeout=6, headers={"User-Agent": "FinDash RSS reader"})
        response.raise_for_status()
        stories = read_feed(response.content, category, source)
    except (requests.RequestException, ElementTree.ParseError, ValueError):
        logger.warning("Could not refresh financial news feed %s", identifier, exc_info=True)
        return cache.get(f"{key}:last-success", []), True

    cache.set(key, stories, timeout=600)
    cache.set(f"{key}:last-success", stories, timeout=86400)
    return stories, False


class NewsView(APIView):
    # The same public headlines are available to every user.
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        with ThreadPoolExecutor(max_workers=len(FEEDS)) as pool:
            reports = list(pool.map(load_feed, FEEDS))

        current = now().astimezone(timezone.utc).replace(microsecond=0)
        oldest = (current - timedelta(days=7)).isoformat()
        latest = current.isoformat()
        by_url = {}
        for stories, _ in reports:
            recent = sorted(
                (story for story in stories if oldest <= story["published_at"] <= latest),
                key=lambda story: story["published_at"],
                reverse=True,
            )
            for story in recent[:20]:
                url = urlsplit(story["url"])
                identifier = (url.hostname, url.path.rstrip("/"))
                existing = by_url.get(identifier)
                if existing:
                    existing["categories"] = list(dict.fromkeys(
                        existing["categories"] + story["categories"]
                    ))
                else:
                    by_url[identifier] = story.copy()

        failed = sum(unavailable for _, unavailable in reports)
        if not by_url and failed == len(FEEDS):
            return Response({"error": "Financial news is temporarily unavailable."}, status=503)

        return Response({
            "articles": sorted(by_url.values(), key=lambda story: story["published_at"], reverse=True),
            "partial": failed > 0,
        })
