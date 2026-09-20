"""Build image data URLs with the media type the bytes actually carry.

Android screencap and WDA both return PNG; a hard-coded ``image/jpeg`` label
is tolerated by Gemini but rejected by Anthropic (400: media type mismatch).
"""

_SIGNATURES = (
    ("iVBOR", "image/png"),
    ("/9j/", "image/jpeg"),
    ("R0lGO", "image/gif"),
    ("UklGR", "image/webp"),
)


def media_type_for_base64(b64: str, default: str = "image/jpeg") -> str:
    head = (b64 or "").lstrip()[:8]
    for prefix, media_type in _SIGNATURES:
        if head.startswith(prefix):
            return media_type
    return default


def image_data_url(b64: str) -> str:
    return f"data:{media_type_for_base64(b64)};base64,{b64}"
