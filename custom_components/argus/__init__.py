"""ARGUS: Altijd Rondkijken, Goedkoopste Uitzoeken, Snel melden — prices of one product at many web shops."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

import voluptuous as vol
from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_change, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CATEGORIES, CONF_DIGEST_TIME, CONF_KNOWN_SHOPS, DEFAULT_DIGEST_TIME, DOMAIN, EVENT_DIGEST, GENERIC_SHOPS, PANEL_ELEMENT,
    PANEL_URL, RETAILERS, STATIC_URL,
)
from .coordinator import ArgusCoordinator
from .csv_import import analyze_csv, importable_rows
from .i18n import T
from .models import normalize_product_id
from .shops import apply_shop_options, profile_ids
from .websocket_api import async_register_websocket

_LOGGER = logging.getLogger(__name__)
VERSION = json.loads((Path(__file__).parent / "manifest.json").read_text())["version"]
PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PRODUCT = vol.Required("product")
SERVICE_SCHEMAS = {
    "add_product": vol.Schema({
        vol.Optional("url"): cv.string, vol.Optional("name"): cv.string, vol.Optional("ean"): cv.string,
        vol.Optional("brand"): cv.string, vol.Optional("model"): cv.string,
        vol.Optional("category"): vol.In(list(CATEGORIES)), vol.Optional("reference_price"): vol.Coerce(float),
        vol.Optional("target_price"): vol.Coerce(float), vol.Optional("priority"): vol.All(vol.Coerce(int), vol.Range(1, 3)),
        vol.Optional("notes"): cv.string,
    }),
    "remove_product": vol.Schema({PRODUCT: cv.string}),
    "find_shops": vol.Schema({vol.Optional("product"): cv.string, vol.Optional("force", default=False): cv.boolean}),
    "refresh": vol.Schema({vol.Optional("product"): cv.string, vol.Optional("force", default=False): cv.boolean}),
    "verify_links": vol.Schema({}),
    "confirm_offer": vol.Schema({PRODUCT: cv.string, vol.Required("retailer"): cv.string}),
    "remove_offer": vol.Schema({PRODUCT: cv.string, vol.Required("retailer"): cv.string,
                                vol.Optional("block", default=True): cv.boolean}),
    "set_offer": vol.Schema({PRODUCT: cv.string, vol.Required("retailer"): cv.string, vol.Required("url"): cv.string}),
    "fix_offer": vol.Schema({PRODUCT: cv.string, vol.Required("retailer"): cv.string, vol.Optional("url"): cv.string,
                             vol.Optional("price"): vol.Coerce(float)}),
    "cancel_job": vol.Schema({}),
    "export_products": vol.Schema({}),
    "export_data": vol.Schema({}),
    "import_data": vol.Schema({
        vol.Optional("data"): dict, vol.Optional("file_path"): cv.string, vol.Optional("merge", default=False): cv.boolean,
    }),
    "import_products": vol.Schema({
        vol.Optional("csv_text"): cv.string, vol.Optional("file_path"): cv.string, vol.Optional("discover", default=True): cv.boolean,
    }),
    "report_price": vol.Schema({
        vol.Required("price"): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=100000)),
        vol.Optional("url"): cv.string, vol.Optional("product"): cv.string,
        vol.Optional("retailer"): cv.string, vol.Optional("title"): vol.All(cv.string, vol.Length(max=400)),
        vol.Optional("via"): vol.In(["userscript", "relay"]), vol.Optional("gtins"): [cv.string],
    }),
    "send_digest": vol.Schema({}),
}


def _coordinator(hass: HomeAssistant) -> ArgusCoordinator:
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise ServiceValidationError("ARGUS is not set up")
    return next(iter(entries.values()))


def digest(coord: ArgusCoordinator) -> dict:
    """What is interesting today."""
    data = coord.data or coord.compute()
    rows = []
    for pid, st in data["statuses"].items():
        if st["is_all_time_low"] or st["high_discount"] or st["target_hit"]:
            p = coord.store["products"][pid]
            price, retailer, url = coord.notifier.shop_offer(pid, st)
            rows.append({"product": pid, "name": p.get("name"), "category": p.get("category"),
                         "price": price, "retailer": retailer,
                         "discount": st["discount_ref"] if st["discount_ref"] is not None else st["discount_avg"],
                         "all_time_low": st["is_all_time_low"], "target_hit": st["target_hit"], "url": url})
    rows.sort(key=lambda r: (not r["target_hit"], not r["all_time_low"], -(r["discount"] or 0)))
    return {"deals": rows, "basket": data["summary"], "threshold": coord.threshold}


async def _send_digest(hass: HomeAssistant, coord: ArgusCoordinator) -> None:
    """Daily digest: event for automations + every notification rule with the 'digest' trigger."""
    d = digest(coord)
    hass.bus.async_fire(EVENT_DIGEST, d)
    await coord.notifier.on_digest(d)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the coordinator, platforms, panel, services, and scheduled refreshes."""
    apply_shop_options(dict(entry.options))
    # Shops new in the imported shop settings are switched on once; afterwards the user's choice wins.
    builtin = profile_ids()
    known = set(entry.options.get(CONF_KNOWN_SHOPS) or entry.options.get("retailers") or [])
    if new_shops := [r for r in builtin if r not in known]:
        enabled = list(entry.options.get("retailers", [r for r in builtin if r in known]))
        enabled += [r for r in new_shops if r not in enabled]
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, "retailers": enabled, CONF_KNOWN_SHOPS: sorted(known | set(builtin))})
    coord = ArgusCoordinator(hass, entry)
    await coord.async_load()
    _LOGGER.info("ARGUS %s starting (request transport: %s)", VERSION, coord.fetcher.transport)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coord
    coord.async_set_updated_data(coord.compute())
    # No shop round at start-up: hammering shops on every HA restart gets us blocked.

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload))

    @callback
    def _push_answer(event: Event) -> None:
        """A button of an ARGUS push message (Home Assistant app): Yes / No for the finds to confirm."""
        if coord.answer_token(str(event.data.get("action") or "")):
            hass.async_create_task(coord.async_request_refresh())

    entry.async_on_unload(hass.bus.async_listen("mobile_app_notification_action", _push_answer))

    if not hass.data.get(f"{DOMAIN}_frontend"):
        hass.data[f"{DOMAIN}_frontend"] = True
        await _register_frontend(hass)
        async_register_websocket(hass)
        _register_services(hass)

    t = dt_util.parse_time(coord.opt(entry, CONF_DIGEST_TIME, DEFAULT_DIGEST_TIME)) or dt_util.parse_time(DEFAULT_DIGEST_TIME)

    async def _daily(_now: datetime) -> None:
        await _send_digest(hass, coord)

    entry.async_on_unload(async_track_time_change(hass, _daily, t.hour, t.minute, t.second))
    entry.async_on_unload(async_track_time_interval(hass, coord.notifier.flush_queues, timedelta(minutes=5)))

    @callback
    def _scheduled_refresh(_now: datetime) -> None:
        if coord.job_running:
            _LOGGER.info("Scheduled price round skipped: %s is still running", coord.job["label"])
            return
        coord._job_source = "schedule"
        coord.start_refresh()

    if coord.refresh_mode == "spread":
        coord.start_spread()
    if coord.auto_refresh:
        for hour, minute in coord.refresh_times:
            entry.async_on_unload(async_track_time_change(hass, _scheduled_refresh, hour, minute, 0))
    return True


async def _register_frontend(hass: HomeAssistant) -> None:
    panel_dir = Path(__file__).parent / "panel"
    await hass.http.async_register_static_paths([StaticPathConfig(STATIC_URL, str(panel_dir), False)])
    # the file's own fingerprint in the URL: after an update the browser always loads the new panel
    import hashlib

    digest_ = await hass.async_add_executor_job(
        lambda: hashlib.sha1((panel_dir / "argus-panel.js").read_bytes()).hexdigest()[:10])
    version = f"{VERSION}-{digest_}"
    await panel_custom.async_register_panel(
        hass, webcomponent_name=PANEL_ELEMENT, frontend_url_path=PANEL_URL,
        sidebar_title="ARGUS", sidebar_icon="mdi:eye-circle",
        module_url=f"{STATIC_URL}/argus-panel.js?v={version}", embed_iframe=False, require_admin=False,
    )


@callback
def _register_services(hass: HomeAssistant) -> None:
    """Register the integration's services (add, refresh, find, ...) once per Home Assistant instance."""
    def _job(fn, *args) -> dict:
        try:
            return {"started": True, **fn(*args)}
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    async def add_product(call: ServiceCall) -> dict:
        d = call.data
        try:
            res = await _coordinator(hass).add_product(
                d.get("url"), name=d.get("name"), ean=d.get("ean"), brand=d.get("brand"), mpn=d.get("model"),
                category=d.get("category"), ref_price=d.get("reference_price"), target_price=d.get("target_price"),
                priority=d.get("priority"), notes=d.get("notes"))
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        return {k: res[k] for k in ("id", "existing", "name", "category", "price")}

    async def remove_product(call: ServiceCall) -> None:
        try:
            _coordinator(hass).remove_product(call.data["product"])
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    async def find_shops(call: ServiceCall) -> dict:
        c = _coordinator(hass)
        if pid := call.data.get("product"):
            pid = normalize_product_id(pid)
            try:
                c._product(pid)
                live = c._live_retailers(call.data["force"])
                c.manual_gate("find")
                c.mark_sites(c._missing(pid, live))
                res = await c.discover_product(pid, live)
            except ValueError as err:
                raise ServiceValidationError(str(err)) from err
            c.push_update()
            return {"started": False, **res}
        return _job(c.start_discover, call.data["force"])

    async def refresh(call: ServiceCall) -> dict:
        """Fetch one product's shop prices now, or start a full round; `force` also wakes paused shops."""
        c = _coordinator(hass)
        if pid := call.data.get("product"):
            pid = normalize_product_id(pid)
            try:
                c._product(pid)
                live = c._live_retailers(call.data["force"])
                c.manual_gate("prices")
                c.mark_sites([r for r in (c.store["offers"].get(pid) or {}) if r in live])
                res = await c.refresh_product(pid, live, force=call.data["force"])
            except ValueError as err:
                raise ServiceValidationError(str(err)) from err
            c.push_update()
            return {"started": False, **res}
        return _job(c.start_full_refresh, call.data["force"])

    async def verify_links(call: ServiceCall) -> dict:
        c = _coordinator(hass)
        res = c.verify_links()
        c.push_update()
        return res

    async def confirm_offer(call: ServiceCall) -> None:
        try:
            _coordinator(hass).confirm_offer(call.data["product"], call.data["retailer"])
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    async def remove_offer(call: ServiceCall) -> None:
        try:
            _coordinator(hass).remove_offer(call.data["product"], call.data["retailer"], call.data["block"])
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    async def set_offer(call: ServiceCall) -> None:
        try:
            _coordinator(hass).update_offer(call.data["product"], call.data["retailer"], url=call.data["url"])
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    async def fix_offer(call: ServiceCall) -> None:
        try:
            _coordinator(hass).fix_offer(call.data["product"], call.data["retailer"], call.data.get("url"), call.data.get("price"))
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    async def cancel_job(call: ServiceCall) -> dict:
        return {"cancelled": _coordinator(hass).cancel_job()}

    async def export_products(call: ServiceCall) -> dict:
        return {"csv": _coordinator(hass).export_csv()}

    async def export_data(call: ServiceCall) -> dict:
        return _coordinator(hass).export_backup()

    async def _read(path: str, encoding: str) -> str:
        if not hass.config.is_allowed_path(path):
            raise ServiceValidationError(f"{path} is not in allowlist_external_dirs")
        return await hass.async_add_executor_job(Path(path).read_text, encoding)

    async def import_data(call: ServiceCall) -> dict:
        data = call.data.get("data")
        if data is None and (path := call.data.get("file_path")):
            data = json.loads(await _read(path, "utf-8"))
        if data is None:
            raise ServiceValidationError("Provide data or file_path")
        try:
            return _coordinator(hass).import_backup(data, merge=call.data["merge"])
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    async def import_products(call: ServiceCall) -> dict:
        c = _coordinator(hass)
        text = call.data.get("csv_text")
        if not text and (path := call.data.get("file_path")):
            text = await _read(path, "utf-8-sig")
        if not text:
            raise ServiceValidationError("Provide csv_text or file_path")
        try:
            rows = importable_rows(analyze_csv(text))
            if not rows:
                raise ValueError(T("No importable lines (every line has errors)."))
            job = c.start_import(rows, call.data["discover"])
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        return {"started": True, "count": len(rows), **job}

    async def report_price(call: ServiceCall) -> None:
        try:
            _coordinator(hass).report_price(call.data["price"], url=call.data.get("url"), product=call.data.get("product"),
                                            retailer=call.data.get("retailer"), title=call.data.get("title"), via=call.data.get("via"),
                                            gtins=call.data.get("gtins"))
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    async def send_digest(call: ServiceCall) -> None:
        await _send_digest(hass, _coordinator(hass))

    for name, handler in (("add_product", add_product), ("find_shops", find_shops), ("refresh", refresh),
                          ("verify_links", verify_links), ("cancel_job", cancel_job), ("export_products", export_products),
                          ("export_data", export_data), ("import_data", import_data), ("import_products", import_products)):
        hass.services.async_register(DOMAIN, name, handler, SERVICE_SCHEMAS[name], supports_response=SupportsResponse.OPTIONAL)
    for name, handler in (("remove_product", remove_product), ("set_offer", set_offer), ("confirm_offer", confirm_offer),
                          ("remove_offer", remove_offer), ("fix_offer", fix_offer), ("report_price", report_price),
                          ("send_digest", send_digest)):
        hass.services.async_register(DOMAIN, name, handler, SERVICE_SCHEMAS[name])


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        coord: ArgusCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coord.async_shutdown()
    return ok
