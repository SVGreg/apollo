"""iOS hierarchy normalizer: WDA /source XML → UIAutomator schema Artemis consumes."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from apollo.drivers.ios.hierarchy import normalize_wda_source
from apollo.utils.ui_filter import filter_ui_hierarchy
from apollo.utils.visualization import format_minimal_list_with_elements

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "wda_source"
SCALE, WIDTH, HEIGHT = 3, 1206, 2622

EXPECTED_TEXTS = {
    "settings_root": {"General", "Accessibility", "Action Button"},
    "settings_general_about": {"About", "Name, iPhone", "iOS Version, 26.2"},
    "safari_start": {"Favorites", "Customize Start Page"},
    "iosworld_clock": set(),
    "iosworld_notes": {"Folders", "Edit"},
    "iosworld_weather": set(),
}


@pytest.mark.parametrize("name", sorted(EXPECTED_TEXTS))
def test_fixture_normalizes_into_uiautomator_schema(name: str):
    source = (FIXTURES / f"{name}.xml").read_text(encoding="utf-8")
    result = normalize_wda_source(source, scale=SCALE, width_px=WIDTH, height_px=HEIGHT)

    root = ET.fromstring(result.xml)
    assert root.tag == "hierarchy"
    nodes = list(root.iter("node"))
    assert nodes and len(nodes) == result.node_count == len(result.elements)

    for node in nodes:
        # The attribute set the Android parser, ui_filter and prompts rely on.
        for attr in ("class", "text", "bounds", "clickable", "enabled", "package", "resource-id"):
            assert attr in node.attrib, f"{name}: node missing {attr}"
        assert node.attrib["class"].startswith("XCUIElementType")
        x1, y1, x2, y2 = _bounds(node.attrib["bounds"])
        assert x2 > x1 and y2 > y1, f"{name}: zero-area node survived"
        assert x1 < WIDTH and y1 < HEIGHT, f"{name}: off-screen node survived"

    texts = {el["text"] for el in result.elements}
    missing = EXPECTED_TEXTS[name] - texts
    assert not missing, f"{name}: expected texts not found: {missing}"


def test_geometry_is_scaled_to_pixels_and_package_is_bundle_id():
    source = (FIXTURES / "settings_root.xml").read_text(encoding="utf-8")
    result = normalize_wda_source(source, scale=SCALE, width_px=WIDTH, height_px=HEIGHT)
    general = next(el for el in result.elements if el["text"] == "General")
    # 402pt-wide screen → 1206px; a full-width row spans most of it.
    assert general["parsed_bounds"]["right"] - general["parsed_bounds"]["left"] > 1000
    assert general["clickable"] == "true"
    assert general["package"] == "com.apple.Preferences"
    assert general["center"] == [
        (general["parsed_bounds"]["left"] + general["parsed_bounds"]["right"]) // 2,
        (general["parsed_bounds"]["top"] + general["parsed_bounds"]["bottom"]) // 2,
    ]


def test_row_labels_are_not_duplicated_by_child_static_text():
    source = (FIXTURES / "settings_root.xml").read_text(encoding="utf-8")
    result = normalize_wda_source(source, scale=SCALE, width_px=WIDTH, height_px=HEIGHT)
    assert [el["text"] for el in result.elements].count("General") == 1


def test_text_fields_expose_value_and_placeholder():
    source = (FIXTURES / "safari_start.xml").read_text(encoding="utf-8")
    result = normalize_wda_source(source, scale=SCALE, width_px=WIDTH, height_px=HEIGHT)
    fields = [el for el in result.elements if el["class"].endswith(("TextField", "SearchField"))]
    assert fields, "Safari start page has an address/search field"
    assert all(el["focusable"] == "true" for el in fields)


@pytest.mark.parametrize("name", ["settings_root", "iosworld_notes"])
def test_artemis_perception_pipeline_accepts_normalized_elements(name: str):
    """filter → minimal list is what the Operator reads; it must not choke or go empty."""
    source = (FIXTURES / f"{name}.xml").read_text(encoding="utf-8")
    result = normalize_wda_source(source, scale=SCALE, width_px=WIDTH, height_px=HEIGHT)
    filtered = filter_ui_hierarchy(result.elements, screen_width=WIDTH, screen_height=HEIGHT)
    text, listed, _ = format_minimal_list_with_elements(filtered, WIDTH, HEIGHT)
    assert len(listed) >= 10
    assert "[1] Text:" in text


def _bounds(value: str) -> tuple[int, int, int, int]:
    left, right = value.split("][")
    x1, y1 = left.strip("[]").split(",")
    x2, y2 = right.strip("[]").split(",")
    return int(x1), int(y1), int(x2), int(y2)
