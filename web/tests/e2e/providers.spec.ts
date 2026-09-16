import { expect, test } from "@playwright/test";

test("the providers page lists built-in providers this repository ships", async ({ page }) => {
  await page.goto("/disk/providers");
  await expect(page.getByText("node-project-dependencies").first()).toBeVisible();
  await expect(page.getByText("git-worktrees").first()).toBeVisible();
});
