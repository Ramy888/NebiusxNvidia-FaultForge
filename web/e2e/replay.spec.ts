import { expect, test } from "@playwright/test";
import { runToVerdict, watchErrors } from "./helpers";

const SERVICES = ["order-service", "webhook-service", "hook-slinger"];

test("the static page says it only hosts files and makes no model calls", async ({ page }) => {
  await page.goto("/");
  const notice = page.getByRole("complementary", { name: "How this demo is hosted" });
  await expect(notice).toContainText("static hosting only");
  await expect(notice).toContainText("makes no model calls");
  await expect(notice).toContainText("Nebius Token Factory");
});

for (const service of SERVICES) {
  test(`replays the recorded ${service} run to a proposed fix`, async ({ page }) => {
    const errors = watchErrors(page);
    await page.goto("/");
    const evidence = await runToVerdict(page, service, "Replay the recorded run");

    await expect(evidence.getByLabel("Patch")).toBeVisible();
    // Replays have no server, so there is nothing to open a pull request with.
    await expect(page.getByRole("button", { name: "Preview the pull request" })).toHaveCount(0);
    expect(errors).toEqual([]);
  });
}
