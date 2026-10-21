"""Notification rules: which products, which events, to whom and how.

A rule = scope (all / priority / categories / products) + triggers (with parameters) +
targets (mobile app, any notify service, notify entity, e-mail, HA notification, TTS, event).
Rules live in the store (no reload needed) and are edited in the panel.
"""
from __future__ import annotations

import html as _html
import logging
import re
import time
import uuid
from urllib.parse import quote
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import CATEGORIES, DOMAIN, PANEL_URL, RETAILERS
from .i18n import LocalizedError, T, tr
from .models import normalize_product_id

if TYPE_CHECKING:
    from .coordinator import ArgusCoordinator

_LOGGER = logging.getLogger(__name__)
EVENT_NOTIFICATION = f"{DOMAIN}_notification"

# trigger id -> (label, per-product?, parameter)
TRIGGERS: dict[str, tuple[str, bool, str | None]] = {
    "target_hit": ("Target price reached", True, None),
    "my_alert": ("Your deal alert on the product (10–50% cheaper)", True, None),
    "candidates": ("Found elsewhere: is it the same item? (with Yes/No buttons)", False, None),
    "all_time_low": ("Lowest price so far", True, None),
    "discount": ("Discount vs reference or 90-day price", True, "discount_pct"),
    "price_below": ("Price below an amount", True, "price_below"),
    "price_drop": ("Price drop", True, "drop_pct"),
    "deal_score": ("Deal score reached", True, "min_score"),
    "new_shop": ("Cheaper at a new shop", True, None),
    "back_in_stock": ("Back in stock / first price", True, None),
    "any_change": ("Any price change", True, None),
    "digest": ("Daily digest", False, None),
    "deal_of_day": ("Deal of the day", False, "dotd_time"),
    "job_done": ("Job finished (refresh, link search…)", False, None),
    "problems": ("Problems (shop paused, errors)", False, None),
}
SCOPES = ("all", "priority", "categories", "products")
TARGET_TYPES = ("mobile", "notify", "entity", "email", "persistent", "tts", "event")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def default_rules(threshold: float, notify_service: str = "") -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = [{"type": "persistent"}]
    if notify_service:
        svc = notify_service if notify_service.startswith("notify.") else f"notify.{notify_service}"
        targets.append({"type": "mobile" if "mobile_app_" in svc else "notify", "service": svc})
    return [
        {"id": "deals", "name": "All deals", "enabled": True, "scope": {"type": "all"},
         "triggers": ["target_hit", "my_alert", "candidates", "all_time_low", "discount"], "params": {"discount_pct": int(threshold)},
         "shops": [], "targets": targets, "cooldown_hours": 24, "quiet": None, "image": True, "link": True},
        {"id": "digest", "name": "Daily digest", "enabled": True, "scope": {"type": "all"},
         "triggers": ["digest"], "params": {}, "shops": [], "targets": list(targets), "cooldown_hours": 0,
         "quiet": None, "image": False, "link": False},
    ]


def validate_rules(rules: Any) -> list[dict[str, Any]]:
    """Clean user input. Raises LocalizedError (English template, translated)."""
    if not isinstance(rules, list) or len(rules) > 50:
        raise LocalizedError("Invalid list of rules (max 50).")
    out = []
    for i, r in enumerate(rules, 1):
        if not isinstance(r, dict):
            raise LocalizedError("Rule {n} is invalid.", n=i)
        name = str(r.get("name") or T("Rule {n}", n=i)).strip()[:60]
        scope = r.get("scope") or {"type": "all"}
        stype = scope.get("type", "all")
        if stype not in SCOPES:
            raise LocalizedError("{rule}: unknown choice of products.", rule=name)
        categories = [c for c in scope.get("categories", []) if c in CATEGORIES]
        products = list(dict.fromkeys(p for p in (normalize_product_id(x) for x in scope.get("products", []))
                                      if re.fullmatch(r"p[0-9a-f]{10}", p)))[:200]
        if stype == "categories" and not categories:
            raise LocalizedError("{rule}: choose at least one category.", rule=name)
        if stype == "products" and not products:
            raise LocalizedError("{rule}: choose at least one product.", rule=name)
        triggers = [t for t in r.get("triggers", []) if t in TRIGGERS]
        if not triggers:
            raise LocalizedError("{rule}: choose at least one event.", rule=name)
        p = r.get("params") or {}
        params: dict[str, Any] = {}
        for key, lo, hi in (("discount_pct", 1, 95), ("price_below", 0.01, 100000), ("drop_pct", 1, 95), ("min_score", 1, 100)):
            if key in p and p[key] not in (None, ""):
                try:
                    v = float(p[key])
                except (TypeError, ValueError) as err:
                    raise LocalizedError("{rule}: {field} is not a number.", rule=name, field=key) from err
                if not lo <= v <= hi:
                    raise LocalizedError("{rule}: {field} must be between {lo} and {hi}.", rule=name, field=key, lo=lo, hi=hi)
                params[key] = v
        if "deal_of_day" in triggers:                  # the time of day the deal of the day is sent
            when = str(p.get("dotd_time") or "09:00")[:5]
            if not TIME_RE.match(when):
                raise LocalizedError("{rule}: time of the deal of the day as HH:MM.", rule=name)
            params["dotd_time"] = when
        for t in triggers:
            need = TRIGGERS[t][2]
            if need and need not in params:
                raise LocalizedError("{rule}: enter a value for '{event}'.", rule=name, event=TRIGGERS[t][0])
        targets = []
        for t in r.get("targets", [])[:10]:
            tt = t.get("type")
            if tt not in TARGET_TYPES:
                raise LocalizedError("{rule}: unknown way of sending.", rule=name)
            clean: dict[str, Any] = {"type": tt}
            if tt in ("mobile", "notify", "email"):
                svc = str(t.get("service") or "").strip()
                if not re.fullmatch(r"notify\.[a-z0-9_]+", svc):
                    raise LocalizedError("{rule}: choose a notify service.", rule=name)
                clean["service"] = svc
            if tt == "email":
                addrs = [a.strip() for a in re.split(r"[,;\s]+", str(t.get("to") or "")) if a.strip()]
                if not addrs or not all(EMAIL_RE.match(a) for a in addrs):
                    raise LocalizedError("{rule}: invalid e-mail address.", rule=name)
                clean["to"] = addrs[:10]
            if tt == "entity":
                ent = str(t.get("entity_id") or "")
                if not re.fullmatch(r"notify\.[a-z0-9_]+", ent):
                    raise LocalizedError("{rule}: choose a notify entity.", rule=name)
                clean["entity_id"] = ent
            if tt == "tts":
                tts, mp = str(t.get("tts") or ""), str(t.get("media_player") or "")
                if not re.fullmatch(r"tts\.[a-z0-9_]+", tts) or not re.fullmatch(r"media_player\.[a-z0-9_]+", mp):
                    raise LocalizedError("{rule}: choose a speech service and a media player.", rule=name)
                clean.update(tts=tts, media_player=mp)
            targets.append(clean)
        if not targets:
            raise LocalizedError("{rule}: choose at least one recipient.", rule=name)
        quiet = r.get("quiet")
        if quiet:
            if not (TIME_RE.match(str(quiet.get("from", ""))) and TIME_RE.match(str(quiet.get("to", "")))):
                raise LocalizedError("{rule}: quiet hours as HH:MM.", rule=name)
            quiet = {"from": quiet["from"], "to": quiet["to"]}
        try:
            cooldown = max(0, min(24 * 30, float(r.get("cooldown_hours", 24))))
        except (TypeError, ValueError):
            cooldown = 24
        out.append({
            "id": str(r.get("id") or uuid.uuid4().hex[:8])[:16], "name": name, "enabled": bool(r.get("enabled", True)),
            "scope": {"type": stype, "categories": categories, "products": products}, "triggers": triggers, "params": params,
            "shops": [s for s in r.get("shops", []) if s in RETAILERS], "targets": targets,
            "cooldown_hours": cooldown, "quiet": quiet, "image": bool(r.get("image", True)), "link": bool(r.get("link", True)),
        })
    ids = [r["id"] for r in out]
    if len(set(ids)) != len(ids):
        raise LocalizedError("Two rules have the same id.")
    return out


def in_quiet(quiet: dict[str, str] | None, now: datetime) -> bool:
    if not quiet:
        return False
    cur = now.strftime("%H:%M")
    a, b = quiet["from"], quiet["to"]
    return a <= cur < b if a < b else (cur >= a or cur < b)


def product_triggers(rule: dict[str, Any], before: dict[str, Any], after: dict[str, Any]) -> list[tuple[str, str]]:
    """Which of the rule's per-product triggers fire for this status change: [(trigger, reason)]."""
    p, out = rule["params"], []
    price, old = after.get("best_price"), before.get("best_price")
    if price is None:
        return out
    if rule["shops"] and after.get("best_retailer") not in rule["shops"]:
        return out
    for t in rule["triggers"]:
        if t == "all_time_low" and after.get("is_all_time_low") and not before.get("is_all_time_low"):
            out.append((t, tr("lowest price so far")))
        elif t == "discount":
            d = after.get("discount_ref") if after.get("discount_ref") is not None else after.get("discount_avg")
            b = before.get("discount_ref") if before.get("discount_ref") is not None else before.get("discount_avg")
            if d is not None and d >= p["discount_pct"] and (b is None or b < p["discount_pct"] or old is None):
                out.append((t, tr("−{pct}% vs usual price", pct=f"{d:.0f}")))
        elif t == "my_alert" and (pct := after.get("alert_pct")):
            d = after.get("discount_avg") if after.get("discount_avg") is not None else after.get("discount_ref")
            b = before.get("discount_avg") if before.get("discount_avg") is not None else before.get("discount_ref")
            if d is not None and d >= pct and (b is None or b < pct or old is None):
                out.append((t, tr("{pct}% cheaper than usual (your alert: {alert}%)", pct=f"{d:.0f}", alert=pct)))
        elif t == "target_hit" and after.get("target_hit") and not before.get("target_hit"):
            out.append((t, tr("below your target price")))
        elif t == "price_below" and price <= p["price_below"] and (old is None or old > p["price_below"]):
            out.append((t, tr("below €{price}", price=f"{p['price_below']:.2f}")))
        elif t == "price_drop" and old and price < old and (old - price) / old * 100 >= p["drop_pct"]:
            out.append((t, tr("dropped {pct}% (was €{old})", pct=f"{(old - price) / old * 100:.0f}", old=f"{old:.2f}")))
        elif t == "deal_score" and after.get("deal_score", 0) >= p["min_score"] > before.get("deal_score", 0):
            out.append((t, tr("deal score {score}", score=after["deal_score"])))
        elif t == "new_shop" and old and price < old and after.get("best_retailer") not in (before.get("shops") or [after.get("best_retailer")]):
            out.append((t, tr("cheaper at a new shop (was €{old})", old=f"{old:.2f}")))
        elif t == "back_in_stock" and old is None:
            out.append((t, tr("available again")))
        elif t == "any_change" and old is not None and abs(price - old) >= 0.01:
            out.append((t, tr("price changed (was €{old})", old=f"{old:.2f}")))
    return out



def _md_url(url: str | None) -> str | None:
    """A web address as a Markdown link target: http(s) only, with brackets, parentheses and spaces encoded."""
    if not url or not re.match(r"https?://", url, re.I):
        return None
    return quote(url, safe=":/?#@!$&'*+,;=%~")

class Notifier:
    def __init__(self, coord: ArgusCoordinator) -> None:
        self.coord = coord
        self.hass: HomeAssistant = coord.hass

    # ------------------------------------------------------------------ data
    @property
    def store(self) -> dict[str, Any]:
        return self.coord.store

    @property
    def rules(self) -> list[dict[str, Any]]:
        return self.store.setdefault("notify_rules", [])

    def in_scope(self, rule: dict[str, Any], pid: str) -> bool:
        sc = rule["scope"]
        p = self.store["products"].get(pid, {})
        return {"all": True, "priority": int(p.get("priority") or 0) >= 2,
                "categories": p.get("category") in sc.get("categories", []), "products": pid in sc.get("products", [])}[sc["type"]]

    def _cooled(self, key: str, hours: float) -> bool:
        sent = self.store.setdefault("notify_sent", {})
        now = time.time()
        if hours and now - sent.get(key, 0) < hours * 3600:
            return False
        sent[key] = now
        if len(sent) > 5000:   # prune
            for k in sorted(sent, key=sent.get)[:1000]:
                del sent[k]
        return True

    def shop_offer(self, pid: str, status: dict[str, Any],
                   shops: list[str] | None = None) -> tuple[float | None, str | None, str | None]:
        """(price, shop, link) of the cheapest offer: the price and shop the deal is about, always together,
        never a dearer shop's price next to the cheapest shop's discount. The link is that shop's product page."""
        price, rid, best = status.get("best_price"), status.get("best_retailer"), status.get("best_url")
        offers = self.store["offers"].get(pid, {})
        if shops and rid not in shops:              # a rule for certain shops: the cheapest of those shops
            priced = sorted((o["last_price"], r, o.get("url")) for r, o in offers.items()
                            if r in shops and o.get("available") and o.get("last_price") and o.get("url"))
            if not priced:
                return price, rid, best
            price, rid, best = priced[0]
        return price, rid, best or (offers.get(rid) or {}).get("url")

    # ---------------------------------------------------------------- events
    async def on_product_change(self, pid: str, before: dict[str, Any], after: dict[str, Any]) -> None:
        """Send enabled, in-scope rule notifications for triggers outside their cooldowns."""
        p = self.store["products"].get(pid, {})
        for rule in self.rules:
            if not rule.get("enabled") or not self.in_scope(rule, pid):
                continue
            hits = [h for h in product_triggers(rule, before, after)
                    if self._cooled(f"{rule['id']}|{pid}|{h[0]}", rule.get("cooldown_hours", 24))]
            if not hits:
                continue
            price, retailer, url = self.shop_offer(pid, after, rule["shops"])
            shop = RETAILERS.get(retailer, ("",))[0]
            title = f"👁 {p.get('name') or pid}".strip()
            message = tr("€{price} at {shop}", price=f"{price:.2f}", shop=shop) + ": " + ", ".join(h[1] for h in hits)
            await self.send(rule, title, message, url=url,
                            image=p.get("image") if rule.get("image") else None,
                            data={"product": pid, "triggers": [h[0] for h in hits], "price": price})

    async def on_candidates(self, pid: str, new: list[dict[str, Any]], waiting: int) -> None:
        """Finds to confirm, bundled per product: one message with every new find (shop, title, price). On the phone
        it has buttons: Yes (all of them), No (none of them) and Open (the list in the panel, to answer one by one)."""
        p = self.store["products"].get(pid, {})
        name = p.get("name") or p.get("ean") or pid
        plain = lambda x: re.sub(r"[\[\]<>`]", "", str(x))   # web-page text: no Markdown links or HTML in the message
        lines = [f"• {plain(c['shop'])}: " + (f"€{c['price']:.2f}" if c.get("price") else tr("no price yet"))
                 + (f" — {plain(c['title'][:70])}" if c.get("title") else "") + (f"\n  {plain(c['url'])}" if c.get("url") else "")
                 for c in new[:8]]
        if len(new) > 8:
            lines.append(tr("… and {n} more", n=len(new) - 8))
        title = "🔎 " + (tr("Is this {name}?", name=name) if len(new) == 1 else tr("{n} possible matches for {name}", n=len(new), name=name))
        message = "\n".join(lines) + "\n" + (tr("Same item? Yes: ARGUS watches its price from now on.") if len(new) == 1
                                              else tr("All the same item? Or answer one by one in the panel ({n} waiting).", n=waiting))
        for rule in self.rules:
            if not rule.get("enabled") or "candidates" not in rule["triggers"] or not self.in_scope(rule, pid):
                continue
            tok = self.coord.candidate_token(pid, new)
            actions = [{"action": f"ARGUS_YES_{tok}", "title": tr("✓ Yes") if len(new) == 1 else tr("✓ Yes, all")},
                       {"action": f"ARGUS_NO_{tok}", "title": tr("✗ No") if len(new) == 1 else tr("✗ None")},
                       {"action": "URI", "title": tr("Open"), "uri": f"/{PANEL_URL}"}]
            await self.send(rule, title, message, url=new[0].get("url") if len(new) == 1 else None,
                            image=p.get("image") if rule.get("image") else None,
                            data={"product": pid, "triggers": ["candidates"], "candidates": [c["retailer"] for c in new]},
                            notification_id=f"{DOMAIN}_ask_{pid}", actions=actions, force=False)

    async def on_digest(self, digest: dict[str, Any]) -> None:
        """Send each enabled digest rule the deals allowed by its scope and shop filters."""
        for rule in self.rules:
            if not rule.get("enabled") or "digest" not in rule["triggers"]:
                continue
            deals = [d for d in digest["deals"] if self.in_scope(rule, d["product"])
                     and (not rule["shops"] or d["retailer"] in rule["shops"])]
            if not deals:
                continue
            lines = [f"• {d['name'] or d['product']}: " + tr("€{price} at {shop}", price=f"{d['price']:.2f}", shop=RETAILERS.get(d["retailer"], ("",))[0])
                     + (f" (−{d['discount']:.0f}%)" if d.get("discount") else "") + (" 🔻" if d.get("all_time_low") else "")
                     + (f"\n  {u}" if (u := d.get("url")) else "")
                     for d in deals[:15]]
            more = "\n" + tr("… and {n} more", n=len(deals) - 15) if len(deals) > 15 else ""
            await self.send(rule, "👁 " + tr("ARGUS deals today ({n})", n=len(deals)), "\n".join(lines) + more,
                            data={"deals": [d["product"] for d in deals]}, notification_id=f"{DOMAIN}_digest_{rule['id']}")

    async def on_job_done(self, job: dict[str, Any]) -> None:
        label = tr(job.get("label") or "Job")
        text = (tr("{label} stopped: {done}/{total} products", label=label, done=job["done"], total=job["total"]) if job.get("cancelled")
                else tr("{label} finished: {done}/{total} products", label=label, done=job["done"], total=job["total"]))
        text += "".join(", " + tr(t, n=job[k]) for k, t in (("updated", "{n} updated"), ("found", "{n} links found"),
                                                          ("errors", "{n} errors")) if job.get(k))
        for rule in self.rules:
            if not rule.get("enabled"):
                continue
            if "job_done" in rule["triggers"]:
                await self.send(rule, "👁 ARGUS", text)
            elif "problems" in rule["triggers"] and job.get("errors") and self._cooled(f"{rule['id']}|job_errors", rule.get("cooldown_hours", 24)):
                await self.send(rule, "⚠️ ARGUS", text)

    async def on_shop_paused(self, retailer: str, hours: float) -> None:
        for rule in self.rules:
            if rule.get("enabled") and "problems" in rule["triggers"] \
                    and self._cooled(f"{rule['id']}|pause|{retailer}", rule.get("cooldown_hours", 24)):
                await self.send(rule, "⚠️ " + tr("Shop paused"),
                                tr("{shop} blocked the price check and is paused for {hours} h.",
                                   shop=RETAILERS.get(retailer, (retailer,))[0], hours=f"{hours:.0f}"))

    # -------------------------------------------------------------- sending
    async def send(self, rule: dict[str, Any], title: str, message: str, *, url: str | None = None,
                   image: str | None = None, data: dict[str, Any] | None = None, notification_id: str | None = None,
                   force: bool = False, actions: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """Send to every target of the rule; queued during quiet hours (except HA notification/event)."""
        results = []
        quiet = not force and in_quiet(rule.get("quiet"), dt_util.now())
        self.hass.bus.async_fire(EVENT_NOTIFICATION, {"rule": rule["id"], "rule_name": rule["name"], "title": title,
                                                      "message": message, "url": url, "image": image, **(data or {})})
        for target in rule["targets"]:
            if quiet and target["type"] not in ("persistent", "event"):
                q = self.store.setdefault("notify_queue", {}).setdefault(rule["id"], [])
                q.append({"title": title, "message": message, "url": url, "dotd": "deal_of_day" in (data or {}).get("triggers", [])})
                if len(q) > 50:                              # the newest 50, never without the deal of the day
                    dotd = [i for i in q if i.get("dotd")][-1:]
                    q[:] = dotd + [i for i in q if not i.get("dotd")][-(50 - len(dotd)):]
                results.append({"target": target, "ok": True, "queued": True})
                continue
            try:
                await self._send_one(target, title, message, url, image, notification_id, actions)
                results.append({"target": target, "ok": True})
            except Exception as err:  # noqa: BLE001 - a broken target must not break the rest
                _LOGGER.warning("Notification via %s failed: %s", target, err)
                results.append({"target": target, "ok": False, "error": str(err)})
        self.coord.log("ok" if all(r["ok"] for r in results) else "error", "notify",
                       f"{rule['name']}: {title} — " + (T("queued (quiet hours)") if quiet else
                       ", ".join(("✓ " if r["ok"] else "✕ ") + r["target"]["type"] + ("" if r["ok"] else f" ({r.get('error')})") for r in results)),
                       product=(data or {}).get("product"))
        log = self.store.setdefault("notify_log", [])
        log.append({"ts": time.time(), "rule": rule["name"], "title": title, "message": message[:300],
                    "ok": all(r["ok"] for r in results), "queued": quiet})
        del log[:-100]
        return results

    async def _send_one(self, t: dict[str, Any], title: str, message: str, url: str | None, image: str | None,
                        notification_id: str | None, actions: list[dict[str, Any]] | None = None) -> None:
        call = self.hass.services.async_call
        full = message + (f"\n{url}" if url and t["type"] in ("email", "notify", "entity") else "")
        if t["type"] == "persistent":
            await call("persistent_notification", "create",
                       {"title": title, "message": message + (f"\n\n[{tr('Open')}]({_md_url(url)})" if _md_url(url) else "")
                        + (f"\n\n[{tr('Answer in ARGUS')}](/{PANEL_URL})" if actions else ""),
                        **({"notification_id": notification_id} if notification_id else {})}, blocking=True)
        elif t["type"] == "mobile":
            extra: dict[str, Any] = {}
            if url:
                extra.update(url=url, clickAction=url)
            if image:
                extra["image"] = image
            if actions:                                    # buttons in the phone's notification (Home Assistant app)
                extra["actions"] = actions
                extra["tag"] = notification_id or "argus"
            await call("notify", t["service"].split(".", 1)[1],
                       {"title": title, "message": message, **({"data": extra} if extra else {})}, blocking=True)
        elif t["type"] == "notify":
            await call("notify", t["service"].split(".", 1)[1], {"title": title, "message": full}, blocking=True)
        elif t["type"] == "email":
            esc = _html.escape                              # shop titles and addresses come from web pages
            body = (f"<h3>{esc(title)}</h3><p>{esc(message).replace(chr(10), '<br>')}</p>"
                    + (f'<p><a href="{esc(url)}">{esc(tr("View in the shop"))}</a></p>' if url else "")
                    + (f'<img src="{esc(image)}" width="240">' if image else ""))
            await call("notify", t["service"].split(".", 1)[1],
                       {"title": title, "message": full, "target": t["to"], "data": {"html": body}}, blocking=True)
        elif t["type"] == "entity":
            await call("notify", "send_message", {"entity_id": t["entity_id"], "title": title, "message": full}, blocking=True)
        elif t["type"] == "tts":
            await call("tts", "speak", {"entity_id": t["tts"], "media_player_entity_id": t["media_player"],
                                        "message": f"{title}. {message}".replace("€", "EUR ").replace("👁", "")}, blocking=True)
        # "event": the argus_notification event was already fired

    async def deal_of_the_day(self, now: datetime | None = None) -> None:
        """Rules with "Deal of the day": once a day, from the chosen time, the best deal among the rule's products
        (the same product the panel shows as deal of the day). No deal yet: tried again later that day."""
        now = now or dt_util.now()
        today = now.strftime("%Y-%m-%d")
        sent = self.store.setdefault("notify_sent", {})
        for rule in self.rules:
            if not rule.get("enabled") or "deal_of_day" not in rule["triggers"]:
                continue
            key = f"{rule['id']}|dotd|{today}"
            if key in sent or now.strftime("%H:%M") < rule["params"].get("dotd_time", "09:00"):
                continue
            top = self.coord.deal_of_the_day(lambda n, r=rule: self.in_scope(r, n), rule["shops"])
            if not top:
                continue
            sent[key] = time.time()
            pid, st = top
            p = self.store["products"].get(pid, {})
            price, retailer, url = self.shop_offer(pid, st, rule["shops"])
            disc = st.get("discount_ref") if st.get("discount_ref") is not None else st.get("discount_avg")
            why = [tr("−{pct}% vs usual price", pct=f"{disc:.0f}")] if disc else []
            why += [tr("lowest price so far")] * bool(st.get("is_all_time_low")) + [tr("below your target price")] * bool(st.get("target_hit"))
            why += [tr("deal score {score}", score=st.get("deal_score", 0))]
            message = tr("€{price} at {shop}", price=f"{price:.2f}", shop=RETAILERS.get(retailer, ("",))[0]) + " · " + ", ".join(why)
            await self.send(rule, f"⭐ {tr('Deal of the day')}: {p.get('name') or pid}".strip(), message, url=url,
                            image=p.get("image") if rule.get("image") else None,
                            data={"product": pid, "triggers": ["deal_of_day"], "price": price})

    async def flush_queues(self, _now: Any = None) -> None:
        """After quiet hours: one bundled message per rule. Also sends the deal of the day when it is time."""
        await self.deal_of_the_day()
        queue = self.store.get("notify_queue") or {}
        now = dt_util.now()
        for rule in self.rules:
            items = queue.get(rule["id"])
            if not items or in_quiet(rule.get("quiet"), now):
                continue
            queue[rule["id"]] = []
            items = sorted(items, key=lambda i: not i.get("dotd"))      # the deal of the day is never cut off
            body = "\n".join(f"• {i['title']}: {i['message']}" for i in items[:15])
            if len(items) > 15:
                body += "\n" + tr("… and {n} more", n=len(items) - 15)
            await self.send(rule, "👁 " + tr("{n} ARGUS notifications (quiet hours)", n=len(items)), body, force=True)

    # --------------------------------------------------------------- options
    def ha_options(self) -> dict[str, Any]:
        """Everything the panel dropdowns need: services, entities, categories, products."""
        from homeassistant.helpers import device_registry as dr

        services = sorted(self.hass.services.async_services_for_domain("notify"))
        devs = {d.name_by_user or d.name for d in dr.async_get(self.hass).devices.values()}
        notify = []
        for svc in services:
            if svc in ("send_message", "persistent_notification"):
                continue
            kind = ("mobile" if svc.startswith("mobile_app_") else
                    "email" if re.search(r"smtp|mail|gmail|outlook", svc) else "notify")
            label = svc.replace("mobile_app_", "").replace("_", " ")
            match = next((d for d in devs if d and re.sub(r"[^a-z0-9]+", "_", d.lower()).strip("_") == svc.replace("mobile_app_", "")), None)
            notify.append({"service": f"notify.{svc}", "label": match or label.title(), "kind": kind})
        states = self.hass.states
        ents = lambda domain: [{"entity_id": s.entity_id, "label": s.name} for s in states.async_all(domain)]  # noqa: E731
        return {
            "notify": notify, "notify_entities": ents("notify"), "tts": ents("tts"), "media_players": ents("media_player"),
            "persons": [{"entity_id": s.entity_id, "label": s.name} for s in states.async_all("person")],
            "categories": dict(CATEGORIES), "triggers": {k: {"label": v[0], "per_product": v[1], "param": v[2]} for k, v in TRIGGERS.items()},
            "retailers": {k: v[0] for k, v in RETAILERS.items()},
            "products": {pid: p.get("name") or pid for pid, p in self.store["products"].items()},
        }
