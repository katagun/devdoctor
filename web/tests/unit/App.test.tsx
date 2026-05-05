import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { LandingRedirect } from "@/App";
import { __testReloadSettings } from "@/hooks/useSettings";

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderLandingRedirect() {
  render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<LandingRedirect />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("LandingRedirect", () => {
  beforeEach(() => {
    localStorage.clear();
    __testReloadSettings();
  });

  it("opens dashboard by default", async () => {
    renderLandingRedirect();

    expect(await screen.findByTestId("location")).toHaveTextContent("/dashboard");
  });

  it("can open disk from local settings", async () => {
    localStorage.setItem(
      "diskdoctor.settings.v1",
      JSON.stringify({ landingPage: "disk" }),
    );
    __testReloadSettings();

    renderLandingRedirect();

    expect(await screen.findByTestId("location")).toHaveTextContent("/disk");
  });

  it("can open memory from local settings", async () => {
    localStorage.setItem(
      "diskdoctor.settings.v1",
      JSON.stringify({ landingPage: "memory" }),
    );
    __testReloadSettings();

    renderLandingRedirect();

    expect(await screen.findByTestId("location")).toHaveTextContent("/memory");
  });
});
