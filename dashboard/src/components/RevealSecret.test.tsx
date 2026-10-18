import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RevealSecret } from "./RevealSecret";

describe("RevealSecret", () => {
  it("asks for the password, shows the secret, and hides it again", async () => {
    const reveal = vi.fn().mockResolvedValue("gsk_the_full_secret_value");
    const onClose = vi.fn();
    render(<RevealSecret title="groq API key" reveal={reveal} onClose={onClose} />);

    expect(screen.queryByText("gsk_the_full_secret_value")).toBeNull();
    fireEvent.change(screen.getByLabelText(/Confirm with your password/), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: /Show key/ }));

    await waitFor(() => expect(screen.getByText("gsk_the_full_secret_value")).toBeTruthy());
    expect(reveal).toHaveBeenCalledWith("pw", undefined);
    expect(screen.getByRole("button", { name: /Copy/ })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Hide/ }));
    expect(onClose).toHaveBeenCalled();
    expect(screen.queryByText("gsk_the_full_secret_value")).toBeNull();
  });

  it("shows the server's error and asks for a code when two-factor is on", async () => {
    const reveal = vi
      .fn()
      .mockRejectedValueOnce(new Error("enter the code from your authenticator app"))
      .mockResolvedValueOnce("secret");
    render(<RevealSecret title="k" reveal={reveal} onClose={() => undefined} />);

    fireEvent.change(screen.getByLabelText(/Confirm with your password/), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: /Show key/ }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("authenticator"));

    fireEvent.change(screen.getByLabelText(/Confirm with your password/), { target: { value: "pw" } });
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: /Show key/ }));
    await waitFor(() => expect(reveal).toHaveBeenLastCalledWith("pw", "123456"));
  });
});
