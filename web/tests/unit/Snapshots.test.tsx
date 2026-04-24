import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import Snapshots from "@/pages/Snapshots";

vi.mock("@/api", () => ({
  apiFetch: vi.fn().mockResolvedValue([
    {
      name: "2026-04-24T12-00-00--manual.json",
      path: "/x/a.json",
      scanned_at: "2026-04-24T12:00:00Z",
      hostname: "h", platform: "darwin", note: null,
      total_bytes: 100, kind: "manual",
      duration_ms: 4821, entry_count: 10, per_provider: null,
    },
    {
      name: "2026-04-24T11-00-00--auto.json",
      path: "/x/b.json",
      scanned_at: "2026-04-24T11:00:00Z",
      hostname: "h", platform: "darwin", note: null,
      total_bytes: 50, kind: "auto",
      duration_ms: 2300, entry_count: 0, per_provider: null,
    },
  ]),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe("Snapshots page", () => {
  it("renders duration next to both auto and manual rows", async () => {
    render(<Snapshots />, { wrapper });
    expect(await screen.findByText("4.8s")).toBeInTheDocument();
    expect(await screen.findByText("2.3s")).toBeInTheDocument();
  });

  it("has at least one element whose trimmed text is 'auto'", async () => {
    const { container } = render(<Snapshots />, { wrapper });
    // Wait for data before searching.
    await screen.findByText("4.8s");
    const autoBadges = Array.from(container.querySelectorAll("*")).filter(
      (el) => el.textContent?.trim() === "auto",
    );
    expect(autoBadges.length).toBeGreaterThan(0);
  });
});
