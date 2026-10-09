"""Sensors: summary sensors plus one best-price sensor per tracked product."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, RETAILERS
from .coordinator import ArgusCoordinator
from .models import offer_price

SUMMARY = (
    SensorEntityDescription(key="tracked_products", translation_key="tracked_products", icon="mdi:eye-circle",
                            state_class=SensorStateClass.MEASUREMENT),
    SensorEntityDescription(key="all_time_lows", translation_key="all_time_lows", icon="mdi:trending-down",
                            state_class=SensorStateClass.MEASUREMENT),
    SensorEntityDescription(key="price_drops", translation_key="price_drops", icon="mdi:sale",
                            state_class=SensorStateClass.MEASUREMENT),
    SensorEntityDescription(key="targets_reached", translation_key="targets_reached", icon="mdi:bullseye-arrow",
                            state_class=SensorStateClass.MEASUREMENT),
    SensorEntityDescription(key="basket_cost", translation_key="basket_cost", icon="mdi:cart-heart",
                            native_unit_of_measurement="EUR", state_class=SensorStateClass.MEASUREMENT,
                            suggested_display_precision=2),
    SensorEntityDescription(key="basket_saving", translation_key="basket_saving", icon="mdi:piggy-bank",
                            native_unit_of_measurement="EUR", state_class=SensorStateClass.MEASUREMENT,
                            suggested_display_precision=2),
    SensorEntityDescription(key="offers_with_errors", translation_key="offers_with_errors", icon="mdi:alert-circle-outline",
                            state_class=SensorStateClass.MEASUREMENT),
    SensorEntityDescription(key="best_deal", translation_key="best_deal", icon="mdi:star-circle",
                            native_unit_of_measurement="pts", state_class=SensorStateClass.MEASUREMENT),
)


def _device(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name="ARGUS", manufacturer="Community", entry_type=None)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coord: ArgusCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(SummarySensor(coord, entry, d) for d in SUMMARY)
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = [n for n in coord.store["products"] if n not in known]
        if new:
            known.update(new)
            async_add_entities(ProductPriceSensor(coord, entry, n) for n in new)

    _add_new()
    entry.async_on_unload(coord.async_add_listener(_add_new))


class SummarySensor(CoordinatorEntity[ArgusCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coord: ArgusCoordinator, entry: ConfigEntry, description: SensorEntityDescription) -> None:
        super().__init__(coord)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device(entry)
        self.entity_id = f"sensor.argus_{description.key}"           # only a suggestion: existing entities keep theirs

    def _flagged(self, flag: str) -> list[str]:
        st = self.coordinator.data["statuses"]
        return [n for n, s in st.items() if s.get(flag)]

    @property
    def native_value(self) -> Any:
        d, key = self.coordinator.data, self.entity_description.key
        if key == "tracked_products":
            return len(self.coordinator.store["products"])
        if key == "all_time_lows":
            return len(self._flagged("is_all_time_low"))
        if key == "price_drops":
            return len(self._flagged("high_discount"))
        if key == "best_deal":
            return max((st["deal_score"] for st in d["statuses"].values()), default=0)
        if key == "targets_reached":
            return len(self._flagged("target_hit"))
        if key == "basket_cost":
            return d["summary"]["cost"]
        if key == "basket_saving":
            return d["summary"]["saving"]
        return sum(s["offers_error"] for s in d["statuses"].values())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        key = self.entity_description.key
        products = self.coordinator.store["products"]
        if key == "offers_with_errors":
            paused = {RETAILERS[r][0]: round(self.coordinator.fetcher.cooldown_left(r) / 3600, 1)
                      for r in self.coordinator.retailers if self.coordinator.fetcher.cooldown_left(r) > 0}
            return {"paused_hours": paused, "transport": self.coordinator.fetcher.transport}
        if key.startswith("basket"):
            return self.coordinator.data["summary"]
        if key == "best_deal":
            st = self.coordinator.data["statuses"]
            top = sorted((n for n in st if st[n]["deal_score"]), key=lambda n: -st[n]["deal_score"])[:5]
            return {"deals": [{"product": n, "name": products[n].get("name"), "score": st[n]["deal_score"],
                               "price": st[n]["best_price"], "retailer": RETAILERS.get(st[n]["best_retailer"], ("",))[0],
                               "url": st[n]["best_url"]} for n in top]}
        flag = {"all_time_lows": "is_all_time_low", "price_drops": "high_discount", "targets_reached": "target_hit"}.get(key)
        if flag:
            st = self.coordinator.data["statuses"]
            return {"products": [{"product": n, "name": products[n].get("name"), "price": st[n]["best_price"],
                                  "retailer": RETAILERS.get(st[n]["best_retailer"], ("",))[0],
                                  "discount": st[n]["discount_ref"] if st[n]["discount_ref"] is not None else st[n]["discount_avg"]}
                                 for n in self._flagged(flag)]}
        return None


class ProductPriceSensor(CoordinatorEntity[ArgusCoordinator], SensorEntity):
    """Cheapest current price of a product; long-term statistics give native HA graphs."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:eye-circle-outline"
    _attr_native_unit_of_measurement = "EUR"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coord: ArgusCoordinator, entry: ConfigEntry, pid: str) -> None:
        super().__init__(coord)
        self._pid = pid
        self._attr_unique_id = f"{entry.entry_id}_product_{pid}"
        self._attr_device_info = _device(entry)
        self.entity_id = f"sensor.argus_{pid}"

    @property
    def name(self) -> str:
        p = self.coordinator.store["products"].get(self._pid, {})
        return (p.get("name") or self._pid)[:80]

    @property
    def available(self) -> bool:
        return self._pid in self.coordinator.store["products"]

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data["statuses"].get(self._pid, {}).get("best_price")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p = self.coordinator.store["products"].get(self._pid, {})
        st = self.coordinator.data["statuses"].get(self._pid, {})
        offers = self.coordinator.store["offers"].get(self._pid, {})
        return {
            "product": self._pid, "category": p.get("category"), "brand": p.get("brand"), "ean": p.get("ean"),
            "reference_price": p.get("ref_price"),
            "best_retailer": RETAILERS.get(st.get("best_retailer"), ("",))[0] or None,
            "url": st.get("best_url"), "all_time_low": st.get("all_time_low"),
            "is_all_time_low": st.get("is_all_time_low"), "target_price": p.get("target_price"),
            "target_hit": st.get("target_hit"), "change_7d": st.get("change_7d"), "change_30d": st.get("change_30d"),
            "deal_score": st.get("deal_score"), "discount_reference": st.get("discount_ref"),
            "discount_average": st.get("discount_avg"), "shop_spread": st.get("shop_spread"),
            "high_discount": st.get("high_discount"), "entity_picture": p.get("image"),
            "prices": {RETAILERS[r][0]: offer_price(o) for r, o in offers.items() if r in RETAILERS and offer_price(o)},
        }
