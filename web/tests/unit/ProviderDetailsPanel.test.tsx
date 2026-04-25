import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { ProviderDetailsPanel } from "@/components/ProviderDetailsPanel";
import type { ProviderRow } from "@/hooks/useProviders";

function classProvider(): ProviderRow {
  return {
    name: "ollama",
    description: "Ollama local LLM models",
    risk: "reclaimable",
    platforms: ["darwin", "linux"],
    available: true,
    required_binary: "ollama",
    kind: "class",
    details: "Models pulled with ollama pull live under ~/.ollama/models.",
    raw_paths: null,
    resolved_paths: null,
    recipe_template: null,
  };
}

function yamlProvider(): ProviderRow {
  return {
    name: "my-yaml",
    description: "yaml driven",
    risk: "safe",
    platforms: ["darwin"],
    available: true,
    required_binary: null,
    kind: "yaml",
    details: null,
    raw_paths: ["~/cache/foo", "~/missing"],
    resolved_paths: ["/Users/me/cache/foo"],
    recipe_template: ["rm -rf {path}", "echo done"],
  };
}

describe("ProviderDetailsPanel", () => {
  it("renders details prose for a class provider", () => {
    render(<ProviderDetailsPanel provider={classProvider()} lastAuto={null} />);
    expect(screen.getByText(/ollama pull/i)).toBeInTheDocument();
    expect(screen.queryByText(/cleanup recipe/i)).not.toBeInTheDocument();
  });

  it("renders raw and resolved paths for a yaml provider", () => {
    render(<ProviderDetailsPanel provider={yamlProvider()} lastAuto={null} />);
    expect(screen.getByText("~/cache/foo")).toBeInTheDocument();
    expect(screen.getByText("/Users/me/cache/foo")).toBeInTheDocument();
    expect(screen.getByText("~/missing")).toBeInTheDocument();
    expect(screen.getByText(/no match/i)).toBeInTheDocument();
  });

  it("renders the recipe template verbatim with {path} preserved", () => {
    render(<ProviderDetailsPanel provider={yamlProvider()} lastAuto={null} />);
    const code = screen.getByTestId("recipe-block");
    expect(within(code).getByText(/rm -rf \{path\}/)).toBeInTheDocument();
    expect(within(code).getByText(/echo done/)).toBeInTheDocument();
  });

  it("omits last-scan section when lastAuto is null", () => {
    render(<ProviderDetailsPanel provider={classProvider()} lastAuto={null} />);
    expect(screen.queryByText(/last scan/i)).not.toBeInTheDocument();
  });

  it("renders last-scan stats when lastAuto is provided", () => {
    render(
      <ProviderDetailsPanel
        provider={classProvider()}
        lastAuto={{ name: "ollama", bytes: 5_000_000_000, entries: 3, duration_ms: 1200 }}
      />,
    );
    expect(screen.getByText(/last scan/i)).toBeInTheDocument();
    expect(screen.getByText(/entries:\s*3/i)).toBeInTheDocument();
    expect(screen.getByText(/1\.2s|1200/)).toBeInTheDocument();
  });

  it("shows globbed resolved paths under the matching raw glob row", () => {
    const provider: ProviderRow = {
      name: "venv",
      description: "venvs",
      risk: "reclaimable",
      platforms: ["darwin"],
      available: true,
      required_binary: null,
      kind: "yaml",
      details: null,
      raw_paths: ["~/projects/*/.venv"],
      resolved_paths: ["/Users/me/proj-a/.venv", "/Users/me/proj-b/.venv"],
      recipe_template: ["rm -rf {path}"],
    };
    render(<ProviderDetailsPanel provider={provider} lastAuto={null} />);

    expect(screen.queryByText(/no match/i)).not.toBeInTheDocument();
    expect(screen.getByText("/Users/me/proj-a/.venv")).toBeInTheDocument();
    expect(screen.getByText("/Users/me/proj-b/.venv")).toBeInTheDocument();
  });
});
