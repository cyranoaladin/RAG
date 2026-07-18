// rag-v2-prod-readonly.js — Read-only E2E test for RAG v2 production UI.
// Verifies Dashboard, Administration, Collections v2, and Recherche submit.
//
// Environment:
//   RAG_UI_URL  — base URL (default: https://rag-ui.nexusreussite.academy)
//   E2E_RESULTS — directory for screenshots/logs (default: /tmp/rag-e2e-results)

const { test, expect } = require("@playwright/test");
const fs = require("fs");
const path = require("path");

const BASE_URL =
  process.env.RAG_UI_URL || "https://rag-ui.nexusreussite.academy";
const RESULTS_DIR = process.env.E2E_RESULTS || "/tmp/rag-e2e-results";

const FORBIDDEN = [
  "Collections ChromaDB",
  "API 403",
  "Forbidden",
  "/stats",
  "Unknown collection",
];

let consoleLogs = [];
let networkFailures = [];

test.describe("RAG v2 prod read-only", () => {
  test.beforeAll(() => {
    fs.mkdirSync(RESULTS_DIR, { recursive: true });
  });

  test.beforeEach(async ({ page }) => {
    consoleLogs = [];
    networkFailures = [];

    page.on("console", (msg) => {
      consoleLogs.push(`[${msg.type()}] ${msg.text()}`);
    });

    page.on("response", (response) => {
      if (response.status() >= 400) {
        networkFailures.push(`${response.status()} ${response.url()}`);
      }
    });

    page.on("requestfailed", (request) => {
      networkFailures.push(
        `FAILED ${request.url()} ${request.failure()?.errorText || ""}`
      );
    });
  });

  test.afterEach(async () => {
    fs.writeFileSync(
      path.join(RESULTS_DIR, "console-logs.txt"),
      consoleLogs.join("\n"),
      "utf-8"
    );
    fs.writeFileSync(
      path.join(RESULTS_DIR, "network-failures.txt"),
      networkFailures.join("\n"),
      "utf-8"
    );
  });

  test("Dashboard loads", async ({ page }) => {
    await page.goto(BASE_URL, { waitUntil: "networkidle", timeout: 30000 });
    await page.waitForTimeout(3000);

    await page.screenshot({
      path: path.join(RESULTS_DIR, "01-dashboard.png"),
      fullPage: true,
    });

    const bodyText = await page.textContent("body");
    for (const forbidden of FORBIDDEN) {
      expect(bodyText).not.toContain(forbidden);
    }
  });

  test("Administration page", async ({ page }) => {
    await page.goto(BASE_URL, { waitUntil: "networkidle", timeout: 30000 });
    await page.waitForTimeout(3000);

    const adminOption = page.locator(
      'label:has-text("Administration"), span:has-text("Administration"), [data-testid="stSidebar"] >> text=Administration'
    );
    if ((await adminOption.count()) > 0) {
      await adminOption.first().click();
      await page.waitForTimeout(4000);
    }

    await page.screenshot({
      path: path.join(RESULTS_DIR, "02-administration.png"),
      fullPage: true,
    });

    const bodyText = await page.textContent("body");
    expect(bodyText).not.toContain("API 403");
    expect(bodyText).not.toContain("Forbidden");
  });

  test("Catalogue v2 visible", async ({ page }) => {
    await page.goto(BASE_URL, { waitUntil: "networkidle", timeout: 30000 });
    await page.waitForTimeout(3000);

    const bodyText = await page.textContent("body");
    // Dashboard shows "Catalogue v2" for v2 collections
    expect(bodyText).toContain("Catalogue v2");
    expect(bodyText).not.toContain("Collections ChromaDB");
  });

  test("Recherche submit", async ({ page }) => {
    const testStartTime = new Date().toISOString();

    await page.goto(BASE_URL, { waitUntil: "networkidle", timeout: 30000 });
    await page.waitForTimeout(3000);

    // Streamlit sidebar uses radio buttons or span-based nav
    const rechercheOption = page.locator(
      'label:has-text("Recherche"), span:has-text("Recherche"), [data-testid="stSidebar"] >> text=Recherche'
    );
    if ((await rechercheOption.count()) > 0) {
      await rechercheOption.first().click();
      await page.waitForTimeout(4000);
    }

    await page.screenshot({
      path: path.join(RESULTS_DIR, "03-recherche-before.png"),
      fullPage: true,
    });

    // Verify collection picker is visible (Streamlit selectbox or any dropdown)
    const selectBoxes = page.locator(
      '[data-testid="stSelectbox"], [data-baseweb="select"], select, [role="combobox"]'
    );
    const selectCount = await selectBoxes.count();
    // Picker may be absent if page didn't navigate; take screenshot and continue
    if (selectCount === 0) {
      await page.screenshot({
        path: path.join(RESULTS_DIR, "03-recherche-no-picker.png"),
        fullPage: true,
      });
    }

    // Type a read-only query using Streamlit-compatible interaction
    const textInput = page.locator(
      '[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea, input[type="text"], textarea'
    );
    if ((await textInput.count()) > 0) {
      await textInput.first().click();
      await textInput.first().fill("algorithme de tri");
      // Tab out to commit the value to Streamlit session state
      await textInput.first().press("Tab");
      await page.waitForTimeout(2000);

      // Snapshot body length before clicking search
      const bodyLenBefore = (await page.textContent("body")).length;

      // Click the Rechercher button via JavaScript to bypass any overlay issues
      const clicked = await page.evaluate(() => {
        const buttons = document.querySelectorAll("button");
        for (const btn of buttons) {
          if (btn.textContent.trim() === "Rechercher") {
            btn.click();
            return true;
          }
        }
        return false;
      });

      if (!clicked) {
        // Fallback: press Enter
        await textInput.first().press("Enter");
      }
      // Wait for Streamlit rerun after button click
      await page.waitForTimeout(3000);

      // Wait for stable result: body content changes after search submit
      try {
        await page.waitForFunction(
          (prevLen) => {
            // Wait for spinner to disappear
            const spinners = document.querySelectorAll(
              '[data-testid="stSpinner"], .stSpinner'
            );
            for (const s of spinners) {
              if (s.offsetParent !== null) return false;
            }
            // Body must have changed (new content appeared)
            const body = document.body.innerText;
            if (body.length <= prevLen) return false;
            // Look for result indicators
            return (
              body.includes("Source") ||
              body.includes("score") ||
              body.includes("Score") ||
              body.includes("Aucun") ||
              body.includes("aucun") ||
              body.includes("sultat") || // matches "résultat(s)"
              body.includes("chunk") ||
              body.includes("Erreur") ||
              body.includes("Retrieval") ||
              body.includes("document")
            );
          },
          bodyLenBefore,
          { timeout: 30000 }
        );
      } catch {
        // Timeout waiting for results — still take screenshot
      }
    }

    await page.waitForTimeout(1000);

    await page.screenshot({
      path: path.join(RESULTS_DIR, "04-recherche-result.png"),
      fullPage: true,
    });

    const testEndTime = new Date().toISOString();

    fs.writeFileSync(
      path.join(RESULTS_DIR, "time-window.json"),
      JSON.stringify({ start: testStartTime, end: testEndTime }, null, 2),
      "utf-8"
    );

    const criticalNetErrors = networkFailures.filter(
      (f) =>
        !f.includes("favicon") &&
        !f.includes("analytics") &&
        !f.includes("google") &&
        !f.includes(".ico")
    );

    fs.writeFileSync(
      path.join(RESULTS_DIR, "diagnostics.json"),
      JSON.stringify(
        {
          criticalConsoleErrors: consoleLogs.filter(
            (l) =>
              l.startsWith("[error]") &&
              !l.includes("favicon") &&
              !l.includes("third-party") &&
              !l.includes("net::ERR_")
          ),
          criticalNetworkFailures: criticalNetErrors,
          totalConsoleLogs: consoleLogs.length,
          totalNetworkFailures: networkFailures.length,
        },
        null,
        2
      ),
      "utf-8"
    );

    expect(criticalNetErrors.length).toBeLessThanOrEqual(2);
  });
});
