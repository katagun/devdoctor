import { expect, test } from "@playwright/test";
import { autoSnapshots } from "./fixture";

test("a full scan writes an auto-snapshot and a filtered scan writes none (#103)", async ({
  page,
}) => {
  await page.goto("/disk");
  await expect(page.getByText(/e2e-sample-cache/).first()).toBeVisible();
  const afterFullScan = autoSnapshots();
  expect(afterFullScan.length).toBeGreaterThanOrEqual(1);

  await page.getByRole("button", { name: "danger", exact: true }).click();
  await expect(page.getByText(/e2e-sample-cache/)).toHaveCount(0);
  expect(autoSnapshots()).toEqual(afterFullScan);

  await page.goto("/disk/snapshots");
  await expect(page.getByText("auto").first()).toBeVisible();
  await page.goto("/disk/history");
  await expect(page.getByRole("heading").first()).toBeVisible();
});
