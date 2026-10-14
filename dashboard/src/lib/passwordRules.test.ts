import { describe, expect, it } from "vitest";
import { passwordAcceptable } from "./passwordRules";

describe("password rules", () => {
  it("accepts a strong password", () => {
    expect(passwordAcceptable("Correct-Horse-Battery-7", "a@example.com")).toBe(true);
    expect(passwordAcceptable("my dog Rufus eats 3 apples")).toBe(true);
  });
  it.each([
    ["short", "Ab1!"],
    ["no uppercase", "correct-horse-battery-7"],
    ["no number", "Correct-Horse-Battery"],
    ["no symbol", "CorrectHorseBattery7"],
    ["repeat", "Correct-Horse-Bxxxx7"],
    ["sequence", "Correct-Horse-1234-Zq"],
    ["common word", "Welcome-To-The-Zoo-42"],
  ])("rejects %s", (_n, pw) => {
    expect(passwordAcceptable(pw)).toBe(false);
  });
  it("rejects the email name", () => {
    expect(passwordAcceptable("Alicealice-1357-Zq", "alice@example.com")).toBe(false);
  });
});
