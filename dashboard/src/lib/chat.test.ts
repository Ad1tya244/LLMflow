import { trimHistory, type ChatMessage } from "./chat";

const turn = (role: ChatMessage["role"], n: number): ChatMessage => ({ role, content: "x".repeat(n) });

describe("trimHistory", () => {
  it("keeps the whole conversation when it fits", () => {
    const chat = [turn("user", 10), turn("assistant", 10), turn("user", 10)];
    expect(trimHistory(chat, 100)).toEqual({ messages: chat, dropped: 0 });
  });

  it("drops the oldest messages first and starts on a user message", () => {
    const chat = [turn("user", 40), turn("assistant", 40), turn("user", 40), turn("assistant", 40), turn("user", 40)];
    const { messages, dropped } = trimHistory(chat, 130);
    expect(messages).toEqual(chat.slice(2));
    expect(dropped).toBe(2);
    expect(messages[0]!.role).toBe("user");
    expect(messages.at(-1)).toBe(chat.at(-1));
  });

  it("never starts on an assistant reply whose question was dropped", () => {
    const chat = [turn("user", 50), turn("assistant", 30), turn("user", 30)];
    const { messages } = trimHistory(chat, 70);
    expect(messages.map((m) => m.role)).toEqual(["user"]);
  });

  it("always keeps the newest message, even when it alone is over the cap", () => {
    const chat = [turn("user", 10), turn("assistant", 10), turn("user", 500)];
    const { messages, dropped } = trimHistory(chat, 100);
    expect(messages).toEqual([chat[2]]);
    expect(dropped).toBe(2);
  });
});
