import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ProviderIcon } from "@/components/ProviderIcon";
import { siDocker } from "simple-icons";

describe("ProviderIcon", () => {
  it("renders a placeholder rect for an unknown slug", () => {
    const { container } = render(<ProviderIcon slug="totally-made-up-slug" />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute("aria-hidden")).toBe("true");
    expect(svg?.hasAttribute("role")).toBe(false);
    expect(container.querySelector("rect")).not.toBeNull();
    expect(container.querySelector("path")).toBeNull();
  });

  it("renders the simple-icons docker path for slug 'docker'", () => {
    const { container } = render(<ProviderIcon slug="docker" />);
    const path = container.querySelector("path");
    expect(path?.getAttribute("d")).toBe(siDocker.path);
    expect(container.querySelector("rect")).toBeNull();
  });

  it("prefix rule matches slug with dash boundary (docker-vm-disk → docker)", () => {
    const { container } = render(<ProviderIcon slug="docker-vm-disk" />);
    const path = container.querySelector("path");
    expect(path?.getAttribute("d")).toBe(siDocker.path);
  });

  it("prefix rule does NOT match when no dash follows (dockerify-foo → placeholder)", () => {
    const { container } = render(<ProviderIcon slug="dockerify-foo" />);
    expect(container.querySelector("rect")).not.toBeNull();
    expect(container.querySelector("path")).toBeNull();
  });
});
