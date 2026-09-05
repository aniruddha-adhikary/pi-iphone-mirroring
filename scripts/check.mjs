import { existsSync, readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

const required = [
  "extensions/image-window.ts",
  "extensions/iphone-mirroring.ts",
  "server/pyproject.toml",
  "server/uv.lock",
  "server/src/macos_mcp/server.py",
  "server/src/macos_mcp/primitives.py",
  "docs/architecture.mmd",
];

for (const path of required) {
  if (!existsSync(path)) throw new Error(`Missing required package file: ${path}`);
}

const manifest = JSON.parse(readFileSync("package.json", "utf8"));
if (!manifest.keywords?.includes("pi-package")) throw new Error("Missing pi-package keyword");
if (manifest.pi?.extensions?.length !== 2) throw new Error("Expected two Pi extensions");

const smoke = spawnSync(
  "uv",
  [
    "run",
    "--project",
    "server",
    "--frozen",
    "python",
    "-c",
    [
      "import asyncio",
      "from macos_mcp.server import server, TOOL_PROFILE",
      "async def check():",
      " names=[tool.name for tool in await server.list_tools()]",
      " assert TOOL_PROFILE == 'grid', TOOL_PROFILE",
      " assert names == ['see_iphone','tap_iphone','type_iphone','scroll_iphone','swipe_iphone','key_iphone'], names",
      "asyncio.run(check())",
    ].join("\n"),
  ],
  { encoding: "utf8" },
);

if (smoke.error) throw smoke.error;
if (smoke.status !== 0) {
  process.stderr.write(smoke.stdout);
  process.stderr.write(smoke.stderr);
  process.exit(smoke.status ?? 1);
}

console.log("Package structure and MCP tool surface are valid.");
