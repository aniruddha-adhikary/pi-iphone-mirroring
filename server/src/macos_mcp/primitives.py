"""In-process macOS input primitives.

Called directly against a live `macos_harness.macos.MacOS` instance and the
frame dict returned by `mac.see(...)`. Coordinates are in that frame's
screenshot pixel space (its ``width``/``height``); we map them to screen
coordinates via the frame's window ``bounds``.

The encodings here are the ones that actually drive both ordinary Mac apps
and iPhone Mirroring (which is undocumented and rejects the obvious ones):

* click  -- warp the *physical* cursor to the target (apps hit-test the real
            pointer), post the button at the HID tap, restore the cursor.
* scroll -- a *continuous, phased* trackpad-style gesture (isContinuous=1,
            scrollPhase Began->Changed->Ended) posted to the **session** tap,
            cursor warped over the content, app frontmost. Positive = down.
* swipe  -- press/drag/release, warping the cursor each drag step.
"""

from __future__ import annotations

import time

import Quartz
from AppKit import NSRunningApplication

# CGScrollWheelEvent integer fields not exposed as Quartz constants
_IS_CONT = 88   # kCGScrollWheelEventIsContinuous
_PHASE = 99     # kCGScrollWheelEventScrollPhase
_PTD1 = 96      # kCGScrollWheelEventPointDeltaAxis1 (vertical)
_D1 = 11        # kCGScrollWheelEventDeltaAxis1
_PTD2 = 97      # kCGScrollWheelEventPointDeltaAxis2 (horizontal)
_D2 = 12        # kCGScrollWheelEventDeltaAxis2
_BEG, _CHG, _END = 1, 2, 4  # CGScrollPhase values

_BTN = {
    "left": (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp, Quartz.kCGMouseButtonLeft),
    "right": (Quartz.kCGEventRightMouseDown, Quartz.kCGEventRightMouseUp, Quartz.kCGMouseButtonRight),
}


def cursor():
    return Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))


def to_screen(frame, x, y):
    b = frame["bounds"]
    return (
        b["x"] + (float(x) / frame["width"]) * b["width"],
        b["y"] + (float(y) / frame["height"]) * b["height"],
    )


def activate(frame):
    """Bring the frame's app frontmost -- required for Mirroring input."""
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(frame["pid"])
    if app is not None:
        app.activateWithOptions_(0)
        time.sleep(0.4)


def click(frame, x, y, button="left", clicks=1):
    sx, sy = to_screen(frame, x, y)
    origin = cursor()
    Quartz.CGWarpMouseCursorPosition((sx, sy))
    Quartz.CGAssociateMouseAndMouseCursorPosition(True)
    time.sleep(0.06)
    down, up, btn = _BTN[button]
    mv = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (sx, sy), btn)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, mv)
    time.sleep(0.04)
    for i in range(clicks):
        for kind in (down, up):
            e = Quartz.CGEventCreateMouseEvent(None, kind, (sx, sy), btn)
            Quartz.CGEventSetIntegerValueField(e, Quartz.kCGMouseEventClickState, i + 1)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)
            time.sleep(0.04)
    Quartz.CGWarpMouseCursorPosition(origin)
    return {"screen": [round(sx, 1), round(sy, 1)]}


def scroll(frame, x, y, amount, axis="vertical", steps=24, settle=0.016):
    """Phased continuous scroll on the session tap. Positive amount = down/right."""
    sx, sy = to_screen(frame, x, y)
    origin = cursor()
    Quartz.CGWarpMouseCursorPosition((sx, sy))
    Quartz.CGAssociateMouseAndMouseCursorPosition(True)
    time.sleep(0.12)
    vertical = axis == "vertical"
    pt_field, ln_field = (_PTD1, _D1) if vertical else (_PTD2, _D2)

    def wheel(dy, phase):
        ln = -1 if dy < 0 else (1 if dy > 0 else 0)
        if vertical:
            e = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitPixel, 1, ln)
        else:
            e = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitPixel, 2, 0, ln)
        Quartz.CGEventSetIntegerValueField(e, _IS_CONT, 1)
        Quartz.CGEventSetIntegerValueField(e, ln_field, ln)
        Quartz.CGEventSetIntegerValueField(e, pt_field, dy)
        Quartz.CGEventSetIntegerValueField(e, _PHASE, phase)
        Quartz.CGEventSetLocation(e, (sx, sy))
        Quartz.CGEventPost(Quartz.kCGSessionEventTap, e)

    per = int(amount / steps) or (1 if amount > 0 else -1)
    wheel(per, _BEG)
    time.sleep(settle)
    for _ in range(steps - 1):
        wheel(per, _CHG)
        time.sleep(settle)
    wheel(0, _END)
    Quartz.CGWarpMouseCursorPosition(origin)
    return {"axis": axis, "amount": amount}


def swipe(frame, x1, y1, x2, y2, steps=20, settle=0.012):
    p1 = to_screen(frame, x1, y1)
    p2 = to_screen(frame, x2, y2)
    origin = cursor()

    def wp(kind, pt):
        Quartz.CGWarpMouseCursorPosition(pt)
        e = Quartz.CGEventCreateMouseEvent(None, kind, pt, Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)

    Quartz.CGAssociateMouseAndMouseCursorPosition(True)
    wp(Quartz.kCGEventMouseMoved, p1)
    time.sleep(0.05)
    wp(Quartz.kCGEventLeftMouseDown, p1)
    time.sleep(0.08)
    for i in range(1, steps + 1):
        t = i / steps
        wp(Quartz.kCGEventLeftMouseDragged, (p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t))
        time.sleep(settle)
    time.sleep(0.03)
    wp(Quartz.kCGEventLeftMouseUp, p2)
    Quartz.CGWarpMouseCursorPosition(origin)
    return {"from": [x1, y1], "to": [x2, y2]}
