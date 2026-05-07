import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/api", () => ({
  apiFetch: vi.fn((path: string) => {
    if (path.startsWith("/memory/providers")) {
      return Promise.resolve([
        {
          id: "browser",
          name: "Browsers",
          kind: "browser",
          status: "available",
          description: "Firefox and Chrome helper processes.",
          detail: "Tab-level attribution depends on browser support.",
          consumer_kinds: ["browser"],
        },
        {
          id: "docker",
          name: "Docker",
          kind: "docker",
          status: "available",
          description: "Docker Desktop, VM, daemon, and container helper processes.",
          detail: "/Applications/Docker.app",
          consumer_kinds: ["docker"],
        },
      ]);
    }
    if (path.startsWith("/memory")) {
      return Promise.resolve({
        scanned_at: "2026-05-07T12:00:00Z",
        hostname: "host",
        platform: "darwin",
        system: {
          total_bytes: 1000,
          available_bytes: 400,
          used_bytes: 600,
          swap_used_bytes: 0,
          compressed_bytes: 0,
          pressure: "ok",
        },
        consumers: [],
        provider_totals: [],
        suggestions: [],
      });
    }
    return Promise.resolve(null);
  }),
}));

import Memory from "@/pages/Memory";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/memory/providers"]}>
        <Routes>
          <Route path="/memory/:tab" element={children} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("Memory providers page", () => {
  it("uses disk-style enabled copy and filters providers by search", async () => {
    const user = userEvent.setup();
    render(<Memory />, { wrapper });

    expect(await screen.findByText("2 of 2 providers enabled")).toBeInTheDocument();

    await user.type(
      screen.getByPlaceholderText("Search memory providers by name or scope..."),
      "docker",
    );

    expect(await screen.findByText("1 match")).toBeInTheDocument();
    expect(screen.getByText("Docker")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText("Browsers")).not.toBeInTheDocument();
    });
  });
});
