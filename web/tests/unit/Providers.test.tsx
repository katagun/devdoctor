import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("@/api", () => ({
  apiFetch: vi.fn((path: string) => {
    if (path.startsWith("/providers")) {
      return Promise.resolve([
        {
          name: "ollama",
          description: "ollama models",
          risk: "reclaimable",
          platforms: ["darwin", "linux"],
          available: true,
          required_binary: "ollama",
          kind: "class",
          details: "Models live under ~/.ollama/models.",
          raw_paths: null,
          resolved_paths: null,
          recipe_template: null,
        },
        {
          name: "my-yaml",
          description: "yaml provider",
          risk: "safe",
          platforms: ["darwin"],
          available: true,
          required_binary: null,
          kind: "yaml",
          details: null,
          raw_paths: ["~/cache/foo"],
          resolved_paths: ["/Users/me/cache/foo"],
          recipe_template: ["rm -rf {path}"],
        },
      ]);
    }
    if (path.startsWith("/snapshots")) {
      return Promise.resolve([]);
    }
    if (path === "/disk-usage") {
      return Promise.resolve({ total: 1, used: 0, free: 1 });
    }
    return Promise.resolve(null);
  }),
}));

import Providers from "@/pages/Providers";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe("Providers page — details expansion", () => {
  it("starts with no rows expanded and aria-expanded=false on chevrons", async () => {
    render(<Providers />, { wrapper });
    const chevrons = await screen.findAllByRole("button", { name: /show details/i });
    expect(chevrons.length).toBe(2);
    chevrons.forEach((c) => expect(c).toHaveAttribute("aria-expanded", "false"));
  });

  it("clicking the chevron expands that row's details panel", async () => {
    const user = userEvent.setup();
    render(<Providers />, { wrapper });
    const chevron = await screen.findByRole("button", { name: /show details for ollama/i });
    await user.click(chevron);

    expect(chevron).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("region", { name: /ollama details/i })).toBeInTheDocument();
  });

  it("supports expanding more than one row at a time", async () => {
    const user = userEvent.setup();
    render(<Providers />, { wrapper });
    await user.click(await screen.findByRole("button", { name: /show details for ollama/i }));
    await user.click(await screen.findByRole("button", { name: /show details for my-yaml/i }));

    expect(screen.getByRole("region", { name: /ollama details/i })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /my-yaml details/i })).toBeInTheDocument();
  });

  it("collapsing removes the panel from the DOM", async () => {
    const user = userEvent.setup();
    render(<Providers />, { wrapper });
    const chevron = await screen.findByRole("button", { name: /show details for ollama/i });
    await user.click(chevron);
    await user.click(chevron);

    expect(chevron).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("region", { name: /ollama details/i })).not.toBeInTheDocument();
  });
});
