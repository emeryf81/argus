"""Shop registry, built from the shop settings file the user imports (plus shops added by hand).

The integration contains no list of shops or websites: until a settings file is imported and its terms are
accepted, there are no shops and nothing is fetched (see ready()). RETAILERS (label, currency), GENERIC_SHOPS
(domain, search template) and SEARCH are module-level dicts shared by the whole integration; apply_shop_options()
rebuilds them from the config entry options.

A shop lists the product categories it sells (electronics, books, ...): a product is only searched at the shops of
its own category.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote_plus, urlparse

from .const import CATEGORIES, DEFAULT_SEARCH, GENERIC_SHOPS, RETAILERS
from .i18n import LocalizedError, T

SETTINGS_FORMAT = "argus-shop-settings"
SETTINGS_VERSION = 1
LEGAL_VERSION = 1                 # raise when the terms change: everyone accepts them again at the next import
CONF_SHOP_PROFILE = "shop_profile"
CONF_LEGAL = "legal"
# how a shop's pages are read (the page structure the parser knows), not a website:
#   marketplace  a marketplace with a "buy box" (the price of the seller that wins it) and product codes in the address
#   retail       a shop whose product data sits in JSON-LD and data attributes
#   generic      any other shop (JSON-LD / meta data)
READERS = ("marketplace", "retail", "generic")
MAX_SHOPS = 60
MAX_FINDERS = 12
FINDER_KINDS = ("websearch", "aggregator")
FINDER_PREFIX = "finder:"        # the key of a finder in the fetcher (cookies, pauses, trace)

SEARCH: dict[str, str] = dict(DEFAULT_SEARCH)      # effective search template per shop
PROFILE: dict[str, dict[str, Any]] = {}            # shop id -> its entry in the imported settings file
ALIASES: list[tuple[str, str]] = []                 # (shop name as written elsewhere, shop id), longest first
CATEGORY_OF: dict[str, tuple[str, ...]] = {}        # shop id -> categories it sells (empty = every category)
FINDERS: dict[str, dict[str, Any]] = {}            # finder id -> {id, name, kind, domain, search}
ENABLED_FINDERS: set[str] = set()
AUTO_SHOPS: dict[str, dict[str, Any]] = {}          # shops found through comparison sites (kept in the store)
MAX_AUTO_SHOPS = 40
STATE = {"profile": False, "legal": False}


def shop_id(name: str) -> str:
    return "c_" + (re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "shop")[:30]


def _domain(value: Any) -> str:
    return re.sub(r"^https?://(www\.)?", "", str(value or "").strip().lower()).split("/")[0]


def _on(url: str, domain: str) -> bool:
    host = (urlparse(url.replace("{query}", "x").replace("{ean}", "1")).hostname or "").lower()
    return host == domain or host.endswith("." + domain)


def valid_search(tpl: str) -> bool:
    return tpl.startswith("https://") and ("{query}" in tpl or "{ean}" in tpl) and " " not in tpl


def _https_on(url: Any, domain: str) -> bool:
    return isinstance(url, str) and url.startswith("https://") and " " not in url and _on(url, domain)


def _categories(raw: Any, who: str) -> list[str]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise LocalizedError("{field}: wrong type in the shop settings file.", field=f"{who}.categories")
    bad = [c for c in raw if c not in CATEGORIES]
    if bad:
        raise LocalizedError("Shop {id}: unknown category {category} (one of: {categories}).", id=who, category=bad[0],
                             categories=", ".join(CATEGORIES))
    return list(dict.fromkeys(raw))


def validate_custom_shop(shop: dict[str, Any]) -> dict[str, Any]:
    name = str(shop.get("name", "")).strip()[:40]
    domain = _domain(shop.get("domain"))
    search = str(shop.get("search", "")).strip()
    if not name:
        raise LocalizedError("Give the shop a name.")
    if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", domain):
        raise LocalizedError("Invalid domain {domain} (e.g. example-shop.be).", domain=domain)
    if search and (not valid_search(search) or not _on(search, domain)):   # the shop's own host
        raise LocalizedError("The search URL must start with https://, be on the shop's domain and contain {query} or {ean}.")
    sid = str(shop.get("id") or shop_id(name))
    return {"id": sid, "name": name, "domain": domain, "search": search,
            "categories": _categories(shop.get("categories"), sid)}


def validate_settings(data: Any) -> dict[str, Any]:
    """A shop settings file, checked and cleaned. Raises LocalizedError with what is wrong."""
    if not isinstance(data, dict) or data.get("format") != SETTINGS_FORMAT:
        raise LocalizedError("This is not a shop settings file for this integration.")
    if data.get("version") != SETTINGS_VERSION:
        raise LocalizedError("Shop settings file version {version} is not supported.", version=data.get("version"))
    if data.get("shops") is not None and not isinstance(data["shops"], list):
        raise LocalizedError("{field}: wrong type in the shop settings file.", field="shops")
    shops, seen = [], set()
    for raw in data.get("shops") or []:
        if not isinstance(raw, dict):
            raise LocalizedError("Every shop must be an object with id, name, domain and reader.")
        rid, name, domain = str(raw.get("id") or "").strip(), str(raw.get("name") or "").strip()[:40], _domain(raw.get("domain"))
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,39}", rid) or rid.startswith(("c_", "a_")) or rid in seen:
            raise LocalizedError("Shop id {id}: use lowercase letters, digits and _, unique, not starting with c_.", id=rid)
        if not name or not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", domain):
            raise LocalizedError("Shop {id}: a name and a valid domain are needed.", id=rid)
        reader = raw.get("reader") or "generic"
        if reader not in READERS:
            raise LocalizedError("Shop {id}: unknown reader {reader} (one of: {readers}).", id=rid, reader=reader, readers=", ".join(READERS))
        shop: dict[str, Any] = {"id": rid, "name": name, "domain": domain, "reader": reader,
                                "categories": _categories(raw.get("categories"), rid)}
        for key in ("search", "home"):
            if (v := raw.get(key)) in (None, ""):
                continue
            if not _https_on(v, domain) or (key == "search" and not valid_search(v)):
                raise LocalizedError("Shop {id}: {field} must be an https:// address on {domain}.", id=rid, field=key, domain=domain)
            shop[key] = v
        aliases = raw.get("aliases") or []
        if not isinstance(aliases, list) or not all(isinstance(x, str) for x in aliases):
            raise LocalizedError("{field}: wrong type in the shop settings file.", field=f"{rid}.aliases")
        shop["aliases"] = [a for a in (x.strip().lower()[:40] for x in aliases) if len(a) >= 3][:20]
        seen.add(rid)
        shops.append(shop)
    finders, fseen = [], set()
    if data.get("finders") is not None and not isinstance(data["finders"], list):
        raise LocalizedError("{field}: wrong type in the shop settings file.", field="finders")
    for raw in data.get("finders") or []:
        if not isinstance(raw, dict):
            raise LocalizedError("Every finder must be an object with id, name, kind, domain and search.")
        fid, name, domain = str(raw.get("id") or "").strip(), str(raw.get("name") or "").strip()[:40], _domain(raw.get("domain"))
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,39}", fid) or fid in fseen:
            raise LocalizedError("Finder id {id}: use lowercase letters, digits and _, unique.", id=fid)
        if not name or not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", domain):
            raise LocalizedError("Finder {id}: a name and a valid domain are needed.", id=fid)
        if raw.get("kind") not in FINDER_KINDS:
            raise LocalizedError("Finder {id}: unknown kind (one of: {kinds}).", id=fid, kinds=", ".join(FINDER_KINDS))
        search = raw.get("search")
        if not _https_on(search, domain) or not valid_search(search):
            raise LocalizedError("Finder {id}: the search URL must start with https://, be on the finder's domain and contain {query} or {ean}.", id=fid)
        fseen.add(fid)
        mark = str(raw.get("mark") or "").strip().lower()
        finders.append({"id": fid, "name": name, "kind": raw["kind"], "domain": domain, "search": search,
                        **({"mark": mark} if re.fullmatch(r"[a-z]", mark) else {})})
    if len(finders) > MAX_FINDERS:
        raise LocalizedError("At most {n} finders in one settings file.", n=MAX_FINDERS)
    if not shops:
        raise LocalizedError("The shop settings file contains no shops.")
    if len(shops) > MAX_SHOPS:
        raise LocalizedError("At most {n} shops in one settings file.", n=MAX_SHOPS)
    return {"format": SETTINGS_FORMAT, "version": SETTINGS_VERSION, "shops": shops, **({"finders": finders} if finders else {})}


def legal_ok(options: dict[str, Any]) -> bool:
    legal = options.get(CONF_LEGAL) or {}
    return bool(legal.get("accepted")) and legal.get("version") == LEGAL_VERSION


def revoke() -> None:
    """Withdrawn: from this moment on nothing is fetched, also before the integration has reloaded."""
    STATE["profile"] = STATE["legal"] = False


def ready() -> bool:
    """Shop settings imported and their terms accepted: only then does the integration contact any website."""
    return STATE["profile"] and STATE["legal"]


def profile_ids() -> list[str]:
    return list(PROFILE)


def reader_of(rid: str) -> str:
    return (PROFILE.get(rid) or {}).get("reader") or "generic"


def apply_shop_options(options: dict[str, Any]) -> None:
    """Rebuild the registry from the options (imported settings + custom shops + search overrides)."""
    profile = options.get(CONF_SHOP_PROFILE)
    try:
        profile = validate_settings(profile) if profile else None
    except (ValueError, TypeError, AttributeError):
        profile = None
    STATE["profile"], STATE["legal"] = profile is not None, legal_ok(options)
    RETAILERS.clear()
    GENERIC_SHOPS.clear()
    DEFAULT_SEARCH.clear()
    PROFILE.clear()
    ALIASES.clear()
    CATEGORY_OF.clear()
    FINDERS.clear()
    for f in (profile or {}).get("finders", []):
        FINDERS[f["id"]] = f
    enabled = options.get("finders")
    ENABLED_FINDERS.clear()
    ENABLED_FINDERS.update(f for f in FINDERS if enabled is None or f in enabled)
    for shop in (profile or {}).get("shops", []):
        PROFILE[shop["id"]] = shop
        RETAILERS[shop["id"]] = (shop["name"], "EUR")
        CATEGORY_OF[shop["id"]] = tuple(shop.get("categories") or ())
        if shop.get("search"):
            DEFAULT_SEARCH[shop["id"]] = shop["search"]
        if shop["reader"] == "generic":
            GENERIC_SHOPS[shop["id"]] = {"domain": shop["domain"], "search": shop.get("search", "")}
        ALIASES.extend((a, shop["id"]) for a in shop["aliases"])
    ALIASES.sort(key=lambda a: -len(a[0]))
    for shop in options.get("custom_shops", []) or []:
        try:
            s = validate_custom_shop(shop)
        except ValueError:
            continue
        if s["id"] in PROFILE:
            continue
        RETAILERS[s["id"]] = (s["name"], "EUR")
        GENERIC_SHOPS[s["id"]] = {"domain": s["domain"], "search": s["search"]}
        CATEGORY_OF[s["id"]] = tuple(s["categories"])
    _add_auto_shops()
    SEARCH.clear()
    SEARCH.update(DEFAULT_SEARCH)
    for rid, g in GENERIC_SHOPS.items():
        if g.get("search"):
            SEARCH[rid] = g["search"]
    for rid, tpl in (options.get("shop_search", {}) or {}).items():
        if rid in RETAILERS and tpl and valid_search(tpl):
            SEARCH[rid] = tpl
            if rid in GENERIC_SHOPS:
                GENERIC_SHOPS[rid]["search"] = tpl


def auto_shop_id(domain: str) -> str:
    return "a_" + re.sub(r"[^a-z0-9]+", "_", domain.lower().removeprefix("www.")).strip("_")[:36]


def _add_auto_shops() -> None:
    for s in AUTO_SHOPS.values():
        if s["id"] in RETAILERS or any(_on("https://" + s["domain"], d) for d in all_domains().values()):
            continue
        RETAILERS[s["id"]] = (s["name"], "EUR")
        GENERIC_SHOPS[s["id"]] = {"domain": s["domain"], "search": ""}
        CATEGORY_OF[s["id"]] = tuple(s.get("categories") or ())


def set_auto_shops(items: Any) -> None:
    """(Re)register the shops ARGUS found itself through comparison sites (stored in the integration's data)."""
    for rid in list(AUTO_SHOPS):
        if rid in RETAILERS and rid not in PROFILE:
            RETAILERS.pop(rid, None)
            GENERIC_SHOPS.pop(rid, None)
            CATEGORY_OF.pop(rid, None)
    AUTO_SHOPS.clear()
    for s in (items or [])[:MAX_AUTO_SHOPS]:
        if isinstance(s, dict) and s.get("id", "").startswith("a_") and s.get("domain"):
            AUTO_SHOPS[s["id"]] = s
    _add_auto_shops()


def export_settings(options: dict[str, Any]) -> dict[str, Any]:
    """The settings in force, as a file you can import again (imported shops, shops added by hand, your search URLs)."""
    profile = options.get(CONF_SHOP_PROFILE) or {"format": SETTINGS_FORMAT, "version": SETTINGS_VERSION, "shops": []}
    out = {"format": SETTINGS_FORMAT, "version": SETTINGS_VERSION,
           "notice": T("You decide yourself which websites your Home Assistant contacts, and you alone are responsible for everything that happens between your Home Assistant and those websites: respecting their terms of use, robots.txt and the law that applies to you, and all legal consequences. The software is provided as is, without any warranty; to the fullest extent permitted by law, its author and contributors cannot be held liable. Use it only for personal, non-commercial purposes and moderately. The names of shops are trademarks of their owners; this project is not affiliated with or endorsed by any of them.")}
    shops = []
    for shop in profile.get("shops", []):
        s = dict(shop)
        if (tpl := (options.get("shop_search") or {}).get(s["id"])) and valid_search(tpl):
            s["search"] = tpl
        shops.append(s)
    out["shops"] = shops
    if profile.get("finders"):
        out["finders"] = list(profile["finders"])
    out["custom_shops"] = [s for s in options.get("custom_shops", []) or []]
    return out


def search_address(rid: str, query: str | None = None, ean: str | None = None) -> str | None:
    """The shop's search page for a name and/or barcode. A template with {ean} needs an EAN, one with {query} a name."""
    tpl = SEARCH.get(rid)
    if not tpl:
        return None
    if "{ean}" in tpl and "{query}" not in tpl and not ean:
        return None
    if "{query}" in tpl and "{ean}" not in tpl and not (query or ean):
        return None
    return tpl.replace("{query}", quote_plus(query or ean or "")).replace("{ean}", quote_plus(ean or query or ""))


def shops_for_category(category: str | None, enabled: list[str] | None = None) -> list[str]:
    """Shops that sell this category (a shop without categories sells everything), in the order of the settings file."""
    ids = [r for r in RETAILERS if enabled is None or r in enabled]
    if not category or category == "other":
        return ids
    return [r for r in ids if not CATEGORY_OF.get(r) or category in CATEGORY_OF[r]]


def finder_key(fid: str) -> str:
    return FINDER_PREFIX + fid


def active_finders(kind: str | None = None) -> list[dict[str, Any]]:
    """The finders that are switched on (in the order of the settings file), optionally of one kind."""
    return [f for f in FINDERS.values() if f["id"] in ENABLED_FINDERS and (kind is None or f["kind"] == kind)]


def finder_address(finder: dict[str, Any], query: str) -> str:
    return finder["search"].replace("{query}", quote_plus(query)).replace("{ean}", quote_plus(query))


def domain_of(rid: str) -> str | None:
    if rid.startswith(FINDER_PREFIX):
        return (FINDERS.get(rid[len(FINDER_PREFIX):]) or {}).get("domain")
    return (PROFILE.get(rid) or {}).get("domain") or GENERIC_SHOPS.get(rid, {}).get("domain")


def home_of(rid: str) -> str | None:
    """The page a visit to this shop starts on (as a visitor would): from the settings, else the shop's root."""
    if rid.startswith(FINDER_PREFIX):
        return None
    home = (PROFILE.get(rid) or {}).get("home")
    if home:
        return home
    return f"https://www.{d}/" if (d := domain_of(rid)) else None


def site_root(rid: str) -> str | None:
    """https://www.<domain>, for links in search results that are relative to the shop."""
    return f"https://www.{d}" if (d := domain_of(rid)) else None


def all_domains() -> dict[str, str]:
    return {rid: d for rid in RETAILERS if (d := domain_of(rid))}


def readers_by_domain() -> dict[str, str]:
    return {d: reader_of(rid) for rid, d in all_domains().items()}
