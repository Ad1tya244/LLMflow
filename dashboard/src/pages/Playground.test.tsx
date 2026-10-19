import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ConnectionProvider } from "../lib/store";
import { Playground } from "./Playground";

const json = (body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json", ...headers } });

interface Sent {
  messages: { role: string; content: string }[];
  stream?: boolean;
}

function stubGateway() {
  const sent: Sent[] = [];
  let n = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/auth/session")) {
        return json({
          authenticated: true,
          csrf_token: "c",
          workspace: { id: "t_1", name: "Acme" },
          user: { email: "a@example.com" },
        });
      }
      if (url.endsWith("/account")) return json({ models: [] });
      if (url.endsWith("/account/chat")) {
        const body = JSON.parse(String(init?.body)) as Sent;
        sent.push(body);
        n += 1;
        const headers = { "x-llmflow-model": "groq-gpt-oss-20b" };
        if (body.stream) {
          const sse = `data: ${JSON.stringify({ choices: [{ delta: { content: `reply ${n}` } }] })}\n\ndata: [DONE]\n\n`;
          return new Response(sse, { status: 200, headers: { "Content-Type": "text/event-stream", ...headers } });
        }
        return json({ choices: [{ message: { content: `reply ${n}` } }] }, headers);
      }
      return json({});
    }),
  );
  return sent;
}

afterEach(() => vi.unstubAllGlobals());

describe("Playground conversation", () => {
  it("sends the whole chat with each message, and a new chat starts with nothing", async () => {
    const sent = stubGateway();
    const say = (text: string) => {
      fireEvent.change(screen.getByLabelText("Message"), { target: { value: text } });
      fireEvent.click(screen.getByRole("button", { name: /send/i }));
    };
    render(
      <ConnectionProvider>
        <Playground />
      </ConnectionProvider>,
    );
    await screen.findByLabelText("Message");

    say("My name is Priya");
    await screen.findByText("reply 1");
    expect(sent[0]!.messages).toEqual([{ role: "user", content: "My name is Priya" }]);

    say("What is my name?");
    await screen.findByText("reply 2");
    expect(sent[1]!.messages).toEqual([
      { role: "user", content: "My name is Priya" },
      { role: "assistant", content: "reply 1" },
      { role: "user", content: "What is my name?" },
    ]);

    fireEvent.click(screen.getByRole("button", { name: /new chat/i }));
    await waitFor(() => expect(screen.queryByText("reply 1")).not.toBeInTheDocument());
    say("Hello again");
    await screen.findByText("reply 3");
    expect(sent[2]!.messages).toEqual([{ role: "user", content: "Hello again" }]);
  });

  it("puts a copy button under each reply that copies that reply", async () => {
    stubGateway();
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    render(
      <ConnectionProvider>
        <Playground />
      </ConnectionProvider>,
    );
    await screen.findByLabelText("Message");
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "hi" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
    await screen.findByText("reply 1");
    const copy = await screen.findByRole("button", { name: "Copy reply" });
    fireEvent.click(copy);
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("reply 1"));
  });
});
