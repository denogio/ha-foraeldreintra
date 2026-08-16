from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .api import Child, ForaldreIntraError
from .const import (
    DEFAULT_SHOW_SCHEDULE_CALENDARS,
    DOMAIN,
    OPT_SELECTED_CHILDREN,
    OPT_SHOW_SCHEDULE_CALENDARS,
)
from .coordinator import ForaldreIntraCoordinator
from .decoding import _decode_display_value

_LOCAL_TIMEZONE = ZoneInfo("Europe/Copenhagen")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one school schedule calendar per selected child."""
    if not bool(
        entry.options.get(
            OPT_SHOW_SCHEDULE_CALENDARS,
            DEFAULT_SHOW_SCHEDULE_CALENDARS,
        )
    ):
        return

    coordinator: ForaldreIntraCoordinator = hass.data[DOMAIN][entry.entry_id]
    children = [
        Child(id=str(child["id"]), name=str(child["name"]))
        for child in (coordinator.data or {}).get("children", [])
        if child.get("id") and child.get("name")
    ]
    selected_children = {
        _decode_display_value(name)
        for name in entry.options.get(
            OPT_SELECTED_CHILDREN,
            [_decode_display_value(child.name) for child in children],
        )
    }

    entities = [
        ForaeldreIntraScheduleCalendar(coordinator, entry, child)
        for child in children
        if not selected_children or _decode_display_value(child.name) in selected_children
    ]
    async_add_entities(entities)


def _as_local_datetime(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=_LOCAL_TIMEZONE)
        return value.astimezone(_LOCAL_TIMEZONE)
    return datetime.combine(value, time.min, tzinfo=_LOCAL_TIMEZONE)


def _schedule_events(schedule: dict[str, Any], child_name: str) -> list[CalendarEvent]:
    events: list[CalendarEvent] = []
    for lesson in schedule.get("lessons", []) or []:
        try:
            lesson_date = date.fromisoformat(str(lesson["date"]))
            start_time = time.fromisoformat(str(lesson["start"]))
            end_time = time.fromisoformat(str(lesson["end"]))
        except (KeyError, TypeError, ValueError):
            continue

        subject = _decode_display_value(lesson.get("subject")) or "Lektion"
        has_substitute = bool(lesson.get("has_substitute"))
        summary = f"{subject} (vikar)" if has_substitute else subject

        description_lines = [f"Barn: {child_name}"]
        substitute_text = _decode_display_value(lesson.get("substitute_text"))
        if substitute_text:
            description_lines.append(substitute_text)

        events.append(
            CalendarEvent(
                summary=summary,
                start=datetime.combine(lesson_date, start_time, tzinfo=_LOCAL_TIMEZONE),
                end=datetime.combine(lesson_date, end_time, tzinfo=_LOCAL_TIMEZONE),
                description="\n".join(description_lines),
            )
        )

    return sorted(events, key=lambda event: event.start)


class ForaeldreIntraScheduleCalendar(
    CoordinatorEntity[ForaldreIntraCoordinator],
    CalendarEntity,
):
    """A Home Assistant calendar backed by SkoleIntra's schedule endpoint."""

    _attr_icon = "mdi:calendar-school"

    def __init__(
        self,
        coordinator: ForaldreIntraCoordinator,
        entry: ConfigEntry,
        child: Child,
    ) -> None:
        super().__init__(coordinator)
        self._child = child
        self._child_display_name = _decode_display_value(child.name) or child.name
        self._attr_name = f"ForældreIntra skoleskema ({self._child_display_name})"
        self._attr_unique_id = f"{entry.entry_id}_calendar_{slugify(self._child_display_name)}"

    def _current_schedule(self) -> dict[str, Any]:
        schedules = (self.coordinator.data or {}).get("schedules", {}) or {}
        for name, schedule in schedules.items():
            if _decode_display_value(name) == self._child_display_name:
                return dict(schedule or {})
        return {}

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next event from the coordinator's current week."""
        now = datetime.now(_LOCAL_TIMEZONE)
        return next(
            (
                event
                for event in _schedule_events(
                    self._current_schedule(),
                    self._child_display_name,
                )
                if _as_local_datetime(event.end) > now
            ),
            None,
        )

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return lessons in the date range requested by Home Assistant."""
        range_start = _as_local_datetime(start_date)
        range_end = _as_local_datetime(end_date)
        monday = range_start.date() - timedelta(days=range_start.weekday())
        events: list[CalendarEvent] = []

        while datetime.combine(monday, time.min, tzinfo=_LOCAL_TIMEZONE) < range_end:
            try:
                schedule = await self.coordinator.client.get_schedule_for_child(
                    self._child,
                    monday,
                )
            except ForaldreIntraError:
                monday += timedelta(days=7)
                continue

            events.extend(_schedule_events(schedule, self._child_display_name))
            monday += timedelta(days=7)

        return [
            event
            for event in sorted(events, key=lambda item: item.start)
            if _as_local_datetime(event.end) > range_start
            and _as_local_datetime(event.start) < range_end
        ]
