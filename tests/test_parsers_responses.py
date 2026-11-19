"""Reading raw response bodies: JSON, JSON inside a browser page, and block pages."""

import pytest

from scraper.parsers import extract_json, is_cloudflare_challenge, is_rate_limit_page

CHALLENGE_PAGE = "<!DOCTYPE html><html><head><title>Just a moment...</title></head></html>"
RATE_LIMIT_PAGE = (
    "<!DOCTYPE html><html><head><title>Access denied | Error 1015</title></head>"
    "<body><h1>You are being rate limited</h1></body></html>"
)


def test_extract_json_reads_a_plain_json_body():
    assert extract_json('\n  {"data": {"kills": [1, 2]}}\n') == {"data": {"kills": [1, 2]}}


def test_extract_json_reads_json_shown_in_a_browser_viewer():
    page = (
        '<html><head><meta name="color-scheme" content="light dark"></head><body>'
        '<pre style="word-wrap: break-word;">{"data": {"name": "Brim &amp; Stone &lt;3"}}</pre>'
        "</body></html>"
    )
    assert extract_json(page) == {"data": {"name": "Brim & Stone <3"}}


def test_extract_json_reads_a_viewer_page_spread_over_lines():
    page = '<HTML><BODY>\n<PRE>\n{\n  "data": [1,\n 2]\n}\n</PRE>\n</BODY></HTML>'
    assert extract_json(page) == {"data": [1, 2]}


def test_extract_json_rejects_html_without_a_json_document():
    with pytest.raises(ValueError, match="HTML"):
        extract_json("<html><body><h1>Bad gateway</h1></body></html>")


@pytest.mark.parametrize("body", ['{"data": ', "<html><pre>not json</pre></html>", ""])
def test_extract_json_rejects_a_broken_body(body):
    with pytest.raises(ValueError):
        extract_json(body)


@pytest.mark.parametrize(
    "marker",
    [
        "<title>Just a moment...</title>",
        "<script>window._cf_chl_opt = {};</script>",
        '<div id="challenge-error-text">Enable JavaScript</div>',
        "<title>Attention Required! | Cloudflare</title>",
        "<h1>Sorry, you have been blocked</h1>",
    ],
)
def test_cloudflare_pages_are_recognised(marker):
    assert is_cloudflare_challenge(f"\n <!DOCTYPE html><html><body>{marker}</body></html>")


def test_cloudflare_check_ignores_letter_case():
    assert is_cloudflare_challenge(CHALLENGE_PAGE.upper())


@pytest.mark.parametrize(
    "body",
    [
        '{"data": {"note": "Just a moment..."}}',
        '<html><body><pre>{"data": {}}</pre></body></html>',
        RATE_LIMIT_PAGE,
        "",
    ],
)
def test_other_bodies_are_not_a_cloudflare_challenge(body):
    assert not is_cloudflare_challenge(body)


@pytest.mark.parametrize(
    "marker", ["<title>Error 1015</title>", "<h1>You are being rate limited</h1>"]
)
def test_rate_limit_pages_are_recognised(marker):
    assert is_rate_limit_page(f"<!DOCTYPE html><html><body>{marker}</body></html>")
    assert is_rate_limit_page(f"<!DOCTYPE html><html><body>{marker.upper()}</body></html>")


@pytest.mark.parametrize(
    "body",
    [
        '{"errors": [{"message": "You are being rate limited"}]}',
        '<html><body><pre>{"data": {}}</pre></body></html>',
        CHALLENGE_PAGE,
        "",
    ],
)
def test_other_bodies_are_not_a_rate_limit_page(body):
    assert not is_rate_limit_page(body)
