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
    DEFAULT_OPTIONAL_TIMETABLE_SUBJECTS_BY_CHILD,
    DEFAULT_SHOW_TIMETABLE_CALENDARS,
    DEFAULT_SUBJECT_ALIASES,
    DEFAULT_TEACHER_ALIASES,
    DOMAIN,
    LEGACY_OPT_SHOW_SCHEDULE_CALENDARS,
    OPT_OPTIONAL_TIMETABLE_SUBJECTS_BY_CHILD,
    OPT_SELECTED_CHILDREN,
    OPT_SHOW_TIMETABLE_CALENDARS,
    OPT_SUBJECT_ALIASES,
    OPT_TEACHER_ALIASES,
)
from .coordinator import ForaldreIntraCoordinator
from .decoding import _decode_display_value
from .formatting import (
    _apply_timetable_aliases,
    _build_subject_alias_map,
    _build_teacher_alias_map,
)

_LOCAL_TIMEZONE = ZoneInfo("Europe/Copenhagen")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one school timetable calendar per selected child."""
    if not bool(
        entry.options.get(
            OPT_SHOW_TIMETABLE_CALENDARS,
            entry.options.get(
                LEGACY_OPT_SHOW_SCHEDULE_CALENDARS,
                DEFAULT_SHOW_TIMETABLE_CALENDARS,
            ),
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
        ForaeldreIntraTimetableCalendar(coordinator, entry, child)
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


def _timetable_events(
    timetable: dict[str, Any],
    child_name: str,
    subject_aliases: dict[str, str] | None = None,
    teacher_aliases: dict[str, str] | None = None,
    optional_subjects_by_child: dict[str, Any] | None = None,
) -> list[CalendarEvent]:
    translated = _apply_timetable_aliases(
        timetable,
        subject_aliases or {},
        teacher_aliases or {},
        child_name,
        optional_subjects_by_child,
    )
    events: list[CalendarEvent] = []
    for lesson in translated.get("lessons", []) or []:
        try:
            lesson_date = date.fromisoformat(str(lesson["date"]))
            start_time = time.fromisoformat(str(lesson["start"]))
            end_time = time.fromisoformat(str(lesson["end"]))
        except (KeyError, TypeError, ValueError):
            continue

        subject = _decode_display_value(lesson.get("subject")) or "Lektion"
        has_substitute = bool(lesson.get("has_substitute"))
        labels = []
        if lesson.get("optional"):
            labels.append("valgfrit")
        if has_substitute:
            labels.append("vikar")
        summary = f"{subject} ({', '.join(labels)})" if labels else subject

        description_lines = [f"Barn: {child_name}"]
        if lesson.get("optional"):
            description_lines.append("Valgfri aktivitet")
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


class ForaeldreIntraTimetableCalendar(
    CoordinatorEntity[ForaldreIntraCoordinator],
    CalendarEntity,
):
    """A Home Assistant calendar backed by SkoleIntra's timetable endpoint."""

    _attr_icon = "mdi:calendar-school"

    def __init__(
        self,
        coordinator: ForaldreIntraCoordinator,
        entry: ConfigEntry,
        child: Child,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._child = child
        self._child_display_name = _decode_display_value(child.name) or child.name
        self._attr_name = f"ForældreIntra skoleskema ({self._child_display_name})"
        self._attr_unique_id = f"{entry.entry_id}_calendar_{slugify(self._child_display_name)}"

    def _subject_aliases(self) -> dict[str, str]:
        return _build_subject_alias_map(
            self._entry.options.get(OPT_SUBJECT_ALIASES, DEFAULT_SUBJECT_ALIASES)
        )

    def _teacher_aliases(self) -> dict[str, str]:
        return _build_teacher_alias_map(
            self._entry.options.get(OPT_TEACHER_ALIASES, DEFAULT_TEACHER_ALIASES)
        )

    def _optional_subjects_by_child(self) -> dict[str, Any]:
        value = self._entry.options.get(
            OPT_OPTIONAL_TIMETABLE_SUBJECTS_BY_CHILD,
            DEFAULT_OPTIONAL_TIMETABLE_SUBJECTS_BY_CHILD,
        )
        return value if isinstance(value, dict) else {}

    def _current_timetable(self) -> dict[str, Any]:
        timetables = (self.coordinator.data or {}).get("timetables", {}) or {}
        for name, timetable in timetables.items():
            if _decode_display_value(name) == self._child_display_name:
                return dict(timetable or {})
        return {}

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next event from the coordinator's current week."""
        now = datetime.now(_LOCAL_TIMEZONE)
        return next(
            (
                event
                for event in _timetable_events(
                    self._current_timetable(),
                    self._child_display_name,
                    self._subject_aliases(),
                    self._teacher_aliases(),
                    self._optional_subjects_by_child(),
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
                timetable = await self.coordinator.client.get_timetable_for_child(
                    self._child,
                    monday,
                )
            except ForaldreIntraError:
                monday += timedelta(days=7)
                continue

            events.extend(
                _timetable_events(
                    timetable,
                    self._child_display_name,
                    self._subject_aliases(),
                    self._teacher_aliases(),
                    self._optional_subjects_by_child(),
                )
            )
            monday += timedelta(days=7)

        return [
            event
            for event in sorted(events, key=lambda item: item.start)
            if _as_local_datetime(event.end) > range_start
            and _as_local_datetime(event.start) < range_end
        ]
