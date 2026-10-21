"""Network access: retailer pages, and finding the same product at the other shops."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp

from .i18n import T
from .models import gtin_key
from .parsers import (TITLE_DOUBT, TITLE_OK, Parsed, accessory_word, bot_wall, is_search_url, parse_page, product_identity,
                      product_match, search_candidates, title_score, url_key, wrong_product)
from .const import RETAILERS
from .finders import offers, product_pages
from .shops import active_finders, shop_names, all_domains, domain_of, finder_address, finder_key, home_of, ready, search_address

_LOGGER = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "nl-BE,nl;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}
# To protect the traffic to and the load on the shops: at most 2 requests a minute per site,
# and a search at most once every 2 minutes per site.
DOMAIN_GAP = 30.0
SEARCH_GAP = 120.0
EAN_CANDIDATE_MIN = 0.2      # a search for the barcode itself: even a weak title match is worth a look at the page
NAME_CANDIDATE_MIN = TITLE_DOUBT
VERIFY_PAGES = 2             # product pages looked at per search before giving up
FINDER_VERIFY = 3            # product pages looked at per finder result before giving up
HARVEST_TTL = 900            # seconds a comparison-site result is reused for the other shops of the same product


class Aborted(Exception):
    """The running job was stopped while a request was waiting for its turn."""


class NotReady(Exception):
    """No shop settings imported, or their terms not accepted: no website is contacted."""


def site_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


REDIRECTS = (301, 302, 303, 307, 308)
MAX_REDIRECTS = 5
MAX_BODY = 25_000_000            # bytes: a page larger than this is refused


def _too_big(size: Any) -> None:
    """Refuse a response (header value or bytes read so far) over MAX_BODY."""
    try:
        n = int(size) if size is not None else 0
    except (TypeError, ValueError):
        return
    if n > MAX_BODY:
        raise ValueError(f"response over {MAX_BODY // 1_000_000} MB")


def registrable(host: str) -> str:
    """'www.shop.com' → 'shop.com', 'www.shop.com.be' → 'shop.com.be' (an IP stays itself)."""
    host = host.lower().rstrip(".")
    labels = host.split(".")
    if not labels or host.replace(".", "").isdigit() or ":" in host:
        return host
    keep = 3 if len(labels) >= 3 and labels[-2] in ("com", "co", "org", "net", "gov", "ac", "edu") else 2
    return ".".join(labels[-keep:])


def redirect_home(retailer: str, url: str) -> str:
    """The site a request (and its redirects) must stay on: a shop's own domain for its pages (so a suffix like
    ne.jp or co.uk is never "the site")."""
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    dom = (domain_of(retailer) or "").lower()
    return dom if dom and (host == dom or host.endswith("." + dom)) else registrable(host)


def check_url(url: str, home: str) -> None:
    """Only http(s), and only the site the request started on (its own subdomains included)."""
    p = urlparse(url)
    host = (p.hostname or "").lower().rstrip(".")
    if p.scheme not in ("http", "https") or not host or not (host == home or host.endswith("." + home)):
        raise ValueError(f"redirect to another site blocked ({host or url[:60]})")


# After a block we stop asking that retailer for a while: hammering makes bot protection stricter.
COOLDOWN_HOURS = (1, 3, 6, 12, 24)
CURL_REQUIREMENT = "curl_cffi>=0.7.0"


def search_variants(product: dict[str, Any]) -> list[str]:
    """The ways one product can be searched by words, surest first: brand + model number, the model number alone,
    brand + name, and a short brand + name (shops' searches choke on long titles). Duplicates are left out."""
    brand = (product.get("brand") or "").strip()
    mpn = (product.get("mpn") or "").strip()
    sku = (product.get("sku") or "").strip()
    name_words = [w for w in (product.get("name") or "").split() if w.lower() != brand.lower()]
    out: list[str] = []
    for q in (f"{brand} {mpn}" if mpn and brand else "", mpn if len(mpn) >= 4 and any(ch.isdigit() for ch in mpn) else "",
              search_terms(product), " ".join(([brand] if brand else []) + name_words[:2]), sku if len(sku) >= 5 else ""):
        q = " ".join(q.split())
        if q and q.lower() not in [x.lower() for x in out]:
            out.append(q)
    return out


def search_terms(product: dict[str, Any], limit: int = 9) -> str:
    """The words to search a product by: brand and name without filler, at most `limit` words."""
    name = " ".join((product.get("name") or "").split())
    brand = (product.get("brand") or "").strip()
    text = name if not brand or brand.lower() in name.lower() else f"{brand} {name}"
    return " ".join(text.split()[:limit])


class Fetcher:
    """Polite fetcher: one request at a time per retailer, jittered delay, block cooldown.

    Transport is either aiohttp, or curl_cffi impersonating Chrome's TLS/HTTP2 fingerprint
    (much less likely to be blocked). curl_cffi is installed on demand and is optional.
    """

    def __init__(self, hass: Any, use_impersonation: bool = True) -> None:
        self._hass = hass
        self._use_impersonation = use_impersonation
        self._curl_ok: bool | None = None
        self._sessions: dict[str, Any] = {}
        self._warmed: set[str] = set()
        self._harvest: dict[str, tuple[Any, ...]] = {}   # product -> (time, offers per shop, offers at other shops)
        self._harvest_locks: dict[str, asyncio.Lock] = {}
        self.discover_quality: dict[str, str | None] = {}   # shop -> "ok" (surely the product) / "maybe" (you decide)
        self._maybe: dict[str, tuple[str, str] | None] = {}
        self.page_info: dict[str, dict[str, Any]] = {}       # address -> what its page said (title, price, picture…)
        self._locks: dict[str, asyncio.Lock] = {}
        self.min_delay = 4.0
        self.blocks: dict[str, int] = {}
        self.no_autopause: set[str] = set()
        self.on_pause = None   # callback(retailer, hours), set by the coordinator
        self.blocked_until: dict[str, float] = {}
        self.discover_error: dict[str, str | None] = {}   # why the last search found nothing, per shop
        self.domain_gap, self.search_gap = DOMAIN_GAP, SEARCH_GAP
        self.last_request: dict[str, float] = {}           # per site: when it was last asked anything
        self.last_search: dict[str, float] = {}            # per site: when it was last searched
        self.abort: Any = None                             # callable: True = stop waiting (the job was stopped)
        self.trace: dict[str, deque] = {}                  # per shop: the last requests, what came back and why
        self._search_meta: dict[str, tuple[int | None, int]] = {}
        self.final_url: dict[str, str] = {}               # per shop: where the last request ended up (redirects)

    def _trace(self, key: str, kind: str, url: str, t0: float, status: int | None = None, size: int = 0,
               result: str | None = None, error: str | None = None, product: str | None = None) -> None:
        self.trace.setdefault(key, deque(maxlen=40)).append(
            {"ts": time.time(), "kind": kind, "url": url, "status": status, "size": size, "product": product,
             "ms": int((time.time() - t0) * 1000), "result": result, "error": error})

    @property
    def transport(self) -> str:
        return "curl_cffi (Chrome impersonation)" if self._curl_ok else "aiohttp"

    async def async_setup(self) -> None:
        if not self._use_impersonation:
            self._curl_ok = False
            return
        try:
            import curl_cffi  # noqa: F401
        except ImportError:
            try:
                from homeassistant.requirements import async_process_requirements

                await async_process_requirements(self._hass, "argus", [CURL_REQUIREMENT], is_built_in=False)
                import curl_cffi  # noqa: F401
            except Exception as err:  # noqa: BLE001 - optional dependency, never fatal
                _LOGGER.warning("curl_cffi unavailable, falling back to aiohttp (more likely to be blocked): %s", err)
                self._curl_ok = False
                return
        self._curl_ok = True

    async def async_close(self) -> None:
        for sess in self._sessions.values():
            try:
                res = sess.close()
                if asyncio.iscoroutine(res):
                    await res
            except Exception:  # noqa: BLE001
                pass
        self._sessions.clear()

    def _session(self, retailer: str) -> Any:
        """One cookie jar per retailer, so consent/session cookies persist between polls."""
        if retailer not in self._sessions:
            if self._curl_ok:
                from curl_cffi.requests import AsyncSession

                self._sessions[retailer] = AsyncSession(impersonate="chrome", timeout=30)
            else:
                from homeassistant.helpers.aiohttp_client import async_create_clientsession

                self._sessions[retailer] = async_create_clientsession(self._hass)
        return self._sessions[retailer]

    async def _request(self, retailer: str, url: str, referer: str | None = None) -> tuple[int, str]:
        """One page. Redirects are followed by hand and only within the same site (e.g. www.shop.be → shop.be/nl/…):
        a page can never send the server to another host or into the local network."""
        headers = dict(BROWSER_HEADERS)
        if referer:
            headers.update({"Referer": referer, "Sec-Fetch-Site": "same-origin"})
        sess = self._session(retailer)
        home = redirect_home(retailer, url)
        for _hop in range(MAX_REDIRECTS + 1):
            check_url(url, home)
            if retailer.startswith("a_"):
                await self._check_public(url)    # a shop found through a comparison site: never the local network
            if self._curl_ok:
                # streamed: a body over MAX_BODY is never held in memory as a whole
                resp = await sess.get(url, headers=headers, allow_redirects=False, stream=True)
                complete = False
                try:
                    status, loc = resp.status_code, resp.headers.get("location")
                    if status in REDIRECTS and loc:
                        url = urljoin(url, loc)
                        continue
                    _too_big(resp.headers.get("content-length"))
                    chunks, size = [], 0
                    async for chunk in resp.aiter_content():
                        size += len(chunk)
                        _too_big(size)
                        chunks.append(chunk)
                    raw, charset = b"".join(chunks), resp.encoding
                    complete = True
                finally:
                    if not complete and getattr(resp, "quit_now", None) is not None:
                        resp.quit_now.set()       # stop the transfer itself (redirect body, too big, error)
                    await resp.aclose()
            else:
                async with sess.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30),
                                    allow_redirects=False) as resp:
                    status, loc = resp.status, resp.headers.get("Location")
                    if status in REDIRECTS and loc:
                        url = urljoin(url, loc)
                        continue
                    _too_big(resp.headers.get("Content-Length"))
                    buf = bytearray()             # read(n) may return early: read until the end or past the limit
                    while len(buf) <= MAX_BODY and (chunk := await resp.content.read(min(65536, MAX_BODY + 1 - len(buf)))):
                        buf += chunk
                    _too_big(len(buf))
                    raw = bytes(buf)
                    try:
                        charset = resp.get_encoding()
                    except Exception:  # noqa: BLE001 - unknown / undetectable charset
                        charset = resp.charset
            self.final_url[retailer] = url
            try:
                return status, raw.decode(charset or "utf-8", errors="replace")
            except LookupError:                       # a charset name Python doesn't know
                return status, raw.decode("utf-8", errors="replace")
        raise ValueError("too many redirects")

    @staticmethod
    async def _check_public(url: str) -> None:
        """Refuse an address whose name resolves to a private, loopback or link-local address."""
        import ipaddress
        import socket

        host = urlparse(url).hostname or ""
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError as err:
            raise ValueError(f"cannot resolve {host}") from err
        for info in infos:
            if not ipaddress.ip_address(info[4][0].split("%")[0]).is_global:
                raise ValueError(f"{host} is not a public address")

    def next_free(self, url_or_site: str, search: bool = False) -> float:
        """Seconds until this site may be asked again (searches: also the search gap)."""
        site = site_of(url_or_site) if "/" in url_or_site else url_or_site
        due = self.last_request.get(site, 0) + self.domain_gap
        if search:
            due = max(due, self.last_search.get(site, 0) + self.search_gap)
        return max(0.0, due - time.time())

    async def _wait_turn(self, site: str, search: bool) -> None:
        while (left := self.next_free(site, search)) > 0:
            if self.abort and self.abort():
                raise Aborted
            await asyncio.sleep(min(left, 1.0))

    async def _get(self, retailer: str, url: str, search: bool = False) -> tuple[int, str]:
        if not ready():          # the one gate every request to a shop passes
            raise NotReady(T("no shop settings imported (or their terms not accepted): nothing is fetched"))
        if self._curl_ok is None:
            await self.async_setup()
        site = site_of(url)
        lock = self._locks.setdefault(site, asyncio.Lock())      # one request at a time per site
        async with lock:
            await self._wait_turn(site, search)
            origin = home_of(retailer)
            if not ready():      # withdrawn while waiting for this site's turn
                raise NotReady(T("no shop settings imported (or their terms not accepted): nothing is fetched"))
            if origin and retailer not in self._warmed:   # look like a visitor: home page first
                self._warmed.add(retailer)
                try:
                    await self._request(retailer, origin)
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(2 + random.random() * 2)
            await asyncio.sleep(self.min_delay + random.random() * 3)
            if not ready():      # withdrawn while waiting for this site's turn
                raise NotReady(T("no shop settings imported (or their terms not accepted): nothing is fetched"))
            try:
                return await self._request(retailer, url, referer=origin)
            finally:
                self.last_request[site] = time.time()
                if search:
                    self.last_search[site] = time.time()

    def reset_cooldowns(self, retailer: str | None = None) -> None:
        if retailer is None:
            self.blocked_until.clear()
            self.blocks.clear()
        else:
            self.blocked_until.pop(retailer, None)
            self.blocks.pop(retailer, None)

    def paused(self) -> dict[str, float]:
        return {r: round(self.cooldown_left(r) / 3600, 2) for r in self.blocked_until if self.cooldown_left(r) > 0}

    def cooldown_left(self, retailer: str) -> float:
        return max(0.0, self.blocked_until.get(retailer, 0) - time.time())

    def _note_block(self, retailer: str) -> None:
        n = self.blocks.get(retailer, 0)
        if retailer in self.no_autopause:       # user chose: never pause this shop
            self.blocks[retailer] = n + 1
            return
        hours = COOLDOWN_HOURS[min(n, len(COOLDOWN_HOURS) - 1)]
        self.blocked_until[retailer] = time.time() + hours * 3600
        if self.on_pause:
            self.on_pause(retailer, hours)
        self.blocks[retailer] = n + 1

    async def fetch_offer(self, retailer: str, url: str, force: bool = False) -> tuple[Parsed | None, str | None]:
        """Returns (parsed, error). force: also try a paused shop (manual action from the panel)."""
        t0 = time.time()
        parsed, status, size, error = await self._fetch_offer(retailer, url, force)
        if not (error or "").startswith("paused"):
            res = None if not parsed else (f"€{parsed.price:.2f}" if parsed.price is not None else "unavailable")
            self._trace(retailer, "page", url, t0, status, size, res, error)
        return parsed, error

    async def _fetch_offer(self, retailer: str, url: str, force: bool) -> tuple[Parsed | None, int | None, int, str | None]:
        if not force and (left := self.cooldown_left(retailer)) > 0:
            return None, None, 0, T("paused {hours} h after being blocked", hours=f"{left / 3600:.1f}")
        try:
            status, page = await self._get(retailer, url)
        except Aborted:
            return None, None, 0, T("paused: the job was stopped")
        except Exception as err:  # noqa: BLE001 - aiohttp and curl_cffi raise different types
            return None, None, 0, T("network error: {error}", error=str(err)[:120])
        size = len(page or "")
        if status in (403, 429, 503):
            self._note_block(retailer)
            return None, status, size, T("blocked (HTTP {status})", status=status)
        if status == 404:
            return None, status, size, T("page not found (HTTP 404)")
        if status >= 400:
            return None, status, size, T("HTTP error {status}", status=status)
        parsed = parse_page(retailer, page)
        if parsed.blocked:
            self._note_block(retailer)
            return None, status, size, T("blocked (captcha / bot protection)")
        if parsed.price is None and not parsed.unavailable:
            return None, status, size, T("price not found on the page")
        self.blocks[retailer] = 0
        return parsed, status, size, None

    async def get_page(self, key: str, url: str, force: bool = False, note_block: bool = True) -> tuple[int, str, str | None]:
        """(status, html, error) for a page, with the same politeness and pauses.
        note_block=False: a refusal doesn't pause the whole site (e.g. only its product pages are blocked)."""
        if not force and (left := self.cooldown_left(key)) > 0:
            return 0, "", T("paused {hours} h after being blocked", hours=f"{left / 3600:.1f}")
        try:
            status, page = await self._get(key, url)
        except Aborted:
            return 0, "", T("paused: the job was stopped")
        except Exception as err:  # noqa: BLE001
            return 0, "", T("network error: {error}", error=str(err)[:120])
        if status in (403, 429, 503) or bot_wall(page):
            if note_block:
                self._note_block(key)
            return status, "", T("blocked (HTTP {status})", status=status) if status >= 400 else T("blocked (captcha / bot protection)")
        return status, page, None

    def _landed_on_product(self, retailer: str, url: str, page: str, product: dict[str, Any]) -> tuple[str, Parsed] | None:
        """A search for an exact barcode often jumps straight to the product page (redirect): that page is the link."""
        final = (self.final_url.get(retailer) or "").split("#")[0]
        if not final or final.split("?")[0] == url.split("?")[0] or is_search_url(final) or site_of(final) != site_of(url):
            return None
        parsed = parse_page(retailer, page)
        if parsed.price is None and not parsed.unavailable and not parsed.title:
            return None
        return (final, parsed) if product_match(product, parsed, final)[0] == "ok" else None

    async def discover(self, retailer: str, product: dict[str, Any], force: bool = False,
                       skip: set[str] | frozenset[str] = frozenset(), url: str | None = None) -> tuple[str | None, str | None]:
        """Find the product's page at this shop; (link, how) with how 'ean', 'agg', 'web' or 'name'.

        Several methods are combined, cheapest and surest first, and every candidate page is fetched and verified
        (barcode / model number / title / accessory words) before it is linked:
          1. the shop's own search for the barcode
          2. links to this shop in price-comparison sites (their sponsored product ads included), one search per product
          3. a web search for "<brand> <name> <shop>": the first results on the shop's domain
          4. the shop's own search for the name
        Every attempt is kept in the shop's trace (Shops → click a shop). skip: url_keys of links blocked for this
        product. url: a search page to use instead of the shop's own search address."""
        t0 = time.time()
        self._search_meta[retailer] = (None, 0)
        found, via = await self._discover(retailer, product, force, skip, url)
        err = self.discover_error.get(retailer)
        if not (err or "").startswith("paused"):
            status, size = self._search_meta.get(retailer, (None, 0))
            self._trace(retailer, "search", url or search_address(retailer, search_terms(product), product.get("ean")) or "",
                        t0, status, size, found, err, product.get("id"))
        return found, via

    async def _discover(self, retailer: str, product: dict[str, Any], force: bool,
                        skip: set[str] | frozenset[str], url: str | None) -> tuple[str | None, str | None]:
        """Every method in turn; a page that surely is the product ends the search, a page that may well be it (title
        close enough, no other barcode, no accessory) is kept as the answer when nothing surer turns up: you confirm it."""
        self.discover_error[retailer] = None
        self.discover_quality[retailer] = None
        self._maybe[retailer] = None
        ean = gtin_key(product.get("ean")) and (product.get("ean") or "").strip()
        shop_ean = ("ean", u) if not url and ean and (u := search_address(retailer, None, ean)) else None
        names: list[tuple[str, str]] = [("name", url)] if url else []
        if not url and product.get("name"):
            for q in search_variants(product)[:3]:
                u = search_address(retailer, q, ean)
                if u and u not in [n[1] for n in names] and (not shop_ean or u != shop_ean[1]):
                    names.append(("name", u))
        finders = bool(not url and retailer in RETAILERS and active_finders())
        if not (shop_ean or names or finders) or (not force and self.cooldown_left(retailer) > 0):
            self.discover_error[retailer] = T("paused after being blocked") if (shop_ean or names or finders) else T("this shop has no search URL")
            return None, None

        def done(found: str | None, how: str | None) -> tuple[str | None, str | None]:
            if found:
                self.discover_quality[retailer] = "ok"
                return found, how
            if self._maybe.get(retailer):
                self.discover_quality[retailer] = "maybe"
                return self._maybe[retailer]
            return None, None

        if shop_ean:
            found, stop = await self._shop_search(retailer, product, *shop_ean, skip)
            if found or stop:
                return done(found, shop_ean[0] if found else None)
        if finders:
            for how, loader in (("agg", self._harvested), ("web", self._web_results)):
                cands = await loader(retailer, product, skip)
                for cand in cands[:FINDER_VERIFY]:
                    verdict = await self._verify(retailer, cand["url"], product)
                    if verdict == "ok":
                        return done(cand["url"], how)
                    if verdict == "maybe" and not self._maybe.get(retailer):
                        self._maybe[retailer] = (cand["url"], how)
                    if verdict == "blocked":
                        return done(None, None)
        for how, search_url in names:
            found, stop = await self._shop_search(retailer, product, how, search_url, skip)
            if found:
                return done(found, how)
            if stop:
                break
        return done(None, None)

    async def _shop_search(self, retailer: str, product: dict[str, Any], how: str, search_url: str,
                           skip: set[str] | frozenset[str]) -> tuple[str | None, bool]:
        """One search on the shop's own site: (link or None, stop). stop: the shop blocked us or the job was stopped."""
        ean = gtin_key(product.get("ean")) and (product.get("ean") or "").strip()
        try:
            status, page = await self._get(retailer, search_url, search=True)
            self._search_meta[retailer] = (status, len(page or ""))
        except Aborted:
            self.discover_error[retailer] = T("paused: the job was stopped")
            return None, True
        except Exception as err:  # noqa: BLE001
            self.discover_error[retailer] = T("could not reach the shop: {error}", error=str(err)[:100])
            return None, False
        if status in (403, 429, 503) or (status < 400 and parse_page(retailer, page).blocked):
            self._note_block(retailer)
            self.discover_error[retailer] = T("the shop blocked the search (HTTP {status})", status=status) if status >= 400 \
                else T("the shop blocked the search (captcha / bot protection)")
            return None, True
        if status >= 400:
            self.discover_error[retailer] = T("search page: HTTP error {status}", status=status)
            return None, False
        if (landed := self._landed_on_product(retailer, search_url, page, product)):
            final, _parsed = landed
            if url_key(retailer, final) not in skip:
                return final, False
        floor = EAN_CANDIDATE_MIN if how == "ean" else NAME_CANDIDATE_MIN
        candidates = [c for c in search_candidates(retailer, page, product, skip) if c["score"] >= floor][:VERIFY_PAGES]
        for cand in candidates:                   # look at the product page itself before trusting a result
            verdict = await self._verify(retailer, cand["url"], product)
            if verdict == "ok":
                return cand["url"], False
            if verdict == "maybe" and not self._maybe.get(retailer):
                self._maybe[retailer] = (cand["url"], how)
            if verdict == "blocked":
                return None, True
        self.discover_error[retailer] = T("no matching product found") if (product.get("name") or "")[:12].lower() in page.lower() \
            or (ean and ean in page) else \
            T("the search page does not contain the product: this shop probably loads its results with JavaScript. Paste the product page URL instead.")
        return None, False

    # ----------------------------------------------------------------- finders (web search, comparison sites)
    async def _finder_page(self, finder: dict[str, Any], query: str, product: dict[str, Any]) -> str:
        """The result page of one finder search ('' when it failed or the finder is paused); traced under the finder."""
        key = finder_key(finder["id"])
        if self.cooldown_left(key) > 0:
            return ""
        url, t0 = finder_address(finder, query), time.time()
        status, page, err = await self.get_page(key, url)
        self._trace(key, "search", url, t0, status or None, len(page or ""), "ok" if page else None, err, product.get("id"))
        return page if not err and status < 400 else ""

    async def _finder_links(self, finder: dict[str, Any], query: str, product: dict[str, Any],
                            skip: set[str] | frozenset[str]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        page = await self._finder_page(finder, query, product)
        if not page:
            return {}, []
        names = shop_names()
        by_shop, others = offers(page, all_domains(), product, skip, url_key, finder["domain"], names)
        if finder.get("follow") and product.get("name"):
            # Tweakers, Kieskeurig, Beslist…: the search lists products; the product's own page there lists every shop
            for url in product_pages(page, finder["domain"], product)[:1]:
                t0 = time.time()
                status, sub, err = await self.get_page(finder_key(finder["id"]), url)
                self._trace(finder_key(finder["id"]), "page", url, t0, status or None, len(sub or ""), "ok" if sub else None, err, product.get("id"))
                if sub and not err and status < 400:
                    more, new = offers(sub, all_domains(), product, skip, url_key, finder["domain"], names)
                    for rid, items in more.items():
                        have = {x["url"] for x in by_shop.setdefault(rid, [])}
                        by_shop[rid].extend(i for i in items if i["url"] not in have or i["url"] is None)
                    others += [o for o in new if o["domain"] not in {x["domain"] for x in others}]
        for items in [*by_shop.values(), others]:
            for i in items:
                i["finder"], i["by_ean"] = finder["id"], bool(gtin_key(query))
        return by_shop, others

    async def harvest(self, product: dict[str, Any], max_age: float = HARVEST_TTL) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        """Every offer comparison sites show for this product: ({shop id: [offers]}, [offers at shops not in your list]).
        One search per comparison site (by barcode, else by name) serves every shop; the result is kept for a while."""
        pid = product.get("id") or product.get("name") or ""
        lock = self._harvest_locks.setdefault(pid, asyncio.Lock())
        async with lock:
            cached = self._harvest.get(pid)
            if not cached or time.time() - cached[0] > max_age:
                merged: dict[str, list[dict[str, Any]]] = {}
                others: list[dict[str, Any]] = []
                ean = gtin_key(product.get("ean")) and (product.get("ean") or "").strip()
                for finder in active_finders("aggregator"):
                    for query in [q for q in (ean, search_terms(product)) if q]:
                        links, new = await self._finder_links(finder, query, product, frozenset())
                        for rid, items in links.items():
                            seen = {x["url"] for x in merged.setdefault(rid, [])}
                            merged[rid].extend(i for i in items if i["url"] not in seen)
                        others.extend(o for o in new if o["domain"] not in {x["domain"] for x in others})
                        if links or new:
                            break                 # the barcode search answered: no need for the name search
                self._harvest[pid] = cached = (time.time(), merged, others)
        return cached[1], cached[2]

    async def _harvested(self, retailer: str, product: dict[str, Any], skip: set[str] | frozenset[str]) -> list[dict[str, Any]]:
        """Links to this shop found in comparison sites."""
        by_shop, _others = await self.harvest(product)
        return [c for c in by_shop.get(retailer, []) if c["url"] and url_key(retailer, c["url"]) not in skip]

    # ----------------------------------------------------------------- identity (name ↔ barcode)
    async def identify(self, name: str | None = None, ean: str | None = None, brand: str | None = None,
                       max_pages: int = 4) -> dict[str, Any]:
        """Who is this product? From a name: find its barcode; from a barcode: find its name, brand, picture.

        Finders (comparison sites first, then web search) and the shops' own barcode search give candidate pages; each
        page is fetched and only counts when it really is the product: for a barcode the page must carry that barcode,
        for a name its title must cover the name (model numbers included) and must not be an accessory. A barcode found
        from a name is only trusted when two pages agree, or one page matches the name very closely.
        Returns {name, brand, ean, mpn, image, category, price, ean_sure, pages: [{retailer, url, price, title}]}."""
        from .models import normalize_gtin

        ean = normalize_gtin(ean) if ean else None
        probe = {"name": name or "", "brand": brand, "ean": ean}
        cands: list[tuple[str, str]] = []

        def add(rid: str, url: str) -> None:
            if (rid, url) not in cands:
                cands.append((rid, url))

        query = ean or search_terms(probe)
        if not query:
            return {}
        for finder in active_finders("aggregator") + active_finders("websearch"):
            by_shop, _new = await self._finder_links(finder, query, probe if name else {}, frozenset())
            ranked = sorted(((i["score"], rid, i["url"]) for rid, items in by_shop.items() for i in items if i["url"]), key=lambda x: -x[0])
            for score, rid, url in ranked:
                if ean or score >= TITLE_OK:
                    add(rid, url)
            if len(cands) >= max_pages:
                break
        if ean and len(cands) < 2:                   # the shops' own barcode search
            for rid in [r for r in RETAILERS if search_address(r, None, ean)][:4]:
                try:
                    status, page = await self._get(rid, search_address(rid, None, ean) or "", search=True)
                except Exception:  # noqa: BLE001 - also NotReady / Aborted: then there is simply nothing
                    continue
                if status >= 400 or bot_wall(page):
                    continue
                final = (self.final_url.get(rid) or "").split("#")[0]
                if final and not is_search_url(final) and site_of(final) == site_of(search_address(rid, None, ean) or ""):
                    add(rid, final)
                for cand in search_candidates(rid, page, probe)[:1]:
                    add(rid, cand["url"])
                if len(cands) >= max_pages:
                    break
        pages: list[dict[str, Any]] = []
        votes: dict[str, int] = {}
        best: tuple[float, Parsed, str] | None = None
        for rid, url in cands[: max_pages + 2]:
            try:
                status, page = await self._get(rid, url)
            except Exception:  # noqa: BLE001
                continue
            if status >= 400 or bot_wall(page):
                continue
            parsed = parse_page(rid, page)
            keys = {gtin_key(g) for g in parsed.gtins} - {None}
            if ean:
                ok, score = gtin_key(ean) in keys, 1.0
            else:
                score = title_score(name, brand, parsed.title)[0] if parsed.title else 0.0
                ok = score >= TITLE_OK and not accessory_word(parsed.title, name)
            if not ok:
                continue
            pages.append({"retailer": rid, "url": url, "price": parsed.price, "title": (parsed.title or "")[:200],
                          "gtins": list(parsed.gtins)})
            for g in parsed.gtins:
                if (n := normalize_gtin(g)):
                    votes[n] = votes.get(n, 0) + 1
            if best is None or score > best[0]:
                best = (score, parsed, url)
            if len(pages) >= (2 if ean else 3):
                break
        if not best:
            return {"name": name, "brand": brand, "ean": ean, "ean_sure": bool(ean), "pages": []}
        ident = product_identity(best[1], best[2])
        found_ean, sure = ean, bool(ean)
        if not ean and votes:
            top, n = max(votes.items(), key=lambda kv: kv[1])
            sure = n >= 2 or (len(votes) == 1 and best[0] >= 0.9)
            found_ean = top if sure else None
        return {**ident, "name": name or ident["name"], "brand": brand or ident["brand"], "ean": found_ean, "ean_sure": sure,
                "pages": pages}

    async def _web_results(self, retailer: str, product: dict[str, Any], skip: set[str] | frozenset[str]) -> list[dict[str, Any]]:
        """Web search for "<brand> <name> <shop>": results on the shop's own domain, in the order the engine gives them."""
        shop = RETAILERS.get(retailer, (retailer,))[0]
        out: list[dict[str, Any]] = []
        ean = gtin_key(product.get("ean")) and (product.get("ean") or "").strip()
        queries = [q for q in [*(search_variants(product)[:2]), ean] if q]
        for finder in active_finders("websearch"):
            for q in queries:
                links, _new = await self._finder_links(finder, f"{q} {shop}".strip(), product, skip)
                for item in links.get(retailer, []):
                    if item["url"] and item["url"] not in [x["url"] for x in out]:
                        out.append(item)
                if out:
                    return out
        return out

    async def _verify(self, retailer: str, url: str, product: dict[str, Any]) -> str:
        """'ok' when the product page proves it is the product, 'blocked' when the shop refused, else 'no'."""
        t0 = time.time()
        try:
            status, page = await self._get(retailer, url)
        except Exception as err:  # noqa: BLE001 - also Aborted
            self._trace(retailer, "page", url, t0, None, 0, None, T("network error: {error}", error=str(err)[:120]), product.get("id"))
            return "no"
        if status in (403, 429, 503) or (status < 400 and bot_wall(page)):
            self._note_block(retailer)
            self.discover_error[retailer] = T("blocked (HTTP {status})", status=status) if status >= 400 \
                else T("blocked (captcha / bot protection)")
            self._trace(retailer, "page", url, t0, status, len(page or ""), None, self.discover_error[retailer], product.get("id"))
            return "blocked"
        if status >= 400:
            self._trace(retailer, "page", url, t0, status, len(page or ""), None, T("HTTP error {status}", status=status), product.get("id"))
            return "no"
        parsed = parse_page(retailer, page)
        verdict, reason = product_match(product, parsed, url)
        self._trace(retailer, "page", url, t0, status, len(page or ""), url if verdict == "ok" else None,
                    None if verdict == "ok" else reason, product.get("id"))
        self.page_info[url] = {"title": (parsed.title or "")[:300], "price": parsed.price, "image": parsed.image,
                               "gtins": list(parsed.gtins), "mpn": parsed.mpn, "reason": reason}
        if len(self.page_info) > 500:
            for k in list(self.page_info)[:100]:
                del self.page_info[k]
        if wrong_product(product, parsed) is not None:
            return "no"
        if verdict == "ok":
            return "ok"
        # may well be it: no other barcode on the page, no accessory, and the title covers at least half of the name
        keys = {gtin_key(g) for g in parsed.gtins} - {None}
        own = gtin_key(product.get("ean"))
        if own and keys and own not in keys:
            return "no"
        score, missing = title_score(product.get("name"), product.get("brand"), parsed.title) if parsed.title else (0.0, [])
        if parsed.title and score >= TITLE_DOUBT and not missing and not accessory_word(parsed.title, product.get("name")):
            return "maybe"
        return "no"
