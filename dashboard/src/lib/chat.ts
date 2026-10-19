import { ApiError, toError, type Connection } from "./api";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatOptions {
  model: string;
  messages: ChatMessage[];
  quality: "low" | "balanced" | "high";
  privacy: "standard" | "strict";
  stream: boolean;
  cache?: boolean;
}

/** Rough cap on the history sent with each message (about 4,000 tokens). A chat keeps its
 *  context, but a long one must not grow every request without limit: that would eat the free
 *  tiers' per-minute token limits and the cost savings. */
export const MAX_HISTORY_CHARS = 16_000;

/** Keeps the newest messages that fit ``maxChars``. The newest message is always kept, and the
 *  result starts on a user message so the model never sees a reply without its question. */
export function trimHistory(
  messages: ChatMessage[],
  maxChars: number = MAX_HISTORY_CHARS,
): { messages: ChatMessage[]; dropped: number } {
  let used = 0;
  let start = messages.length;
  for (let i = messages.length - 1; i >= 0; i--) {
    const size = messages[i]!.content.length;
    if (i < messages.length - 1 && used + size > maxChars) break;
    used += size;
    start = i;
  }
  while (start < messages.length - 1 && messages[start]!.role !== "user") start++;
  return { messages: messages.slice(start), dropped: start };
}

export interface RouteInfo {
  model: string;
  provider: string;
  attempts: string;
  reason: string;
  cost: string | null;
  cache: string | null;
}

function routeInfo(res: Response): RouteInfo {
  return {
    model: res.headers.get("x-llmflow-model") ?? "",
    provider: res.headers.get("x-llmflow-provider") ?? "",
    attempts: res.headers.get("x-llmflow-attempts") ?? "",
    reason: res.headers.get("x-llmflow-route-reason") ?? "",
    cost: res.headers.get("x-llmflow-shadow-cost-usd"),
    cache: res.headers.get("x-llmflow-cache"),
  };
}

/** Pulls the text delta out of one OpenAI-style SSE payload. */
export function deltaOf(payload: string): string {
  if (payload === "[DONE]") return "";
  try {
    const obj = JSON.parse(payload) as { choices?: { delta?: { content?: string } }[] };
    return obj.choices?.[0]?.delta?.content ?? "";
  } catch {
    return "";
  }
}

export async function sendChat(
  conn: Connection,
  opts: ChatOptions,
  onText: (text: string) => void,
  signal: AbortSignal,
): Promise<RouteInfo> {
  let res: Response;
  try {
    res = await fetch(`${conn.baseUrl.replace(/\/+$/, "")}/account/chat`, {
      method: "POST",
      signal,
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-LLMFlow-CSRF": conn.csrf },
      body: JSON.stringify({
        model: opts.model,
        stream: opts.stream && !opts.cache,
        messages: opts.messages,
        llmflow: { quality: opts.quality, privacy: opts.privacy, ...(opts.cache ? { cache: "on" } : {}) },
      }),
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(`Cannot reach the gateway at ${conn.baseUrl}.`, 0, "network");
  }
  if (!res.ok) throw await toError(res);
  const info = routeInfo(res);

  if (!opts.stream || opts.cache || !res.body) {
    const body = (await res.json()) as { choices?: { message?: { content?: string } }[] };
    onText(body.choices?.[0]?.message?.content ?? "");
    return info;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let text = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const ev of events) {
      const line = ev.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      text += deltaOf(line.slice(5).trim());
      onText(text);
    }
  }
  return info;
}
