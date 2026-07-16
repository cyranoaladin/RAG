#!/usr/bin/env node
/*
 * LOT 27 P3 — validation visuelle Playwright strictement read-only.
 *
 * Variables :
 *   RAG_UI_URL   URL publique de l'interface Streamlit.
 *   E2E_RESULTS  Repertoire des captures et diagnostics.
 *   E2E_MODE     Mode de validation :
 *                  current-prod  — production actuelle (pre-P3)
 *                  p3-preview    — instance locale executant le code P3
 *                  post-deploy   — production apres deploiement P3
 */

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const BASE_URL = process.env.RAG_UI_URL || "https://rag-ui.nexusreussite.academy";
const RESULTS_DIR = process.env.E2E_RESULTS || "/tmp/rag-lot27-p3-e2e-results";
const E2E_MODE = process.env.E2E_MODE || "current-prod";
const UI_HOST = new URL(BASE_URL).host;

if (!["current-prod", "p3-preview", "post-deploy"].includes(E2E_MODE)) {
  console.error(`E2E_MODE invalide : ${E2E_MODE}. Valeurs : current-prod, p3-preview, post-deploy`);
  process.exit(1);
}

// -- Textes interdits (communs a tous les modes) ----------------------------

const FORBIDDEN_COMMON = [
  "API 403",
  "Forbidden",
  "/stats",
  "Collections ChromaDB",
  "rag_francais_premiere",
  "rag_maths_premiere",
  "rag_education",
  "rag_web3",
  "rag_divers",
];

// En mode P3/post-deploy l'URL interne ne doit plus etre visible.
const FORBIDDEN_P3 = [...FORBIDDEN_COMMON, "http://ingestor:8001"];

const FORBIDDEN_RENDERED_TEXT = E2E_MODE === "current-prod" ? FORBIDDEN_COMMON : FORBIDDEN_P3;

// -- Assertions par page et par mode ----------------------------------------

const PAGES_CURRENT_PROD = [
  {
    navigation: "Dashboard",
    screenshot: "01-dashboard.png",
    expected: [
      "Dashboard RAG v2",
      "D\u00e9clar\u00e9es",
      "Instanci\u00e9es",
      "Non instanci\u00e9es",
      "Quarantaine",
    ],
  },
  {
    navigation: "Recherche",
    screenshot: "02-recherche.png",
    expected: ["Recherche RAG v2", "Collection cible"],
  },
  {
    navigation: "Ingestion",
    screenshot: "03-ingestion.png",
    expected: ["Ingestion RAG v2", "Collection cible", "Type de document", "Droits"],
  },
  {
    navigation: "Administration",
    screenshot: "04-administration.png",
    expected: [
      "Administration RAG v2",
      "Catalogue v2 complet",
      "Collections instanci\u00e9es",
      "Collections retrievable",
      "Quarantaine",
    ],
  },
];

const PAGES_P3 = [
  {
    navigation: "Dashboard",
    screenshot: "01-dashboard.png",
    expected: [
      "Dashboard RAG v2",
      "Catalogue scolaire Nexus R\u00e9ussite",
      "D\u00e9clar\u00e9es",
      "Instanci\u00e9es",
      "Non instanci\u00e9es",
      "Quarantaine",
      "Tableau du catalogue",
    ],
  },
  {
    navigation: "Recherche",
    screenshot: "02-recherche.png",
    expected: [
      "Recherche RAG v2",
      "Seules les collections instanci\u00e9es et interrogeables (retrievable) sont propos\u00e9es.",
      "Collection cible",
    ],
  },
  {
    navigation: "Ingestion",
    screenshot: "03-ingestion.png",
    expected: [
      "Ingestion RAG v2",
      "Collection cible",
      "Type de document",
      "Droits",
      "needs_review",
      // "Drive v2 non activé" est dans l'onglet Google Drive, masqué par défaut.
      // Streamlit innerText ne capture que l'onglet actif (Upload fichiers).
      "Google Drive",
    ],
  },
  {
    navigation: "Administration",
    screenshot: "04-administration.png",
    expected: [
      "Administration RAG v2",
      "Catalogue v2 complet",
      "Collections instanci\u00e9es",
      "Collections d\u00e9clar\u00e9es non instanci\u00e9es",
      "Collections retrievable",
      "Quarantaine",
      "Contr\u00f4les de coh\u00e9rence",
    ],
  },
];

const PAGES = E2E_MODE === "current-prod" ? PAGES_CURRENT_PROD : PAGES_P3;

// -- Collecteurs ------------------------------------------------------------

const consoleLogs = [];
const networkEvents = [];
const blockedRequests = [];
const pageFailures = [];
const screenshotFailures = [];
const pageResults = [];
const responseDiagnostics = [];

// Categorised failures
const networkFailuresBlocking = [];
const networkWarningsNonBlocking = [];
const thirdPartyBlocked = [];
const streamlitInfraNoise = [];

// -- Helpers ----------------------------------------------------------------

function isRelevant(url) {
  try {
    return new URL(url).host === UI_HOST;
  } catch {
    return false;
  }
}

function isStcoreEndpoint(url) {
  try {
    return new URL(url).pathname.startsWith("/_stcore/");
  } catch {
    return false;
  }
}

function isJavaScriptBundle(url) {
  try {
    const pathname = new URL(url).pathname;
    return pathname.startsWith("/static/") && pathname.endsWith(".js");
  } catch {
    return false;
  }
}

function isStaticAsset(url) {
  try {
    const pathname = new URL(url).pathname;
    return pathname.startsWith("/static/");
  } catch {
    return false;
  }
}

function isPostDeployCriticalConsoleError(entry) {
  if (E2E_MODE !== "post-deploy") {
    return false;
  }

  return (
    entry.text.includes("ChunkLoadError") ||
    entry.text.includes("status of 502") ||
    entry.text.includes("Unexpected response code: 502") ||
    entry.text.includes("MIME type")
  );
}

function isStaticBundleConsoleNoise(entry) {
  return (
    entry.text.includes("ChunkLoadError") ||
    entry.text.includes("status of 502") ||
    entry.text.includes("Unexpected response code: 502") ||
    entry.text.includes("MIME type")
  );
}

function isRagHost5xxFailure(errorText) {
  return (
    errorText.includes("Unexpected response code: 502") ||
    /\b(?:HTTP\/?\d?(?:\.\d)?\s+|status(?:\s+code)?(?:\s+of)?\s*|response(?:\s+code)?\s*)5\d\d\b/i.test(
      errorText,
    )
  );
}

// -- Event recording --------------------------------------------------------

function recordPageEvents(page, pageName) {
  page.on("console", (message) => {
    consoleLogs.push({
      page: pageName,
      type: message.type(),
      text: message.text(),
    });
  });

  page.on("response", (response) => {
    responseDiagnostics.push(recordResponse(response, pageName));
  });

  page.on("requestfailed", (request) => {
    const errorText = request.failure()?.errorText || "request failed";
    const url = request.url();
    const entry = { page: pageName, method: request.method(), error: errorText, url };

    if (!isRelevant(url)) {
      return;
    }
    // A failed Streamlit WebSocket handshake can have no response event. Keep
    // an upstream 5xx blocking before classifying /_stcore/ as infra noise.
    if (isRagHost5xxFailure(errorText)) {
      networkFailuresBlocking.push(entry);
      return;
    }
    if (isStcoreEndpoint(url)) {
      streamlitInfraNoise.push(entry);
      return;
    }
    if (errorText.includes("ERR_NETWORK_CHANGED") || errorText.includes("ERR_ABORTED")) {
      if (isStaticAsset(url)) {
        networkWarningsNonBlocking.push(entry);
      } else {
        networkFailuresBlocking.push(entry);
      }
      return;
    }
    networkFailuresBlocking.push(entry);
  });
}

async function recordResponse(response, pageName) {
  if (!isRelevant(response.url())) {
    return;
  }

  const request = response.request();
  const event = {
    page: pageName,
    method: request.method(),
    status: response.status(),
    url: response.url(),
  };
  const forbiddenUrlToken = FORBIDDEN_RENDERED_TEXT.find((value) =>
    event.url.includes(value),
  );
  if (forbiddenUrlToken) {
    event.forbiddenUrlToken = forbiddenUrlToken;
  }
  networkEvents.push(event);

  // Every server error from the RAG UI host is a go-live failure. This branch
  // intentionally precedes Streamlit and static-asset classifications.
  if (response.status() >= 500) {
    networkFailuresBlocking.push(event);
  } else if (response.status() >= 400) {
    if (isStcoreEndpoint(event.url)) {
      streamlitInfraNoise.push(event);
    } else if (isStaticAsset(event.url)) {
      networkWarningsNonBlocking.push(event);
    } else {
      networkFailuresBlocking.push(event);
    }
  }
  if (forbiddenUrlToken) {
    networkFailuresBlocking.push({ ...event });
  }

  const contentType = response.headers()["content-type"] || "";
  if (!/(?:text|json|javascript|xml)/i.test(contentType)) {
    return;
  }

  try {
    const text = await responseTextWithin(response, 2_000);
    if (text === null) {
      event.responseTextInspection = "timed_out";
      return;
    }
    const forbidden = FORBIDDEN_RENDERED_TEXT.find((value) => text.includes(value));
    if (forbidden) {
      event.forbiddenResponseText = forbidden;
      if (!isJavaScriptBundle(event.url)) {
        networkFailuresBlocking.push({ ...event });
      }
    }
  } catch (error) {
    networkFailuresBlocking.push({
      ...event,
      error: error instanceof Error ? error.message : String(error),
    });
  }
}

function responseTextWithin(response, timeoutMs) {
  return new Promise((resolve) => {
    const timeout = setTimeout(() => resolve(null), timeoutMs);
    response
      .text()
      .then((text) => {
        clearTimeout(timeout);
        resolve(text);
      })
      .catch(() => {
        clearTimeout(timeout);
        resolve(null);
      });
  });
}

// -- Read-only guard --------------------------------------------------------

async function guardRequests(context) {
  await context.route("**/*", async (route) => {
    const request = route.request();
    const method = request.method();
    const url = request.url();
    const permitted = method === "GET" || method === "HEAD" || method === "OPTIONS";

    if (permitted) {
      await route.continue();
      return;
    }

    blockedRequests.push({ method, url });
    if (isRelevant(url)) {
      thirdPartyBlocked.push({ method, url, reason: "non-read-only on RAG host" });
    } else {
      thirdPartyBlocked.push({ method, url, reason: "third-party" });
    }
    await route.abort("blockedbyclient");
  });
}

// -- Navigation and assertion -----------------------------------------------

async function waitForText(page, value) {
  await page.waitForFunction((expected) => document.body.innerText.includes(expected), value, {
    timeout: 30_000,
  });
}

async function navigate(page, label) {
  if (label === "Dashboard") {
    return;
  }

  const sidebarLabel = page
    .locator('[data-testid="stSidebar"] label')
    .filter({ hasText: new RegExp(`^${label}$`) })
    .first();

  if (await sidebarLabel.count()) {
    await sidebarLabel.click();
  } else {
    await page.getByText(label, { exact: true }).first().click();
  }
  await page.waitForTimeout(750);
}

function assertExpectedText(body, scenario) {
  for (const expected of scenario.expected) {
    if (!body.includes(expected)) {
      throw new Error(`${scenario.navigation}: libelle attendu absent : ${expected}`);
    }
  }
  for (const forbidden of FORBIDDEN_RENDERED_TEXT) {
    if (body.includes(forbidden)) {
      throw new Error(`${scenario.navigation}: contenu interdit affiche : ${forbidden}`);
    }
  }
}

async function verifyPage(context, scenario) {
  const page = await context.newPage();
  recordPageEvents(page, scenario.navigation);
  try {
    await page.goto(BASE_URL, { waitUntil: "domcontentloaded", timeout: 30_000 });
    await waitForText(page, "Dashboard RAG v2");
    await navigate(page, scenario.navigation);
    await waitForText(page, scenario.expected[0]);
    await page.waitForTimeout(750);

    const body = await page.locator("body").innerText();
    assertExpectedText(body, scenario);
  } finally {
    const screenshotPath = path.join(RESULTS_DIR, scenario.screenshot);
    try {
      await page.screenshot({
        path: screenshotPath,
        fullPage: true,
      });
    } catch (error) {
      screenshotFailures.push(
        `${scenario.navigation}: capture impossible : ${error instanceof Error ? error.message : String(error)}`,
      );
    }
    await page.close();
  }

  return { navigation: scenario.navigation, screenshot: scenario.screenshot };
}

// -- Artifacts --------------------------------------------------------------

function validatePageArtifacts() {
  const successfulPages = new Set(pageResults.map((result) => result.navigation));

  if (pageResults.length !== PAGES.length || successfulPages.size !== PAGES.length) {
    screenshotFailures.push(
      `pages valides insuffisantes : ${successfulPages.size}/${PAGES.length}`,
    );
  }

  for (const scenario of PAGES) {
    const screenshotPath = path.join(RESULTS_DIR, scenario.screenshot);
    if (!fs.existsSync(screenshotPath)) {
      screenshotFailures.push(`${scenario.navigation}: capture absente`);
      continue;
    }
    if (fs.statSync(screenshotPath).size === 0) {
      screenshotFailures.push(`${scenario.navigation}: capture vide`);
    }
  }
}

function writeArtifacts() {
  fs.mkdirSync(RESULTS_DIR, { recursive: true });
  const categorised = {
    network_failures_blocking: networkFailuresBlocking,
    network_warnings_non_blocking: networkWarningsNonBlocking,
    third_party_blocked: thirdPartyBlocked,
    streamlit_infra_noise: streamlitInfraNoise,
  };
  fs.writeFileSync(
    path.join(RESULTS_DIR, "console-logs.json"),
    `${JSON.stringify(consoleLogs, null, 2)}\n`,
    "utf8",
  );
  fs.writeFileSync(
    path.join(RESULTS_DIR, "network-events.json"),
    `${JSON.stringify(networkEvents, null, 2)}\n`,
    "utf8",
  );
  fs.writeFileSync(
    path.join(RESULTS_DIR, "network-categorised.json"),
    `${JSON.stringify(categorised, null, 2)}\n`,
    "utf8",
  );
  fs.writeFileSync(
    path.join(RESULTS_DIR, "blocked-requests.json"),
    `${JSON.stringify(blockedRequests, null, 2)}\n`,
    "utf8",
  );
  fs.writeFileSync(
    path.join(RESULTS_DIR, "e2e-summary.json"),
    `${JSON.stringify({ page_results: pageResults, screenshot_failures: screenshotFailures }, null, 2)}\n`,
    "utf8",
  );
}

// -- Main -------------------------------------------------------------------

async function main() {
  console.log(`E2E LOT 27 P3 — mode: ${E2E_MODE}, url: ${BASE_URL}`);
  fs.mkdirSync(RESULTS_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await guardRequests(context);

  try {
    for (const scenario of PAGES) {
      try {
        pageResults.push(await verifyPage(context, scenario));
      } catch (error) {
        pageFailures.push(error instanceof Error ? error.message : String(error));
      }
    }
  } finally {
    await Promise.allSettled(responseDiagnostics);
    await context.close();
    await browser.close();
  }

  validatePageArtifacts();
  writeArtifacts();

  // Console errors: filter only genuine non-infra errors
  const consoleErrors = consoleLogs.filter(
    (entry) =>
      entry.type === "error" &&
      !entry.text.includes("ERR_BLOCKED_BY_CLIENT") &&
      !entry.text.includes("Segment snippet") &&
      !(isStaticBundleConsoleNoise(entry) && E2E_MODE !== "post-deploy") &&
      (!entry.text.includes("_stcore/") || isPostDeployCriticalConsoleError(entry)),
  );

  // Static assets may be noisy, except when a post-deploy bundle failed to load.
  const consoleBlocking = consoleErrors.filter(
    (entry) => {
      if (isPostDeployCriticalConsoleError(entry)) {
        return true;
      }
      return !entry.text.includes("ERR_NETWORK_CHANGED") && !entry.text.includes("ERR_ABORTED");
    },
  );

  // RAG-host blocked requests are blocking
  const ragHostBlocked = blockedRequests.filter((entry) => isRelevant(entry.url));

  const failures = [
    ...pageFailures,
    ...screenshotFailures,
    ...ragHostBlocked.map((e) => `requete non read-only bloquee : ${e.method} ${e.url}`),
    ...networkFailuresBlocking.map((e) => `echec reseau : ${JSON.stringify(e)}`),
    ...consoleBlocking.map((e) => `erreur console : ${e.text}`),
  ];

  // Summary
  console.log(`\n--- Resultats E2E LOT 27 P3 (${E2E_MODE}) ---`);
  console.log(`Pages testees       : ${PAGES.length}`);
  console.log(`Echecs page         : ${pageFailures.length}`);
  console.log(`Reseau bloquant     : ${networkFailuresBlocking.length}`);
  console.log(`Reseau warnings     : ${networkWarningsNonBlocking.length}`);
  console.log(`Streamlit infra     : ${streamlitInfraNoise.length}`);
  console.log(`Tiers bloques       : ${thirdPartyBlocked.filter((e) => e.reason === "third-party").length}`);
  console.log(`RAG host bloques    : ${ragHostBlocked.length}`);
  console.log(`Console bloquant    : ${consoleBlocking.length}`);
  console.log(`Artefacts           : ${RESULTS_DIR}`);

  if (networkWarningsNonBlocking.length > 0) {
    console.log(`\nP3-warnings (non bloquants) :`);
    for (const w of networkWarningsNonBlocking) {
      console.log(`  ${w.status || w.error} ${w.url}`);
    }
  }

  if (failures.length > 0) {
    console.log("");
    throw new Error(`Echec E2E LOT 27 P3 (${E2E_MODE}):\n- ${failures.join("\n- ")}`);
  }

  for (const result of pageResults) {
    console.log(`Page PASS : ${result.navigation} (${result.screenshot})`);
  }
  console.log(`\nE2E LOT 27 P3 (${E2E_MODE}) PASS`);
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
