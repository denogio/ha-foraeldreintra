import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from custom_components.foraeldreintra.api import Child
from custom_components.foraeldreintra.calendar import (
    ForaeldreIntraTimetableCalendar,
    _timetable_events,
)


def test_timetable_events_marks_substitute_and_adds_description():
    timetable = {
        "lessons": [
            {
                "date": "2026-08-24",
                "start": "08:05",
                "end": "09:05",
                "subject": "Matematik",
                "has_substitute": True,
                "substitute_text": "Viggo Vikar er vikar for Frida Fraværende",
            }
        ]
    }

    events = _timetable_events(timetable, "Testbarn")

    assert len(events) == 1
    assert events[0].summary == "Matematik (vikar)"
    assert events[0].description == (
        "Barn: Testbarn\nViggo Vikar er vikar for Frida Fraværende"
    )
    assert events[0].start == datetime(
        2026, 8, 24, 8, 5, tzinfo=ZoneInfo("Europe/Copenhagen")
    )
    assert events[0].end == datetime(
        2026, 8, 24, 9, 5, tzinfo=ZoneInfo("Europe/Copenhagen")
    )


def test_calendar_fetches_each_week_in_requested_range():
    class FakeClient:
        def __init__(self):
            self.requested_dates = []

        async def get_timetable_for_child(self, child, week_date):
            self.requested_dates.append(week_date)
            return {
                "lessons": [
                    {
                        "date": week_date.isoformat(),
                        "start": "08:00",
                        "end": "09:00",
                        "subject": "Dansk",
                    }
                ]
            }

    client = FakeClient()
    coordinator = SimpleNamespace(client=client, data={"timetables": {}})
    entry = SimpleNamespace(entry_id="test-entry")
    entity = ForaeldreIntraTimetableCalendar(
        coordinator,
        entry,
        Child(id="123", name="Testbarn"),
    )

    events = asyncio.run(
        entity.async_get_events(
            SimpleNamespace(),
            datetime(2026, 8, 19, tzinfo=ZoneInfo("Europe/Copenhagen")),
            datetime(2026, 9, 1, tzinfo=ZoneInfo("Europe/Copenhagen")),
        )
    )

    assert client.requested_dates == [date(2026, 8, 17), date(2026, 8, 24), date(2026, 8, 31)]
    assert [event.start.date() for event in events] == [date(2026, 8, 24), date(2026, 8, 31)]


def test_timetable_events_skips_malformed_lessons_and_sorts_events():
    timetable = {
        "lessons": [
            {"date": "invalid", "start": "08:00", "end": "09:00", "subject": "Fejl"},
            {"date": "2026-08-25", "start": "10:00", "end": "11:00", "subject": "Dansk"},
            {"date": "2026-08-25", "start": "08:00", "end": "09:00", "subject": "Idræt"},
        ]
    }

    events = _timetable_events(timetable, "Testbarn")

    assert [event.summary for event in events] == ["Idræt", "Dansk"]
