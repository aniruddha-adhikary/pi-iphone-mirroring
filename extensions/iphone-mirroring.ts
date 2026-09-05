import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { createMcpAdapter } from "pi-mcp-adapter";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const serverRoot = join(packageRoot, "server");

const installAdapter = createMcpAdapter({
	config: {
		settings: {
			toolPrefix: "none",
			scriptMode: false,
			disableProxyTool: true,
			hostConfigDiscovery: "off",
			requestTimeoutMs: 120_000,
		},
		mcpServers: {
			iphone: {
				command: "uv",
				args: ["run", "--frozen", "macos-mcp"],
				cwd: serverRoot,
				env: { IPHONE_TOOL_PROFILE: "grid" },
				lifecycle: "eager",
				directTools: true,
				exposeResources: false,
			},
		},
	},
});

const IPHONE_SYSTEM_PROMPT = `You are controlling only Apple's iPhone Mirroring app through vision-based tools.

Rules:
- Call see_iphone before acting. Action tools return a fresh screenshot; inspect it to verify the result.
- Every point uses normalized coordinates from 0 to 1000 independently on each axis.
- (0, 0) is top-left and (1000, 1000) is bottom-right. Use the labeled 100-unit grid.
- Never use screenshot pixels or macOS screen coordinates.
- For text fields: tap to focus, use key_iphone with cmd+a when replacing text, call type_iphone, then submit with key_iphone using return or tap the visible button.
- type_iphone supports Chinese and other Unicode through the native macOS pasteboard and a real HID paste chord.
- In WeChat chats, a negative vertical scroll amount moves toward older messages and a positive amount moves toward newer messages. Anchor around (500, 500) on plain chat background, not a message bubble.
- Check visible_change, marked tap locations, and returned screenshots. Never claim success without visual verification.`;

export default function iphoneMirroringPackage(pi: ExtensionAPI) {
	if (process.platform !== "darwin") {
		throw new Error("pi-iphone-mirroring requires macOS");
	}

	installAdapter(pi);

	pi.on("before_agent_start", (event) => ({
		systemPrompt: `${event.systemPrompt}\n\n${IPHONE_SYSTEM_PROMPT}`,
	}));
}
