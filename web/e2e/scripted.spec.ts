import { expect, test } from "@playwright/test";
import { runToVerdict, watchErrors } from "./helpers";

// Demo mode: the real FastAPI server, event stream and local sandbox, with prewritten model
// answers instead of Nemotron, so no credit is spent.
const SERVICES = ["order-service", "webhook-service"];

test("the server badge says the run is scripted, with no hosting notice", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Demo: scripted model responses, no Nemotron calls")).toBeVisible();
  await expect(page.getByRole("complementary", { name: "How this demo is hosted" })).toHaveCount(0);
});

for (const service of SERVICES) {
  test(`runs ${service} through the API to a proposed fix and a pull request preview`, async ({
    page,
  }) => {
    const errors = watchErrors(page);
    await page.goto("/");
    const evidence = await runToVerdict(page, service, "Break it and repair it");

    await page.getByRole("button", { name: /Proposed fix/ }).click();
    await expect(evidence.getByLabel("Patch")).toBeVisible();

    await page.getByRole("button", { name: "Preview the pull request" }).click();
    await expect(page.getByText("the hosted demo only previews")).toBeVisible();
    await expect(page.locator(".pr-files li").first()).toBeVisible();
    expect(errors).toEqual([]);
  });
}
