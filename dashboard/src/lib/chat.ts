import { ApiError, toError, type Connection } from "./api";

export interface ChatOptions {
  model: string;
  prompt: string;
  quality: "low" | "balanced" | "high";
  privacy: "standard" | "strict";
  stream: boolean;
  cache?: boolean;
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
        messages: [{ role: "user", content: opts.prompt }],
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
