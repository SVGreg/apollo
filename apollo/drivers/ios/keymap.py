"""Map Artemis key names onto iOS gestures and WDA calls.

iOS has no system BACK or APP_SWITCH key: BACK taps the navigation-bar back
control (or edge-swipes when there is none) and APP_SWITCH is the home-indicator
swipe-and-hold. HOME/lock/volume go through ``/wda/pressButton``; ENTER and
DELETE are typed as XCTest special characters.
"""

import asyncio

from apollo.clients.wda_client import KEY_DELETE, KEY_RETURN, WdaClient, WdaError
from apollo.utils.logger import get_logger

logger = get_logger(__name__)

# Buttons WDA's /wda/pressButton accepts. Lock/volume only make sense on devices.
PRESS_BUTTON = {
    "home": "home",
    "power": "lock",
    "lock": "lock",
    "volume_up": "volumeUp",
    "volume_down": "volumeDown",
}

TYPED_KEYS = {
    "enter": KEY_RETURN,
    "return": KEY_RETURN,
    "delete": KEY_DELETE,
    "backspace": KEY_DELETE,
    "del": KEY_DELETE,
}

# Ordered predicates for the navigation-bar back control.
_BACK_PREDICATES = (
    "type == 'XCUIElementTypeButton' AND name == 'Back'",
    "type == 'XCUIElementTypeButton' AND label == 'Back'",
    "type == 'XCUIElementTypeButton' AND name == 'BackButton'",
    "type == 'XCUIElementTypeButton' AND name BEGINSWITH 'Back'",
    "type == 'XCUIElementTypeButton' AND (label BEGINSWITH 'Back' OR label == 'Cancel' OR label == 'Close' OR label == 'Done')",
)


def normalize_key(key: object) -> str:
    """'KeyCode.BACK' / 'BACK' / KeyCode.BACK → 'back'."""
    name = str(key).lower()
    if name.startswith("keycode."):
        name = name[len("keycode.") :]
    return name.strip()


async def press_back(client: WdaClient, *, width_pt: int, height_pt: int) -> bool:
    """Navigation-bar back button first, edge swipe otherwise."""
    for predicate in _BACK_PREDICATES:
        try:
            element_id = await client.find_element("predicate string", predicate)
        except WdaError as exc:
            logger.debug(f"back lookup failed for {predicate!r}: {exc}")
            continue
        if element_id:
            try:
                await client.element_click(element_id)
                return True
            except WdaError as exc:
                logger.debug(f"back button click failed: {exc}")
    # Interactive pop gesture from the left screen edge.
    await client.drag(2, height_pt * 0.5, width_pt * 0.45, height_pt * 0.5, duration_ms=300)
    return True


async def open_app_switcher(client: WdaClient, *, width_pt: int, height_pt: int) -> bool:
    """Swipe up from the home indicator and hold."""
    x = width_pt / 2
    steps = [
        {"type": "pointerMove", "duration": 0, "x": x, "y": height_pt - 1},
        {"type": "pointerDown", "button": 0},
        {"type": "pointerMove", "duration": 350, "x": x, "y": height_pt * 0.5},
        {"type": "pause", "duration": 700},
        {"type": "pointerUp", "button": 0},
    ]
    await client.post("/actions", json=WdaClient._pointer_actions(steps))
    return True


async def press_key(client: WdaClient, key: object, *, width_pt: int, height_pt: int) -> bool:
    name = normalize_key(key)
    if name == "back":
        return await press_back(client, width_pt=width_pt, height_pt=height_pt)
    if name in ("app_switch", "recent", "recents"):
        return await open_app_switcher(client, width_pt=width_pt, height_pt=height_pt)
    if name in TYPED_KEYS:
        await client.keys(TYPED_KEYS[name])
        return True
    if name in PRESS_BUTTON:
        await client.press_button(PRESS_BUTTON[name])
        if name == "home":
            await asyncio.sleep(0.5)  # activeAppInfo lags the Springboard transition
        return True
    logger.warning(f"Unsupported key on iOS: {key!r}")
    return False
