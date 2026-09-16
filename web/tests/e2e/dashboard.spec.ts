import { expect, test, type Page } from "@playwright/test";
import { CACHE_LABEL } from "./fixture";

test("the dashboard's estimated reclaimable matches the disk page (#102)", async ({ page }) => {
  await page.goto("/disk");
  const headline = page.locator("header").getByText(/estimated reclaimable/);
  await expect(headline).not.toContainText("~0B");
  const disk = (await headline.innerText()).match(/~\S+/)?.[0];
  expect(disk).toBeTruthy();

  // Hold the dashboard's own live scan so only the cached summary from
  // /api/dashboard/disk-summary can feed the tile: that is the path #102 broke,
  // and on a two-entry fixture the live scan would otherwise mask it.
  await page.route(
    (url) => /\/api\/(disk\/)?scan$/.test(url.pathname),
    (route) => {
      setTimeout(() => void route.continue().catch(() => undefined), 30_000);
    },
  );
  await page.goto("/dashboard");
  // The dashboard renders the stat as a label element beside a value element.
  const dashboard = page.getByText("estimated reclaimable", { exact: true }).locator("..");
  await expect(dashboard).not.toContainText("…");
  await expect(dashboard).toContainText(disk!);
});

const SCAN_URL = /\/api\/(disk\/)?scan(\?|$)/;
const DISK_LINK = { name: "disk", exact: true };

function recordScans(page: Page): string[] {
  const scans: string[] = [];
  page.on("request", (request) => {
    if (SCAN_URL.test(request.url())) scans.push(request.url());
  });
  return scans;
}

test("opening the disk page while the dashboard's scan runs joins it (#104)", async ({ page }) => {
  // Hold the scan so it is still in flight when the disk page mounts (long
  // enough for a cold CI browser); two pages used to send two requests here.
  await page.route(SCAN_URL, (route) => {
    setTimeout(() => void route.continue().catch(() => undefined), 5000);
  });
  const scans = recordScans(page);
  await page.goto("/dashboard");
  await expect.poll(() => scans.length).toBe(1);

  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", DISK_LINK).click();
  await expect(page.getByText(CACHE_LABEL).first()).toBeVisible();
  expect(scans).toHaveLength(1);
});

test("within the cadence, the disk page reuses the dashboard's finished scan (#104)", async ({
  page,
}) => {
  await page.addInitScript(() => {
    localStorage.setItem("devdoctor.settings.v1", JSON.stringify({ cadence: "hourly" }));
  });
  const scans = recordScans(page);
  await page.goto("/dashboard");
  await expect(page.getByText("estimated reclaimable", { exact: true }).locator("..")).toContainText(
    "~",
  );
  await expect.poll(() => scans.length).toBe(1);

  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", DISK_LINK).click();
  await expect(page.getByText(CACHE_LABEL).first()).toBeVisible();
  expect(scans).toHaveLength(1);
});
