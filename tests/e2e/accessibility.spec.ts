import { expect, test } from "@playwright/test";
import axe from "axe-core";

test("homepage has no automatically detectable WCAG A/AA violations", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("main")).toBeVisible();
  await page.addScriptTag({ content: axe.source });

  const violations = await page.evaluate(async () => {
    const axeApi = (globalThis as typeof globalThis & {
      axe: {
        run: (
          context: Document,
          options: { runOnly: { type: string; values: string[] } },
        ) => Promise<{
          violations: Array<{
            id: string;
            help: string;
            nodes: Array<{ target: unknown; html: string; failureSummary?: string }>;
          }>;
        }>;
      };
    }).axe;
    const result = await axeApi.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
    });
    return result.violations.map(({ id, help, nodes }) => ({ id, help, nodes }));
  });

  expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
});
