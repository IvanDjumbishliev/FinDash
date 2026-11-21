import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup
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


MEDIA = "{http://search.yahoo.com/mrss/}"


def preview_details(item, title):
    description = BeautifulSoup(item.findtext("description", ""), "html.parser")
    for node in description.select("script, style, ul, ol"):
        node.decompose()
    paragraph = description.find("p")
    text = paragraph.get_text() if paragraph else description.get_text(" ")
    summary = " ".join(text.split())
    words = summary.split()
    if summary.casefold().rstrip(".") == title.casefold().rstrip("."):
        summary = ""
    elif len(words) > 25:
        summary = " ".join(words[:25]).rstrip(" ,;:") + "…"

    photos = []
    for tag in item.iter():
        image_type = tag.get("type", "")
        if tag.tag in {f"{MEDIA}content", f"{MEDIA}thumbnail", "enclosure"} and (
            image_type.startswith("image/")
            or (tag.tag != "enclosure" and not image_type and tag.get("medium", "image") == "image")
        ):
            width = tag.get("width", "")
            photos.append((int(width) if width.isdecimal() else 0, tag.get("url", ""), ""))

    for image in description.find_all("img"):
        photos.append((0, image.get("src", ""), image.get("alt", "")))

    for _, image_url, alt in sorted(photos, key=lambda photo: photo[0], reverse=True):
        try:
            url = urlsplit(image_url)
        except ValueError:
            continue
        if url.scheme == "https" and url.hostname:
            return summary, image_url, alt
    return summary, "", ""


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
        summary, image_url, image_alt = preview_details(item, title)
        stories.append({
            "title": title,
            "url": link,
            "source": source,
            "categories": [category],
            "published_at": published.astimezone(timezone.utc).isoformat(),
            "summary": summary,
            "image_url": image_url,
            "image_alt": image_alt,
        })
    return stories


def load_feed(feed):
    identifier, category, source, url = feed
    key = f"financial-news-previews:{identifier}"
    fresh = cache.get(key)
    if fresh is not None:
        return fresh, False

    try:
        response = requests.get(url, timeout=6, headers={"User-Agent": "FinDash RSS reader"})
        response.raise_for_status()
        stories = read_feed(response.content, category, source)
    except (requests.RequestException, ElementTree.ParseError, ValueError):
        logger.warning("Could not refresh financial news feed %s", identifier)
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
