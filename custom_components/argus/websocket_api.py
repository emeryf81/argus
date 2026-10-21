"""Websocket API used by the sidebar panel."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import voluptuous as vol
from aiohttp import web
from homeassistant.components import websocket_api
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.core import HomeAssistant, callback

from .const import ALERT_STEPS, API_LEVEL, CATEGORIES, CONF_DEV_FULL_REFRESH, DOMAIN, PANEL_URL, RETAILERS
from .i18n import LANGUAGES, T, tr
from .models import combined_history, normalize_product_id, offer_price
from .shops import CATEGORY_OF, home_of


def _coord(hass: HomeAssistant):
    entries = hass.data.get(DOMAIN, {})
    return next(iter(entries.values()), None)


def _not_loaded(connection, msg) -> None:
    connection.send_error(msg["id"], "not_loaded", "ARGUS is not loaded")


def _card(coord, pid: str, with_history: bool = False) -> dict[str, Any]:
    """Build a panel product card with offers and optional price history."""
    p = coord.store["products"][pid]
    st = (coord.data or coord.compute())["statuses"].get(pid, {})
    offers = coord.store["offers"].get(pid, {})
    series = combined_history(offers)
    card = {
        **p, **st,
        "id": pid,
        "deal": coord.is_deal(st),
        "spark": [pr for _, pr in series][-60:],
        "shops_for": coord.shops_for(pid),
        "candidates": sorted(({k: c.get(k) for k in ("retailer", "shop", "url", "title", "price", "image", "how", "via", "sure", "found", "new_shop")}
                              for c in (coord.store.get("candidates") or {}).get(pid, {}).values()), key=lambda c: c.get("found") or 0),
        "offers": {
            rid: {"label": RETAILERS[rid][0], "url": o.get("url"), "price": offer_price(o),
                  "auto_price": o.get("auto_price") if o.get("manual_price") else None,
                  "manual_price": (o.get("manual_price") or {}).get("price"), "manual_url": bool(o.get("manual_url")),
                  "available": o.get("available"), "error": o.get("error"), "checked": o.get("last_checked"),
                  "unavailable": o.get("unavailable") if not o.get("available") else None,
                  "low": min((pr for _, pr in o.get("history", [])), default=None),
                  "title": o.get("title"), "gtins": o.get("gtins"), "link_status": o.get("link_status"),
                  "link_reason": o.get("link_reason"), "found_via": o.get("found_via"),
                  "via": o.get("last_via") if o.get("available") and not o.get("manual_price") else None,
                  "suspect": o.get("suspect"), "approved": o.get("approved"), "price_choice": o.get("price_choice"),
                  "ignored": bool(o.get("error") and o.get("ignored_error") == o.get("error")),
                  "finder_price": o.get("finder_price")}
            for rid, o in offers.items() if rid in RETAILERS
        },
    }
    if with_history:
        card["history"] = {rid: o.get("history", []) for rid, o in offers.items()}
        card["combined"] = series
    return card


def _marks() -> dict[str, dict[str, str]]:
    """The letter in a circle next to a price that came from a comparison service (ⓢ Shoparize, ⓟ Producthero…)."""
    from .finders import CSS_SERVICES
    from .shops import FINDERS

    out = {k: {"letter": v[1], "name": v[0]} for k, v in CSS_SERVICES.items()}
    for fid, f in FINDERS.items():
        out.setdefault(fid, {"letter": (f.get("mark") or f["name"][:1]).lower(), "name": f["name"]})
    return out


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    """Register panel websocket commands and the userscript and relay HTTP views."""
    for cmd in (ws_overview, ws_product, ws_product_preview, ws_candidate, ws_add_product, ws_update_product, ws_remove_product, ws_product_find,
                ws_product_refresh, ws_collection, ws_import_preview, ws_import_run, ws_job, ws_settings_get, ws_settings_set,
                ws_shop_settings_import, ws_shop_settings_export, ws_shop_settings_accept, ws_shop_settings_withdraw,
                ws_shop_action, ws_ignore_error, ws_notify_get, ws_notify_set, ws_notify_test, ws_log, ws_logs_export,
                ws_report, ws_shop_detail, ws_offer_update, ws_offer_fetch, ws_offer_approve, ws_offer_reject,
                ws_offer_confirm, ws_offer_price_choice, ws_client_error, ws_filter_test, ws_dev_tool, ws_lab, ws_ticker,
                ws_error_stats):
        websocket_api.async_register_command(hass, cmd)
    hass.http.register_view(UserscriptView())
    hass.http.register_view(RelayView())



# a page source you paste rides in one websocket message (Home Assistant takes at most 4 MB): the panel slims it first
PAGE_SOURCE_MAX = 3_500_000

@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/overview"})
@callback
def ws_overview(hass, connection, msg):
    """Send panel overview data, or a not-loaded error when no coordinator is available."""
    coord = _coord(hass)
    if coord is None:
        _not_loaded(connection, msg)
        return
    from . import VERSION

    data = coord.data or coord.compute()
    connection.send_result(msg["id"], {
        "version": VERSION, "api": API_LEVEL, "transport": coord.fetcher.transport,
        "shop_settings": coord.shop_settings_info(),
        "threshold": coord.threshold,
        "categories": dict(CATEGORIES),
        "retailers": {k: v[0] for k, v in RETAILERS.items()},
        "shop_categories": {k: list(CATEGORY_OF.get(k) or ()) for k in RETAILERS},
        "products": [_card(coord, n) for n in coord.store["products"]],
        "summary": data["summary"],
        "events": list(reversed(coord.store.get("events", [])[-40:])),
        "retailer_stats": coord.retailer_stats(),
        **coord.job_info(),
        "language": coord.language, "languages": LANGUAGES,
        "userscript_last": coord.store.get("userscript_last"), "relay_last": coord.store.get("relay_last"),
        "relay": {"enabled": coord.relay_enabled, "pending": coord.relay_items(100)["total"] if coord.relay_enabled else 0,
                  "continuous": coord.continuous_items(1)["counts"] if coord.relay_enabled else {},
                  "heartbeat": coord.store.get("relay_heartbeat")},
        "deal_rules": coord.deal_rules, "marks": _marks(), "alert_steps": list(ALERT_STEPS),
        "auto_shops": {k: {"name": v["name"], "domain": v["domain"], "found_by": coord.via_name(v.get("found_by"))}
                       for k, v in (coord.store.get("auto_shops") or {}).items() if k in RETAILERS},
        "product_limit": coord.product_limit, "full_refresh": coord.dev(CONF_DEV_FULL_REFRESH), "manual": coord.manual_status(),
        "health": {
            "errors": sum(s["offers_error"] for s in data["statuses"].values()),
            "paused_hours": {RETAILERS[r][0]: round(coord.fetcher.cooldown_left(r) / 3600, 1)
                             for r in coord.retailers if coord.fetcher.cooldown_left(r) > 0},
        },
    })


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/product/preview", vol.Optional("url", default=""): vol.All(str, vol.Length(max=2000)),
                                  vol.Optional("name", default=""): vol.All(str, vol.Length(max=200)),
                                  vol.Optional("ean", default=""): vol.All(str, vol.Length(max=40)),
                                  vol.Optional("html", default=""): vol.All(str, vol.Length(max=PAGE_SOURCE_MAX)),
                                  vol.Optional("details", default={}): {vol.Optional(k): vol.All(str, vol.Length(max=200))
                                                                        for k in ("name", "brand", "mpn", "sku", "ean")}})
@websocket_api.async_response
async def ws_product_preview(hass, connection, msg):
    """Before adding: who the product is (looked up by address, name or barcode) and which shops to watch it at."""
    coord = _coord(hass)
    if coord is None:
        _not_loaded(connection, msg)
        return
    try:
        res = await coord.preview_product(msg["url"], msg["name"], msg["ean"], html=msg["html"] or None,
                                          details={k: v for k, v in msg["details"].items() if v})
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], res)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/candidate", vol.Required("product"): str,
                                  vol.Optional("retailer"): vol.Any(None, str), vol.Required("answer"): vol.In(["yes", "no"])})
@callback
def ws_candidate(hass, connection, msg):
    """Your answer to a find: is it the same item? (retailer None: every find of the product)."""
    coord = _coord(hass)
    if coord is None:
        _not_loaded(connection, msg)
        return
    n = coord.answer_candidate(msg["product"], msg.get("retailer"), msg["answer"] == "yes")
    connection.send_result(msg["id"], {"answered": n})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/product", vol.Required("product"): str})
@callback
def ws_product(hass, connection, msg):
    coord = _coord(hass)
    pid = normalize_product_id(msg["product"])
    if coord is None or pid not in coord.store["products"]:
        connection.send_error(msg["id"], "not_found", f"Product {pid} not tracked")
        return
    connection.send_result(msg["id"], _card(coord, pid, with_history=True))


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/add_product", vol.Optional("url", default=""): vol.All(str, vol.Length(max=2000)),
    vol.Optional("name"): vol.All(str, vol.Length(max=200)), vol.Optional("ean"): vol.All(str, vol.Length(max=40)),
    vol.Optional("brand"): vol.All(str, vol.Length(max=100)), vol.Optional("mpn"): vol.All(str, vol.Length(max=100)),
    vol.Optional("category"): str, vol.Optional("ref_price"): vol.Any(None, vol.Coerce(float)),
    vol.Optional("target_price"): vol.Any(None, vol.Coerce(float)), vol.Optional("priority"): vol.Any(None, int),
    vol.Optional("notes"): vol.All(str, vol.Length(max=500)), vol.Optional("shops"): [str],
    vol.Optional("alert_pct"): vol.Any(None, int), vol.Optional("image"): vol.Any(None, str),
    vol.Optional("sku"): vol.All(str, vol.Length(max=100)), vol.Optional("html"): vol.All(str, vol.Length(max=PAGE_SOURCE_MAX)),
})
@websocket_api.async_response
async def ws_add_product(hass, connection, msg):
    """Add a product by the address of a product page (or by name/barcode); ARGUS looks it up at the other shops."""
    coord = _coord(hass)
    if coord is None:
        _not_loaded(connection, msg)
        return
    try:
        res = await coord.add_product(msg["url"], **{k: msg[k] for k in ("name", "ean", "brand", "mpn", "category", "ref_price",
                                                                           "target_price", "priority", "notes", "shops", "alert_pct", "image", "sku", "html")
                                                 if msg.get(k) not in (None, "", [])})
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], {**res, "product": _card(coord, res["id"])})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/update_product", vol.Required("product"): str,
                                  vol.Required("fields"): dict})
@callback
def ws_update_product(hass, connection, msg):
    coord = _coord(hass)
    pid = normalize_product_id(msg["product"])
    if coord is None or pid not in coord.store["products"]:
        connection.send_error(msg["id"], "not_found", f"Product {pid} not tracked")
        return
    try:
        coord.update_product(pid, msg["fields"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], _card(coord, pid, with_history=True))


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/remove_product", vol.Required("product"): str})
@callback
def ws_remove_product(hass, connection, msg):
    coord = _coord(hass)
    try:
        coord.remove_product(msg["product"])
    except ValueError as err:
        connection.send_error(msg["id"], "not_found", str(err))
        return
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/product/find", vol.Required("product"): str,
                                  vol.Optional("force", default=False): bool})
@websocket_api.async_response
async def ws_product_find(hass, connection, msg):
    """Look the product up at every shop of its category that has no link yet (once every 2 minutes)."""
    coord = _coord(hass)
    pid = normalize_product_id(msg["product"])
    try:
        coord._product(pid)
        live = coord._live_retailers(msg["force"])
        coord.manual_gate("find")
        coord.mark_sites(coord._missing(pid, live))
        res = await coord.discover_product(pid, live, force=msg["force"])
        coord.push_update()
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], {"result": res, "product": _card(coord, pid, with_history=True)})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/product/refresh", vol.Required("product"): str,
                                  vol.Optional("force", default=False): bool})
@websocket_api.async_response
async def ws_product_refresh(hass, connection, msg):
    """Fetch this product's prices at all its shops now (once every 2 minutes)."""
    coord = _coord(hass)
    pid = normalize_product_id(msg["product"])
    try:
        coord._product(pid)
        live = coord._live_retailers(msg["force"])
        coord.manual_gate("prices")
        coord.mark_sites([r for r in (coord.store["offers"].get(pid) or {}) if r in live])
        res = await coord.refresh_product(pid, live, source="panel", force=msg["force"])
        coord._snapshot()
        coord.push_update()
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], {"result": res, "product": _card(coord, pid, with_history=True)})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/collection"})
@callback
def ws_collection(hass, connection, msg):
    """The cost of everything you track over time."""
    coord = _coord(hass)
    if coord is None:
        _not_loaded(connection, msg)
        return
    connection.send_result(msg["id"], {"series": coord.series(), "snapshots": coord.store["snapshots"],
                                       "summary": (coord.data or coord.compute())["summary"]})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/import_preview",
                                  vol.Required("csv_text"): vol.All(str, vol.Length(max=1_500_000))})
@callback
def ws_import_preview(hass, connection, msg):
    """Dry run: parse a CSV of products without changing anything."""
    from .csv_import import analyze_csv, importable_rows

    try:
        analysis = analyze_csv(msg["csv_text"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    rows = importable_rows(analysis)
    connection.send_result(msg["id"], {"mapping": analysis["mapping"], "columns": analysis["columns"], "count": len(rows),
                                       "truncated": analysis["truncated"], "sample": rows[:8]})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/import_products",
                                  vol.Required("csv_text"): vol.All(str, vol.Length(max=1_500_000)),
                                  vol.Optional("discover", default=True): bool})
@callback
def ws_import_run(hass, connection, msg):
    """Add the products of a CSV one after the other in the background (a job)."""
    from .csv_import import analyze_csv, importable_rows

    coord = _coord(hass)
    try:
        rows = importable_rows(analyze_csv(msg["csv_text"]))
        if not rows:
            raise ValueError(T("No importable lines (every line has errors)."))
        job = coord.start_import(rows, msg["discover"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], {"job": job, "count": len(rows)})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/job"})
@callback
def ws_job(hass, connection, msg):
    """Progress of the running background job (polled by the panel)."""
    coord = _coord(hass)
    if coord is None:
        _not_loaded(connection, msg)
        return
    connection.send_result(msg["id"], coord.job_info())


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/settings/get"})
@callback
def ws_settings_get(hass, connection, msg):
    coord = _coord(hass)
    if coord is None:
        _not_loaded(connection, msg)
        return
    connection.send_result(msg["id"], coord.settings_get())


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/settings/set", vol.Required("fields"): dict})
@websocket_api.async_response
async def ws_settings_set(hass, connection, msg):
    """Validate and store settings; the entry reloads itself (update listener) to apply them."""
    coord = _coord(hass)
    if coord is None:
        _not_loaded(connection, msg)
        return
    try:
        options = coord.settings_validate(msg["fields"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    coord.log("info", "settings", "settings changed: " + ", ".join(sorted(msg["fields"])), source="panel")
    coord._save()
    hass.config_entries.async_update_entry(coord.entry, options=options)
    connection.send_result(msg["id"], {"saved": True})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/shop_settings/import", vol.Required("settings"): dict,
                                  vol.Required("accept"): bool})
@websocket_api.async_response
async def ws_shop_settings_import(hass, connection, msg):
    """Import a shop settings file. Only with the terms accepted (accept: true): then the shops in it are used."""
    from .shops import CONF_LEGAL, CONF_SHOP_PROFILE, LEGAL_VERSION, validate_custom_shop, validate_settings

    coord = _coord(hass)
    if coord is None:
        _not_loaded(connection, msg)
        return
    if msg["accept"] is not True:
        connection.send_error(msg["id"], "invalid_format", T("Accept the terms to import shop settings."))
        return
    try:
        profile = validate_settings(msg["settings"])
    except (ValueError, TypeError, AttributeError) as err:     # any malformed file is refused with a message
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    options = {**coord.entry.options, CONF_SHOP_PROFILE: profile,
               CONF_LEGAL: {"accepted": time.time(), "version": LEGAL_VERSION, "user": connection.user.id if connection.user else None}}
    if isinstance(extra := msg["settings"].get("custom_shops"), list):     # shops you added by hand (an exported file)
        try:
            mine = {s["id"]: s for s in coord.entry.options.get("custom_shops", []) or []}
            mine.update({(v := validate_custom_shop(s))["id"]: v for s in extra if isinstance(s, dict)})
        except ValueError as err:
            connection.send_error(msg["id"], "invalid_format", str(err))
            return
        options["custom_shops"] = [s for rid, s in mine.items() if rid not in {p["id"] for p in profile["shops"]}]
    coord.log("info", "settings", T("Shop settings imported: {n} shops; terms accepted", n=len(profile["shops"])), source="panel")
    coord._save()
    hass.config_entries.async_update_entry(coord.entry, options=options)
    connection.send_result(msg["id"], {"imported": True, "shops": len(profile["shops"])})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/shop_settings/export"})
@callback
def ws_shop_settings_export(hass, connection, msg):
    """The shop settings in force, as a file you can import again."""
    from .shops import export_settings

    coord = _coord(hass)
    if coord is None:
        _not_loaded(connection, msg)
        return
    connection.send_result(msg["id"], export_settings(dict(coord.entry.options)))


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/shop_settings/accept", vol.Required("accept"): bool})
@websocket_api.async_response
async def ws_shop_settings_accept(hass, connection, msg):
    """Accept the terms (again) for the shop settings already in place, e.g. after the terms changed."""
    from .shops import CONF_LEGAL, CONF_SHOP_PROFILE, LEGAL_VERSION

    coord = _coord(hass)
    if coord is None:
        _not_loaded(connection, msg)
        return
    if not coord.entry.options.get(CONF_SHOP_PROFILE):
        connection.send_error(msg["id"], "invalid_format", T("There are no shop settings yet: import a settings file."))
        return
    if msg["accept"] is not True:
        connection.send_error(msg["id"], "invalid_format", T("Accept the terms to import shop settings."))
        return
    coord.log("info", "settings", T("Terms for the shop settings accepted"), source="panel")
    coord._save()
    hass.config_entries.async_update_entry(coord.entry, options={
        **coord.entry.options, CONF_LEGAL: {"accepted": time.time(), "version": LEGAL_VERSION,
                                            "user": connection.user.id if connection.user else None}})
    connection.send_result(msg["id"], {"accepted": True})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/shop_settings/withdraw"})
@websocket_api.async_response
async def ws_shop_settings_withdraw(hass, connection, msg):
    """Remove the imported shop settings and the acceptance of the terms: from then on no shop is contacted.
    Your products, prices and links stay."""
    from .shops import CONF_LEGAL, CONF_SHOP_PROFILE, revoke

    coord = _coord(hass)
    if coord is None:
        _not_loaded(connection, msg)
        return
    options = {k: v for k, v in coord.entry.options.items() if k not in (CONF_SHOP_PROFILE, CONF_LEGAL)}
    revoke()                    # at once, not only after the reload
    coord.log("info", "settings", T("Shop settings removed and terms withdrawn: no shop is contacted any more"), source="panel")
    coord._save()
    hass.config_entries.async_update_entry(coord.entry, options=options)
    connection.send_result(msg["id"], {"withdrawn": True})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/shop_action",
                                  vol.Required("action"): vol.In(["resume", "resume_all", "discover_all", "refresh_all"]),
                                  vol.Optional("retailer"): str, vol.Optional("force", default=False): bool})
@callback
def ws_shop_action(hass, connection, msg):
    coord = _coord(hass)
    if coord is None:
        _not_loaded(connection, msg)
        return
    try:
        if msg["action"] in ("resume", "resume_all"):
            coord.resume_shop(msg.get("retailer") if msg["action"] == "resume" else None)
        elif msg["action"] == "discover_all":
            coord.start_discover(msg["force"])
        else:
            coord.start_full_refresh(msg["force"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], coord.job_info())


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/ignore_error", vol.Required("product"): str,
                                  vol.Required("retailer"): str, vol.Optional("ignore", default=True): bool})
@callback
def ws_ignore_error(hass, connection, msg):
    """Hide a known error in the errors tab until a different error occurs."""
    coord = _coord(hass)
    offer = (coord.store["offers"].get(normalize_product_id(msg["product"])) or {}).get(msg["retailer"]) if coord else None
    if offer is None:
        connection.send_error(msg["id"], "not_found", "Unknown link")
        return
    if msg["ignore"]:
        offer["ignored_error"] = offer.get("error")
    else:
        offer.pop("ignored_error", None)
    coord.push_update()
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/notify/get"})
@callback
def ws_notify_get(hass, connection, msg):
    coord = _coord(hass)
    if coord is None:
        _not_loaded(connection, msg)
        return
    connection.send_result(msg["id"], {"rules": coord.notifier.rules, "options": coord.notifier.ha_options(),
                                       "log": list(reversed(coord.store.get("notify_log", [])[-30:])),
                                       "queued": {k: len(v) for k, v in (coord.store.get("notify_queue") or {}).items() if v}})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/notify/set", vol.Required("rules"): list})
@callback
def ws_notify_set(hass, connection, msg):
    from .notifications import validate_rules

    coord = _coord(hass)
    try:
        rules = validate_rules(msg["rules"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    coord.store["notify_rules"] = rules
    coord.push_update()
    connection.send_result(msg["id"], {"rules": rules})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/notify/test", vol.Required("rule"): dict})
@websocket_api.async_response
async def ws_notify_test(hass, connection, msg):
    """Send a sample message to every target of a (possibly unsaved) rule."""
    from .notifications import validate_rules

    coord = _coord(hass)
    try:
        rule = validate_rules([msg["rule"]])[0]
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    sample = next((p for p in coord.store["products"].values() if p.get("image")), {})
    res = await coord.notifier.send(
        rule, "👁 " + tr("Test notification ARGUS"),
        tr("This is what a notification of '{rule}' looks like.", rule=rule["name"])
        + (" " + tr("Example: {product}", product=(sample.get("name") or "")) if sample else ""),
        url=home_of(next(iter(RETAILERS), "")) if rule.get("link") else None, image=sample.get("image") if rule.get("image") else None,
        force=True)
    connection.send_result(msg["id"], {"results": res})


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/log", vol.Optional("level", default=""): str, vol.Optional("kind", default=""): str,
    vol.Optional("retailer", default=""): str, vol.Optional("source", default=""): str,
    vol.Optional("product", default=""): str, vol.Optional("q", default=""): str, vol.Optional("status", default=""): str,
    vol.Optional("before"): vol.Any(None, vol.Coerce(float)), vol.Optional("limit", default=100): vol.All(int, vol.Range(1, 500)),
})
@callback
def ws_log(hass, connection, msg):
    from .models import query_activity

    coord = _coord(hass)
    if coord is None:
        _not_loaded(connection, msg)
        return
    connection.send_result(msg["id"], query_activity(coord.store, **{k: msg[k] for k in (
        "level", "kind", "retailer", "source", "product", "q", "status", "limit")}, before=msg.get("before")))


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/logs/export", vol.Required("parts"): [vol.In(["checks", "history", "total", "reports"])],
    vol.Optional("start"): vol.Coerce(float), vol.Optional("end"): vol.Coerce(float), vol.Optional("filters", default={}): dict,
})
@callback
def ws_logs_export(hass, connection, msg):
    """Logbook export as CSV: shop checks, price history per product and/or in total, with filters."""
    from . import log_export

    coord = _coord(hass)
    if coord is None:
        _not_loaded(connection, msg)
        return
    if not msg["parts"]:
        connection.send_error(msg["id"], "invalid", tr("Choose at least one part to export."))
        return
    prio = (msg.get("filters") or {}).get("priority")
    if prio not in (None, "", 0):
        try:
            if isinstance(prio, bool) or float(prio) != int(float(prio)) or not 1 <= int(float(prio)) <= 3:
                raise ValueError
        except (TypeError, ValueError):
            connection.send_error(msg["id"], "invalid", tr("Invalid priority filter."))
            return
    text, counts = log_export.build(coord.store, msg)
    connection.send_result(msg["id"], {"csv": text, "counts": counts})


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/report", vol.Required("product"): str,
    vol.Optional("problems", default=[]): [str], vol.Optional("shops", default=[]): [str],
    vol.Optional("comment", default=""): str, vol.Optional("save", default=True): bool,
})
@callback
def ws_report(hass, connection, msg):
    """'Problem with this product': everything known about it plus what is wrong; to the logbook and/or as CSV."""
    coord = _coord(hass)
    pid = normalize_product_id(msg["product"])
    if coord is None or pid not in coord.store["products"]:
        connection.send_error(msg["id"], "not_found", tr("Product {id} is not tracked.", id=pid))
        return
    rep, text = coord.report_problem(pid, msg["problems"], msg["shops"], msg["comment"], msg["save"])
    connection.send_result(msg["id"], {"id": rep["id"], "saved": msg["save"], "csv": text})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/shop/detail", vol.Required("retailer"): str})
@callback
def ws_shop_detail(hass, connection, msg):
    """Shops → click a shop: last requests, results, errors and a diagnosis (polled while open)."""
    coord = _coord(hass)
    if coord is None or msg["retailer"] not in RETAILERS:
        connection.send_error(msg["id"], "not_found", "Unknown shop")
        return
    connection.send_result(msg["id"], coord.shop_detail(msg["retailer"]))


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/offer/update", vol.Required("product"): str, vol.Required("retailer"): str,
    vol.Optional("url"): vol.Any(None, str), vol.Optional("manual_price"): vol.Any(None, str, int, float),
})
@callback
def ws_offer_update(hass, connection, msg):
    """Set or clear a manual link / manual price (empty = back to automatic)."""
    coord = _coord(hass)
    kwargs = {k: msg[k] for k in ("url", "manual_price") if k in msg}
    try:
        coord.update_offer(msg["product"], msg["retailer"], **kwargs)
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], _card(coord, normalize_product_id(msg["product"]), with_history=True))


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/offer/fetch", vol.Required("product"): str, vol.Required("retailer"): str,
    vol.Optional("url"): str,
})
@websocket_api.async_response
async def ws_offer_fetch(hass, connection, msg):
    """Fetch one shop for one product now (searching a link first if there is none). Works for paused shops."""
    coord = _coord(hass)
    try:
        result = await coord.fetch_shop(msg["product"], msg["retailer"], msg.get("url"))
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    connection.send_result(msg["id"], {"result": result, "product": _card(coord, normalize_product_id(msg["product"]), with_history=True)})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/offer/price_choice", vol.Required("product"): str,
                                  vol.Required("retailer"): str, vol.Required("accept"): bool})
@callback
def ws_offer_price_choice(hass, connection, msg):
    """Your own price or the newly fetched one: accept = the fetched price counts from now on."""
    coord = _coord(hass)
    try:
        price = coord.resolve_price_choice(msg["product"], msg["retailer"], msg["accept"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    connection.send_result(msg["id"], {"price": price})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/offer/reject", vol.Required("product"): str,
                                  vol.Required("retailer"): str})
@callback
def ws_offer_reject(hass, connection, msg):
    """'Never visit this link again': only this link is blocked, the shop is searched again for the product."""
    coord = _coord(hass)
    try:
        coord.reject_link(msg["product"], msg["retailer"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    coord._save()
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/offer/confirm", vol.Required("product"): str,
                                  vol.Required("retailer"): str})
@callback
def ws_offer_confirm(hass, connection, msg):
    """'This is the right product': the link counts, whatever the title says."""
    coord = _coord(hass)
    try:
        coord.confirm_offer(msg["product"], msg["retailer"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/offer/approve", vol.Required("product"): str,
                                  vol.Required("retailer"): str})
@callback
def ws_offer_approve(hass, connection, msg):
    """Approve a price that was held back as suspicious: it counts, and prices like it count from now on."""
    coord = _coord(hass)
    try:
        price = coord.approve_price(msg["product"], msg["retailer"])
    except ValueError as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    connection.send_result(msg["id"], {"price": price, "product": _card(coord, normalize_product_id(msg["product"]), with_history=True)})


_CLIENT_ERRORS: list[float] = []


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/client_error", vol.Required("message"): str,
                                  vol.Optional("stack", default=""): str, vol.Optional("ua", default=""): str,
                                  vol.Optional("view", default=""): str})
@callback
def ws_client_error(hass, connection, msg):
    """The panel failed to draw (e.g. in the iPhone app): log it with the stack, at most 20 per hour."""
    import logging

    now = time.time()
    _CLIENT_ERRORS[:] = [t for t in _CLIENT_ERRORS if now - t < 3600]
    if len(_CLIENT_ERRORS) < 20:
        _CLIENT_ERRORS.append(now)
        logging.getLogger(__package__).warning("Panel error in %s (view %s): %s\n%s", msg["ua"][:300], msg["view"][:60],
                                                msg["message"][:500], msg["stack"][:3000])
    connection.send_result(msg["id"], {"logged": len(_CLIENT_ERRORS) <= 20})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/filter/test", vol.Required("title"): str,
                                  vol.Optional("product_name", default=""): str,
                                  vol.Optional("block_words"): [str], vol.Optional("allow_words"): [str]})
@callback
def ws_filter_test(hass, connection, msg):
    """Product filter: is this title an accessory? With the given (unsaved) word lists, else the saved ones."""
    from . import parsers
    from .const import CONF_ALLOW_WORDS, CONF_BLOCK_WORDS

    coord = _coord(hass)
    saved = (coord.opt(coord.entry, CONF_BLOCK_WORDS, []), coord.opt(coord.entry, CONF_ALLOW_WORDS, []))
    parsers.set_custom_words(msg.get("block_words", saved[0]), msg.get("allow_words", saved[1]))
    try:
        word = parsers.accessory_word(msg["title"], msg["product_name"])
    finally:
        parsers.set_custom_words(*saved)
    connection.send_result(msg["id"], {"word": word or None})


class RelayView(HomeAssistantView):
    """Browser relay for the userscript (needs the user's long-lived token).

    GET  -> shop pages the browser should fetch (failed or stale on the server)
    POST -> {"results": [{"product", "retailer", "url", "price"?, "title"?, "error"?}]}"""

    url = f"/api/{DOMAIN}/relay"
    name = f"api:{DOMAIN}:relay"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        coord = _coord(request.app[KEY_HASS])
        if coord is None:
            return self.json_message("not loaded", 503)
        try:
            limit = max(1, min(100, int(request.query.get("limit", "40"))))
        except ValueError:
            limit = 40
        if request.query.get("mode") == "check":               # asked before every page: still allowed to fetch?
            from .shops import ready
            return self.json({"ready": ready() and coord.relay_enabled})
        if request.query.get("mode") == "continuous":          # the userscript's continuous check
            return self.json(coord.continuous_items(min(limit, 50)))
        return self.json(coord.relay_items(limit))

    async def post(self, request: web.Request) -> web.Response:
        coord = _coord(request.app[KEY_HASS])
        if coord is None:
            return self.json_message("not loaded", 503)
        try:
            body = await request.json()
            results = body.get("results") or []
            assert isinstance(results, list) and len(results) <= 100
            if isinstance(body.get("heartbeat"), dict):
                coord.relay_heartbeat(body["heartbeat"])
        except Exception:  # noqa: BLE001 - any malformed body
            return self.json_message("invalid body", 400)
        out: dict[str, Any] = {"ok": 0, "fail": 0, "rejected": [], "follow": []}
        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                res = coord.relay_result(item)
                if isinstance(res, dict):
                    out["follow"].append(res)
                else:
                    out[res] += 1
            except ValueError as err:           # not tracked / suspicious price
                out["rejected"].append(str(err))
        coord.push_update()
        return self.json(out)


class UserscriptView(HomeAssistantView):
    """Serves a Tampermonkey userscript generated for this HA instance and the configured shops.

    No auth: Tampermonkey fetches it outside HA. It contains no secrets (the token is entered
    by the user inside Tampermonkey)."""

    url = f"/api/{DOMAIN}/argus.user.js"
    name = f"api:{DOMAIN}:userscript"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        from . import VERSION
        from .shops import all_domains, readers_by_domain

        hass = request.app[KEY_HASS]
        template = await hass.async_add_executor_job(
            (Path(__file__).parent / "userscript.template.js").read_text, "utf-8")
        base = f"{request.scheme}://{request.host}"
        if request.headers.get("X-Forwarded-Proto") in ("http", "https"):   # behind a reverse proxy / Nabu Casa
            base = f"{request.headers['X-Forwarded-Proto']}://{request.host}"
        matches = "\n".join(f"// @match        https://www.{d}/*\n// @match        https://{d}/*"
                            for d in sorted(set(all_domains().values())))
        # Home Assistant itself (browser relay): this address and the panel on any address
        matches += f"\n// @include      {base}/*\n// @include      *://*/{PANEL_URL}*"
        body = (template.replace("{{VERSION}}", VERSION).replace("{{MATCHES}}", matches)
                .replace("{{READERS}}", json.dumps(readers_by_domain(), sort_keys=True))
                .replace("{{HA_URL}}", base).replace("{{SELF_URL}}", base + self.url))
        # {{t:English}} -> translated text, {{tj:English}} -> translated JS string literal
        body = re.sub(r"\{\{tj:(.+?)\}\}", lambda m: json.dumps(tr(m.group(1))), body)
        body = re.sub(r"\{\{t:(.+?)\}\}", lambda m: tr(m.group(1)), body)
        return web.Response(text=body, content_type="text/javascript", charset="utf-8",
                            headers={"Cache-Control": "no-cache"})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/dev/tool",
                                  vol.Required("action"): vol.In(["stats", "reset", "parse", "fetch", "queue", "outliers",
                                                                  "debug", "dump", "health", "schedule", "jobs"]),
                                  vol.Optional("what", default=""): str, vol.Optional("retailer"): str,
                                  vol.Optional("html", default=""): vol.All(str, vol.Length(max=5_000_000)),
                                  vol.Optional("url", default=""): str,
                                  vol.Optional("apply", default=False): bool, vol.Optional("on", default=False): bool})
@websocket_api.async_response
async def ws_dev_tool(hass, connection, msg):
    """Developer tools (see devtools.py)."""
    from . import devtools

    coord = _coord(hass)
    a = msg["action"]
    try:
        if a == "stats":
            out: Any = devtools.stats(coord)
        elif a == "reset":
            if msg["what"] not in devtools.RESETS:
                raise ValueError(msg["what"])
            out = {"removed": devtools.reset(coord, msg["what"])}
            coord.push_update()
        elif a == "parse":
            out = await hass.async_add_executor_job(devtools.parse, msg.get("retailer"), msg["html"], msg["url"])
        elif a == "fetch":
            if not msg["url"].startswith(("https://", "http://")):
                raise ValueError("URL")
            out = await devtools.fetch(coord, msg["url"])
        elif a == "queue":
            out = coord.continuous_items(100)
        elif a == "outliers":
            out = {"points": devtools.outliers(coord, msg["apply"])}
            if msg["apply"]:
                coord.push_update()
        elif a == "debug":
            out = {"debug": devtools.set_debug(msg["on"])}
        elif a == "health":
            out = {"findings": devtools.health(coord, msg["apply"])}
            if msg["apply"]:
                coord.push_update()
        elif a == "schedule":
            out = devtools.schedule(coord)
        elif a == "jobs":
            out = {"jobs": devtools.jobs(coord)}
        else:
            out = json.loads(json.dumps(devtools.dump(coord), default=str))
    except ValueError as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    connection.send_result(msg["id"], out)


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/lab",
                                  vol.Required("action"): vol.In(["links", "run", "log"]),
                                  vol.Optional("retailer"): vol.Any(None, str), vol.Optional("product"): vol.Any(None, str),
                                  vol.Optional("url", default=""): vol.All(str, vol.Length(max=2000)),
                                  vol.Optional("html", default=""): vol.All(str, vol.Length(max=5_000_000)),
                                  vol.Optional("result"): dict})
@websocket_api.async_response
async def ws_lab(hass, connection, msg):
    """Parser lab (Manage → Parser lab): addresses for a shop + product, a test run with analysis, or a result to the log."""
    from . import lab

    coord = _coord(hass)
    pid = normalize_product_id(msg["product"]) if msg.get("product") else None
    try:
        if msg["action"] == "links":
            if not (msg.get("retailer") and pid):
                raise ValueError(T("Pick a shop and a product."))
            out: Any = lab.links(coord, msg["retailer"], pid)
        elif msg["action"] == "run":
            out = await lab.run(coord, msg.get("retailer"), pid, msg["url"].strip(), msg["html"])
        else:
            lab.to_log(coord, msg.get("result") or {})
            coord.push_update()
            out = {"ok": True}
    except ValueError as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    connection.send_result(msg["id"], out)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/ticker", vol.Optional("lang", default="nl"): str,
                                  vol.Optional("since"): vol.Any(None, int, float)})
@websocket_api.async_response
async def ws_ticker(hass, connection, msg):
    """The ticker at the bottom of the panel: latest prices, deals and news."""
    coord = _coord(hass)
    if coord is None:
        connection.send_result(msg["id"], {"items": [], "news": []})
        return
    connection.send_result(msg["id"], await coord.ticker_data(msg["lang"], msg.get("since")))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/error_stats"})
@callback
def ws_error_stats(hass, connection, msg):
    """Logbook → Open errors: solved and new errors per day, and the latest of each."""
    coord = _coord(hass)
    if coord is None:
        connection.send_result(msg["id"], {"open": 0, "days": {}, "solved": [], "new": []})
        return
    connection.send_result(msg["id"], coord.error_stats())
