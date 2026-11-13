"""Read-only release signal in Home Assistant's native update list."""
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, VERSION
from .updates import DATA_UPDATES


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([DeyeEMSReleaseUpdate(hass.data[DATA_UPDATES], entry)])


class DeyeEMSReleaseUpdate(UpdateEntity):
    """A version notice, deliberately without installation authority."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Nowe wydanie"
    _attr_title = "Deye EMS"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_supported_features = UpdateEntityFeature(0)

    def __init__(self, manager, entry):
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_public_release"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name="Deye EMS",
            manufacturer="Deye EMS community", model="Local energy management",
            sw_version=VERSION)

    @property
    def installed_version(self):
        return VERSION

    @property
    def latest_version(self):
        return self._manager.status.get("latest_version")

    @property
    def release_url(self):
        return self._manager.status.get("release_url")

    @property
    def release_summary(self):
        status = self._manager.status
        if status.get("status") == "error":
            return "Nie udało się sprawdzić wydań. Ostatnio znana wersja może być nieaktualna."
        return ("Wynik sprawdzania wydań GitHub. Instalację wykonaj jawnie w Marketplace; "
                "jego lista wersji korzysta z osobnej pamięci podręcznej. "
                "Ta encja nie instaluje aktualizacji ani nie restartuje Home Assistanta.")

    @property
    def extra_state_attributes(self):
        state = self._manager.status
        return {key: state.get(key) for key in (
            "checked_at", "next_check_at", "automatic", "interval_seconds", "stale")}

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self._manager.async_add_listener(self._updated))

    @callback
    def _updated(self):
        self.async_write_ha_state()

    async def async_update(self):
        """Allow HA's public refresh action to check this entity's own source."""
        await self._manager.async_check()
