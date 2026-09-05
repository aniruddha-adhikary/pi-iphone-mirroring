# Pi iPhone Mirroring

A [Pi](https://pi.dev) package that gives vision-capable models a small,
reliable toolset for controlling Apple's **iPhone Mirroring** app.

![Capabilities added around a vision-capable LLM](docs/architecture.png)

## What it adds

- **iPhone-only scope** — no app-selection ambiguity.
- **Predictable taps** — normalized 0–1000 coordinates with a visible grid and hard bounds.
- **Small context** — only the latest screenshot is sent to providers that accept one image.
- **Working native input** — Quartz HID taps and trackpad-style scrolling accepted by iPhone Mirroring.
- **Unicode typing** — native `NSPasteboard` plus a real HID Command+V sequence.
- **Verification** — every action returns a fresh screenshot so the model can see whether it worked.

The default tool surface stays intentionally small:

```text
see_iphone  tap_iphone  type_iphone
scroll_iphone  swipe_iphone  key_iphone
```

## Requirements

- macOS with iPhone Mirroring available
- [Pi](https://pi.dev)
- [`uv`](https://docs.astral.sh/uv/) on `PATH`
- Accessibility and Screen Recording permission for the terminal running Pi
- A Pi model with image input and tool use

## Install

```bash
pi install git:github.com/aniruddha-adhikary/pi-iphone-mirroring
```

Start Pi and select an image-capable model:

```bash
pi
```

The package starts its embedded MCP server automatically. No separate server
clone or `.mcp.json` is needed.

## How coordinates work

Every point is normalized independently on each axis:

```text
(0, 0)                         (1000, 0)
   ┌───────────────────────────────┐
   │          iPhone image         │
   └───────────────────────────────┘
(0, 1000)                    (1000, 1000)
```

`see_iphone` draws grid lines every 100 units. The server maps the selected
point into the current iPhone Mirroring window immediately before acting.

## Under the hood

- Pi extensions provide the model instructions and one-image context window.
- `pi-mcp-adapter` exposes the six direct tools.
- The embedded Python MCP server uses `macos-harness`, Pillow, Quartz/CoreGraphics,
  and AppKit.

There is no bridged iOS accessibility tree; observation is visual.

## Safety

The package generates real mouse and keyboard input with the permissions of
your Pi process. Keep a human in the loop for purchases, messages, deletion,
authentication, and other consequential actions.

## Development

```bash
npm install
npm test
```

Architecture source: [`docs/architecture.svg`](docs/architecture.svg) and
[`docs/architecture.mmd`](docs/architecture.mmd).

MIT licensed.
