"""Finders: web search engines and price-comparison sites used to find a product's page at a shop.

A finder is a website listed in the shop settings file (so it falls under the same terms and the same legal gate as a
shop). Two kinds:

  websearch   a search engine; ARGUS searches "<brand> <name> <shop>" and takes the first result on the shop's domain
  aggregator  a comparison / shopping site (its sponsored product ads included); one search per product returns links
              to many shops at once

Whatever a finder returns is only a *suggestion*: it is a link to the shop, and the shop's own product page is still
fetched and verified (barcode, model number, title, accessory words) before it is linked. Prices are always read from
the shop's page, never from the finder.
"""
from __future__ import annotations

import base64
import binascii
import html as htmllib
import re
from typing import Any
from urllib.parse import parse_qsl, unquote, urlparse

from .parsers import ASSET_RE, accessory_word, is_search_url, normalize_url, slug_title, title_score

KINDS = ("websearch", "aggregator")
URL_RE = re.compile(r"https?(?::|%3[Aa])(?://|%2[Ff]%2[Ff])[^\s\"'<>\\]+")
HREF_RE = re.compile(r"<a\b[^>]*?\bhref\s*=\s*([\"'])(.*?)\1[^>]*>(.*?)</a>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")


def _flatten(raw: str) -> str:
    """Page text with the escapes web pages use inside scripts and attributes undone."""
    text = raw.replace("\\/", "/").replace("\\u0026", "&").replace("\\u003d", "=").replace("\\u002F", "/").replace("\\u003a", ":")
    return htmllib.unescape(text)


def _urls_in(value: str) -> list[str]:
    """Every http(s) address inside a value, also when it is percent-encoded or hidden in a redirect parameter
    (url=, adurl=, uddg=, u=, ued=…) or in Bing's base64 click addresses (u=a1aHR0…)."""
    out: list[str] = []

    def walk(text: str, depth: int) -> None:
        if depth > 3:
            return
        for m in URL_RE.finditer(text):
            raw = m.group(0)
            if m.start() > 0 and text[m.start() - 1] == "=":          # a value inside a query string ends at the next &
                raw = raw.split("&", 1)[0]
            url = unquote(raw) if "%3" in raw[:12].lower() else raw
            if url not in out:
                out.append(url)
            for _k, v in parse_qsl(urlparse(url).query, keep_blank_values=False):
                if v.startswith("a1") and len(v) > 12:           # Bing: "a1" + base64url of the target
                    try:
                        walk(base64.urlsafe_b64decode(v[2:] + "=" * (-len(v[2:]) % 4)).decode("utf-8", "ignore"), depth + 1)
                    except (binascii.Error, ValueError):
                        pass
                elif "http" in v.lower():
                    walk(unquote(v), depth + 1)

    walk(value, 0)
    return out


def _host_ok(url: str, domain: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host == domain or host.endswith("." + domain)


def extract(page: str, domains: dict[str, str], product: dict[str, Any] | None = None,
            skip: set[str] | frozenset[str] = frozenset(), url_key: Any = None) -> dict[str, list[dict[str, Any]]]:
    """Links to shops in a finder's result page: {shop id: [{"url", "title", "score"}]}, best first.

    Every address on a shop's domain counts, whether it is an organic result or a sponsored one (ads hide the shop's
    address in a redirect parameter). Search pages, the shop's home page and pictures are dropped; a link whose text or
    address names an accessory is dropped; the rest is ranked by how well its text covers the product's name."""
    text = _flatten(page)
    anchors: dict[str, str] = {}
    for m in HREF_RE.finditer(text):
        label = " ".join(htmllib.unescape(TAG_RE.sub(" ", m.group(3))).split())[:200]
        for u in _urls_in(m.group(2)):
            anchors.setdefault(u, label)
    ordered: list[str] = list(anchors)
    for u in _urls_in(text):
        if u not in anchors:
            ordered.append(u)
            anchors[u] = ""
    name, brand = (product or {}).get("name"), (product or {}).get("brand")
    found: dict[str, dict[str, dict[str, Any]]] = {}
    for pos, raw in enumerate(ordered):
        for rid, domain in domains.items():
            if not _host_ok(raw, domain):
                continue
            try:
                url = normalize_url(raw)
            except ValueError:
                continue
            path = urlparse(url).path
            if len(path.strip("/")) < 3 or is_search_url(url) or ASSET_RE.search(path):
                continue
            label = anchors.get(raw, "")
            words = f"{label} {slug_title(url)}".strip()
            if accessory_word(words, name):
                continue
            key = url_key(rid, url) if url_key else path.lower()
            if key in skip:
                continue
            score = title_score(name, brand, words)[0] if name and words else 0.0
            cur = found.setdefault(rid, {})
            if key not in cur or score > cur[key]["score"]:
                cur[key] = {"url": url, "title": label, "score": score, "pos": pos}
    return {rid: sorted(c.values(), key=lambda x: (-round(x["score"], 1), x["pos"])) for rid, c in found.items()}
