from pathlib import Path

from scoutmini.news import NewsItem, get_news, parse_rss

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = (FIXTURES / "news_sample.xml").read_text()


def test_parse_rss_extracts_items():
    items = parse_rss(SAMPLE)
    assert len(items) == 3
    first = items[0]
    assert isinstance(first, NewsItem)
    assert first.title == "Norris takes pole in Austria"
    assert first.link == "https://example.com/news/norris-pole"
    assert "Norris" in first.summary


def test_parse_rss_handles_garbage():
    assert parse_rss("not xml at all") == []


def test_get_news_limit():
    items = get_news(fetch_text=lambda url: SAMPLE, limit=2)
    assert len(items) == 2


def test_get_news_filters_by_query():
    items = get_news("Norris", fetch_text=lambda url: SAMPLE, limit=5)
    assert len(items) == 1
    assert "Norris" in items[0].title


def test_get_news_falls_back_to_latest_when_no_match():
    # No item mentions "Hamilton" -> fall back to latest rather than empty.
    items = get_news("Hamilton", fetch_text=lambda url: SAMPLE, limit=3)
    assert len(items) == 3


def test_get_news_network_failure_returns_empty():
    def boom(url):
        raise OSError("network down")

    # News is non-critical: a fetch failure must not raise.
    assert get_news("Norris", fetch_text=boom) == []
