import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import type { AppSettings } from "@/hooks/useAppSettings";
import { __testReloadSettings } from "@/hooks/useSettings";
import Settings from "@/pages/Settings";

const INITIAL: AppSettings = {
  storage_backend: "filesystem",
  data_dir: "/data",
  sqlite_path: "/data/devdoctor.sqlite3",
  available_backends: ["filesystem", "sqlite"],
};

// A /settings endpoint that applies each PATCH and answers with the result,
// resolving a leading "~/" the way the backend expands the SQLite path.
const { server } = vi.hoisted(() => ({ server: { settings: null as AppSettings | null } }));
vi.mock("@/api", () => ({
  apiFetch: async (url: string, init?: RequestInit) => {
    if (url !== "/settings") return new Promise(() => {}); // the header's disk bar
    if (init?.method === "PATCH") {
      const patch = JSON.parse(String(init.body)) as Partial<AppSettings>;
      if (patch.sqlite_path) patch.sqlite_path = patch.sqlite_path.replace(/^~\//, "/home/me/");
      server.settings = { ...server.settings!, ...patch };
    }
    return server.settings;
  },
}));

function renderSettings() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  render(<Settings />, { wrapper });
  return client;
}

beforeEach(() => {
  localStorage.clear();
  __testReloadSettings();
  server.settings = { ...INITIAL };
});

describe("Settings SQLite path", () => {
  it("shows the server's path, and keeps an edit while the server's path is unchanged", async () => {
    const client = renderSettings();
    const field = await screen.findByDisplayValue("/data/devdoctor.sqlite3");

    fireEvent.change(field, { target: { value: "/tmp/scratch.sqlite3" } });
    fireEvent.click(screen.getByRole("button", { name: "sqlite" }));
    await waitFor(() =>
      expect(client.getQueryData(["app-settings"])).toMatchObject({ storage_backend: "sqlite" }),
    );

    expect(field).toHaveValue("/tmp/scratch.sqlite3");
  });

  it("shows the path the server saved", async () => {
    renderSettings();
    const field = await screen.findByDisplayValue("/data/devdoctor.sqlite3");

    fireEvent.change(field, { target: { value: " ~/devdoctor.sqlite3 " } });
    fireEvent.click(screen.getByRole("button", { name: "save" }));

    expect(await screen.findByDisplayValue("/home/me/devdoctor.sqlite3")).toBe(field);
  });
});
