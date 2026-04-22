import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ProviderIcon } from "@/components/ProviderIcon";

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
});
