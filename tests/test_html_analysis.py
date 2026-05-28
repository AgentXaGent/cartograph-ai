"""Tests for ``cartograph_ai.stages.html_analysis``."""

from __future__ import annotations

import pytest

from cartograph_ai.stages.html_analysis import analyze_html


# ---------------- Helpers ---------------------------------------------

SASAKI_LIKE = """\
<!doctype html>
<html data-wf-domain="example.com">
<head>
  <title>Sasaki Projects</title>
  <meta property="og:title" content="Projects">
  <link rel="preload" href="/_next/static/chunks/main.js">
</head>
<body>
  <div id="root">
    <h1>Featured Projects</h1>
    <p>Some real visible content describing the projects in detail. We have 90 projects in our portfolio across landscape architecture, urban design, and planning.</p>
  </div>
  <script id="__NEXT_DATA__">{"page":"projects","queryKeys":[]}</script>
  <script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Sasaki"}</script>
  <script>
    const ALGOLIA_API_KEY = "abc";
    fetch("https://AHNZ21XTZ6-dsn.algolia.net/1/indexes/prod_projects/query");
    fetch("/api/v1/projects");
  </script>
</body>
</html>
"""


# ---------------- Top-level shape -------------------------------------


def test_analyze_html_returns_expected_top_level_keys():
    out = analyze_html("<html><body></body></html>", "https://x.com/")
    assert set(out.keys()) == {
        "fingerprints",
        "embedded_data",
        "api_endpoints",
        "form_gated_endpoints",
        "bulk_download_links",
        "structure",
    }


def test_analyze_html_runs_fingerprints():
    out = analyze_html(SASAKI_LIKE, "https://x.com/")
    fp_ids = {fp["id"] for fp in out["fingerprints"]}
    assert "nextjs" in fp_ids
    assert "json_ld" in fp_ids
    assert "open_graph" in fp_ids
    assert "algolia" in fp_ids


# ---------------- Embedded data ---------------------------------------


def test_extract_json_ld_block_small_inline():
    html = (
        '<html><body>'
        '<script type="application/ld+json">{"@type":"Product"}</script>'
        '</body></html>'
    )
    out = analyze_html(html, "https://x.com/")
    blobs = out["embedded_data"]
    assert any(b["kind"] == "json_ld" for b in blobs)
    jsonld = next(b for b in blobs if b["kind"] == "json_ld")
    assert jsonld["sample_truncated"] is False
    assert "content" in jsonld
    assert "@type" in jsonld["content"]
    assert len(jsonld["sha256_16"]) == 16


def test_extract_next_data_blob():
    html = '<html><body><script id="__NEXT_DATA__">{"page":"x"}</script></body></html>'
    out = analyze_html(html, "https://x.com/")
    blobs = out["embedded_data"]
    assert any(b["key"] == "__NEXT_DATA__" for b in blobs)


def test_extract_apollo_state_blob():
    html = (
        '<html><body>'
        '<script>window.__APOLLO_STATE__ = {"x":1};</script>'
        '</body></html>'
    )
    out = analyze_html(html, "https://x.com/")
    blobs = out["embedded_data"]
    keys = {b["key"] for b in blobs}
    assert "window.__APOLLO_STATE__" in keys


def test_extract_initial_state_blob():
    html = (
        '<html><body>'
        '<script>window.__INITIAL_STATE__ = {};</script>'
        '</body></html>'
    )
    out = analyze_html(html, "https://x.com/")
    keys = {b["key"] for b in out["embedded_data"]}
    assert "window.__INITIAL_STATE__" in keys


def test_large_blob_gets_truncated_with_sample():
    big_payload = "x" * 10_000
    html = (
        '<html><body>'
        f'<script id="__NEXT_DATA__">{{"big":"{big_payload}"}}</script>'
        '</body></html>'
    )
    out = analyze_html(html, "https://x.com/")
    nd = next(b for b in out["embedded_data"] if b["key"] == "__NEXT_DATA__")
    assert nd["sample_truncated"] is True
    assert "content" not in nd
    assert "sample" in nd
    assert len(nd["sample"]) == 500  # _BLOB_SAMPLE_HEAD
    assert nd["size_bytes"] > 10_000


def test_empty_jsonld_block_is_skipped():
    html = '<html><body><script type="application/ld+json">   </script></body></html>'
    out = analyze_html(html, "https://x.com/")
    assert out["embedded_data"] == []


# ---------------- API endpoint discovery ------------------------------


def test_discovers_rest_api_paths():
    html = '<script>fetch("/api/v1/products")</script>'
    out = analyze_html(html, "https://x.com/")
    types = {e["type"] for e in out["api_endpoints"]}
    assert "rest_api" in types


def test_discovers_graphql_endpoint():
    html = '<script>fetch("/graphql", {})</script>'
    out = analyze_html(html, "https://x.com/")
    types = {e["type"] for e in out["api_endpoints"]}
    assert "graphql" in types


def test_discovers_wp_json_path():
    html = '<script>fetch("/wp-json/wp/v2/posts")</script>'
    out = analyze_html(html, "https://x.com/")
    urls = {e["url"] for e in out["api_endpoints"]}
    assert "/wp-json/wp/v2/posts" in urls


def test_discovers_algolia_host():
    html = '<script>fetch("https://AHNZ21XTZ6-dsn.algolia.net/1/indexes/prod/query?x=1")</script>'
    out = analyze_html(html, "https://x.com/")
    endpoints = out["api_endpoints"]
    algolia = [e for e in endpoints if e["type"] == "algolia_search_api"]
    assert algolia
    assert algolia[0]["url"].startswith("https://AHNZ21XTZ6-dsn.algolia.net/")


def test_discovers_underscore_api():
    html = '<script>fetch("/_api/foo")</script>'
    out = analyze_html(html, "https://x.com/")
    urls = {e["url"] for e in out["api_endpoints"]}
    assert "/_api/foo" in urls


def test_api_endpoints_dedupe():
    html = (
        '<script>fetch("/api/v1/foo"); fetch("/api/v1/foo")</script>'
        '<script>const x = "/api/v1/foo";</script>'
    )
    out = analyze_html(html, "https://x.com/")
    foo_hits = [e for e in out["api_endpoints"] if e["url"] == "/api/v1/foo"]
    assert len(foo_hits) == 1


def test_api_endpoints_ignore_unquoted_text():
    """Random body text mentioning /api should not be treated as an endpoint."""
    html = "<html><body><p>Visit our /api section to learn more.</p></body></html>"
    out = analyze_html(html, "https://x.com/")
    # The /api/ regex requires surrounding quotes/backticks, so the
    # narrative reference should not match.
    rest = [e for e in out["api_endpoints"] if e["type"] == "rest_api"]
    assert rest == []


# ---------------- Form-gated endpoints --------------------------------


def test_extracts_form_gated_action_and_inputs():
    html = """
    <html><body>
    <form method="POST" action="/api/export">
      <input name="year">
      <input name="state">
    </form>
    </body></html>
    """
    out = analyze_html(html, "https://x.com/")
    assert out["form_gated_endpoints"] == [
        {"action": "/api/export", "method": "post", "input_names": ["year", "state"]}
    ]


def test_plain_form_is_not_listed():
    html = '<form method="post" action="/contact"></form>'
    out = analyze_html(html, "https://x.com/")
    assert out["form_gated_endpoints"] == []


# ---------------- Bulk download links ---------------------------------


def test_extracts_bulk_download_links():
    html = """
    <html><body>
    <a href="/data/inventory.csv">Inventory CSV</a>
    <a href="/dump.zip">Archive</a>
    <a href="/feed.json?since=2026">Feed</a>
    <a href="/data.html">Not a bulk file</a>
    </body></html>
    """
    out = analyze_html(html, "https://x.com/")
    links = out["bulk_download_links"]
    types = {link["type"] for link in links}
    assert "csv" in types
    assert "zip" in types
    assert "json" in types
    # html links are not extracted.
    assert all(not link["url"].endswith(".html") for link in links)


# ---------------- Structure analysis ----------------------------------


def test_structure_counts_match_simple_page():
    html = """
    <html><head><title>Hello</title></head>
    <body>
      <h1>Real Content</h1>
      <p>""" + ("Real content text. " * 30) + """</p>
      <img src="a.jpg"><img src="b.jpg">
      <form><input></form>
      <a href="https://other.com/">External</a>
      <a href="https://x.com/about">Internal</a>
    </body></html>
    """
    out = analyze_html(html, "https://x.com/")
    s = out["structure"]
    assert s["title"] == "Hello"
    assert s["body_present"] is True
    assert s["image_count"] == 2
    assert s["form_count"] == 1
    assert s["link_count"] == 2
    assert s["external_link_count"] == 1
    assert s["spa_shell"] is False
    assert s["body_visible_text_chars"] > 200


def test_structure_flags_spa_shell():
    html = '<html><body><div id="root"></div><script>app.start()</script></body></html>'
    out = analyze_html(html, "https://x.com/")
    assert out["structure"]["spa_shell"] is True
    assert out["structure"]["body_visible_text_chars"] <= 200


def test_structure_no_body():
    out = analyze_html("<html></html>", "https://x.com/")
    assert out["structure"]["body_present"] is False
