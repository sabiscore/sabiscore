import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AuthModal } from "./AuthModal";
import { AuthProvider } from "@/lib/auth-context";

function renderAuth(defaultMode: "login" | "register" = "login") {
  return render(
    <AuthProvider>
      <AuthModal open={true} onOpenChange={vi.fn()} defaultMode={defaultMode} />
    </AuthProvider>,
  );
}

describe("AuthModal Component", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders sign in with Google and email/password authentication", () => {
    renderAuth();

    expect(screen.getByText("Welcome back")).toBeDefined();
    expect(screen.getByRole("button", { name: /Continue with Google/i })).toBeDefined();
    expect(screen.getByLabelText("Email address")).toBeDefined();
    expect(screen.getByLabelText("Password")).toBeDefined();
    expect(screen.getByText("Keep me signed in on this device")).toBeDefined();
  });

  it("switches to registration and exposes account creation fields", () => {
    renderAuth();

    fireEvent.click(screen.getByRole("tab", { name: "Register" }));

    expect(screen.getByText("Create your SabiScore account")).toBeDefined();
    expect(screen.getByLabelText("Analyst username")).toBeDefined();
    expect(screen.getByLabelText("Display name (optional)")).toBeDefined();
    expect(screen.getByLabelText("Confirm password")).toBeDefined();
    expect(screen.getByRole("button", { name: /Sign up with Google/i })).toBeDefined();
  });

  it("rejects mismatched registration passwords before making a request", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({}), { status: 200 }),
    );

    renderAuth("register");

    fireEvent.change(screen.getByLabelText("Analyst username"), {
      target: { value: "analyst_2026" },
    });
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "analyst@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "password123" },
    });
    fireEvent.change(screen.getByLabelText("Confirm password"), {
      target: { value: "password456" },
    });

    fireEvent.submit(screen.getByRole("button", { name: /Create Free Account/i }).closest("form")!);

    expect(await screen.findByRole("alert")).toHaveTextContent("Passwords do not match.");
    expect(fetchSpy).not.toHaveBeenCalledWith("/api/auth/register", expect.anything());
  });
});
