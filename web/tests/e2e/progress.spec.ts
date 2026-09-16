import { expect, test } from "@playwright/test";
import { CACHE_LABEL } from "./fixture";

const SCAN_URL = /\/api\/(disk\/)?scan(\?|$)/;
const PROGRESS_URL = /\/api\/scan\/progress(\?|$)/;

function frame(data: object): string {
  return `event: progress\ndata: ${JSON.stringify(data)}\n\n`;
}

const RUNNING = {
  scan_id: 1,
  status: "running",
  started_at: "2026-09-15T10:00:00+00:00",
  total: 3,
  done: 1,
  running: [CACHE_LABEL],
  entries: 1,
  bytes: 300_000,
  providers: [],
};

test("the loading line follows the progress stream while the scan is held (#117)", async ({
  page,
}) => {
  // The fixture scan finishes in milliseconds, so hold the scan and answer the
  // stream with a canned snapshot: this proves the page wires the stream in.
  await page.route(SCAN_URL, (route) => {
    setTimeout(() => void route.continue().catch(() => undefined), 4000);
  });
  await page.route(PROGRESS_URL, (route) =>
    route.fulfill({ status: 200, contentType: "text/event-stream", body: frame(RUNNING) }),
  );
  await page.goto("/disk");

  const loading = page.getByText(/^scanning…/);
  await expect(loading).toContainText("1/3 providers");
  await expect(loading).toContainText(`running: ${CACHE_LABEL}`);
  await expect(page.getByRole("progressbar", { name: "scan progress" })).toHaveAttribute(
    "aria-valuenow",
    "1",
  );

  await expect(page.getByText(CACHE_LABEL).first()).toBeVisible();
  await expect(loading).toHaveCount(0);
});

test("the loading line says finishing once every provider is done (#117)", async ({ page }) => {
  await page.route(SCAN_URL, (route) => {
    setTimeout(() => void route.continue().catch(() => undefined), 4000);
  });
  await page.route(PROGRESS_URL, (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: frame({ ...RUNNING, status: "done", done: 3, running: [] }),
    }),
  );
  await page.goto("/disk");

  await expect(page.getByText(/^scanning…/)).toContainText("3/3 providers · finishing…");
});

test("the server answers /api/scan/progress with an event stream (#117)", async ({ page }) => {
  await page.goto("/disk");
  const first = await page.evaluate(async () => {
    const controller = new AbortController();
    const response = await fetch("/api/scan/progress", { signal: controller.signal });
    const reader = response.body!.getReader();
    const { value } = await reader.read();
    controller.abort();
    return {
      contentType: response.headers.get("content-type"),
      text: new TextDecoder().decode(value),
    };
  });
  expect(first.contentType).toContain("text/event-stream");
  expect(first.text).toContain("event: progress");
  expect(first.text).toContain('"scan_id"');
});
