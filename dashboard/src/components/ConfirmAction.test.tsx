import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmAction } from "./ConfirmAction";

describe("ConfirmAction", () => {
  it("does nothing until a password is entered, then calls onConfirm", async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    render(<ConfirmAction prompt="Confirm with your password" confirmLabel="Remove key" danger onConfirm={onConfirm} onCancel={() => undefined} />);

    const button = screen.getByRole("button", { name: "Remove key" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(onConfirm).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Confirm with your password"), { target: { value: "pw" } });
    fireEvent.click(button);
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith("pw", undefined));
  });

  it("shows a wrong-password error and keeps the action from completing", async () => {
    const onConfirm = vi.fn().mockRejectedValue(new Error("password is incorrect"));
    render(<ConfirmAction prompt="Confirm" confirmLabel="Remove key" onConfirm={onConfirm} onCancel={() => undefined} />);
    fireEvent.change(screen.getByLabelText("Confirm"), { target: { value: "bad" } });
    fireEvent.click(screen.getByRole("button", { name: "Remove key" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("password is incorrect"));
  });

  it("asks for an authenticator code when the server requires one", async () => {
    const onConfirm = vi
      .fn()
      .mockRejectedValueOnce(new Error("enter the code from your authenticator app"))
      .mockResolvedValueOnce(undefined);
    render(<ConfirmAction prompt="Confirm" confirmLabel="Remove key" onConfirm={onConfirm} onCancel={() => undefined} />);
    fireEvent.change(screen.getByLabelText("Confirm"), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: "Remove key" }));
    await waitFor(() => expect(screen.getByLabelText("Authenticator code")).toBeTruthy());

    fireEvent.change(screen.getByLabelText("Confirm"), { target: { value: "pw" } });
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Remove key" }));
    await waitFor(() => expect(onConfirm).toHaveBeenLastCalledWith("pw", "123456"));
  });

  it("cancel closes without calling onConfirm", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<ConfirmAction prompt="Confirm" confirmLabel="Remove key" onConfirm={onConfirm} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
