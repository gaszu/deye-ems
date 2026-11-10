"""Durable panel-only preferences, separate from energy configuration/state."""
from __future__ import annotations

import asyncio

from homeassistant.components import frontend
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

STORAGE_KEY = "deye_ems_appearance"
DATA_APPEARANCE = STORAGE_KEY


class AppearanceManager:
    """Serialize preference writes and publish only successfully saved values."""

    def __init__(self, hass, *, store=None):
        self._hass = hass
        self._store = store if store is not None else Store(hass, 1, STORAGE_KEY)
        self._lock = asyncio.Lock()
        self._theme = ""

    @property
    def appearance(self):
        return {"theme": self._theme}

    async def async_load(self):
        async with self._lock:
            try:
                saved = await self._store.async_load()
            except Exception:
                # A cosmetic preference must not prevent the energy engine
                # from starting. Do not overwrite an unreadable stored value.
                return
            if isinstance(saved, dict):
                theme = saved.get("theme")
                # Keep a previously selected name across a temporarily absent
                # theme during startup/reload. The panel inherits HA if missing.
                if isinstance(theme, str) and len(theme) <= 256:
                    self._theme = theme

    async def async_set_theme(self, theme):
        async with self._lock:
            if not isinstance(theme, str) or len(theme) > 256:
                raise ValueError("Wybierz poprawny motyw panelu.")
            if theme and theme not in frontend.async_get_theme_names(self._hass):
                raise ValueError("Wybrany motyw nie jest dostępny w Home Assistant.")
            try:
                await self._store.async_save({"theme": theme})
            except Exception as error:
                raise HomeAssistantError("Nie udało się zapisać wyglądu panelu.") from error
            self._theme = theme
