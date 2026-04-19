import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { RiskBadge } from "@/components/RiskBadge";

describe("RiskBadge", () => {
  it("renders SAFE in the safe color scheme", () => {
    const { container } = render(<RiskBadge risk="safe" />);
    expect(screen.getByText(/safe/i)).toBeInTheDocument();
    expect(container.firstChild).toHaveAttribute("data-risk", "safe");
  });
  it("renders RECLAIM for reclaimable", () => {
    render(<RiskBadge risk="reclaimable" />);
    expect(screen.getByText(/reclaim/i)).toBeInTheDocument();
  });
  it("renders DANGER for dangerous", () => {
    render(<RiskBadge risk="dangerous" />);
    expect(screen.getByText(/danger/i)).toBeInTheDocument();
  });
});
