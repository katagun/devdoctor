import { expect, test } from "@playwright/test";

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
