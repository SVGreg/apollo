"""Text input strategies for iOS (design §6.4).

Typing goes through ``/wda/keys`` (XCTest ``typeText``: Unicode-safe, needs a
focused field). Clearing prefers the element ``clear`` endpoint on the active
element and falls back to deleting the current value character by character.
"""

from apollo.clients.wda_client import KEY_DELETE, WdaClient, WdaError
from apollo.utils.logger import get_logger

logger = get_logger(__name__)


async def _active_element(client: WdaClient) -> str | None:
    element_id = await client.active_element()
    if element_id:
        return element_id
    # Some keyboards report no active element; the focused text control usually
    # still resolves through a predicate.
    try:
        return await client.find_element(
            "predicate string",
            "type IN {'XCUIElementTypeTextField','XCUIElementTypeSecureTextField',"
            "'XCUIElementTypeSearchField','XCUIElementTypeTextView'} AND hasKeyboardFocus == 1",
        )
    except WdaError:
        return None


async def clear_focused_field(client: WdaClient) -> bool:
    element_id = await _active_element(client)
    if element_id is None:
        return False
    try:
        await client.element_clear(element_id)
        return True
    except WdaError as exc:
        logger.debug(f"element clear failed ({exc}); deleting by value length")
    try:
        value = await client.element_attribute(element_id, "value")
    except WdaError:
        value = None
    length = len(str(value)) if value else 0
    if length:
        await client.keys(KEY_DELETE * length)
    return True


async def type_text(client: WdaClient, text: str, *, clear_existing: bool) -> bool:
    if clear_existing:
        await clear_focused_field(client)
    if not text:
        return True
    try:
        await client.keys(text)
        return True
    except WdaError as exc:
        # Typical cause: no first responder. Try the direct value setter on a
        # resolvable text control before giving up.
        logger.debug(f"/wda/keys failed ({exc}); trying element value")
        element_id = await _active_element(client)
        if element_id is None:
            logger.warning("input_text: no focused text field on screen")
            return False
        try:
            await client.element_set_value(element_id, text)
            return True
        except WdaError as exc2:
            logger.error(f"input_text failed: {exc2}")
            return False


async def set_field_value(client: WdaClient, text: str) -> bool:
    """Long-text fallback: replace the focused field's value in one call."""
    element_id = await _active_element(client)
    if element_id is None:
        return False
    await client.element_set_value(element_id, text)
    return True
