"""Async HTTP client for WebDriverAgent (the on-device runner, Apollo's Helper analog).

WDA speaks W3C WebDriver JSON over HTTP. All geometry here is in *points*; the
driver converts from screenshot pixels before calling in. One long-lived session
per runner; it is transparently re-created when WDA reports it invalid.
"""

import asyncio
import base64
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from apollo.utils.logger import get_logger

logger = get_logger(__name__)

# WDA calls are chatty (several per agent step); keep httpx request logging out of the console.
logging.getLogger("httpx").setLevel(logging.WARNING)

DEFAULT_TIMEOUT = 30.0
SOURCE_TIMEOUT = 20.0

# Keys WDA's /wda/keys understands as special characters (XCUIKeyboardKey* constants).
KEY_RETURN = "\n"
KEY_DELETE = "\b"


class WdaError(RuntimeError):
    """Raised for transport failures or WebDriver error responses."""

    def __init__(self, message: str, *, status: int | None = None, error: str | None = None):
        super().__init__(message)
        self.status = status
        self.error = error


@dataclass
class ScreenInfo:
    width_pt: int
    height_pt: int
    scale: int
    status_bar_height_pt: int

    @property
    def width_px(self) -> int:
        return self.width_pt * self.scale

    @property
    def height_px(self) -> int:
        return self.height_pt * self.scale


@dataclass
class ActiveApp:
    bundle_id: str
    pid: int | None
    name: str | None


def _value(resp: httpx.Response) -> Any:
    try:
        payload = resp.json()
    except ValueError:
        raise WdaError(
            f"non-JSON response ({resp.status_code}): {resp.text[:200]}", status=resp.status_code
        ) from None
    value = payload.get("value") if isinstance(payload, dict) else payload
    if resp.status_code >= 400 or (
        isinstance(value, dict) and "error" in value and "message" in value
    ):
        err = value.get("error") if isinstance(value, dict) else None
        msg = value.get("message") if isinstance(value, dict) else resp.text[:200]
        raise WdaError(f"{err or resp.status_code}: {msg}", status=resp.status_code, error=err)
    return value


class WdaClient:
    def __init__(self, base_url: str, *, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)
        self._session_id: str | None = None
        self._session_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    # ----------------------------------------------------------------- session

    @property
    def session_id(self) -> str | None:
        return self._session_id

    async def status(self, *, timeout: float = 3.0) -> dict[str, Any]:
        resp = await self._client.get("/status", timeout=timeout)
        return _value(resp)

    async def is_ready(self) -> bool:
        try:
            return bool((await self.status()).get("ready", True))
        except Exception:
            return False

    async def ensure_session(self) -> str:
        if self._session_id:
            return self._session_id
        async with self._session_lock:
            if self._session_id:
                return self._session_id
            resp = await self._client.post(
                "/session",
                json={"capabilities": {"alwaysMatch": {"platformName": "iOS"}}},
                timeout=60.0,
            )
            value = _value(resp)
            self._session_id = value["sessionId"]
            logger.debug(f"WDA session created: {self._session_id}")
            return self._session_id

    async def _request(self, method: str, path: str, *, retry: bool = True, **kwargs) -> Any:
        """Session-scoped request; recreates the session once on invalid-session errors."""
        sid = await self.ensure_session()
        resp = await self._client.request(method, f"/session/{sid}{path}", **kwargs)
        try:
            return _value(resp)
        except WdaError as exc:
            invalid = exc.error == "invalid session id" or (
                resp.status_code == 404 and "session" in (exc.args[0] or "").lower()
            )
            if invalid and retry:
                logger.warning("WDA session invalid; recreating")
                self._session_id = None
                return await self._request(method, path, retry=False, **kwargs)
            raise

    async def get(self, path: str, **kwargs) -> Any:
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, json: Any | None = None, **kwargs) -> Any:
        return await self._request("POST", path, json=json if json is not None else {}, **kwargs)

    # --------------------------------------------------------------- perception

    async def screen_info(self) -> ScreenInfo:
        value = await self.get("/wda/screen")
        size = value.get("screenSize") or {}
        bar = value.get("statusBarSize") or {}
        return ScreenInfo(
            width_pt=int(size.get("width", 0)),
            height_pt=int(size.get("height", 0)),
            scale=int(value.get("scale", 1) or 1),
            status_bar_height_pt=int(bar.get("height", 0)),
        )

    async def source(self, *, fmt: str = "xml") -> str:
        return await self.get("/source", params={"format": fmt}, timeout=SOURCE_TIMEOUT)

    async def screenshot(self) -> bytes:
        return base64.b64decode(await self.get("/screenshot"))

    async def screenshot_base64(self) -> str:
        return await self.get("/screenshot")

    async def active_app(self) -> ActiveApp:
        value = await self.get("/wda/activeAppInfo")
        return ActiveApp(
            bundle_id=value.get("bundleId", ""), pid=value.get("pid"), name=value.get("name")
        )

    async def set_settings(self, **settings: Any) -> dict[str, Any]:
        return await self.post("/appium/settings", json={"settings": settings})

    async def get_settings(self) -> dict[str, Any]:
        return await self.get("/appium/settings")

    # --------------------------------------------------------------- app lifecycle

    async def launch_app(self, bundle_id: str, *, wait_active: float = 10.0) -> bool:
        await self.post("/wda/apps/launch", json={"bundleId": bundle_id})
        return await self.wait_for_active(bundle_id, timeout=wait_active)

    async def activate_app(self, bundle_id: str) -> None:
        await self.post("/wda/apps/activate", json={"bundleId": bundle_id})

    async def terminate_app(self, bundle_id: str) -> bool:
        value = await self.post("/wda/apps/terminate", json={"bundleId": bundle_id})
        return bool(value) if isinstance(value, bool) else True

    async def app_state(self, bundle_id: str) -> int:
        """0 unknown, 1 not running, 2 background suspended, 3 background, 4 foreground."""
        return int(await self.post("/wda/apps/state", json={"bundleId": bundle_id}) or 0)

    async def wait_for_active(self, bundle_id: str, *, timeout: float = 10.0) -> bool:
        """After launch, /source may still describe Springboard; wait until the app is frontmost."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if (await self.active_app()).bundle_id == bundle_id:
                    return True
            except WdaError:
                pass
            await asyncio.sleep(0.25)
        return False

    async def open_url(self, url: str) -> None:
        await self.post("/url", json={"url": url})

    # --------------------------------------------------------------- input (points)

    @staticmethod
    def _pointer_actions(steps: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "actions": [
                {
                    "type": "pointer",
                    "id": "finger1",
                    "parameters": {"pointerType": "touch"},
                    "actions": steps,
                }
            ]
        }

    async def tap(self, x: float, y: float, *, duration_ms: int = 100) -> None:
        steps = [
            {"type": "pointerMove", "duration": 0, "x": x, "y": y},
            {"type": "pointerDown", "button": 0},
            {"type": "pause", "duration": max(duration_ms, 1)},
            {"type": "pointerUp", "button": 0},
        ]
        await self.post("/actions", json=self._pointer_actions(steps))

    async def multi_tap(self, x: float, y: float, *, times: int, delay_ms: int = 100) -> None:
        steps: list[dict[str, Any]] = [{"type": "pointerMove", "duration": 0, "x": x, "y": y}]
        for i in range(times):
            steps += [
                {"type": "pointerDown", "button": 0},
                {"type": "pause", "duration": 50},
                {"type": "pointerUp", "button": 0},
            ]
            if i < times - 1:
                steps.append({"type": "pause", "duration": max(delay_ms, 1)})
        await self.post("/actions", json=self._pointer_actions(steps))

    async def long_press(self, x: float, y: float, *, duration_ms: int = 1000) -> None:
        await self.tap(x, y, duration_ms=duration_ms)

    async def drag(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        duration_ms: int = 800,
        hold_ms: int = 50,
    ) -> None:
        steps = [
            {"type": "pointerMove", "duration": 0, "x": x1, "y": y1},
            {"type": "pointerDown", "button": 0},
            {"type": "pause", "duration": hold_ms},
            {"type": "pointerMove", "duration": max(duration_ms, 1), "x": x2, "y": y2},
            {"type": "pointerUp", "button": 0},
        ]
        await self.post("/actions", json=self._pointer_actions(steps))

    async def keys(self, text: str) -> None:
        """Type into the focused element (XCTest typeText; Unicode OK; "\\n" Return, "\\b" Delete)."""
        await self.post("/wda/keys", json={"value": [text]})

    async def press_button(self, name: str, *, duration: float | None = None) -> None:
        payload: dict[str, Any] = {"name": name}
        if duration is not None:
            payload["duration"] = duration
        await self.post("/wda/pressButton", json=payload)

    # --------------------------------------------------------------- elements

    async def find_element(self, using: str, value: str) -> str | None:
        try:
            found = await self.post("/element", json={"using": using, "value": value})
        except WdaError as exc:
            if exc.error == "no such element" or exc.status == 404:
                return None
            raise
        return found.get("ELEMENT") or found.get("element-6066-11e4-a52e-4f735466cecf")

    async def find_elements(self, using: str, value: str) -> list[str]:
        found = await self.post("/elements", json={"using": using, "value": value})
        return [e.get("ELEMENT") or e.get("element-6066-11e4-a52e-4f735466cecf") for e in found]

    async def active_element(self) -> str | None:
        try:
            found = await self.get("/element/active")
        except WdaError:
            return None
        return found.get("ELEMENT") or found.get("element-6066-11e4-a52e-4f735466cecf")

    async def element_click(self, element_id: str) -> None:
        await self.post(f"/element/{element_id}/click")

    async def element_clear(self, element_id: str) -> None:
        await self.post(f"/element/{element_id}/clear")

    async def element_set_value(self, element_id: str, value: str) -> None:
        await self.post(f"/element/{element_id}/value", json={"value": [value]})

    async def element_attribute(self, element_id: str, name: str) -> Any:
        return await self.get(f"/element/{element_id}/attribute/{name}")

    # --------------------------------------------------------------- alerts / pasteboard

    async def alert_text(self) -> str | None:
        try:
            return await self.get("/alert/text")
        except WdaError:
            return None

    async def alert_accept(self) -> None:
        await self.post("/alert/accept")

    async def alert_dismiss(self) -> None:
        await self.post("/alert/dismiss")

    async def set_pasteboard(self, text: str) -> None:
        await self.post(
            "/wda/setPasteboard",
            json={"content": base64.b64encode(text.encode()).decode(), "contentType": "plaintext"},
        )
