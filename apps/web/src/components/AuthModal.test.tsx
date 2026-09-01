import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AuthModal } from "./AuthModal";
import { AuthProvider } from "@/lib/auth-context";

describe("AuthModal Component", () => {
  it("renders sign in modal and switches to register tab", () => {
    render(
      <AuthProvider>
        <AuthModal open={true} onOpenChange={() => {}} defaultMode="login" />
      </AuthProvider>
    );

    expect(screen.getByText("Sign In to SabiScore")).toBeDefined();
    expect(screen.getByLabelText("Email Address")).toBeDefined();
    expect(screen.getByLabelText("Password")).toBeDefined();

    // Switch to Register
    const registerTab = screen.getByRole("button", { name: "Register" });
    fireEvent.click(registerTab);

    expect(screen.getByText("Create Free Analyst Account")).toBeDefined();
    expect(screen.getByLabelText("Username")).toBeDefined();
  });
});
