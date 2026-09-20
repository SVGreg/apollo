"""Normalize WDA's XCUIElement page source into Artemis's UIAutomator-style hierarchy.

Everything above the driver (perception, OCR fusion, ``filter_ui_hierarchy``,
prompts, the console) consumes the Android ``<hierarchy><node …/></hierarchy>``
schema, so iOS trees are converted at the driver boundary and nothing upstream
changes. Geometry is converted from points to screenshot pixels with the
device scale so XML bounds line up with the PNG, exactly as on Android.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import quoteattr

TYPE_PREFIX = "XCUIElementType"

# Element types the Operator may tap. Mirrors what `clickable="true"` means on Android.
CLICKABLE_TYPES = frozenset(
    {
        "Button",
        "Cell",
        "Link",
        "Switch",
        "TextField",
        "SecureTextField",
        "SearchField",
        "TextView",
        "Icon",
        "Tab",
        "MenuItem",
        "MenuButton",
        "Key",
        "Slider",
        "Stepper",
        "SegmentedControl",
        "PickerWheel",
        "DatePicker",
        "CheckBox",
        "RadioButton",
        "PopUpButton",
        "ToolbarButton",
        "TabBar",
        "DisclosureTriangle",
        "Toggle",
    }
)

SCROLLABLE_TYPES = frozenset({"ScrollView", "Table", "CollectionView", "WebView", "TextView"})
TEXT_INPUT_TYPES = frozenset({"TextField", "SecureTextField", "SearchField", "TextView"})
# Pure structural wrappers; kept only when they carry an identifier or a label.
WRAPPER_TYPES = frozenset({"Window", "Other", "Group"})


@dataclass
class NormalizedHierarchy:
    xml: str
    elements: list[dict[str, Any]]
    node_count: int


def _short_type(tag: str) -> str:
    return tag[len(TYPE_PREFIX) :] if tag.startswith(TYPE_PREFIX) else tag


def _as_bool(value: str | None) -> bool:
    return (value or "").lower() == "true"


def _traits(node: ET.Element) -> set[str]:
    return {t.strip() for t in (node.get("traits") or "").split(",") if t.strip()}


def _px(value: str | None, scale: float) -> int:
    try:
        return int(round(float(value or 0) * scale))
    except ValueError:
        return 0


def _bounds(node: ET.Element, scale: float) -> tuple[int, int, int, int]:
    x = _px(node.get("x"), scale)
    y = _px(node.get("y"), scale)
    w = _px(node.get("width"), scale)
    h = _px(node.get("height"), scale)
    return x, y, x + w, y + h


def _visible_on_screen(b: tuple[int, int, int, int], width_px: int, height_px: int) -> bool:
    x1, y1, x2, y2 = b
    if x2 <= x1 or y2 <= y1:
        return False
    if x2 <= 0 or y2 <= 0:
        return False
    if width_px and x1 >= width_px:
        return False
    if height_px and y1 >= height_px:
        return False
    return True


def _resource_id(node: ET.Element, label: str) -> str:
    """WDA's ``name`` is the accessibility identifier when it differs from the label."""
    name = node.get("name") or ""
    return name if name and name != label else ""


def _node_attrs(
    node: ET.Element,
    *,
    scale: float,
    package: str,
    width_px: int,
    height_px: int,
    index: int,
) -> dict[str, str] | None:
    """Return UIAutomator attributes for one XCUIElement, or None to drop it."""
    stype = _short_type(node.tag)
    b = _bounds(node, scale)
    visible = _as_bool(node.get("visible"))
    if not _visible_on_screen(b, width_px, height_px):
        return None

    label = node.get("label") or ""
    value = node.get("value") or ""
    placeholder = node.get("placeholderValue") or ""
    traits = _traits(node)
    rid = _resource_id(node, label)

    # Structural wrappers without identity add nothing the filter cannot infer.
    if stype in WRAPPER_TYPES and not rid and not label and not value:
        return None

    if stype in TEXT_INPUT_TYPES:
        text = value or ""
        hint = placeholder or (label if not value else "")
    else:
        text = label or value
        hint = placeholder

    clickable = (
        stype in CLICKABLE_TYPES
        or "Button" in traits
        or "Link" in traits
        or "SearchField" in traits
    )
    attrs = {
        "index": str(index),
        "text": text,
        "resource-id": rid,
        "class": f"{TYPE_PREFIX}{stype}",
        "package": package,
        "content-desc": label if (label and label != text) else "",
        "checkable": "true" if stype in ("Switch", "Toggle", "CheckBox") else "false",
        "checked": "true"
        if (stype in ("Switch", "Toggle", "CheckBox") and value in ("1", "true"))
        else "false",
        "clickable": "true" if clickable else "false",
        "enabled": "false"
        if ("NotEnabled" in traits or not _as_bool(node.get("enabled")))
        else "true",
        "focusable": "true" if (clickable or stype in TEXT_INPUT_TYPES) else "false",
        "focused": "true" if node.get("focused") == "true" else "false",
        "scrollable": "true" if stype in SCROLLABLE_TYPES else "false",
        "long-clickable": "false",
        "password": "true" if stype == "SecureTextField" else "false",
        "selected": "true" if ("Selected" in traits or node.get("selected") == "true") else "false",
        "visible-to-user": "true" if visible else "false",
        "bounds": f"[{b[0]},{b[1]}][{b[2]},{b[3]}]",
    }
    if hint:
        attrs["hint"] = hint
    return attrs


def normalize_wda_source(
    source_xml: str,
    *,
    scale: float,
    width_px: int = 0,
    height_px: int = 0,
    package: str | None = None,
) -> NormalizedHierarchy:
    """Convert a WDA ``/source?format=xml`` document to UIAutomator XML + flat elements."""
    root = ET.fromstring(source_xml)
    bundle = package or root.get("bundleId") or ""
    if not width_px or not height_px:
        # Application node carries the full screen size in points.
        width_px = width_px or _px(root.get("width"), scale)
        height_px = height_px or _px(root.get("height"), scale)

    out: list[str] = ['<?xml version="1.0" encoding="UTF-8"?>', '<hierarchy rotation="0">']
    elements: list[dict[str, Any]] = []
    count = 0

    def walk(node: ET.Element, depth: int, sibling_index: int, parent_text: str) -> None:
        nonlocal count
        attrs = _node_attrs(
            node,
            scale=scale,
            package=bundle,
            width_px=width_px,
            height_px=height_px,
            index=sibling_index,
        )
        children = list(node)
        if attrs is None:
            # Dropped wrapper: splice its children into the parent level.
            for i, child in enumerate(children):
                walk(child, depth, i, parent_text)
            return
        # XCTest synthesizes a Cell/Button label from its children, so the same
        # text would appear twice (row + StaticText). Keep the tappable row only.
        if (
            not children
            and _short_type(node.tag) == "StaticText"
            and parent_text
            and attrs["text"]
            and attrs["text"] in parent_text
        ):
            return
        count += 1
        attr_text = " ".join(f"{k}={quoteattr(v)}" for k, v in attrs.items())
        own_text = attrs["text"] if attrs["clickable"] == "true" else ""
        if children:
            out.append(f"{'  ' * depth}<node {attr_text}>")
            for i, child in enumerate(children):
                walk(child, depth + 1, i, own_text)
            out.append(f"{'  ' * depth}</node>")
        else:
            out.append(f"{'  ' * depth}<node {attr_text} />")
        elements.append(_element_dict(attrs))

    walk(root, 1, 0, "")
    out.append("</hierarchy>")
    return NormalizedHierarchy(xml="\n".join(out), elements=elements, node_count=count)


_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def _element_dict(attrs: dict[str, str]) -> dict[str, Any]:
    """Flat element record in the shape ``_parse_hierarchy_xml_to_elements`` produces."""
    element: dict[str, Any] = dict(attrs)
    if attrs.get("content-desc"):
        element["accessibilityText"] = attrs["content-desc"]
    m = _BOUNDS_RE.match(attrs["bounds"])
    if m:
        x1, y1, x2, y2 = map(int, m.groups())
        element["parsed_bounds"] = {"left": x1, "top": y1, "right": x2, "bottom": y2}
        element["center"] = [(x1 + x2) // 2, (y1 + y2) // 2]
    return element
