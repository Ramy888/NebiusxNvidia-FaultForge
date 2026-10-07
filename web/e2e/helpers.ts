import { expect, type Page } from "@playwright/test";

/** Collects uncaught page errors and console errors, so a test can assert the page stayed clean. */
export function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  return errors;
}

/** Picks a service, starts a run with the given button, and waits for the verdict. */
export async function runToVerdict(page: Page, service: string, button: string) {
  // The radio input is visually hidden behind its card, so pick the card a person would click.
  await page.locator("label.example", { hasText: service }).click();
  await expect(page.locator(`input[name="example"][value="${service}"]`)).toBeChecked();
  await page.getByRole("button", { name: button }).click();
  await expect(page.getByRole("list", { name: "Run progress" })).toBeVisible();
  await expect(page.getByText("Proposed fix")).toBeVisible();
  const evidence = page.getByRole("region", { name: "Evidence" });
  await expect(evidence).toContainText("A repair fixed the reproduced failure");
  await expect(page.getByRole("status")).toContainText("Reproduced:");
  return evidence;
}
