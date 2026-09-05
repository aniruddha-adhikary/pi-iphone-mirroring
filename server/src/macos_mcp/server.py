"""iPhone Mirroring MCP server with vision-model-friendly coordinates.

The exposed tools target only Apple's iPhone Mirroring app. Point coordinates
use a normalized 0..1000 space on both axes, matching the convention commonly
used by visual-grounding models. Screenshots include a faint 100-unit grid.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import time
from typing import Annotated, Literal

from mcp.server.mcpserver import Image, MCPServer
from pydantic import Field

from macos_harness.macos import MacOS

from . import primitives

IPHONE_APP = "iPhone Mirroring"
TOOL_PROFILE = os.environ.get("IPHONE_TOOL_PROFILE", "grid").strip().lower()
COORD_MIN = 0.0
COORD_MAX = 1000.0
Coord = Annotated[
    float,
    Field(
        ge=COORD_MIN,
        le=COORD_MAX,
        description="Normalized 0..1000 coordinate; not a screenshot pixel",
    ),
]
ScrollAmount = Annotated[
    int,
    Field(
        ge=-1000,
        le=1000,
        description="Normalized distance; positive moves down or right",
    ),
]
Occurrence = Annotated[int, Field(ge=1, description="1-based matching-text occurrence")]

server = MCPServer(
    "macos",
    instructions=(
        "Control only the iPhone Mirroring app. Call see_iphone before acting. "
        "All point coordinates are normalized independently from 0 to 1000: "
        "(0,0) is the screenshot's top-left and (1000,1000) is its bottom-right. "
        "Use the screenshot's labeled 100-unit grid; never use screenshot pixels "
        "or macOS screen coordinates. Tap a text field before typing; use key_iphone "
        "for select-all or Return. Action tools return a fresh screenshot for "
        "immediate verification. In WeChat chats, negative vertical scroll moves "
        "to older messages and positive moves to newer messages; anchor on plain "
        "chat background rather than a message bubble."
    ),
)

# One serialized session: cursor-warping input must not interleave.
_mac: MacOS | None = None
_lock = threading.Lock()


def _session() -> MacOS:
    global _mac
    if _mac is None:
        _mac = MacOS()
    return _mac


def _validate_coord(name: str, value: float) -> float:
    value = float(value)
    if not COORD_MIN <= value <= COORD_MAX:
        raise ValueError(
            f"{name} must be a normalized coordinate from 0 to 1000; got {value:g}"
        )
    return value


def _to_pixels(frame: dict, x: float, y: float) -> tuple[float, float]:
    """Convert normalized model coordinates to screenshot-pixel coordinates."""
    x = _validate_coord("x", x)
    y = _validate_coord("y", y)
    return x * frame["width"] / 1000.0, y * frame["height"] / 1000.0


def _hid_command(keycode: int) -> None:
    """Post a real Command chord; Mirroring ignores modifier flags alone."""
    import Quartz

    command_keycode = 55

    def post(code: int, down: bool, flags: int) -> None:
        event = Quartz.CGEventCreateKeyboardEvent(None, code, down)
        Quartz.CGEventSetFlags(event, flags)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        time.sleep(0.06)

    flags = Quartz.kCGEventFlagMaskCommand
    post(command_keycode, True, flags)
    post(keycode, True, flags)
    post(keycode, False, flags)
    post(command_keycode, False, 0)


def _type_text(mac: MacOS, text: str) -> None:
    """Type ASCII directly and paste Unicode through native NSPasteboard."""
    if text.isascii():
        mac.type(text, app=IPHONE_APP)
        return

    from AppKit import NSPasteboard, NSPasteboardTypeString

    pasteboard = NSPasteboard.generalPasteboard()
    previous = pasteboard.stringForType_(NSPasteboardTypeString)
    pasteboard.clearContents()
    if not pasteboard.setString_forType_(text, NSPasteboardTypeString):
        raise RuntimeError("failed to write text to the macOS pasteboard")
    try:
        time.sleep(0.4)
        _hid_command(9)  # V
        # iPhone Mirroring may consume the pasteboard asynchronously under load.
        # Keep the Unicode payload available until the remote paste completes.
        time.sleep(1.2)
    finally:
        pasteboard.clearContents()
        if previous is not None:
            pasteboard.setString_forType_(previous, NSPasteboardTypeString)


def _fresh_frame(mac: MacOS, activate: bool = False) -> dict:
    frame = mac.see(IPHONE_APP, window_index=0, show_pointer=False)
    if activate:
        primitives.activate(frame)
        frame = mac.see(IPHONE_APP, window_index=0, show_pointer=False)
    return frame


def _see_bytes(mac: MacOS) -> tuple[dict, bytes]:
    fd, path = tempfile.mkstemp(suffix=".png", prefix="macos_mcp_")
    os.close(fd)
    try:
        frame = mac.see(
            IPHONE_APP, window_index=0, path=path, show_pointer=False
        )
        with open(path, "rb") as fh:
            data = fh.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return frame, data


def _grid_image(
    data: bytes,
    viewport: tuple[float, float, float, float] = (0, 0, 1000, 1000),
    marker: tuple[float, float] | None = None,
) -> bytes:
    """Crop and overlay global normalized coordinates without changing semantics."""
    from PIL import Image as PILImage, ImageDraw, ImageFont

    source = PILImage.open(io.BytesIO(data)).convert("RGBA")
    source_width, source_height = source.size
    left, top, right, bottom = viewport
    crop_box = (
        round(left * source_width / 1000),
        round(top * source_height / 1000),
        round(right * source_width / 1000),
        round(bottom * source_height / 1000),
    )
    image = source.crop(crop_box)
    width, height = image.size
    overlay = PILImage.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.load_default(size=14)

    line = (0, 180, 255, 80)
    major_line = (255, 170, 0, 110)
    label_bg = (0, 0, 0, 175)
    label_fg = (255, 255, 255, 240)

    def local_x(value: float) -> float:
        return (value - left) * width / (right - left)

    def local_y(value: float) -> float:
        return (value - top) * height / (bottom - top)

    for n in range(0, 1001, 100):
        if left <= n <= right:
            x = round(local_x(n))
            draw.line((x, 0, x, height), fill=major_line if n % 200 == 0 else line, width=1)
            if 0 < x < width:
                text = str(n)
                box = draw.textbbox((0, 0), text, font=font)
                text_width = box[2] - box[0]
                draw.rectangle((x - text_width / 2 - 2, 2, x + text_width / 2 + 2, 20), fill=label_bg)
                draw.text((x - text_width / 2, 3), text, fill=label_fg, font=font)
        if top <= n <= bottom:
            y = round(local_y(n))
            draw.line((0, y, width, y), fill=major_line if n % 200 == 0 else line, width=1)
            if 0 < y < height:
                text = str(n)
                box = draw.textbbox((0, 0), text, font=font)
                text_width = box[2] - box[0]
                draw.rectangle((2, y - 9, text_width + 6, y + 9), fill=label_bg)
                draw.text((4, y - 8), text, fill=label_fg, font=font)

    if marker is not None and left <= marker[0] <= right and top <= marker[1] <= bottom:
        mx, my = local_x(marker[0]), local_y(marker[1])
        radius = 12
        draw.ellipse((mx - radius, my - radius, mx + radius, my + radius), outline=(255, 30, 30, 255), width=4)
        draw.line((mx - 18, my, mx + 18, my), fill=(255, 30, 30, 255), width=2)
        draw.line((mx, my - 18, mx, my + 18), fill=(255, 30, 30, 255), width=2)

    output = io.BytesIO()
    PILImage.alpha_composite(image, overlay).convert("RGB").save(output, "PNG")
    return output.getvalue()


def _recognized_text(data: bytes) -> list[dict]:
    """Run Apple Vision OCR and return top-left normalized bounding boxes."""
    from Foundation import NSData
    import Vision

    nsdata = NSData.dataWithBytes_length_(data, len(data))
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setRecognitionLanguages_(["zh-Hans", "zh-Hant", "en-US"])
    request.setUsesLanguageCorrection_(True)
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(nsdata, {})
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f"Apple Vision OCR failed: {error}")

    results = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if not candidates:
            continue
        candidate = candidates[0]
        bounds = observation.boundingBox()
        x1 = bounds.origin.x * 1000
        x2 = (bounds.origin.x + bounds.size.width) * 1000
        y1 = (1 - bounds.origin.y - bounds.size.height) * 1000
        y2 = (1 - bounds.origin.y) * 1000
        results.append(
            {
                "text": str(candidate.string()),
                "confidence": round(float(candidate.confidence()), 3),
                "box": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                "center": [round((x1 + x2) / 2, 1), round((y1 + y2) / 2, 1)],
            }
        )
    return sorted(results, key=lambda item: (item["box"][1], item["box"][0]))


def _text_matches(data: bytes, query: str) -> list[dict]:
    needle = "".join(query.casefold().split())
    if not needle:
        raise ValueError("query must not be empty")
    return [
        item
        for item in _recognized_text(data)
        if needle in "".join(item["text"].casefold().split())
    ]


def _post_action_result(
    mac: MacOS,
    before: bytes,
    marker: tuple[float, float] | None,
    metadata: dict,
    settle: float = 0.6,
) -> list:
    time.sleep(settle)
    _, after = _see_bytes(mac)
    difference = round(_content_diff(before, after), 2)
    metadata.update({"difference": difference, "visible_change": difference >= 1.0})
    return [
        Image(data=_present_image(after, marker=marker), format="png"),
        json.dumps(metadata, ensure_ascii=False),
    ]


def _present_image(
    data: bytes,
    viewport: tuple[float, float, float, float] = (0, 0, 1000, 1000),
    marker: tuple[float, float] | None = None,
) -> bytes:
    """Apply profile-specific visual aids to an outgoing screenshot."""
    if TOOL_PROFILE == "normalized" and viewport == (0, 0, 1000, 1000):
        return data
    return _grid_image(data, viewport=viewport, marker=marker)


def _content_diff(before: bytes, after: bytes) -> float:
    """Mean per-channel pixel difference over the main content region."""
    from PIL import Image as PILImage, ImageChops

    a = PILImage.open(io.BytesIO(before)).convert("RGB")
    b = PILImage.open(io.BytesIO(after)).convert("RGB")
    if a.size != b.size:
        return 999.0
    width, height = a.size
    box = (
        int(width * 0.03),
        int(height * 0.06),
        int(width * 0.97),
        int(height * 0.96),
    )
    difference = ImageChops.difference(a.crop(box), b.crop(box))
    histogram = difference.histogram()
    total = sum(i * histogram[i] for i in range(256))
    total += sum(i * histogram[256 + i] for i in range(256))
    total += sum(i * histogram[512 + i] for i in range(256))
    pixels = (box[2] - box[0]) * (box[3] - box[1]) * 3
    return total / pixels if pixels else 0.0


# Fractions tried when a vertical gesture lands on an inner horizontal carousel.
_VERTICAL_ANCHORS = [
    (0.12, 0.24),
    (0.12, 0.36),
    (0.12, 0.60),
    (0.12, 0.82),
    (0.50, 0.48),
    (0.50, 0.72),
    (0.88, 0.50),
]
_MOVE_THRESHOLD = 4.0


@server.tool()
def see_iphone() -> list:
    """Capture iPhone Mirroring with a labeled normalized 0..1000 grid.

    Use the grid to estimate targets. Origin is top-left; x increases right and
    y increases down. Coordinates are normalized, not screenshot pixels.
    """
    with _lock:
        frame, data = _see_bytes(_session())
    metadata = {
        "coordinate_space": {"x": [0, 1000], "y": [0, 1000]},
        "origin": "top-left",
        "screenshot_pixels": [frame["width"], frame["height"]],
        "target": IPHONE_APP,
        "tool_profile": TOOL_PROFILE,
        "target_is_frontmost": frame["focus"]["target_is_frontmost"],
    }
    return [Image(data=_present_image(data), format="png"), json.dumps(metadata)]


@server.tool()
def inspect_iphone(region: Literal["top", "middle", "bottom"]) -> list:
    """Return an enlarged vertical region while preserving global coordinates."""
    viewports = {
        "top": (0, 0, 1000, 400),
        "middle": (0, 300, 1000, 700),
        "bottom": (0, 600, 1000, 1000),
    }
    viewport = viewports[region]
    with _lock:
        frame, data = _see_bytes(_session())
    metadata = {
        "region": region,
        "viewport": viewport,
        "coordinate_space": "global normalized 0..1000",
        "screenshot_pixels": [frame["width"], frame["height"]],
    }
    return [Image(data=_present_image(data, viewport=viewport), format="png"), json.dumps(metadata)]


@server.tool()
def find_text(query: str) -> str:
    """Find visible iPhone text with Apple Vision OCR; return normalized boxes."""
    with _lock:
        _, data = _see_bytes(_session())
        matches = _text_matches(data, query)
    return json.dumps({"query": query, "count": len(matches), "matches": matches}, ensure_ascii=False)


@server.tool()
def tap_text(query: str, occurrence: Occurrence = 1) -> list:
    """Find visible text and tap its center; occurrence is 1-based reading order."""
    with _lock:
        mac = _session()
        _fresh_frame(mac, activate=True)
        frame, before = _see_bytes(mac)
        matches = _text_matches(before, query)
        if not matches:
            raise ValueError(f"visible text not found: {query!r}")
        if occurrence > len(matches):
            raise ValueError(
                f"occurrence {occurrence} exceeds {len(matches)} match(es) for {query!r}"
            )
        match = matches[occurrence - 1]
        nx, ny = match["center"]
        px, py = _to_pixels(frame, nx, ny)
        primitives.click(frame, px, py)
        return _post_action_result(
            mac,
            before,
            (nx, ny),
            {"query": query, "occurrence": occurrence, "match": match},
        )


@server.tool()
def tap_iphone(x: Coord, y: Coord) -> list:
    """Tap normalized x,y and return a fresh screenshot marked at the tap."""
    with _lock:
        mac = _session()
        _fresh_frame(mac, activate=True)
        frame, before = _see_bytes(mac)
        px, py = _to_pixels(frame, x, y)
        result = primitives.click(frame, px, py)
        return _post_action_result(
            mac,
            before,
            (float(x), float(y)),
            {
                "normalized": [float(x), float(y)],
                "pixels": [round(px, 1), round(py, 1)],
                **result,
            },
        )


@server.tool()
def type_at_iphone(x: Coord, y: Coord, text: str) -> list:
    """Tap normalized x,y, type text, and return the resulting screenshot."""
    with _lock:
        mac = _session()
        _fresh_frame(mac, activate=True)
        frame, before = _see_bytes(mac)
        px, py = _to_pixels(frame, x, y)
        primitives.click(frame, px, py)
        time.sleep(0.25)
        _type_text(mac, text)
        return _post_action_result(
            mac,
            before,
            (float(x), float(y)),
            {"normalized": [float(x), float(y)], "typed": len(text)},
        )


@server.tool()
def replace_at_iphone(x: Coord, y: Coord, text: str, submit: bool = False) -> list:
    """Tap a field, select all, replace its text, optionally press Return, and verify."""
    with _lock:
        mac = _session()
        _fresh_frame(mac, activate=True)
        frame, before = _see_bytes(mac)
        px, py = _to_pixels(frame, x, y)
        primitives.click(frame, px, py)
        time.sleep(0.25)
        _hid_command(0)  # A
        _type_text(mac, text)
        if submit:
            mac.key("return", app=IPHONE_APP)
        return _post_action_result(
            mac,
            before,
            (float(x), float(y)),
            {"normalized": [float(x), float(y)], "typed": len(text), "submitted": submit},
            settle=0.9 if submit else 0.6,
        )


@server.tool()
def type_iphone(text: str) -> list:
    """Type exact text, including Chinese, Bengali, and other Unicode, then verify."""
    with _lock:
        mac = _session()
        _fresh_frame(mac, activate=True)
        _, before = _see_bytes(mac)
        _type_text(mac, text)
        return _post_action_result(mac, before, None, {"typed": len(text)})


@server.tool()
def scroll_iphone(
    amount: ScrollAmount,
    x: Coord | None = None,
    y: Coord | None = None,
    axis: Literal["vertical", "horizontal"] = "vertical",
) -> list:
    """Scroll iPhone Mirroring using a normalized signed distance.

    In WeChat chats, a negative vertical amount moves to older messages and a
    positive amount moves to newer messages. An anchor near (500, 500) usually
    works, but place it on plain chat background rather than a message bubble
    to avoid opening the long-press menu. Optional x,y anchors use normalized
    0..1000 coordinates. Omit the anchor for automatic vertical scrolling.
    """
    if axis not in ("vertical", "horizontal"):
        raise ValueError("axis must be 'vertical' or 'horizontal'")
    if not -1000 <= amount <= 1000:
        raise ValueError("amount must be between -1000 and 1000")
    with _lock:
        mac = _session()
        frame = _fresh_frame(mac, activate=True)
        width, height = frame["width"], frame["height"]
        _, initial = _see_bytes(mac)
        pixel_amount = round(amount * (height if axis == "vertical" else width) / 1000)

        if x is not None or y is not None or axis != "vertical":
            nx = 500.0 if x is None else _validate_coord("x", x)
            ny = 500.0 if y is None else _validate_coord("y", y)
            px, py = _to_pixels(frame, nx, ny)
            primitives.scroll(frame, px, py, pixel_amount, axis=axis)
            return _post_action_result(
                mac,
                initial,
                None,
                {"axis": axis, "amount": amount, "anchor": [nx, ny]},
            )

        before = initial
        for fx, fy in _VERTICAL_ANCHORS:
            px, py = fx * width, fy * height
            primitives.scroll(frame, px, py, pixel_amount, axis="vertical")
            frame, after = _see_bytes(mac)
            difference = _content_diff(before, after)
            if difference >= _MOVE_THRESHOLD:
                return [
                    Image(data=_present_image(after), format="png"),
                    json.dumps(
                        {
                            "axis": "vertical",
                            "amount": amount,
                            "anchor": [round(fx * 1000), round(fy * 1000)],
                            "difference": round(difference, 2),
                            "visible_change": True,
                            "moved": True,
                        }
                    ),
                ]
            before = after
        return [
            Image(data=_present_image(after), format="png"),
            json.dumps(
                {
                    "axis": "vertical",
                    "amount": amount,
                    "difference": round(_content_diff(initial, after), 2),
                    "visible_change": False,
                    "moved": False,
                    "hint": "retry with x/y over a plain text row or the left margin",
                }
            ),
        ]


@server.tool()
def swipe_iphone(x1: Coord, y1: Coord, x2: Coord, y2: Coord) -> list:
    """Swipe between normalized points and return the resulting screenshot."""
    with _lock:
        mac = _session()
        _fresh_frame(mac, activate=True)
        frame, before = _see_bytes(mac)
        px1, py1 = _to_pixels(frame, x1, y1)
        px2, py2 = _to_pixels(frame, x2, y2)
        result = primitives.swipe(frame, px1, py1, px2, py2)
        return _post_action_result(
            mac,
            before,
            (float(x2), float(y2)),
            {"normalized": [[float(x1), float(y1)], [float(x2), float(y2)]], **result},
        )


@server.tool()
def key_iphone(keys: str) -> list:
    """Send a key or chord and return the resulting iPhone screenshot."""
    with _lock:
        mac = _session()
        _fresh_frame(mac, activate=True)
        _, before = _see_bytes(mac)
        normalized_keys = keys.casefold().replace("command", "cmd").replace(" ", "")
        if normalized_keys == "cmd+a":
            _hid_command(0)  # A
        else:
            mac.key(keys, app=IPHONE_APP)
        return _post_action_result(mac, before, None, {"sent": keys})


_BASE_TOOLS = {
    "see_iphone",
    "tap_iphone",
    "type_iphone",
    "scroll_iphone",
    "swipe_iphone",
    "key_iphone",
}
_TOOL_PROFILES = {
    "normalized": _BASE_TOOLS,
    "grid": _BASE_TOOLS,
    "ocr": _BASE_TOOLS | {"find_text", "tap_text"},
    "composite": _BASE_TOOLS
    | {"find_text", "tap_text", "type_at_iphone", "replace_at_iphone"},
    "full": _BASE_TOOLS
    | {
        "inspect_iphone",
        "find_text",
        "tap_text",
        "type_at_iphone",
        "replace_at_iphone",
    },
}


def _apply_tool_profile() -> None:
    enabled = _TOOL_PROFILES.get(TOOL_PROFILE)
    if enabled is None:
        choices = ", ".join(_TOOL_PROFILES)
        raise ValueError(f"unknown IPHONE_TOOL_PROFILE={TOOL_PROFILE!r}; choose {choices}")
    for name in set().union(*_TOOL_PROFILES.values()) - enabled:
        server.remove_tool(name)


_apply_tool_profile()


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
