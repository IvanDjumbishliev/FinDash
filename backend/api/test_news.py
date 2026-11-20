from datetime import datetime, timezone
from unittest.mock import patch
from xml.sax.saxutils import escape

import requests
from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.test import APIClient

from api.views.news import load_feed, read_feed


def rss(*stories):
    items = "".join(
        f"<item><title>{escape(title)}</title><link>{escape(link)}</link>"
        f"<pubDate>{date}</pubDate></item>"
        for title, link, date in stories
    )
    return f"<rss><channel>{items}</channel></rss>".encode()


class NewsTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    @patch("api.views.news.now", return_value=datetime(2026, 11, 21, tzinfo=timezone.utc))
    @patch("api.views.news.load_feed")
    def test_feed_merges_topics_and_returns_recent_articles_newest_first(self, load, current):
        stories = rss(
            ("Market update", "https://example.com/update", "Fri, 20 Nov 2026 15:00:00 GMT"),
            ("Older story", "https://example.com/older", "Fri, 20 Nov 2026 09:00:00 +0200"),
            ("Expired", "https://example.com/archive", "Tue, 10 Nov 2026 10:00:00 GMT"),
            ("Invalid date", "https://example.com/invalid", "unknown"),
            ("Invalid URL", "javascript:void(0)", "Fri, 20 Nov 2026 09:00:00 GMT"),
        )
        load.side_effect = lambda feed: (
            read_feed(stories, feed[1], feed[2]) if feed[0] in {"markets", "banking"} else [],
            feed[0] == "money",
        )
        client = APIClient()
        response = client.get("/api/news/", HTTP_AUTHORIZATION="Bearer expired-token")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["partial"])
        articles = response.data["articles"]
        self.assertEqual([article["title"] for article in articles], ["Market update", "Older story"])
        self.assertEqual(articles[0]["categories"], ["Markets", "Banking"])
        self.assertEqual(articles[1]["published_at"], "2026-11-20T07:00:00+00:00")

    @patch("api.views.news.requests.get")
    def test_feed_uses_cached_headlines_when_refresh_fails(self, get):
        feed = ("test", "Markets", "Example", "https://example.com/rss")
        get.return_value.content = rss(
            ("Market update", "https://example.com/update", "Fri, 20 Nov 2026 15:00:00 GMT"),
        )
        first, unavailable = load_feed(feed)
        self.assertFalse(unavailable)
        self.assertEqual(len(first), 1)
        self.assertEqual(load_feed(feed), (first, False))
        get.assert_called_once()

        cache.delete("financial-news-previews:test")
        get.side_effect = requests.ConnectionError("offline")
        self.assertEqual(load_feed(feed), (first, True))

    def test_previews_pick_a_publisher_photo_and_clean_the_description(self):
        stories = read_feed(b"""
            <rss xmlns:media="http://search.yahoo.com/mrss/"><channel><item>
                <title>Market closes higher</title>
                <link>https://example.com/story</link>
                <pubDate>Fri, 20 Nov 2026 15:00:00 GMT</pubDate>
                <description><![CDATA[<p>Shares rose after the <b>rate decision</b>.</p>
                    <p>More in the original article.</p>]]></description>
                <media:content url="https://example.com/small.jpg" width="140"/>
                <media:content url="https://example.com/large.jpg" width="700"/>
                <media:content url="https://example.com/video.mp4" medium="video" width="900"/>
            </item></channel></rss>
        """, "Markets", "Example")

        self.assertEqual(stories[0]["summary"], "Shares rose after the rate decision.")
        self.assertEqual(stories[0]["image_url"], "https://example.com/large.jpg")
