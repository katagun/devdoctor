import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ProviderIcon } from "@/components/ProviderIcon";
import { siDocker, siFirefox, siPytorch } from "simple-icons";

describe("ProviderIcon", () => {
  it("renders a subtle placeholder dot for an unknown slug", () => {
    const { container } = render(<ProviderIcon slug="totally-made-up-slug" />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute("aria-hidden")).toBe("true");
    expect(svg?.hasAttribute("role")).toBe(false);
    expect(svg?.getAttribute("opacity")).toBe("0.4");
    expect(container.querySelector("circle")).not.toBeNull();
    expect(container.querySelector("path")).toBeNull();
  });

  it("renders the simple-icons docker path for slug 'docker'", () => {
    const { container } = render(<ProviderIcon slug="docker" />);
    const path = container.querySelector("path");
    expect(path?.getAttribute("d")).toBe(siDocker.path);
    expect(container.querySelector("circle")).toBeNull();
  });

  it("prefix rule matches slug with dash boundary (docker-vm-disk → docker)", () => {
    const { container } = render(<ProviderIcon slug="docker-vm-disk" />);
    const path = container.querySelector("path");
    expect(path?.getAttribute("d")).toBe(siDocker.path);
  });

  it("prefix rule does NOT match when no dash follows (dockerify-foo → placeholder)", () => {
    const { container } = render(<ProviderIcon slug="dockerify-foo" />);
    expect(container.querySelector("circle")).not.toBeNull();
    expect(container.querySelector("path")).toBeNull();
  });

  it("applies the size prop to width and height", () => {
    const { container } = render(<ProviderIcon slug="docker" size={20} />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("width")).toBe("20");
    expect(svg?.getAttribute("height")).toBe("20");
  });

  it("defaults to size=14 when omitted", () => {
    const { container } = render(<ProviderIcon slug="docker" />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("width")).toBe("14");
    expect(svg?.getAttribute("height")).toBe("14");
  });

  it("forwards className to the <svg>", () => {
    const { container } = render(
      <ProviderIcon slug="docker" className="text-text-muted custom-mark" />,
    );
    const svg = container.querySelector("svg");
    expect(svg?.className.baseVal).toContain("text-text-muted");
    expect(svg?.className.baseVal).toContain("custom-mark");
  });

  it("forwards className on the placeholder path too", () => {
    const { container } = render(
      <ProviderIcon slug="no-such-slug" className="text-text-dim" />,
    );
    const svg = container.querySelector("svg");
    expect(svg?.className.baseVal).toContain("text-text-dim");
  });

  it("firefox-cache slug resolves to the firefox icon", () => {
    const { container } = render(<ProviderIcon slug="firefox-cache" />);
    const path = container.querySelector("path");
    expect(path?.getAttribute("d")).toBe(siFirefox.path);
  });

  it("torch-hub-cache slug resolves to the pytorch icon", () => {
    const { container } = render(<ProviderIcon slug="torch-hub-cache" />);
    const path = container.querySelector("path");
    expect(path?.getAttribute("d")).toBe(siPytorch.path);
  });

  it("uv-cache slug resolves to the locally-bundled uv mark", () => {
    const { container } = render(<ProviderIcon slug="uv-cache" />);
    const path = container.querySelector("path");
    // Sanity: non-empty path, not the placeholder dot.
    expect(path).not.toBeNull();
    expect(path?.getAttribute("d")).toMatch(/^M4 5/);
    expect(container.querySelector("circle")).toBeNull();
  });

  it("vscode-cache slug resolves to the locally-bundled vscode mark", () => {
    const { container } = render(<ProviderIcon slug="vscode-cache" />);
    const path = container.querySelector("path");
    expect(path).not.toBeNull();
    expect(path?.getAttribute("d")).toMatch(/^M15 2/);
    expect(container.querySelector("circle")).toBeNull();
  });
});
