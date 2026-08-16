from custom_components.foraeldreintra.api import Child


def test_child_uses_preserved_path_name_for_urls():
    child = Child(
        id="123",
        name="Alva Højgaard",
        path_name="Alva_H%C3%B8jgaard",
    )
    assert child.url_name == "Alva_H%C3%B8jgaard"


def test_child_builds_encoded_url_name_from_display_name():
    child = Child(id="123", name="Alva Højgaard")
    assert child.url_name == "Alva_H%C3%B8jgaard"
