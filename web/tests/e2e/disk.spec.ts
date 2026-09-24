import { expect, test } from "@playwright/test";
import fs from "node:fs";
import { CACHE_LABEL, PROJECT_NAME, STORE_LABEL, cachePath, nodeModulesPath } from "./fixture";

test("the scan lists the fixture entries", async ({ page }) => {
  await page.goto("/disk");
  await expect(page.getByText(CACHE_LABEL).first()).toBeVisible();
  await expect(page.getByText(`${PROJECT_NAME}/node_modules`)).toBeVisible();
  await expect(page.getByText(STORE_LABEL).first()).toBeVisible();
});

test("the safe chip narrows the table without another scan (#104)", async ({ page }) => {
  await page.goto("/disk");
  await expect(page.getByText(`${PROJECT_NAME}/node_modules`)).toBeVisible();
  const scans: string[] = [];
  page.on("request", (request) => {
    if (/\/api\/(disk\/)?scan(\?|$)/.test(request.url())) scans.push(request.url());
  });

  await page.getByRole("button", { name: "safe", exact: true }).click();

  await expect(page.getByText(CACHE_LABEL).first()).toBeVisible();
  await expect(page.getByText(`${PROJECT_NAME}/node_modules`)).toHaveCount(0);
  // The header still describes the whole scan.
  await expect(page.locator("header").getByText(/3 caches/)).toBeVisible();
  expect(scans).toEqual([]);
});

test("selecting one row reads 'clean up 1 item' and the review step runs nothing", async ({
  page,
}) => {
  await page.goto("/disk");
  // Rows are virtualised divs; the row checkbox is labelled "select <provider> <label>".
  const rowCheckbox = page.getByRole("checkbox", { name: new RegExp(`^select ${CACHE_LABEL} `) });
  await expect(rowCheckbox).toBeVisible();

  await rowCheckbox.check();
  const cleanUp = page.getByRole("button", { name: /^clean up 1 item$/ });
  await expect(cleanUp).toBeVisible();

  await cleanUp.click();
  // The wizard opens on its review step: the execute button is offered, not pressed.
  const close = page.getByRole("button", { name: "Close cleanup wizard" });
  await expect(close).toBeVisible();
  await expect(page.getByRole("button", { name: "execute", exact: true })).toBeEnabled();
  await close.click();
  await expect(close).toHaveCount(0);

  expect(fs.existsSync(cachePath())).toBe(true);
  expect(fs.existsSync(nodeModulesPath())).toBe(true);
});

test("the age chips hide fresh rows without another scan, and the scan states its coverage", async ({
  page,
}) => {
  await page.goto("/disk");
  await expect(page.getByText(`${PROJECT_NAME}/node_modules`)).toBeVisible();
  const scans: string[] = [];
  page.on("request", (request) => {
    if (/\/api\/(disk\/)?scan(\?|$)/.test(request.url())) scans.push(request.url());
  });
  // The fixture was written moments ago, so nothing is 30 days untouched.
  await page.getByRole("button", { name: "30d+", exact: true }).click();
  await expect(page.getByText(`${PROJECT_NAME}/node_modules`)).toHaveCount(0);
  await expect(page.getByText(CACHE_LABEL).first()).toHaveCount(0);
  await expect(page.getByText(/^0 shown/)).toBeVisible();
  await expect(page.getByText("(no entries match the chips above)")).toBeVisible();
  await page.getByRole("button", { name: "any age", exact: true }).click();
  await expect(page.getByText(`${PROJECT_NAME}/node_modules`)).toBeVisible();
  expect(scans).toEqual([]);

  // An unfiltered scan says how much of the volume's used space it accounts for.
  await expect(page.getByText(/accounts for .+ of .+ used · \d+%/)).toBeVisible();
});
