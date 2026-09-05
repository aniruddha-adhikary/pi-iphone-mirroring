/**
 * Sliding image window for pi.
 *
 * BaseRT accepts at most one image per request, counted across the whole
 * `messages` array. A screenshot-driven agent adds one image per `see` call and
 * pi replays the full history every turn, so the second screenshot makes every
 * subsequent request fail with:
 *
 *   400 {"message":"Only one image per request is supported"}
 *
 * This rewrites the outgoing payload so only the newest N images survive; older
 * ones become a text placeholder. pi's own session history is untouched, so the
 * transcript, /tree and forks keep every screenshot.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const DEFAULT_MAX_IMAGES = 1;
const DEFAULT_PROVIDERS = ["basert"];

function readMaxImages(value: string | undefined): number {
	if (value === undefined || value.trim() === "") return DEFAULT_MAX_IMAGES;
	const parsed = Number(value);
	return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : DEFAULT_MAX_IMAGES;
}

type ContentPart = { type?: string; text?: string; [k: string]: unknown };
type Message = { role?: string; content?: unknown; [k: string]: unknown };
type Payload = { messages?: unknown; [k: string]: unknown };

function isImagePart(part: unknown): part is ContentPart {
	const type = (part as ContentPart | null)?.type;
	// "image_url" is the OpenAI wire form; "image" covers providers that pass
	// pi's native part through unchanged.
	return type === "image_url" || type === "image";
}

function placeholder(index: number, total: number): ContentPart {
	return {
		type: "text",
		text:
			`[image ${index} of ${total} omitted: this model accepts only the most recent image. ` +
			`It showed the screen at an earlier step. Rely on the newest image and on the tool ` +
			`results above for what has changed since.]`,
	};
}

/**
 * Return a payload carrying at most `maxImages` images, keeping the newest.
 *
 * Pure and copy-on-write: messages without images are passed through by
 * reference so the multi-hundred-KB base64 strings are never copied.
 */
export function windowImages(payload: unknown, maxImages = DEFAULT_MAX_IMAGES): unknown {
	maxImages = Number.isSafeInteger(maxImages) && maxImages >= 0 ? maxImages : DEFAULT_MAX_IMAGES;
	const messages = (payload as Payload | null)?.messages;
	if (!Array.isArray(messages)) {
		return payload;
	}

	// Locate every image part as (message index, part index).
	const found: Array<[number, number]> = [];
	messages.forEach((message: Message, m) => {
		const content = message?.content;
		if (!Array.isArray(content)) return;
		content.forEach((part, p) => {
			if (isImagePart(part)) found.push([m, p]);
		});
	});

	if (found.length <= maxImages) {
		return payload;
	}

	// Keep the tail; everything before the cut becomes a placeholder.
	const cut = found.length - maxImages;
	const drop = new Map<number, Set<number>>();
	found.slice(0, cut).forEach(([m, p], i) => {
		if (!drop.has(m)) drop.set(m, new Set());
		drop.get(m)!.add(p);
	});
	const ordinal = new Map(found.map(([m, p], i) => [`${m}:${p}`, i + 1]));

	const rewritten = messages.map((message: Message, m) => {
		const drops = drop.get(m);
		if (!drops) return message;
		const content = (message.content as ContentPart[]).map((part, p) =>
			drops.has(p) ? placeholder(ordinal.get(`${m}:${p}`)!, found.length) : part,
		);
		return { ...message, content };
	});

	return { ...(payload as Payload), messages: rewritten };
}

export default function (pi: ExtensionAPI) {
	const maxImages = readMaxImages(process.env.PI_IMAGE_WINDOW);
	const providers = (process.env.PI_IMAGE_WINDOW_PROVIDERS ?? DEFAULT_PROVIDERS.join(","))
		.split(",")
		.map((s) => s.trim())
		.filter(Boolean);

	pi.on("before_provider_request", (event, ctx) => {
		// Other providers happily take many images; only clamp the ones that can't.
		const provider = ctx.model?.provider;
		if (provider !== undefined && !providers.includes(provider)) {
			return undefined;
		}
		return windowImages(event.payload, maxImages);
	});
}
