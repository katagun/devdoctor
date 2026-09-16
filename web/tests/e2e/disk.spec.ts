import { expect, test } from "@playwright/test";
import fs from "node:fs";
import { CACHE_LABEL, PROJECT_NAME, cachePath, nodeModulesPath } from "./fixture";

test("the scan lists both fixture entries", async ({ page }) => {
  await page.goto("/disk");
  await expect(page.getByText(CACHE_LABEL).first()).toBeVisible();
  await expect(page.getByText(`${PROJECT_NAME}/node_modules`)).toBeVisible();
});

test("the safe chip narrows the table to safe entries", async ({ page }) => {
  await page.goto("/disk");
  await expect(page.getByText(`${PROJECT_NAME}/node_modules`)).toBeVisible();

  await page.getByRole("button", { name: "safe", exact: true }).click();

  await expect(page.getByText(CACHE_LABEL).first()).toBeVisible();
  await expect(page.getByText(`${PROJECT_NAME}/node_modules`)).toHaveCount(0);
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
  await expect(page.getByText(/estimated reclaimable/).last()).toBeVisible();
  await page.getByRole("button", { name: "Close cleanup wizard" }).click();

  expect(fs.existsSync(cachePath())).toBe(true);
  expect(fs.existsSync(nodeModulesPath())).toBe(true);
});
