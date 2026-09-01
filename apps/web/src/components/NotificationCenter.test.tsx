import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NotificationCenter } from "./NotificationCenter";

describe("NotificationCenter Component", () => {
  it("renders notification bell button with accessible label", () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <NotificationCenter />
      </QueryClientProvider>
    );

    const button = screen.getByRole("button", { name: /notification center/i });
    expect(button).toBeDefined();
  });
});
