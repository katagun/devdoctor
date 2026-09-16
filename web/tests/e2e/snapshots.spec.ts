import { expect, test } from "@playwright/test";
import { PROJECT_NAME, PROJECT_PROVIDER, autoSnapshots } from "./fixture";

test("a full scan writes an auto-snapshot and a filtered scan writes none (#103)", async ({
  page,
}) => {
  await page.goto("/disk");
  await expect(page.getByText(/e2e-sample-cache/).first()).toBeVisible();
  const afterFullScan = autoSnapshots();
  expect(afterFullScan.length).toBeGreaterThanOrEqual(1);

  // A provider-filtered scan is the one filter still answered by the server
  // (risk chips filter in the page); wait for its response before checking
  // that it wrote nothing.
  const filteredScan = page.waitForResponse(
    (response) =>
      /\/api\/(disk\/)?scan\?/.test(response.url()) && response.url().includes("provider="),
  );
  await page.goto(`/disk?provider=${PROJECT_PROVIDER}`);
  await filteredScan;
  await expect(page.getByText(`${PROJECT_NAME}/node_modules`)).toBeVisible();
  await expect(page.getByText(/e2e-sample-cache/)).toHaveCount(0);
  expect(autoSnapshots()).toEqual(afterFullScan);

  await page.goto("/disk/snapshots");
  await expect(page.getByText("auto").first()).toBeVisible();
  await page.goto("/disk/history");
  await expect(page.getByRole("heading").first()).toBeVisible();
});
