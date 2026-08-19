import asyncio

from custom_components.foraeldreintra.api import Child
from custom_components.foraeldreintra.coordinator import ForaldreIntraCoordinator


class EmptyHomeworkClient:
    def __init__(self):
        self.login_calls = 0
        self.homework_calls = 0
        self.children = [Child(id="123", name="Test Barn", path_name="Test_Barn")]

    async def get_children(self):
        return self.children

    async def get_homework_for_children(self, children):
        self.homework_calls += 1
        return []

    async def get_weekplans_for_children(self, children):
        return {"Test Barn": {"week": "34-2026"}}

    async def get_timetables_for_children(self, children):
        return {"Test Barn": {"week": "34-2026"}}

    async def login(self):
        self.login_calls += 1


def _coordinator_with_previous_homework():
    coordinator = object.__new__(ForaldreIntraCoordinator)
    coordinator.client = EmptyHomeworkClient()
    coordinator._last_good_data = {
        "children": [{"id": "123", "name": "Test Barn"}],
        "items": [{"barn": "Test Barn", "fag": "Dansk", "tekst": "Læs"}],
        "weeklyplans": {},
        "timetables": {},
    }
    coordinator._consecutive_empty_homework_updates = 0
    return coordinator


def test_first_unexpected_empty_homework_update_retries_and_preserves_previous_items():
    coordinator = _coordinator_with_previous_homework()

    result = asyncio.run(coordinator._fetch_children_and_homework())

    assert coordinator.client.login_calls == 1
    assert coordinator.client.homework_calls == 2
    assert result["items"] == coordinator._last_good_data["items"]
    assert coordinator._consecutive_empty_homework_updates == 1


def test_second_confirmed_empty_homework_update_is_accepted():
    coordinator = _coordinator_with_previous_homework()
    coordinator._consecutive_empty_homework_updates = 1

    result = asyncio.run(coordinator._fetch_children_and_homework())

    assert result["items"] == []
    assert coordinator._consecutive_empty_homework_updates == 2
