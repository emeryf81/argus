"""Data coordinator: owns the store, polls retailers, finds the same product at other shops, computes statuses."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .client import DOMAIN_GAP, SEARCH_GAP, Fetcher
from .const import (
    CATEGORIES, CONF_ALLOW_WORDS, CONF_AUTO_REFRESH, CONF_BLOCK_WORDS, CONF_CUSTOM_SHOPS, CONF_DEAL_ATL, CONF_DEAL_MIN_SCORE,
    CONF_DEAL_TARGET, CONF_DEV_FIXED_TIMES, CONF_DEV_FREE_CYCLE, CONF_DEV_FULL_REFRESH, CONF_DEV_UNLIMITED, CONF_DIGEST_TIME,
    CONF_DISCOUNT_THRESHOLD, CONF_IMPERSONATE, CONF_LANGUAGE, CONF_MIN_HISTORY_DAYS, CONF_NO_AUTOPAUSE, CONF_NOTIFY,
    CONF_REFRESH_MODE, CONF_REFRESH_TIMES, CONF_RELAY, CONF_RELAY_HOURS, CONF_RETAILERS, CONF_SHOP_SEARCH, CONF_SPREAD_HOURS,
    CONF_TICKER, CONF_WATCH_CYCLE, CYCLE_CHOICES, DEFAULT_CATEGORY, DEFAULT_DEAL_MIN_SCORE, DEFAULT_DIGEST_TIME,
    DEFAULT_DISCOUNT_THRESHOLD, DEFAULT_MIN_HISTORY_DAYS, DEFAULT_REFRESH_MODE, DEFAULT_REFRESH_TIMES, DEFAULT_RELAY_HOURS,
    DEFAULT_SEARCH, DEFAULT_SPREAD_HOURS, DOMAIN, EVENT_HIGH_DISCOUNT, EVENT_JOB_DONE, EVENT_NEW_LOW, EVENT_TARGET_HIT,
    FULL_REFRESH_GAP, GENERIC_SHOPS, MANUAL_GAP, PRODUCT_LIMIT, RETAILERS, STORAGE_KEY, STORAGE_VERSION, TICKER_DEFAULT,
    TICKER_GOOD_SCORE, TICKER_RELOAD, WATCH_CYCLE_CHOICES,
)
from .i18n import DEFAULT_LANGUAGE, LANGUAGES, LocalizedError, T, resolve, set_language
from .models import (
    add_activity, add_event, basket_summary, clean_history, compute_status, gtin_key, is_suspicious_price, new_store,
    normalize_gtin, normalize_product_id, offer_price, product_id, product_rows, PRODUCT_COLUMNS, query_activity, record_price,
    rows_to_csv, today_iso, validate_backup,
)
from .notifications import Notifier, default_rules
from .parsers import (BUILTIN_WORDS, Parsed, accessory_word, clean_title, is_search_url, link_check, normalize_url, parse_page,
                      product_identity, retailer_from_url, search_candidates, set_custom_words, slug_title, url_key, wrong_product,
                      TITLE_OK)
from .shops import (CONF_LEGAL, CONF_SHOP_PROFILE, LEGAL_VERSION, SEARCH, domain_of, home_of, profile_ids, reader_of, ready,
                    search_address, shops_for_category, valid_search)

_LOGGER = logging.getLogger(__name__)
_UNSET: Any = object()


class ArgusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """data = {"statuses": {product: status}, "summary": {...}}"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize storage, fetchers, notification handling, and background-job state."""
        # No polling interval: shop rounds run as background jobs (buttons or the schedule).
        super().__init__(hass, _LOGGER, name=DOMAIN, config_entry=entry, update_interval=None)
        self.entry = entry
        self._store = Store[dict[str, Any]](hass, STORAGE_VERSION, STORAGE_KEY)
        self.store: dict[str, Any] = new_store()
        self.fetcher = Fetcher(hass, bool(self.opt(entry, CONF_IMPERSONATE, True)))
        self.fetcher.no_autopause = set(self.opt(entry, CONF_NO_AUTOPAUSE, []) or [])
        self._alerted: set[tuple[str, str]] = set()
        self.job: dict[str, Any] | None = None
        self.last_job: dict[str, Any] | None = None
        self._job_task: asyncio.Task | None = None
        self._cancel = False
        self._job_source = "panel"
        self.notifier = Notifier(self)
        self._first_checks: list[str] = []                         # products just added, waiting for their first search
        self._first_busy = False
        self._first_current: str | None = None
        self._rediscover: list[tuple[str, str]] = []               # (product, shop) to search again after a blocked link
        self._spread_active = False
        self._spread_unsub: Callable[[], None] | None = None
        self._spread_next: float | None = None
        self._spread_last: dict[str, Any] | None = None
        self._last_full_refresh = 0.0

        def _paused(rid: str, hours: float) -> None:
            self.log("error", "shop", T("{shop} blocked us: paused for {hours} h", shop=RETAILERS.get(rid, (rid,))[0], hours=hours), retailer=rid)
            self.hass.async_create_task(self.notifier.on_shop_paused(rid, hours))
        self.fetcher.on_pause = _paused
        self.fetcher.abort = lambda: self._cancel and self.job_running     # 'Stop' also ends a wait for a site
        self._manual: dict[str, float] = {}

    # ---------------------------------------------------------------- options
    @staticmethod
    def opt(entry: ConfigEntry, key: str, default: Any) -> Any:
        return entry.options.get(key, entry.data.get(key, default))

    @property
    def threshold(self) -> float:
        return float(self.opt(self.entry, CONF_DISCOUNT_THRESHOLD, DEFAULT_DISCOUNT_THRESHOLD))

    @property
    def retailers(self) -> list[str]:
        return [r for r in self.opt(self.entry, CONF_RETAILERS, profile_ids()) if r in RETAILERS]

    @property
    def language(self) -> str:
        return resolve(self.opt(self.entry, CONF_LANGUAGE, DEFAULT_LANGUAGE), self.hass.config.language)

    # ---------------------------------------------------------------- storage
    async def async_load(self) -> None:
        """Load stored data, initialize the fetcher, and restore cooldowns."""
        set_language(self.language)
        set_custom_words(self.opt(self.entry, CONF_BLOCK_WORDS, []), self.opt(self.entry, CONF_ALLOW_WORDS, []))
        await self.fetcher.async_setup()
        if (data := await self._store.async_load()):
            self.store = {**new_store(), **data}
        if "notify_rules" not in self.store:     # first run: sensible defaults
            self.store["notify_rules"] = default_rules(self.threshold, self.opt(self.entry, CONF_NOTIFY, "") or "")
        cd = self.store.get("cooldowns") or {}
        now = time.time()
        self.fetcher.blocked_until.update({r: t for r, t in (cd.get("until") or {}).items() if t > now})
        self.fetcher.blocks.update(cd.get("blocks") or {})
        self.verify_links()      # flag wrong links right away

    def open_error_keys(self) -> dict[str, str]:
        """{"product|shop": kind} for every open error, the same list as Logbook → Open errors: a product without any
        shop link, a shop page that failed, a suspicious link or price. Ignored errors don't count."""
        out: dict[str, str] = {}
        for pid in self.store["products"]:
            offers = self.store["offers"].get(pid) or {}
            if not offers:
                out[f"{pid}|"] = "nolinks"
            for rid, o in offers.items():
                if o.get("ignored") or not (o.get("error") or o.get("link_status") == "suspect"):
                    continue
                out[f"{pid}|{rid}"] = "suspect" if o.get("link_status") == "suspect" else "error"
        return out

    def _track_errors(self, now: float | None = None) -> None:
        """Keep count of the errors that are solved and the ones that come in, per day (Logbook → Open errors).
        The first time, today's open errors are only the starting point (not counted as new)."""
        now = now or time.time()
        tr = self.store.setdefault("err_track", {})
        cur = self.open_error_keys()
        day = dt_util.as_local(dt_util.utc_from_timestamp(now)).date().isoformat()
        if "open" not in tr:
            tr.update(open={k: now for k in cur}, days={}, solved=[], new=[], since=now)
            return
        was: dict[str, float] = tr["open"]
        for k in [k for k in was if k not in cur and k.partition("|")[0] not in self.store["products"]]:
            was.pop(k)                                     # the product was removed: not solved, just gone
        gone = [k for k in was if k not in cur]
        came = [k for k in cur if k not in was]
        if not gone and not came:
            return
        d = tr["days"].setdefault(day, {"new": 0, "solved": 0})
        d["solved"] += len(gone)
        d["new"] += len(came)
        for k in gone:
            tr["solved"].append([now, k, was.pop(k)])
        for k in came:
            was[k] = now
            tr["new"].append([now, k, cur[k]])
        del tr["solved"][:-500], tr["new"][:-500]
        for old in sorted(tr["days"])[:-400]:              # a little more than a year of days
            del tr["days"][old]

    def error_stats(self) -> dict[str, Any]:
        """Solved and new errors per day (for charts per day, week and month) and the latest of each, with
        the product, the shop and how long the error was open."""
        self._track_errors()
        tr = self.store.get("err_track") or {}

        def row(e: list[Any], solved: bool) -> dict[str, Any]:
            pid, _, rid = e[1].partition("|")
            p = self.store["products"].get(pid) or {}
            return {"ts": e[0], "product": pid, "name": p.get("name") or "", "retailer": rid or None,
                    "shop": RETAILERS.get(rid, (rid,))[0] if rid else None,
                    **({"open_for": max(0, e[0] - e[2])} if solved else {"kind": e[2]})}
        return {"open": len(tr.get("open") or {}), "since": tr.get("since"), "days": tr.get("days") or {},
                "solved": [row(e, True) for e in reversed(tr.get("solved") or [])][:200],
                "new": [row(e, False) for e in reversed(tr.get("new") or [])][:200]}

    def _save(self) -> None:
        # pauses survive restarts/reloads, otherwise a reload would hammer a shop that just blocked us
        try:
            self._track_errors()
        except Exception:  # noqa: BLE001 - statistics must never stop a save
            _LOGGER.exception("error statistics failed")
        self.store["cooldowns"] = {"until": dict(self.fetcher.blocked_until), "blocks": dict(self.fetcher.blocks)}
        self._store.async_delay_save(lambda: self.store, 5)

    async def async_shutdown(self) -> None:
        self.stop_spread()
        self._cancel = True
        if self._job_task and not self._job_task.done():
            self._job_task.cancel()
        await self._store.async_save(self.store)
        await self.fetcher.async_close()
        await super().async_shutdown()

    # -------------------------------------------------------------- computing
    def compute(self) -> dict[str, Any]:
        min_days = int(self.opt(self.entry, CONF_MIN_HISTORY_DAYS, DEFAULT_MIN_HISTORY_DAYS))
        statuses = {
            pid: compute_status(p, self.store["offers"].get(pid, {}), threshold=self.threshold, min_history_days=min_days)
            for pid, p in self.store["products"].items()
        }
        return {"statuses": statuses, "summary": basket_summary(self.store, statuses)}

    async def _async_update_data(self) -> dict[str, Any]:
        return self.compute()

    def push_update(self) -> None:
        """Recompute without hitting the network (after edits/imports)."""
        self._save()
        self.async_set_updated_data(self.compute())

    def _product(self, pid: str) -> dict[str, Any]:
        pid = normalize_product_id(pid)
        try:
            return self.store["products"][pid]
        except KeyError as err:
            raise LocalizedError("Product {id} is not tracked.", id=pid) from err

    def _statuses(self) -> dict[str, dict[str, Any]]:
        return (self.data or self.compute())["statuses"]

    # ------------------------------------------------------------------ schedule
    @property
    def refresh_times(self) -> list[tuple[int, int]]:
        raw = str(self.opt(self.entry, CONF_REFRESH_TIMES, DEFAULT_REFRESH_TIMES))
        out = []
        for h, m in re.findall(r"(\d{1,2})[:.hu](\d{2})", raw):
            if int(h) < 24 and int(m) < 60:
                out.append((int(h), int(m)))
        return sorted(set(out))

    def dev(self, key: str) -> bool:
        return bool(self.opt(self.entry, key, False))

    @property
    def refresh_mode(self) -> str:
        mode = self.opt(self.entry, CONF_REFRESH_MODE, None)
        if mode is None:
            mode = DEFAULT_REFRESH_MODE if self.opt(self.entry, CONF_AUTO_REFRESH, True) else "off"
        if mode == "times" and not self.dev(CONF_DEV_FIXED_TIMES):
            mode = "spread"            # full rounds at fixed times put too much load on the shops
        return mode if mode in ("spread", "times", "off") else DEFAULT_REFRESH_MODE

    @property
    def watch_cycle_minutes(self) -> int:
        try:
            v = int(self.opt(self.entry, CONF_WATCH_CYCLE, 0) or 0)
        except (TypeError, ValueError):
            return 0
        return v if v in WATCH_CYCLE_CHOICES else 0

    @property
    def product_limit(self) -> int | None:
        return None if self.dev(CONF_DEV_UNLIMITED) else PRODUCT_LIMIT

    @property
    def deal_rules(self) -> dict[str, Any]:
        """What counts as a deal (the panel's Deals view and badges)."""
        try:
            score = max(0, min(100, int(self.opt(self.entry, CONF_DEAL_MIN_SCORE, DEFAULT_DEAL_MIN_SCORE))))
        except (TypeError, ValueError):
            score = DEFAULT_DEAL_MIN_SCORE
        return {"threshold": self.threshold, "min_score": score, "atl": bool(self.opt(self.entry, CONF_DEAL_ATL, True)),
                "target": bool(self.opt(self.entry, CONF_DEAL_TARGET, True))}

    def is_deal(self, st: dict[str, Any], rules: dict[str, Any] | None = None) -> bool:
        rules = rules or self.deal_rules
        if st.get("best_price") is None:
            return False
        disc = st.get("discount_ref") if st.get("discount_ref") is not None else st.get("discount_avg")
        return bool((rules["atl"] and st.get("is_all_time_low")) or (rules["target"] and st.get("target_hit"))
                    or st.get("deal_score", 0) >= rules["min_score"] or (disc or 0) >= rules["threshold"])

    def deal_of_the_day(self, include: Any = None, shops: list[str] | None = None) -> tuple[str, dict[str, Any]] | None:
        """The best deal right now (as the panel shows it under Today): a product that counts as a deal,
        highest deal score first. include(pid): which products may count (default: all)."""
        rules, best = self.deal_rules, None
        for pid, st in self._statuses().items():
            if pid not in self.store["products"] or (include and not include(pid)):
                continue
            if st.get("best_price") is None or (shops and st.get("best_retailer") not in shops):
                continue
            key = (st.get("deal_score", 0), st.get("discount_ref") or st.get("discount_avg") or 0)
            if self.is_deal(st, rules) and (best is None or key > best[0]):
                best = (key, pid, st)
        return (best[1], best[2]) if best else None

    @property
    def spread_hours(self) -> float:
        try:
            h = max(1.0, min(168.0, float(self.opt(self.entry, CONF_SPREAD_HOURS, DEFAULT_SPREAD_HOURS))))
        except (TypeError, ValueError):
            return DEFAULT_SPREAD_HOURS
        if self.dev(CONF_DEV_FREE_CYCLE):
            return h
        return float(min(CYCLE_CHOICES, key=lambda c: (abs(c - h), -c)))   # nearest allowed choice

    def is_priority(self, pid: str) -> bool:
        return int(self.store["products"].get(pid, {}).get("priority") or 0) >= 2

    # ------------------------------------------------------------ spread checks
    def _spread_candidates(self) -> list[str]:
        return list(self.store["products"])

    def _watch_hours(self) -> float | None:
        """Priority cycle in hours (never slower than the normal cycle), or None when off."""
        wc = self.watch_cycle_minutes
        return min(wc / 60, self.spread_hours) if wc else None

    def check_rates(self) -> dict[str, float]:
        """Checks per hour: the normal cycle, the priority cycle, and together."""
        cands = set(self._spread_candidates())
        wh = self._watch_hours()
        fast_set = {p for p in cands if self.is_priority(p)} if wh else set()
        main = len(cands - fast_set) / self.spread_hours
        fast = len(fast_set) / wh if wh else 0.0
        return {"main": main, "watch": fast, "total": main + fast, "products": len(cands - fast_set), "priority": len(fast_set)}

    def spread_interval(self) -> float:
        """Seconds between two product checks, so every product is checked once per cycle (priority products
        once per priority cycle)."""
        rate = self.check_rates()["total"]
        return max(20.0, 3600 / rate) if rate else 3600.0

    def start_spread(self, delay: float = 60) -> None:
        from homeassistant.helpers.event import async_call_later

        self.stop_spread()
        self._spread_active = True
        self._spread_next = time.time() + delay
        self._spread_unsub = async_call_later(self.hass, delay, self._spread_tick)

    def stop_spread(self) -> None:
        self._spread_active = False
        if self._spread_unsub:
            self._spread_unsub()
        self._spread_unsub = None

    def next_spread_product(self) -> str | None:
        cands = self._spread_candidates()
        if not cands:
            return None
        checked = lambda n: self.store["products"][n].get("checked", 0)   # noqa: E731
        now = time.time()
        if (wh := self._watch_hours()):            # priority products that are due go first
            due = [n for n in cands if self.is_priority(n) and now - checked(n) >= wh * 3600]
            if due:
                return min(due, key=checked)
            cands = [n for n in cands if not self.is_priority(n)] or cands
        pid = min(cands, key=checked)
        if now - checked(pid) < self.spread_hours * 3600 * 0.5:
            return None        # everything was checked recently (e.g. after a full manual round)
        return pid

    async def _spread_tick(self, _now: Any = None) -> None:
        from homeassistant.helpers.event import async_call_later

        self._spread_unsub = None
        try:
            if ready() and not self.job_running and (pid := self.next_spread_product()):
                live = self._live_retailers(False)
                if self._discover_due(pid, live):
                    await self.discover_product(pid, live)
                await self.refresh_product(pid, live, source="schedule")
                self._spread_last = {"product": pid, "ts": time.time()}
                self.push_update()
        except Exception:  # noqa: BLE001 - the loop must keep running
            _LOGGER.exception("Spread check failed")
        finally:
            if self._spread_active:
                interval = self.spread_interval()
                self._spread_next = time.time() + interval
                self._spread_unsub = async_call_later(self.hass, interval, self._spread_tick)

    def next_refresh(self) -> float | None:
        if not (self.refresh_mode == "times" and self.refresh_times):
            return None
        now = dt_util.now()
        cands = []
        for h, m in self.refresh_times:
            t = now.replace(hour=h, minute=m, second=0, microsecond=0)
            cands.append(t if t > now else t + timedelta(days=1))
        return min(cands).timestamp()

    @property
    def auto_refresh(self) -> bool:
        return self.refresh_mode == "times" and bool(self.refresh_times)

    def schedule_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {"mode": self.refresh_mode, "auto": self.refresh_mode != "off",
                                "times": [f"{h:02d}:{m:02d}" for h, m in self.refresh_times], "next": self.next_refresh()}
        if self.refresh_mode == "spread":
            interval = self.spread_interval()
            day = time.time() - 86400
            rates = self.check_rates()
            info.update(watch_cycle_min=self.watch_cycle_minutes,
                        rates={k: round(v, 1) if isinstance(v, float) else v for k, v in rates.items()})
            info.update(cycle_hours=self.spread_hours, interval=round(interval), per_hour=round(3600 / interval, 1),
                        next=self._spread_next, next_product=self.next_spread_product(), last=self._spread_last,
                        checked_24h=sum(1 for p in self.store["products"].values() if p.get("checked", 0) > day),
                        total=len(self._spread_candidates()))
        return info

    # ------------------------------------------------------------ manual actions (load protection)
    def _site(self, rid: str) -> str:
        return (domain_of(rid) or rid).removeprefix("www.")

    def manual_left(self, key: str) -> float:
        return max(0.0, self._manual.get(key, 0) + MANUAL_GAP - time.time())

    def manual_gate(self, key: str) -> None:
        """Manual fetches and searches: at most once every 2 minutes (per product action, per shop site)."""
        if not ready():
            raise LocalizedError("First import the shop settings and accept their terms (Manage → Shops).")
        if (left := self.manual_left(key)) > 0:
            s = int(left) + 1
            if key == "prices":
                raise LocalizedError("To protect the traffic to and the load on the shops, fetching prices is possible once every 2 minutes. Try again in {s} s.", s=s)
            if key == "find":
                raise LocalizedError("To protect the traffic to and the load on the shops, searching the shops is possible once every 2 minutes. Try again in {s} s.", s=s)
            raise LocalizedError("To protect the traffic to and the load on this shop, it can be fetched once every 2 minutes. Try again in {s} s.", s=s)
        self._manual[key] = time.time()

    def manual_status(self) -> dict[str, Any]:
        """When each manual button is available again (epoch seconds), for the panel to grey them out."""
        until = lambda k: (self._manual[k] + MANUAL_GAP) if self.manual_left(k) > 0 else None  # noqa: E731
        return {"now": time.time(), "gap": MANUAL_GAP, "prices": until("prices"), "find": until("find"),
                "shops": {rid: u for rid in RETAILERS if (u := until("site:" + self._site(rid)))}}

    def mark_sites(self, rids: list[str]) -> None:
        now = time.time()
        for rid in rids:
            self._manual["site:" + self._site(rid)] = now

    def _price_choice(self, pid: str, rid: str, offer: dict[str, Any], price: float | None, source: str) -> None:
        """Your own price counts, but the shop now says something else: ask once (logbook, product) whether the
        new price should count from now on or your price stays. A price you declined is not asked again."""
        manual = float((offer.get("manual_price") or {}).get("price") or 0)
        if price is None or not manual or abs(price - manual) < 0.01:
            offer.pop("price_choice", None)
            return
        if offer.get("declined_price") is not None and abs(offer["declined_price"] - price) < 0.01:
            return
        if (offer.get("price_choice") or {}).get("price") == price:
            return
        offer["price_choice"] = {"price": price, "manual": manual, "ts": time.time()}
        self.log("warning", "price", T("the shop now says €{new}; your own price €{manual} still counts: choose which one", new=f"{price:.2f}", manual=f"{manual:.2f}"),
                 product=pid, retailer=rid, url=offer.get("url"), price=price, old_price=manual, source=source, choice=True)

    def resolve_price_choice(self, pid: str, retailer: str, accept: bool) -> float:
        """Logbook choice for a shop with your own price: accept the fetched price (your price goes away, the
        shop's price counts from now on) or keep your price (this fetched price is not asked again)."""
        pid = normalize_product_id(pid)
        offer = (self.store["offers"].get(pid) or {}).get(retailer)
        if not offer or not offer.get("price_choice"):
            raise LocalizedError("There is no new price to choose for this shop.")
        choice = offer.pop("price_choice")
        before = self.compute()["statuses"].get(pid, {})
        if accept:
            offer.pop("manual_price", None)
            offer.pop("declined_price", None)
            record_price(offer, float(choice["price"]))
            offer["last_ok"] = time.time()
            self.log("ok", "price", T("new price €{price} approved; your own price is gone", price=f"{choice['price']:.2f}"),
                     product=pid, retailer=retailer, url=offer.get("url"), price=choice["price"], source="panel")
        else:
            offer["declined_price"] = float(choice["price"])
            self.log("info", "price", T("your own price €{price} kept", price=f"{choice['manual']:.2f}"),
                     product=pid, retailer=retailer, url=offer.get("url"), price=choice["manual"], source="panel")
        self._fire_events(pid, before, self.compute()["statuses"].get(pid, {}))
        self.push_update()
        return float(choice["price"] if accept else choice["manual"])

    def approve_price(self, pid: str, rid: str) -> float:
        """A price held back as suspicious is right after all: store it, and accept prices like it (±25 %)
        for this link from now on."""
        pid = normalize_product_id(pid)
        offer = (self.store["offers"].get(pid) or {}).get(rid)
        if not offer or not offer.get("suspect"):
            raise LocalizedError("There is no suspicious price to approve for this shop.")
        price = float(offer.pop("suspect")["price"])
        before = self.compute()["statuses"].get(pid, {})
        offer["approved"] = price
        record_price(offer, price)
        offer["last_ok"], offer["error"] = offer.get("last_checked") or time.time(), None
        offer.pop("ignored_error", None)
        self.log("ok", "price", T("suspicious price €{price} approved by hand", price=f"{price:.2f}"),
                 product=pid, retailer=rid, url=offer.get("url"), price=price, source="panel")
        self._fire_events(pid, before, self.compute()["statuses"].get(pid, {}))
        self.push_update()
        return price

    def report_problem(self, pid: str, problems: list[str], shops: list[str], comment: str,
                       save: bool = True) -> tuple[dict[str, Any], str]:
        """'Problem with this product': a snapshot of links, prices, errors and the recent log, with the user's remark."""
        from . import report

        rep = report.build(self.store, pid, self.compute()["statuses"].get(pid, {}), problems, shops, comment)
        if save:
            report.save(self.store, rep)
            what = ", ".join(rep["problems"]) or "?"
            # the remark itself stays in the report (export is for administrators); the shared logbook only says that there is one
            self.log("warning", "report", T("problem reported ({what})", what=what) + (" · " + T("with a remark") if rep["comment"] else ""),
                     product=pid, report=rep["id"], retailer=rep["shops"][0] if len(rep["shops"]) == 1 else None,
                     source="panel")
            self.push_update()
        return rep, report.to_csv([rep])

    def log(self, level: str, kind: str, message: str, **fields: Any) -> None:
        """Everything the integration does ends up here (Manage → Logbook)."""
        fields.setdefault("source", "server")
        add_activity(self.store, level, kind, message, **fields)

    # ---------------------------------------------------------------------- jobs
    def job_info(self) -> dict[str, Any]:
        return {"job": dict(self.job) if self.job else None, "last": self.last_job,
                "paused": {RETAILERS[r][0]: h for r, h in self.fetcher.paused().items() if r in RETAILERS},
                "schedule": self.schedule_info(), "first_checks": self.first_checks}

    @property
    def first_checks(self) -> list[str]:
        """Products just added that are still waiting for (or getting) their first search and prices."""
        return ([self._first_current] if self._first_current else []) + list(self._first_checks)

    @property
    def job_running(self) -> bool:
        return self._job_task is not None and not self._job_task.done()

    def start_job(self, kind: str, label: str, items: list[str],
                  worker: Callable[[str], Awaitable[dict[str, int] | None]], note: str | None = None) -> dict[str, Any]:
        if self.job_running:
            raise LocalizedError("A job is already running: {label} ({done}/{total}).", label=self.job["label"],
                                 done=self.job["done"], total=self.job["total"])
        self._cancel = False
        self.job = {"kind": kind, "label": label, "total": len(items), "done": 0, "current": None,
                    "found": 0, "updated": 0, "errors": 0, "skipped": 0, "started": time.time(),
                    "running": True, "cancelled": False, "note": note}
        self.job["shops"] = {}
        self.log("info", "job", T("{label} started for {n} products", label=label, n=len(items)) + (f" ({note})" if note else ""),
                 source=self._job_source)
        self._job_source = "panel"
        self._job_task = self.entry.async_create_background_task(
            self.hass, self._run_job(items, worker), f"{DOMAIN}_{kind}")
        return dict(self.job)

    def cancel_job(self) -> bool:
        if not self.job_running:
            return False
        self._cancel = True
        return True

    async def _run_job(self, items: list[str], worker: Callable[[str], Awaitable[dict[str, int] | None]]) -> None:
        job = self.job
        assert job is not None
        try:
            for item in items:
                if self._cancel:
                    job["cancelled"] = True
                    break
                job["current"] = f"{self.store['products'].get(item, {}).get('name') or item}".strip()
                try:
                    res = await worker(item)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - one bad product must not stop the round
                    _LOGGER.exception("%s failed for %s", job["kind"], item)
                    job["errors"] += 1
                else:
                    for k, v in (res or {}).items():
                        job[k] = job.get(k, 0) + v
                job["done"] += 1
                if job["done"] % 10 == 0:
                    self.push_update()
        finally:
            job["running"] = False
            job["current"] = None
            job["finished"] = time.time()
            self.last_job = dict(job)
            hist = self.store.setdefault("job_history", [])          # developer tools: the last jobs and how long they took
            hist.append({k: job.get(k) for k in ("kind", "label", "total", "done", "updated", "found", "errors", "skipped",
                                                 "started", "finished", "cancelled")})
            del hist[: max(0, len(hist) - 30)]
            parts = [T("{n} updated", n=job["updated"]) if job.get("updated") else "",
                     T("{n} links found", n=job["found"]) if job.get("found") else "",
                     T("{n} skipped (paused)", n=job["skipped"]) if job.get("skipped") else "",
                     T("{n} errors", n=job["errors"]) if job.get("errors") else ""]
            done_txt = (T("{label} stopped: {done}/{total} products", label=job["label"], done=job["done"], total=job["total"])
                        if job["cancelled"] else
                        T("{label} finished: {done}/{total} products", label=job["label"], done=job["done"], total=job["total"]))
            done_txt += "".join(", " + p for p in parts if p)
            self.log("warning" if job.get("errors") else "ok", "job", done_txt)
            for rid, st in (job.get("shops") or {}).items():
                why = sorted((st.get("why") or {}).items(), key=lambda x: -x[1])[:3]
                self.log("ok" if not st["err"] else "warning" if st["ok"] else "error", "fetch",
                         T("{shop}: {ok} succeeded, {failed} failed", shop=RETAILERS.get(rid, (rid,))[0], ok=st["ok"], failed=st["err"])
                         + "".join(f" · {n}× {r}" for r, n in why), retailer=rid)
            if job["kind"] == "refresh":
                self._snapshot()
            if job["kind"] in ("refresh", "update"):
                self.verify_links()
            self.push_update()
            self.hass.async_create_task(self.notifier.on_job_done(dict(job)))
            self.hass.bus.async_fire(EVENT_JOB_DONE, {k: job[k] for k in ("kind", "total", "done", "found", "updated",
                                                                         "errors", "skipped", "cancelled")})

    # ----------------------------------------------------------------- discovery
    def _live_retailers(self, force: bool) -> list[str]:
        if force:
            self.fetcher.reset_cooldowns()
        if not ready():          # no shop settings imported or terms not accepted: no shop is contacted
            return []
        return [r for r in self.retailers if self.fetcher.cooldown_left(r) <= 0]

    def shops_for(self, pid: str, live: list[str] | None = None) -> list[str]:
        """The shops this product is looked up at: the ones that sell its category."""
        p = self.store["products"].get(pid, {})
        return shops_for_category(p.get("category"), live if live is not None else self.retailers)

    def _missing(self, pid: str, live: list[str]) -> list[str]:
        offers = self.store["offers"].get(pid, {})
        return [r for r in self.shops_for(pid, live) if r not in offers or not offers[r].get("url")]

    def _discover_due(self, pid: str, live: list[str]) -> bool:
        """A product with shops that have no link yet is searched again about once a week (new shops, new stock)."""
        p = self.store["products"][pid]
        return bool(self._missing(pid, live)) and time.time() - p.get("discovered", 0) > 7 * 86400

    async def _discover(self, rid: str, pid: str, force: bool = False, url: str | None = None) -> tuple[str | None, str | None]:
        skip = set(self.store.get("rejected", {}).get(pid, []))
        p = {**self.store["products"][pid], "id": pid}
        found, how = await self.fetcher.discover(rid, p, force=force, skip=skip, url=url)
        self._note_js(rid)
        return found, how

    def _note_js(self, rid: str) -> None:
        """Remember shops whose search page is built with JavaScript (the userscript can render it in a tab)."""
        if "JavaScript" in (self.fetcher.discover_error.get(rid) or ""):
            first = rid not in self.store.setdefault("shop_js", {})
            self.store["shop_js"][rid] = time.time()
            if first:                            # earlier browser searches read an empty page: allow them again
                searched = self.store.setdefault("relay_searched", {})
                for k in [k for k in searched if k.endswith("|" + rid)]:
                    del searched[k]

    def start_discover(self, force: bool = False) -> dict[str, Any]:
        live = self._live_retailers(force)
        pids = [n for n in self.store["products"] if self._missing(n, live)]
        paused = [RETAILERS[r][0] for r in self.retailers if r not in live]
        note = T("spread out: each shop is searched at most once every 2 minutes")
        if paused:
            note += "; " + T("paused and skipped: {shops}", shops=", ".join(paused))
        return self.start_job("discover", T("Finding the product at other shops"), pids, lambda n: self.discover_product(n, live), note)

    async def discover_product(self, pid: str, retailers: list[str] | None = None, force: bool = False) -> dict[str, int]:
        """Look the product up at every shop of its category that has no link yet: by barcode, then by name;
        a link is only kept after the product page itself proved it is the same product."""
        live = retailers if retailers is not None else self._live_retailers(False)
        todo = self._missing(pid, live)
        self.store["products"][pid]["discovered"] = time.time()
        results = list(await asyncio.gather(*(self._discover(r, pid, force) for r in todo)))
        rejected = set(self.store.setdefault("rejected", {}).get(pid, []))
        found = 0
        for rid, (url, how) in zip(todo, results):
            if url and url_key(rid, url) not in rejected:
                self._set_discovered(self.store["offers"].setdefault(pid, {}), rid, url, how)
                found += 1
                self.log("ok", "discover", {"ean": T("link found by barcode"), "agg": T("link found via a price-comparison site"),
                                            "web": T("link found via a web search")}.get(how or "", T("link found by name")),
                         product=pid, retailer=rid, url=url)
            elif url:
                self.log("info", "discover", T("found a link you rejected earlier; not linked again"), product=pid, retailer=rid, url=url)
            elif self.job and self.job.get("running"):
                st = self.job["shops"].setdefault(rid, {"ok": 0, "err": 0})
                st["err"] += 1                  # summarised per shop at the end of the job, with the reasons
                why = st.setdefault("why", {})
                reason = self.fetcher.discover_error.get(rid) or T("no matching product found")
                why[reason] = why.get(reason, 0) + 1
            else:
                self.log("info", "discover", self.fetcher.discover_error.get(rid) or T("no matching product found"), product=pid, retailer=rid)
            if url and self.job and self.job.get("running"):
                self.job["shops"].setdefault(rid, {"ok": 0, "err": 0})["ok"] += 1
        return {"found": found}

    @staticmethod
    def _set_discovered(offers: dict[str, Any], retailer: str, url: str, how: str | None = None) -> None:
        """A link found by searching (not chosen by hand): the same page keeps its history, a manual
        price always stays; a hand-set confirmation or an earlier link verdict no longer applies."""
        old = offers.get(retailer) or {}
        if old.get("url") and url_key(retailer, old["url"]) == url_key(retailer, url):
            o = old
            o["url"] = url
        else:
            o = offers[retailer] = {"url": url, "history": [], "found": time.time(),
                                    **({"manual_price": old["manual_price"]} if old.get("manual_price") else {})}
        for key in ("manual_url", "link_status", "link_reason", "error"):
            o.pop(key, None)
        o["found_via"] = how or "search"
        o["link_status"], o["link_reason"] = "ok", T("the product page proved it is the same product")

    # ------------------------------------------------------------------- refresh
    def start_full_refresh(self, force: bool = False) -> dict[str, Any]:
        """'Refresh all prices' by hand or by service: off unless enabled in developer mode (a full round
        puts a lot of load on the shops), and then at most once a minute."""
        if not self.dev(CONF_DEV_FULL_REFRESH):
            raise LocalizedError("Switched off: fetching every product at once puts too much load on the shops. Prices are checked product by product in the background; use ↻ in a product to fetch it now.")
        wait = FULL_REFRESH_GAP - (time.time() - self._last_full_refresh)
        if wait > 0:
            raise LocalizedError("A full price round can start at most once a minute: try again in {s} s.", s=int(wait) + 1)
        job = self.start_refresh(force)
        self._last_full_refresh = time.time()
        return job

    def start_refresh(self, force: bool = False) -> dict[str, Any]:
        """Start a background job that fetches the shop prices of every product with a live link;
        `force` also includes paused shops."""
        live = self._live_retailers(force)
        pids = [n for n, offers in self.store["offers"].items()
                if n in self.store["products"] and any(r in live and o.get("url") for r, o in offers.items())]
        paused = [RETAILERS[r][0] for r in self.retailers if r not in live]
        note = T("paused and skipped: {shops}", shops=", ".join(paused)) if paused else None
        return self.start_job("refresh", T("Refreshing shop prices"), pids, lambda n: self.refresh_product(n, live), note)

    def start_update(self, pids: list[str], force: bool = False) -> dict[str, Any]:
        """Search and price a chosen list of products (e.g. after an import) in the background."""
        live = self._live_retailers(force)

        async def work(pid: str) -> dict[str, int]:
            counts = await self.discover_product(pid, live)
            counts.update(await self.refresh_product(pid, live, source="update"))
            return counts
        return self.start_job("update", T("Finding the product at other shops and fetching prices"),
                              [p for p in pids if p in self.store["products"]], work)

    def start_import(self, rows: list[dict[str, Any]], discover: bool = True) -> dict[str, Any]:
        """Add the products of an import (CSV) one after the other in the background: each address is fetched
        politely, and with `discover` every new product is then looked up at the other shops."""
        if not ready():
            raise LocalizedError("First import the shop settings and accept their terms (Manage → Shops).")
        if self.job_running:
            raise LocalizedError("A job is already running: {label} ({done}/{total}).", label=self.job["label"],
                                 done=self.job["done"], total=self.job["total"])

        async def work(key: str) -> dict[str, int]:
            row = rows[int(key)]
            try:
                res = await self.add_product(row.get("url"), **{k: v for k, v in row.items() if k != "url" and v is not None},
                                             discover=discover)
            except ValueError as err:
                self.log("warning", "import", str(err), url=row.get("url"), source="import")
                return {"errors": 1}
            return {"updated": 0 if res["existing"] else 1}
        return self.start_job("import", T("Importing products"), [str(i) for i in range(len(rows))], work)

    async def _fetch(self, rid: str, offer: dict[str, Any], force: bool = False) -> tuple[Parsed | None, str | None]:
        return await self.fetcher.fetch_offer(rid, offer["url"], force=force)

    async def refresh_product(self, pid: str, retailers: list[str] | None = None, source: str = "server",
                              force: bool = False) -> dict[str, int]:
        """Fetch all shop pages of one product, shops in parallel (each shop stays sequential and polite).

        Writes one 'check' entry to the logbook with a green/red result per shop, plus separate
        'price' entries for changes. A manual price always wins over the automatic one."""
        live = retailers if retailers is not None else self._live_retailers(False)
        p = self.store["products"][pid]
        before = self.compute()["statuses"].get(pid, {})
        offers = [(rid, o) for rid, o in self.store["offers"].get(pid, {}).items()
                  if rid in live and o.get("url") and o.get("link_status") != "rejected"]
        results = await asyncio.gather(*(self._fetch(rid, o, force) for rid, o in offers))
        counts = {"updated": 0, "errors": 0, "skipped": 0}
        shop_results: dict[str, dict[str, Any]] = {}
        # every shop's price in this round (and the last known ones): the yardstick for a suspicious price
        round_prices = {rid: pr.price for (rid, _o), (pr, _e) in zip(offers, results) if pr and pr.price}
        known = {rid: o.get("last_price") for rid, o in self.store["offers"].get(pid, {}).items()
                 if o.get("available") and o.get("last_price")}
        for (rid, offer), (parsed, error) in zip(offers, results):
            if error and error.startswith("paused"):
                counts["skipped"] += 1        # keep the last known price, just skip
                shop_results[rid] = {"ok": None, "error": error}
                continue
            if parsed:
                if parsed.title:
                    offer["title"] = parsed.title[:300]
                offer["gtins"] = list(parsed.gtins)
                offer["mpn"] = parsed.mpn
                if parsed.list_price:
                    offer["list_price"] = parsed.list_price
            status, reason = link_check(offer, p)
            offer["link_status"], offer["link_reason"] = status, reason
            if status == "suspect" and self._auto_reject(pid, rid, offer, source):
                shop_results[rid] = {"ok": None, "error": offer.get("link_reason")}
                continue
            price = parsed.price if parsed else None
            others = [pr for r, pr in {**known, **round_prices}.items() if r != rid]
            if price is not None and (warn := is_suspicious_price(price, p, offer, others)):
                offer["suspect"] = {"price": price, "reason": warn, "ts": time.time()}   # kept: you can approve it
                price, error = None, warn
            elif price is not None:
                offer.pop("suspect", None)
            manual = offer.get("manual_price")
            if manual:                        # manual price has priority: only remember what the shop said
                offer["auto_price"], offer["last_checked"], offer["error"] = price, time.time(), error
                self._price_choice(pid, rid, offer, price, source)
            else:
                old_price = offer.get("last_price") if offer.get("available") else None
                record_price(offer, price, error=error)
                if price is not None and (old_price is None or abs(old_price - price) >= 0.01):
                    self.log("ok", "price", T("€{old} → €{new}", old=f"{old_price:.2f}", new=f"{price:.2f}") if old_price
                             else T("first price €{price}", price=f"{price:.2f}"),
                             product=pid, retailer=rid, url=offer.get("url"), price=price, old_price=old_price, source=source)
            shop_results[rid] = {"ok": not error, "price": price, "error": error, "manual": bool(manual)}
            # the page says it is sold out / no longer sold: a warning with the reason, not an error to solve
            why = parsed.reason if parsed and parsed.unavailable and price is None and not error else None
            if why:
                shop_results[rid]["unavailable"] = why
                if offer.get("unavailable") != why:
                    self.log("warning", "price", T("no price: sold out") if why == "sold_out" else T("no price: no longer sold (out of the range)"),
                             product=pid, retailer=rid, url=offer.get("url"), source=source, unavailable=why)
                offer["unavailable"] = why
            elif price is not None:
                offer.pop("unavailable", None)
            elif error and offer.get("unavailable") != "discontinued":
                offer.pop("unavailable", None)             # out of the range stays: a failed fetch confirms nothing
            if self.job and self.job.get("running"):
                st = self.job["shops"].setdefault(rid, {"ok": 0, "err": 0})
                st["err" if error else "ok"] += 1
            if status == "suspect" and offer.get("_logged_suspect") != reason:
                offer["_logged_suspect"] = reason
                self.log("warning", "link", T("suspicious link: {reason}", reason=reason), product=pid, retailer=rid,
                         url=offer.get("url"), source=source)
            if price is not None:
                offer["last_ok"] = time.time()
                counts["updated"] += 1
            if error:
                counts["errors"] += 1
                _LOGGER.debug("%s/%s: %s", pid, rid, error)
            if parsed and status in ("ok", "confirmed"):
                if parsed.image and not p.get("image"):
                    p["image"] = parsed.image
                if parsed.brand and not p.get("brand"):
                    p["brand"] = parsed.brand
        p["checked"] = time.time()
        self._learn_ean(pid)
        if shop_results:
            ok = sum(1 for r in shop_results.values() if r["ok"])
            failed = sum(1 for r in shop_results.values() if r["ok"] is False)
            level = "ok" if not failed else "error" if not ok else "warning"
            self.log(level, "check", T("{ok} of {n} shops OK", ok=ok, n=len(shop_results)), product=pid,
                     results=shop_results, source=source)
        after = self.compute()["statuses"].get(pid, {})
        self._fire_events(pid, before, after)
        return counts

    def _learn_ean(self, pid: str) -> None:
        """A product without a barcode learns it from its pages: the address you added it with, or a barcode two
        shops agree on. A wrong barcode would poison every later match, so one stray page never decides."""
        p = self.store["products"][pid]
        if gtin_key(p.get("ean")):
            return
        votes: dict[str, set[str]] = {}
        for rid, o in (self.store["offers"].get(pid) or {}).items():
            if o.get("link_status") not in ("ok", "confirmed"):
                continue
            for g in o.get("gtins") or []:
                if (k := gtin_key(g)) and (norm := normalize_gtin(g)):
                    votes.setdefault(norm, set()).add(rid)
        source = p.get("source_shop")
        for norm, shops in votes.items():
            if len(shops) >= 2 or (source in shops and len(shops) == 1 and len(votes) == 1 and p.get("source_url")):
                p["ean"], p["ean_source"] = norm, "shop"
                self.log("info", "meta", T("barcode {ean} learned from the shop pages", ean=norm), product=pid, source="server")
                return

    async def fetch_shop(self, pid: str, retailer: str, url: str | None = None) -> dict[str, Any]:
        """Panel button per shop: fetch this shop for this product now, also when the shop is paused.
        Without a link the shop is searched first.
        url: what you pasted — a product page (becomes the link) or a search page of the shop (searched)."""
        pid = normalize_product_id(pid)
        self._product(pid)
        if retailer not in RETAILERS:
            raise LocalizedError("Unknown shop {shop}.", shop=retailer)
        self.manual_gate("site:" + self._site(retailer))
        offers = self.store["offers"].setdefault(pid, {})
        found = False
        search_page = None
        if url and (url := url.strip()):
            if is_search_url(url):
                search_page = url if url.startswith("http") else None
            else:
                # a product page is the link; the same page keeps its history, a manual price stays
                self.update_offer(pid, retailer, url=url)
        if search_page or not (offers.get(retailer) or {}).get("url"):
            found_url, how = await self._discover(retailer, pid, force=True, url=search_page)
            rejected = set(self.store.setdefault("rejected", {}).get(pid, []))
            if not found_url or url_key(retailer, found_url) in rejected:
                reason = T("found a link you rejected earlier; not linked again") if found_url else \
                    (self.fetcher.discover_error.get(retailer) or T("no matching product found"))
                self.log("warning", "discover", reason, product=pid, retailer=retailer, url=found_url, source="panel")
                self.push_update()
                return {"ok": False, "found": False, "error": reason}
            self._set_discovered(offers, retailer, found_url, how)
            found = True
            self.log("ok", "discover", T("link found"), product=pid, retailer=retailer, url=found_url, source="panel")
        await self.refresh_product(pid, [retailer], source="panel", force=True)
        o = offers[retailer]
        self._snapshot()
        self.push_update()
        return {"ok": not o.get("error"), "found": found, "price": offer_price(o), "error": o.get("error")}

    async def refresh_all(self) -> None:
        """Synchronous full round (used by tests); the UI uses start_refresh()."""
        live = self._live_retailers(False)
        for pid in list(self.store["offers"]):
            if pid in self.store["products"]:
                await self.refresh_product(pid, live)
        self._snapshot()
        self._save()

    async def discover_offers(self, product: str | None = None) -> int:
        """Inline discovery for one product (or all, used by tests)."""
        pids = [normalize_product_id(product)] if product else list(self.store["products"])
        found = 0
        for pid in pids:
            found += (await self.discover_product(pid))["found"]
        self.push_update()
        return found

    # ------------------------------------------------------------ browser relay (userscript)
    @property
    def relay_enabled(self) -> bool:
        return bool(self.opt(self.entry, CONF_RELAY, True))

    def relay_items(self, limit: int = 40) -> dict[str, Any]:
        """Shop pages the user's own browser should fetch (userscript relay): links that failed on the
        server or weren't fetched in the last 20 h, oldest first."""
        items: list[tuple[float, dict[str, Any]]] = []
        if self.relay_enabled and ready():          # no shop settings or terms: the browser fetches nothing either
            day = time.time() - 20 * 3600
            for pid, offers in self.store["offers"].items():
                if pid not in self.store["products"]:
                    continue
                for rid, o in offers.items():
                    if (rid not in self.retailers or not o.get("url") or o.get("manual_price") or o.get("link_status") == "rejected"):
                        continue
                    last = o.get("last_ok") or 0
                    if o.get("error") or last < day:
                        items.append((last, {"product": pid, "retailer": rid, "shop": RETAILERS[rid][0], "url": o["url"]}))
        items.sort(key=lambda x: x[0])
        return {"enabled": self.relay_enabled, "interval_hours": int(self.opt(self.entry, CONF_RELAY_HOURS, DEFAULT_RELAY_HOURS)),
                "items": [i for _, i in items[:limit]], "total": len(items)}

    RELAY_SEARCH_DAYS = 7          # a product/shop searched by the browser without result: not again for a week
    RELAY_FAIL_HOURS = 6           # a link the server can't fetch: the browser checks it at most every 6 h

    def continuous_items(self, limit: int = 20) -> dict[str, Any]:
        """Work for the userscript's continuous check, most useful first:
        1. links that never had a price; 2. open errors: the browser fetches the page, a price solves the error;
        3. shops that have no link yet: products without any price, shops the server could not search (their search
           page is built with JavaScript, or they are paused), and products the server already searched without luck;
        4. links the server can't fetch (blocked, paused) and not checked by the browser recently."""
        now = time.time()
        searched = self.store.setdefault("relay_searched", {})
        items: list[tuple[int, float, dict[str, Any]]] = []
        if not self.relay_enabled or not ready():   # no shop settings or terms: the browser fetches nothing either
            return {"enabled": False, "items": [], "total": 0, "counts": {}}
        for pid, p in self.store["products"].items():
            offers = self.store["offers"].get(pid, {})
            priced = any(o.get("available") and o.get("last_price") or o.get("manual_price") for o in offers.values())
            for rid in self.shops_for(pid):
                o = offers.get(rid)
                base = {"product": pid, "retailer": rid, "shop": RETAILERS[rid][0]}
                if o and o.get("url"):
                    if o.get("manual_price") or o.get("link_status") == "rejected":
                        continue
                    last_try = o.get("relay_ts", 0)
                    if not o.get("history") and not o.get("last_ok"):
                        if now - last_try > 3600:                       # never a price: first, once an hour at most
                            items.append((0, last_try, {**base, "url": o["url"], "reason": "no_price"}))
                    elif o.get("error") and o.get("ignored_error") != o["error"] and not o.get("suspect"):
                        if now - last_try > 3600:                       # an open error: try it in the browser, once an hour
                            items.append((1, last_try, {**base, "url": o["url"], "reason": "open_error"}))
                    elif (o.get("error") or self.fetcher.cooldown_left(rid) > 0) and now - max(last_try, o.get("last_ok") or 0) > self.RELAY_FAIL_HOURS * 3600:
                        items.append((3, o.get("last_ok") or 0, {**base, "url": o["url"], "reason": "server_fails"}))
                elif (not priced or p.get("discovered") or rid in self.store.get("shop_js", {}) or self.fetcher.cooldown_left(rid) > 0) \
                        and (url := search_address(rid, self._search_words(p), p.get("ean"))) \
                        and now - searched.get(f"{pid}|{rid}", 0) > self.RELAY_SEARCH_DAYS * 86400:
                    items.append((2, searched.get(f"{pid}|{rid}", 0), {**base, "kind": "search", "url": url, "reason": "search",
                                                                       "words": (p.get("brand") or (p.get("name") or "").split(" ")[0])[:40],
                                                                       "render": rid in self.store.get("shop_js", {})}))
        items.sort(key=lambda x: (x[0], x[1]))
        counts: dict[str, int] = {}
        for _, _, it in items:
            counts[it["reason"]] = counts.get(it["reason"], 0) + 1
        return {"enabled": True, "items": [i for _, _, i in items[:limit]], "total": len(items), "counts": counts,
                "site_gap": DOMAIN_GAP, "search_gap": SEARCH_GAP}

    @staticmethod
    def _search_words(p: dict[str, Any]) -> str:
        from .client import search_terms

        return search_terms(p)

    def relay_heartbeat(self, beat: dict[str, Any]) -> None:
        """The userscript's continuous check says it is alive (shown under Manage → Userscript)."""
        keep = {k: beat.get(k) for k in ("done", "ok", "fail", "found", "waiting", "version") if isinstance(beat.get(k), (int, float, str))}
        self.store["relay_heartbeat"] = {"ts": time.time(), "on": bool(beat.get("on", True)), **keep}

    def _relay_search(self, item: dict[str, Any]) -> str | dict[str, Any]:
        """A shop's search page fetched by the browser: find the product here (same rules as the server, but the
        browser's page is not checked afterwards, so only a title that clearly fits is linked)."""
        rid, pid = item.get("retailer"), normalize_product_id(str(item.get("product") or ""))
        if rid not in RETAILERS or pid not in self.store["products"]:
            raise ValueError(f"{rid}: {pid}: not a tracked product / shop")
        p = self.store["products"][pid]
        html = item.get("html") if isinstance(item.get("html"), str) else ""
        try:
            status = int(item.get("status") or 0)
        except (TypeError, ValueError):
            status = 0
        readable = bool(html) and 0 < status < 400
        if readable:              # blocked / failed searches are tried again, only real answers wait a week
            self.store.setdefault("relay_searched", {})[f"{pid}|{rid}"] = time.time()
        skip = set(self.store.get("rejected", {}).get(pid, []))
        cands = search_candidates(rid, html, {**p, "id": pid}, skip) if readable else []
        found = next((c["url"] for c in cands if c["score"] >= TITLE_OK), None)
        offers = self.store["offers"].setdefault(pid, {})
        if found and not (offers.get(rid) or {}).get("url"):
            offers[rid] = {"url": found, "history": [], "found": time.time(), "found_via": "relay"}
            self.log("ok", "discover", T("link found by your browser"), product=pid, retailer=rid, url=found, source="relay")
            return {"product": pid, "retailer": rid, "shop": RETAILERS[rid][0], "url": found, "reason": "no_price"}
        why = (T("the shop blocked the search (HTTP {status})", status=status) if status in (403, 429, 503)
               else T("could not reach the shop: {error}", error=str(item.get("error") or "?")[:100]) if not status
               else T("search page: HTTP error {status}", status=status) if status >= 400
               else T("no matching product found") if cands or (p.get("name") or "")[:10].lower() in html.lower()
               else T("the search page does not contain the product: this shop probably loads its results with JavaScript. Paste the product page URL instead."))
        if "JavaScript" in why and not item.get("rendered"):
            self.fetcher.discover_error[rid] = why
            self._note_js(rid)
            if readable:
                self.store.setdefault("relay_searched", {})[f"{pid}|{rid}"] = time.time()
        self.log("info", "discover", T("your browser searched: {reason}", reason=why), product=pid, retailer=rid, url=item.get("url"), source="relay")
        return "fail"

    def relay_result(self, item: dict[str, Any]) -> str | dict[str, Any]:
        """One page fetched by the user's browser: a price (stored like the userscript) or a failure."""
        if item.get("kind") == "search":
            return self._relay_search(item)
        url, price, error = item.get("url"), item.get("price"), item.get("error")
        rid = item.get("retailer") or (retailer_from_url(url) if url else None)
        pid = normalize_product_id(item["product"]) if item.get("product") else None
        if pid and rid and (o := self.store["offers"].get(pid, {}).get(rid)):
            o["relay_ts"] = time.time()                      # the continuous check doesn't ask for it again at once
        if price:
            self.report_price(float(price), url=url, product=pid, retailer=rid, title=item.get("title"), via="relay",
                              gtins=item.get("gtins"))
            status = "ok"
        else:
            self.log("warning", "userscript", T("your browser could not fetch the price either: {error}", error=str(error or "")[:120] or "?"),
                     product=pid, retailer=rid, url=url, source="relay")
            status = "fail"
        rl = self.store.setdefault("relay_last", {"ts": 0, "ok": 0, "fail": 0})
        if time.time() - rl.get("ts", 0) > 900:           # a new run: start counting again
            rl.update(ok=0, fail=0)
        rl["ts"] = time.time()
        rl[status] = rl.get(status, 0) + 1
        return status

    def report_price(self, price: float, *, url: str | None = None, product: str | None = None,
                     retailer: str | None = None, title: str | None = None, via: str | None = None,
                     gtins: list[str] | None = None) -> str:
        """Accept a price observed elsewhere (userscript, automation). Returns the product id."""
        if url and not retailer:
            retailer = retailer_from_url(url)
        pid = normalize_product_id(product) if product else None
        found: tuple[str, str] | None = None
        if url and retailer:
            key = url_key(retailer, url)
            for n, offers in self.store["offers"].items():
                o = offers.get(retailer)
                if o and o.get("url") and url_key(retailer, o["url"]) == key and (pid is None or n == pid):
                    found = (n, retailer)
                    break
        if found is None and pid and retailer:
            if pid not in self.store["products"]:
                raise LocalizedError("Product {id} is not tracked yet; add it first.", id=pid)
            offer = self.store["offers"].setdefault(pid, {}).setdefault(retailer, {"url": url or "", "history": []})
            if url and not offer.get("url"):
                offer["url"] = normalize_url(url)
            found = (pid, retailer)
        source = ("relay" if via == "relay" else "userscript") if url else "panel"
        if found is None:
            self.log("warning", "userscript" if url else "user", T("price received for a product that is not tracked"),
                     url=url, retailer=retailer, price=price, source=source, product=pid)
            raise LocalizedError("No matching link: this page is not tracked (add the product or link it first).")
        pid, retailer = found
        others = [o["last_price"] for r, o in self.store["offers"][pid].items() if r != retailer and o.get("available") and o.get("last_price")]
        if url and (warn := is_suspicious_price(price, self.store["products"][pid], self.store["offers"][pid][retailer], others)):
            self.store["offers"][pid][retailer]["suspect"] = {"price": price, "reason": warn, "ts": time.time()}
            self.log("error", "userscript", warn, product=pid, retailer=retailer, url=url, price=price, source=source)
            raise ValueError(warn)   # already English (panel translates)
        offer = self.store["offers"][pid][retailer]
        if gtins:   # ... and the barcodes the page declares: the surest way to know it is the same product
            offer["gtins"] = [g for g in (normalize_gtin(x) for x in gtins[:5] if isinstance(x, str)) if g][:3]
        if title or gtins:   # the userscript sends the page title: lets the link check judge the link
            if title:
                offer["title"] = title[:300]
            offer["link_status"], offer["link_reason"] = link_check(offer, self.store["products"][pid])
        before = self.compute()["statuses"].get(pid, {})
        had_error = bool(offer.get("error"))
        record_price(offer, price)
        offer["last_ok"] = offer["last_checked"]
        if url:
            offer["last_via"] = source                       # 'relay' / 'userscript': shown as ⓤ next to the price
        msg = (T("price €{price} fetched by your browser (relay)", price=f"{price:.2f}") if source == "relay"
               else T("price €{price} received via Tampermonkey", price=f"{price:.2f}") if url
               else T("price €{price} entered by hand", price=f"{price:.2f}"))
        if url:          # a price from the shop page itself: the open error is solved (it leaves the error lists)
            offer["error"] = None
            offer.pop("ignored_error", None)
            offer.pop("suspect", None)
        self.log("ok", "userscript" if url else "user", msg,
                 product=pid, retailer=retailer, url=url or offer.get("url"), price=price, source=source)
        if url and had_error:
            self.log("ok", "userscript", T("open error solved by your browser"), product=pid, retailer=retailer,
                     url=url, source=source)
        if url:
            self.store["userscript_last"] = {"ts": time.time(), "product": pid, "retailer": retailer, "price": price}
        self._fire_events(pid, before, self.compute()["statuses"].get(pid, {}))
        self.push_update()
        return pid

    # ----------------------------------------------------------------- ticker/news
    @property
    def ticker(self) -> dict[str, Any]:
        """Return ticker defaults merged with the configured overrides."""
        return {**TICKER_DEFAULT, **(self.opt(self.entry, CONF_TICKER, None) or {})}

    async def ticker_data(self, lang: str, since: float | None = None) -> dict[str, Any]:
        """The ticker at the bottom of the panel, each part as configured under Settings (on/off and how many):
        the current deals (deal score at least the minimum under Settings, best first), products whose price
        dropped lately but are not a deal yet, and news."""
        from .news import NewsFeed, for_language

        cfg, now, out = self.ticker, time.time(), []
        statuses = self._statuses()

        def item(kind: str, pid: str, st: dict[str, Any]) -> dict[str, Any]:
            """One product at its current lowest price; the discount only when there is one."""
            disc = st.get("discount_ref") if st.get("discount_ref") is not None else st.get("discount_avg")
            return {"kind": kind, "ts": self.store["products"][pid].get("last_deal") or now, "product": pid,
                    "name": self.store["products"][pid].get("name") or "", "price": st["best_price"],
                    "discount": disc if disc is not None and disc > 0 else None, "score": st.get("deal_score"),
                    "change": st.get("change_7d"), "shop": RETAILERS.get(st.get("best_retailer"), ("",))[0], "url": st.get("best_url")}
        by_score = lambda n: (-(statuses[n].get("deal_score") or 0), n)  # noqa: E731
        priced = [n for n in self.store["products"] if statuses.get(n, {}).get("best_price") is not None]
        min_score = self.deal_rules["min_score"]
        deals = sorted((n for n in priced if (statuses[n].get("deal_score") or 0) >= min_score), key=by_score) if cfg["deals"] else []
        shown = set(deals) if cfg["max_deals"] else set()
        if cfg["drops"] and cfg["max_drops"]:
            drops = sorted((n for n in priced if n not in shown and (statuses[n].get("change_7d") or 0) <= -5
                            or n not in shown and (statuses[n].get("deal_score") or 0) >= TICKER_GOOD_SCORE),
                           key=lambda n: (statuses[n].get("change_7d") or 0, n))
            out += [item("price", n, statuses[n]) for n in drops[: cfg["max_drops"]]]
        if cfg["deals"] and cfg["max_deals"]:
            out += [item("deal", n, statuses[n]) for n in deals[: cfg["max_deals"]]]
        news: list[dict[str, Any]] = []
        news_hash = ""
        if cfg["news"] and cfg["max_news"]:
            if not hasattr(self, "news"):
                self.news = NewsFeed(lambda: async_get_clientsession(self.hass))
            every = await self.news.get()
            # changes when a new news file is put online: news you closed shows again then
            news_hash = hashlib.sha1(json.dumps(every, sort_keys=True).encode()).hexdigest()[:16] if every else ""
            news = for_language(every, lang)[: cfg["max_news"]]
        # errors solved since the previous ticker (shown once; gone at the next ticker load)
        self._track_errors(now)
        since = now - TICKER_RELOAD if since is None else max(float(since), now - 86400)
        # oldest first, at most 10 per load; when more are waiting, the cursor stops at the last one sent,
        # so the rest come with the next load instead of being skipped
        waiting = [(ts, key) for ts, key, _opened in (self.store.get("err_track") or {}).get("solved") or []
                   if ts > since and key.partition("|")[0] in self.store["products"]]
        fixed = []
        for ts, key in waiting[:10]:
            pid, _, rid = key.partition("|")
            fixed.append({"kind": "fixed", "ts": ts, "product": pid, "name": self.store["products"][pid].get("name") or "",
                          "shop": RETAILERS.get(rid, (rid,))[0] if rid else None})
        cursor = fixed[-1]["ts"] if len(waiting) > 10 else now
        return {"items": out, "news": news, "news_hash": news_hash, "fixed": fixed, "config": cfg, "now": now,
                "cursor": cursor, "reload": TICKER_RELOAD}

    # --------------------------------------------------------------- settings
    def shop_settings_info(self) -> dict[str, Any]:
        """Shop settings imported? Terms accepted (when, which version)? Without both, no shop is contacted."""
        legal = self.entry.options.get(CONF_LEGAL) or {}
        return {"imported": bool(self.entry.options.get(CONF_SHOP_PROFILE)), "ready": ready(), "shops": len(profile_ids()),
                "accepted": legal.get("accepted"), "legal_version": LEGAL_VERSION, "accepted_version": legal.get("version")}

    def settings_get(self) -> dict[str, Any]:
        """Return panel settings and shop state."""
        from .shops import CATEGORY_OF, ENABLED_FINDERS, FINDERS, finder_key

        o = {**self.entry.data, **self.entry.options}
        shops = []
        for rid, (label, _) in RETAILERS.items():
            shops.append({
                "id": rid, "label": label, "builtin": not rid.startswith("c_"),
                "generic": rid in GENERIC_SHOPS, "domain": domain_of(rid), "reader": reader_of(rid),
                "categories": list(CATEGORY_OF.get(rid) or ()),
                "search": SEARCH.get(rid, ""), "default_search": DEFAULT_SEARCH.get(rid, GENERIC_SHOPS.get(rid, {}).get("search", "")),
                "enabled": rid in self.retailers,
                "paused_hours": round(self.fetcher.cooldown_left(rid) / 3600, 2),
                "blocks": self.fetcher.blocks.get(rid, 0), "autopause": rid not in self.fetcher.no_autopause,
            })
        return {
            "shop_settings": self.shop_settings_info(),
            "discount_threshold": self.threshold, "min_history_days": int(self.opt(self.entry, CONF_MIN_HISTORY_DAYS, DEFAULT_MIN_HISTORY_DAYS)),
            "auto_refresh": bool(o.get(CONF_AUTO_REFRESH, True)), "refresh_times": ", ".join(f"{h:02d}:{m:02d}" for h, m in self.refresh_times),
            "digest_time": str(o.get(CONF_DIGEST_TIME, DEFAULT_DIGEST_TIME))[:5], "use_impersonation": bool(o.get(CONF_IMPERSONATE, True)),
            "notify_service": o.get(CONF_NOTIFY, "") or "",
            "shops": shops, "transport": self.fetcher.transport,
            "finders": [{**f, "enabled": f["id"] in ENABLED_FINDERS, "paused_hours": round(self.fetcher.cooldown_left(finder_key(f["id"])) / 3600, 2)}
                        for f in FINDERS.values()],
            "refresh_mode": self.refresh_mode, "spread_hours": self.spread_hours, "watch_cycle_min": self.watch_cycle_minutes,
            "deal_min_score": self.deal_rules["min_score"], "deal_atl": self.deal_rules["atl"], "deal_target": self.deal_rules["target"],
            "cycle_choices": list(CYCLE_CHOICES), "watch_cycle_choices": list(WATCH_CYCLE_CHOICES), "product_limit": self.product_limit,
            "dev": {k: self.dev(k) for k in (CONF_DEV_FIXED_TIMES, CONF_DEV_FULL_REFRESH, CONF_DEV_FREE_CYCLE, CONF_DEV_UNLIMITED)},
            "language": o.get(CONF_LANGUAGE, DEFAULT_LANGUAGE), "languages": LANGUAGES, "categories": dict(CATEGORIES),
            "browser_relay": bool(o.get(CONF_RELAY, True)), "ticker": self.ticker,
            "block_words": list(o.get(CONF_BLOCK_WORDS, [])), "allow_words": list(o.get(CONF_ALLOW_WORDS, [])),
            "builtin_words": list(BUILTIN_WORDS), "relay_hours": int(o.get(CONF_RELAY_HOURS, DEFAULT_RELAY_HOURS)),
        }

    def settings_validate(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Merge + validate panel settings into a new options dict. Raises LocalizedError."""
        from .models import parse_times
        from .shops import validate_custom_shop

        opts = dict(self.entry.options)

        def num(key: str, lo: int, hi: int) -> None:
            try:
                v = int(float(fields[key]))
            except (TypeError, ValueError) as err:
                raise LocalizedError("{field}: not a number", field=key) from err
            if not lo <= v <= hi:
                raise LocalizedError("{field}: must be between {lo} and {hi}", field=key, lo=lo, hi=hi)
            opts[key] = v
        if "discount_threshold" in fields:
            num("discount_threshold", 1, 90)
        if "min_history_days" in fields:
            num("min_history_days", 0, 90)
        if CONF_DEAL_MIN_SCORE in fields:
            num(CONF_DEAL_MIN_SCORE, 1, 100)
        for key in (CONF_DEAL_ATL, CONF_DEAL_TARGET):
            if key in fields:
                opts[key] = bool(fields[key])
        if CONF_TICKER in fields:
            raw, tk = fields[CONF_TICKER] if isinstance(fields[CONF_TICKER], dict) else {}, {}
            for k, v in TICKER_DEFAULT.items():
                val = raw.get(k, v)
                if isinstance(v, bool):
                    tk[k] = bool(val)
                else:
                    try:
                        tk[k] = max(0, min(50, int(float(val))))
                    except (TypeError, ValueError) as err:
                        raise LocalizedError("{field}: not a number", field=k) from err
            opts[CONF_TICKER] = tk
        for key in ("auto_refresh", "use_impersonation", CONF_RELAY, CONF_DEV_FIXED_TIMES, CONF_DEV_FULL_REFRESH,
                    CONF_DEV_FREE_CYCLE, CONF_DEV_UNLIMITED):
            if key in fields:
                opts[key] = bool(fields[key])
        for key in (CONF_BLOCK_WORDS, CONF_ALLOW_WORDS):
            if key in fields:
                raw = fields[key]
                items = re.split(r"[\n,;]+", raw) if isinstance(raw, str) else raw if isinstance(raw, list) else None
                if items is None:
                    raise LocalizedError("{field}: not a valid choice", field=key)
                words: list[str] = []
                for w in items:
                    w = re.sub(r"\s+", " ", str(w)).strip()
                    if not w:
                        continue
                    if not 2 <= len(w.rstrip("*")) <= 60 or "*" in w.rstrip("*"):
                        raise LocalizedError("Word list: “{word}” must be 2 to 60 characters (a * only at the end)", word=w[:60])
                    if w.lower() not in (x.lower() for x in words):
                        words.append(w)
                if len(words) > 300:
                    raise LocalizedError("Word list: at most 300 words")
                opts[key] = words
        if "refresh_times" in fields:
            times = parse_times(str(fields["refresh_times"]))
            if not 1 <= len(times) <= 6:
                raise LocalizedError("Enter 1 to 6 times as HH:MM, e.g. 07:30, 19:30")
            opts[CONF_REFRESH_TIMES] = ", ".join(times)
        if "digest_time" in fields:
            t = parse_times(str(fields["digest_time"]))
            if len(t) != 1:
                raise LocalizedError("Digest time: one time as HH:MM")
            opts[CONF_DIGEST_TIME] = t[0] + ":00"
        if "notify_service" in fields:
            ns = str(fields["notify_service"] or "").strip()
            if ns and not re.fullmatch(r"(notify\.)?[a-z0-9_]+", ns):
                raise LocalizedError("Notify service like notify.mobile_app_phone")
            opts[CONF_NOTIFY] = ns
        if "custom_shops" in fields:
            shops, seen = [], set()
            for shop in fields["custom_shops"] or []:
                v = validate_custom_shop(shop)
                if v["id"] in seen or v["id"] in RETAILERS and not v["id"].startswith("c_"):
                    raise LocalizedError("Shop {name} already exists", name=v["name"])
                seen.add(v["id"])
                shops.append(v)
            opts[CONF_CUSTOM_SHOPS] = shops
        if "shop_search" in fields:
            searches = {}
            for rid, tpl in (fields["shop_search"] or {}).items():
                tpl = str(tpl or "").strip()
                if tpl and not valid_search(tpl):
                    raise LocalizedError("Search URL for {shop}: must start with https:// and contain {query} or {ean}",
                                         shop=RETAILERS.get(rid, (rid,))[0], query="{query}", ean="{ean}")
                if tpl == DEFAULT_SEARCH.get(rid):
                    continue                     # default: don't store, so future default fixes still apply
                searches[rid] = tpl
            opts[CONF_SHOP_SEARCH] = searches
        if CONF_WATCH_CYCLE in fields:
            try:
                wc = int(fields[CONF_WATCH_CYCLE] or 0)
            except (TypeError, ValueError) as err:
                raise LocalizedError("{field}: not a valid choice", field=CONF_WATCH_CYCLE) from err
            if wc not in WATCH_CYCLE_CHOICES:
                raise LocalizedError("{field}: not a valid choice", field=CONF_WATCH_CYCLE)
            opts[CONF_WATCH_CYCLE] = wc
        if fields.get("refresh_mode") == "times" and not (fields.get(CONF_DEV_FIXED_TIMES) or self.dev(CONF_DEV_FIXED_TIMES)):
            raise LocalizedError("Checking at fixed times is switched off: a full round at once puts too much load on the shops.")
        if "spread_hours" in fields and not (fields.get(CONF_DEV_FREE_CYCLE) or self.dev(CONF_DEV_FREE_CYCLE)):
            try:
                ok = float(fields["spread_hours"]) in CYCLE_CHOICES
            except (TypeError, ValueError):
                ok = False
            if not ok:
                raise LocalizedError("Cycle: choose {choices} hours", choices="/".join(map(str, CYCLE_CHOICES)))
        if "refresh_mode" in fields:
            if fields["refresh_mode"] not in ("spread", "times", "off"):
                raise LocalizedError("Unknown refresh mode")
            opts[CONF_REFRESH_MODE] = fields["refresh_mode"]
            opts[CONF_AUTO_REFRESH] = fields["refresh_mode"] != "off"
        if "spread_hours" in fields:
            num("spread_hours", 1, 168)
        if "language" in fields:
            if fields["language"] != "auto" and fields["language"] not in LANGUAGES:
                raise LocalizedError("Unknown language")
            opts[CONF_LANGUAGE] = fields["language"]
        if "relay_hours" in fields:
            num(CONF_RELAY_HOURS, 1, 168)
        valid_ids = set(RETAILERS) | {s["id"] for s in opts.get(CONF_CUSTOM_SHOPS, [])}
        if "retailers" in fields:
            opts[CONF_RETAILERS] = [r for r in fields["retailers"] if r in valid_ids]
        if "custom_shops" in fields:
            # a shop you just added is searched and fetched right away (switch it off under Shops if you like)
            before = {s["id"] for s in self.opt(self.entry, CONF_CUSTOM_SHOPS, []) or []}
            active = list(opts.get(CONF_RETAILERS, self.opt(self.entry, CONF_RETAILERS, profile_ids())))
            opts[CONF_RETAILERS] = [r for r in active if r in valid_ids] + \
                [s["id"] for s in opts[CONF_CUSTOM_SHOPS] if s["id"] not in before and s["id"] not in active]
        if "finders" in fields:
            from .shops import FINDERS
            opts["finders"] = [f for f in fields["finders"] if f in FINDERS]
        if "no_autopause" in fields:
            opts[CONF_NO_AUTOPAUSE] = [r for r in fields["no_autopause"] if r in valid_ids]
        return opts

    def resume_shop(self, retailer: str | None) -> None:
        self.fetcher.reset_cooldowns(retailer)
        self.log("info", "shop", (T("pause lifted for {shop}", shop=RETAILERS.get(retailer, (retailer,))[0]) if retailer else T("pause lifted for all shops")),
                 retailer=retailer, source="panel")
        self.push_update()

    # --------------------------------------------------------------- link check
    def verify_links(self) -> dict[str, int]:
        """Re-judge every link offline (barcode/title/URL/price). Suspect links stop counting for prices."""
        counts = {"ok": 0, "suspect": 0, "unknown": 0, "confirmed": 0, "cleaned": 0}
        for pid, offers in self.store["offers"].items():
            p = self.store["products"].get(pid, {})
            for offer in offers.values():
                counts["cleaned"] += clean_history(offer, p.get("ref_price"))
                status, reason = link_check(offer, p)
                offer["link_status"], offer["link_reason"] = status, reason
                counts["unknown" if status is None else status] += 1
        return counts

    def confirm_offer(self, pid: str, retailer: str) -> None:
        offer = self._offer(pid, retailer)
        self.log("ok", "link", T("link approved"), product=normalize_product_id(pid), retailer=retailer,
                 url=offer.get("url"), source="panel")
        offer["link_status"], offer["link_reason"] = "confirmed", T("confirmed by hand")
        self.push_update()

    def _auto_reject(self, pid: str, rid: str, offer: dict[str, Any], source: str) -> str | None:
        """A link that is clearly another product (an accessory, another barcode) goes away by itself: only this
        link is blocked, and the same shop is searched again for the right page. A link or price you set
        yourself is never touched; a mere doubt stays (you choose in the logbook)."""
        if offer.get("manual_url") or offer.get("manual_price") or offer.get("link_status") == "confirmed" \
                or offer.get("url") == self.store["products"][pid].get("source_url"):
            return None
        why = wrong_product(self.store["products"][pid], Parsed(None, offer.get("title"), gtins=tuple(offer.get("gtins") or ()),
                                                                mpn=offer.get("mpn")))
        if not why:
            return None
        rej = self.store.setdefault("rejected", {}).setdefault(pid, [])
        if (key := url_key(rid, offer["url"])) not in rej:
            rej.append(key)
        self.store["offers"][pid].pop(rid, None)
        self.log("warning", "link", T("wrong product ({reason}): this link is blocked, the shop is searched again", reason=why),
                 product=pid, retailer=rid, url=offer.get("url"), source=source)
        self.queue_rediscover(pid, rid)
        return why

    def queue_rediscover(self, pid: str, rid: str) -> None:
        """Search one shop again for a product, in the background (after a link was blocked)."""
        if (pid, rid) in self._rediscover:
            return
        self._rediscover.append((pid, rid))
        if len(self._rediscover) == 1 and self.hass and self.entry:
            self.entry.async_create_background_task(self.hass, self._run_rediscover(), f"{DOMAIN}_rediscover")

    async def _run_rediscover(self) -> None:
        try:
            while self._rediscover and ready():
                pid, rid = self._rediscover[0]
                if pid in self.store["products"] and not (self.store["offers"].get(pid) or {}).get(rid):
                    try:
                        if (await self.discover_product(pid, [rid]))["found"]:
                            await self.refresh_product(pid, [rid], source="rediscover")
                        self.push_update()
                    except Exception:  # noqa: BLE001 - the regular rounds try again
                        _LOGGER.exception("searching %s again for %s failed", rid, pid)
                self._rediscover.pop(0)
        finally:
            self._rediscover = []

    def reject_link(self, pid: str, retailer: str) -> None:
        """Logbook choice 'never visit this link again': block only this link and search the shop again."""
        pid = normalize_product_id(pid)
        self.remove_offer(pid, retailer, block=True)
        self.queue_rediscover(pid, retailer)

    def remove_offer(self, pid: str, retailer: str, block: bool = True) -> None:
        pid = normalize_product_id(pid)
        offer = self._offer(pid, retailer)
        if block and offer.get("url"):
            rej = self.store.setdefault("rejected", {}).setdefault(pid, [])
            key = url_key(retailer, offer["url"])
            if key not in rej:
                rej.append(key)
        self.log("info", "link", T("link removed and blocked") if block else T("link removed"), product=pid,
                 retailer=retailer, url=offer.get("url"), source="panel")
        del self.store["offers"][pid][retailer]
        self.push_update()

    def update_offer(self, pid: str, retailer: str, url: Any = _UNSET, manual_price: Any = _UNSET) -> None:
        """Manual link / manual price for one shop. Manual always wins over automatic and is never
        removed by the integration. An empty value clears it and hands the field back to automation:
        - url: "https://…" = set by hand (same page keeps its history), "" = remove the link
          (not blocked: 'find links' may search again)
        - manual_price: number = fixed price that wins, "" / None = back to the automatic price"""
        pid = normalize_product_id(pid)
        self._product(pid)
        if retailer not in RETAILERS:
            raise LocalizedError("Unknown shop {shop}.", shop=retailer)
        offers = self.store["offers"].setdefault(pid, {})
        if url is not _UNSET:
            if url in ("", None):
                if retailer in offers:
                    self.log("info", "link", T("link cleared: automatic search allowed again"), product=pid,
                             retailer=retailer, url=offers[retailer].get("url"), source="panel")
                    del offers[retailer]
                manual_price = _UNSET
            else:
                if is_search_url(str(url)):
                    raise LocalizedError("This is a search page, not a product page. Use 🔎 Find to search it, or paste the page of the product itself.")
                try:
                    new = normalize_url(str(url))
                except ValueError as err:
                    raise LocalizedError("Provide a full product URL.") from err
                host = (new.split("/")[2] if new.count("/") >= 2 else "").lower()
                dom = (domain_of(retailer) or "").lower()
                if dom and not (host == dom or host.endswith("." + dom)):
                    raise LocalizedError("The address is not on {shop} ({domain}): pick the right shop or address.",
                                         shop=RETAILERS[retailer][0], domain=dom)
                rej = self.store.setdefault("rejected", {}).get(pid, [])
                if url_key(retailer, new) in rej:          # chosen by hand: no longer blocked
                    rej.remove(url_key(retailer, new))
                old = offers.get(retailer)
                if old and old.get("url") and url_key(retailer, old["url"]) == url_key(retailer, new):
                    old["url"] = new
                else:
                    keep_manual = old.get("manual_price") if old else None
                    offers[retailer] = {"url": new, "history": [], **({"manual_price": keep_manual} if keep_manual else {})}
                o = offers[retailer]
                o.update(manual_url=True, link_status="confirmed", link_reason=T("set by hand"), error=None)
                self.log("ok", "link", T("link set by hand"), product=pid, retailer=retailer, url=new, source="panel")
        if manual_price is not _UNSET:
            offer = offers.get(retailer)
            if offer is None:
                raise LocalizedError("This shop has no link yet: enter the link as well.")
            offer.pop("price_choice", None)          # a new own price (or none): earlier choices no longer apply
            offer.pop("declined_price", None)
            if manual_price in ("", None):
                if offer.pop("manual_price", None):
                    auto = offer.pop("auto_price", None)
                    if auto:
                        record_price(offer, auto)
                    self.log("info", "user", T("manual price cleared: the automatic price is used again"),
                             product=pid, retailer=retailer, source="panel")
            else:
                try:
                    price = round(float(manual_price), 2)
                except (TypeError, ValueError) as err:
                    raise LocalizedError("Invalid price.") from err
                if not 0 < price <= 100000:
                    raise LocalizedError("Invalid price.")
                before = self.compute()["statuses"].get(pid, {})
                offer["manual_price"] = {"price": price, "ts": time.time()}
                record_price(offer, price)
                offer["error"] = None
                offer["last_ok"] = time.time()
                self.log("ok", "user", T("manual price €{price} set (wins over automatic)", price=f"{price:.2f}"),
                         product=pid, retailer=retailer, url=offer.get("url"), price=price, source="panel")
                self._fire_events(pid, before, self.compute()["statuses"].get(pid, {}))
        self.push_update()

    def fix_offer(self, pid: str, retailer: str, url: str | None = None, price: float | None = None) -> None:
        """Errors tab / service: correct link and/or price in one go (both count as manual)."""
        if not url and price is None:
            raise LocalizedError("Enter a link and/or a price.")
        self.update_offer(pid, retailer, url=url if url else _UNSET, manual_price=price if price is not None else _UNSET)

    def _offer(self, pid: str, retailer: str) -> dict[str, Any]:
        pid = normalize_product_id(pid)
        try:
            return self.store["offers"][pid][retailer]
        except KeyError as err:
            raise LocalizedError("No link for product {id} at {shop}.", id=pid, shop=retailer) from err

    def _snapshot(self) -> None:
        summary = basket_summary(self.store, self.compute()["statuses"])
        day = today_iso()
        snaps = self.store["snapshots"]
        row = [day, summary["cost"], summary["priced"], summary["products"]]
        if snaps and snaps[-1][0] == day:
            snaps[-1] = row
        else:
            snaps.append(row)

    def _fire_events(self, pid: str, before: dict, after: dict) -> None:
        """Emit eligible deal events once per day and schedule notifications for changed status."""
        p = self.store["products"][pid]
        # the link opens the product page itself; price, shop and discount describe that same offer
        price, retailer, url = self.notifier.shop_offer(pid, after)
        discount = after.get("discount_ref") if after.get("discount_ref") is not None else after.get("discount_avg")
        payload = {"product": pid, "name": p.get("name"), "category": p.get("category"),
                   "price": price, "retailer": retailer, "url": url, "discount": discount,
                   "target_price": p.get("target_price")}
        day = today_iso()
        for flag, event in (("is_all_time_low", EVENT_NEW_LOW), ("high_discount", EVENT_HIGH_DISCOUNT),
                            ("target_hit", EVENT_TARGET_HIT)):
            key = (pid, flag + day)
            if after.get(flag) and not before.get(flag) and key not in self._alerted:
                self._alerted.add(key)
                self.hass.bus.async_fire(event, payload)
                p["last_deal"] = time.time()      # sort deals by when they came in
                add_event(self.store, flag, {k: payload[k] for k in ("product", "name", "price", "retailer", "url")}
                          | {"discount": payload["discount"], "score": after.get("deal_score")})
        if before.get("best_price") != after.get("best_price") or any(
                before.get(k) != after.get(k) for k in ("is_all_time_low", "target_hit", "deal_score")):
            self.hass.async_create_task(self.notifier.on_product_change(pid, dict(before), dict(after)))

    # ------------------------------------------------------------------ products
    async def add_product(self, url: str | None = None, *, name: str | None = None, ean: str | None = None,
                          brand: str | None = None, mpn: str | None = None, category: str | None = None,
                          ref_price: float | None = None, target_price: float | None = None, priority: int | None = None,
                          notes: str | None = None, discover: bool = True) -> dict[str, Any]:
        """Add a product from the address of a product page at one of your shops: the page tells name, brand, barcode,
        model number and price, and ARGUS then looks the same product up at the other shops of its category.
        Without an address a name (and ideally a barcode) is enough: it is searched at the shops."""
        url = (url or "").strip()
        name = (name or "").strip()
        if not url and not name and not ean:
            raise LocalizedError("Enter the address of a product page, or at least a name.")
        if ean and not normalize_gtin(ean):
            raise LocalizedError("The barcode (EAN/ISBN) is not valid.")
        if category and category not in CATEGORIES:
            raise LocalizedError("Unknown category.")
        parsed: Parsed | None = None
        rid = None
        error = None
        if url:
            try:
                url = normalize_url(url)
            except ValueError as err:
                raise LocalizedError("Provide a full product URL.") from err
            if is_search_url(url):
                raise LocalizedError("This is a search page, not a product page. Paste the page of the product itself.")
            rid = retailer_from_url(url)
            if not ready():
                raise LocalizedError("First import the shop settings and accept their terms (Manage → Shops).")
            if not rid:
                raise LocalizedError("This address is not on one of your shops. Add the shop first (Manage → Shops & jobs), or import a shop settings file that has it.")
            parsed, error = await self.fetcher.fetch_offer(rid, url, force=True)
        ident = product_identity(parsed, url) if parsed else {"name": clean_title(slug_title(url).title()) if url else "", "brand": None,
                                                              "ean": None, "mpn": None, "image": None, "price": None, "category": None}
        name = name or ident["name"] or (slug_title(url) if url else "")
        ean = normalize_gtin(ean) or ident["ean"]
        if not category:
            from .shops import CATEGORY_OF

            single = CATEGORY_OF.get(rid, ()) if rid else ()
            category = ident["category"] or (single[0] if len(single) == 1 else None) or DEFAULT_CATEGORY
        pid = product_id(ean, url or name)
        if (limit := self.product_limit) is not None and pid not in self.store["products"] and len(self.store["products"]) >= limit:
            raise LocalizedError("You track {n} products already: remove one first.", n=limit)
        existing = pid in self.store["products"]
        p = self.store["products"].setdefault(pid, {
            "id": pid, "name": name, "brand": brand or ident["brand"], "ean": ean, "mpn": mpn or ident["mpn"],
            "category": category, "image": ident["image"], "source_url": url or None, "source_shop": rid,
            "added": time.time(), "checked": 0})
        for key, val in (("name", name), ("brand", brand), ("mpn", mpn), ("notes", notes), ("ref_price", ref_price),
                         ("target_price", target_price), ("priority", priority)):
            if val not in (None, "") and (not existing or not p.get(key)):
                p[key] = val
        if existing and category and p.get("category") == DEFAULT_CATEGORY:
            p["category"] = category
        offers = self.store["offers"].setdefault(pid, {})
        if url and rid and rid not in offers:
            offer: dict[str, Any] = {"url": url, "history": [], "found": time.time(), "found_via": "source",
                                     "link_status": "ok", "link_reason": T("the address you added the product with")}
            offers[rid] = offer
            if parsed:
                offer["title"] = (parsed.title or "")[:300]
                offer["gtins"] = list(parsed.gtins)
                offer["mpn"] = parsed.mpn
                if parsed.price is not None:
                    record_price(offer, parsed.price)
                    offer["last_ok"] = offer["last_checked"]
                elif parsed.unavailable:
                    offer["unavailable"] = parsed.reason or "sold_out"
                    record_price(offer, None)
            if error:
                record_price(offer, None, error=error)
        self.log("ok" if not error else "warning", "user",
                 (T("product already tracked: this shop was added") if existing else T("product added")) + (f" · {error}" if error else ""),
                 product=pid, retailer=rid, url=url or None, source="panel")
        if discover:
            self.queue_first_check(pid)
        self.push_update()
        return {"id": pid, "existing": existing, "name": p["name"], "category": p["category"], "ean": p.get("ean"),
                "price": parsed.price if parsed else None, "error": error}

    def queue_first_check(self, pid: str) -> None:
        """A product that was never searched at the other shops is searched and priced right after it is added,
        instead of waiting for the next round. Products are done one after the other, so a bulk add stays polite."""
        if pid in self._first_checks or pid == self._first_current:
            return
        self._first_checks.append(pid)
        if not self._first_busy:
            self._first_busy = True
            self.entry.async_create_background_task(self.hass, self._run_first_checks(), f"{DOMAIN}_first_check")

    async def _run_first_checks(self) -> None:
        """Work through the products waiting for their first search; always release the busy flag."""
        try:
            while self._first_checks and ready():
                pid = self._first_checks.pop(0)
                if pid not in self.store["products"]:
                    continue                                       # removed again in the meantime
                self._first_current = pid
                try:
                    live = self._live_retailers(False)
                    await self.discover_product(pid, live)
                    await self.refresh_product(pid, live, source="added")
                except Exception:  # noqa: BLE001 - the regular rounds try again
                    _LOGGER.exception("first check failed for %s", pid)
                self._first_current = None
                self.push_update()
        finally:
            self._first_busy, self._first_current = False, None

    def remove_product(self, pid: str) -> None:
        pid = normalize_product_id(pid)
        name = self._product(pid).get("name")
        for key in ("products", "offers", "rejected"):
            self.store[key].pop(pid, None)
        if pid in self._first_checks:
            self._first_checks.remove(pid)
        self.log("info", "user", T("product removed: {name}", name=name or pid), source="panel")
        self.push_update()

    COERCE: dict[str, type] = {"ref_price": float, "target_price": float, "priority": int}

    def update_product(self, pid: str, fields: dict[str, Any]) -> None:
        """Edit a product: name, brand, barcode, model, category, reference price, target price, priority, notes, image."""
        pid = normalize_product_id(pid)
        p = self._product(pid)
        for key, val in fields.items():
            if key in ("name", "brand", "mpn", "notes"):
                val = re.sub(r"\s+", " ", str(val or "")).strip()
                if key == "name" and not val:
                    raise LocalizedError("A product needs a name.")
                p[key] = val[:160] if key == "name" else (val[:500 if key == "notes" else 160] or None)
            elif key == "ean":
                if val in ("", None):
                    p.pop("ean", None)
                elif not (g := normalize_gtin(val)):
                    raise LocalizedError("The barcode (EAN/ISBN) is not valid.")
                else:
                    p["ean"], p["ean_source"] = g, "user"
            elif key == "category":
                if val not in CATEGORIES:
                    raise LocalizedError("Unknown category.")
                p["category"] = val
            elif key in ("ref_price", "target_price"):
                if val in ("", None):
                    p.pop(key, None)
                    continue
                try:
                    v = round(float(str(val).replace(",", ".")), 2)
                except ValueError as err:
                    raise LocalizedError("{field}: not a number", field=key) from err
                if not 0 < v <= 100000:
                    raise LocalizedError("{field}: must be between {lo} and {hi}", field=key, lo=0.01, hi=100000)
                p[key] = v
            elif key == "priority":
                if val in ("", None, 0, "0"):
                    p.pop("priority", None)
                    continue
                try:
                    v = int(val)
                except (TypeError, ValueError) as err:
                    raise LocalizedError("{field}: not a number", field=key) from err
                if v not in (1, 2, 3):
                    raise LocalizedError("{field}: must be between {lo} and {hi}", field=key, lo=1, hi=3)
                p[key] = v
            elif key == "image":
                if val and not str(val).startswith("https://"):
                    raise LocalizedError("The picture must be an https:// address.")
                p["image"] = val or None
        self.verify_links()
        self.push_update()

    # ------------------------------------------------------------- insights
    def shop_detail(self, rid: str) -> dict[str, Any]:
        """Shops → click a shop: its settings, the last requests (what was asked, what came back, why it
        failed), its recent log and a plain diagnosis."""
        stats = self.retailer_stats().get(rid, {})
        site = self._site(rid)
        trace = list(reversed(self.fetcher.trace.get(rid, [])))
        offers = [o for by in self.store["offers"].values() for r, o in by.items() if r == rid]
        log = query_activity(self.store, retailer=rid, limit=40)["entries"]
        hints = []
        if rid not in self.retailers:
            hints.append(T("This shop is switched off (Settings → Shops)."))
        if self.fetcher.cooldown_left(rid) > 0:
            hints.append(T("Paused after a block: the shop refused the requests. It is tried again automatically later."))
        searches = [x for x in trace if x["kind"] == "search"]
        js = sum(1 for x in searches if "JavaScript" in (x.get("error") or ""))
        blocked = sum(1 for x in trace if x.get("status") in (403, 429, 503) or "blocked" in (x.get("error") or ""))
        if (js and js >= len(searches) / 2) or rid in self.store.get("shop_js", {}):
            hints.append(T("The shop's search page loads its results with JavaScript, so the server sees no products there. The userscript can search it in a background tab (Manage → Userscript), or paste the product page address yourself."))
        if blocked and blocked >= len(trace) / 2:
            hints.append(T("Most requests are blocked by the shop's bot protection. The browser relay (userscript) or a manual price helps."))
        if not offers and not searches:
            hints.append(T("No links yet and not searched since the last restart: use Find links, or paste a product link in a product."))
        if not hints and stats.get("errors"):
            hints.append(T("Some links fail: open the failing products below to see the error per link."))
        return {
            "id": rid, "label": RETAILERS.get(rid, (rid,))[0], "site": site, "stats": stats,
            "enabled": rid in self.retailers, "search": SEARCH.get(rid), "blocks": self.fetcher.blocks.get(rid, 0),
            "paused_until": self.fetcher.blocked_until.get(rid) if self.fetcher.cooldown_left(rid) > 0 else None,
            "last_request": self.fetcher.last_request.get(site), "next_free": self.fetcher.next_free(site),
            "next_search": self.fetcher.next_free(site, search=True), "trace": trace, "log": log, "hints": hints,
            "js": rid in self.store.get("shop_js", {}), "now": time.time(),
        }

    def retailer_stats(self) -> dict[str, dict[str, Any]]:
        """Summarize each retailer's offers, errors, cheapest prices, and cooldown."""
        statuses = self._statuses()
        out: dict[str, dict[str, Any]] = {}
        for rid, (label, _) in RETAILERS.items():
            offers = [(n, o) for n, by in self.store["offers"].items() for r, o in by.items() if r == rid]
            last_ok = max((o.get("last_ok") or 0 for _, o in offers), default=0)
            out[rid] = {
                "label": label, "enabled": rid in self.retailers, "offers": len(offers),
                "ok": sum(1 for _, o in offers if o.get("available")),
                "errors": sum(1 for _, o in offers if o.get("error")),
                "suspect": sum(1 for _, o in offers if o.get("link_status") == "suspect"),
                "cheapest": sum(1 for n, _ in offers if statuses.get(n, {}).get("best_retailer") == rid),
                "last_ok": last_ok or None,
                "paused_hours": round(self.fetcher.cooldown_left(rid) / 3600, 1),
                "failing": [{"product": n, "name": self.store["products"].get(n, {}).get("name"), "error": o["error"],
                             "suspect": (o.get("suspect") or {}).get("price")}
                            for n, o in offers if o.get("error")][:50],
            }
        return out

    # ------------------------------------------------------------- import/export
    def export_csv(self) -> str:
        return rows_to_csv(product_rows(self.store, self.compute()["statuses"]), PRODUCT_COLUMNS)

    def export_backup(self) -> dict[str, Any]:
        return {"version": 1, "exported": today_iso(), **copy.deepcopy(self.store)}

    def import_backup(self, data: Any, merge: bool = False) -> dict[str, int]:
        clean = copy.deepcopy(validate_backup(data))
        if merge:
            for pid, p in clean["products"].items():
                self.store["products"].setdefault(pid, p)
            for pid, offers in clean["offers"].items():
                self.store["offers"].setdefault(pid, {}).update(
                    {r: o for r, o in offers.items() if r not in self.store["offers"].get(pid, {})})
        else:
            self.store = clean
        self.verify_links()
        self.push_update()
        return {"products": len(self.store["products"])}

    def series(self) -> list[dict[str, float]]:
        from .models import basket_series

        return basket_series(self.store)
