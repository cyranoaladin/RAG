#!/usr/bin/env node
/*
 * LOT 27 P3 — validation visuelle Playwright strictement read-only.
 *
 * Variables :
 *   RAG_UI_URL  URL publique de l'interface Streamlit.
 *   E2E_RESULTS Répertoire des captures et diagnostics.
 */

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const BASE_URL = process.env.RAG_UI_URL || "https://rag-ui.nexusreussite.academy";
const RESULTS_DIR = process.env.E2E_RESULTS || "/tmp/rag-lot27-p3-e2e-results";
const UI_HOST = new URL(BASE_URL).host;

const FORBIDDEN_RENDERED_TEXT = [
  "API 403",
  "Forbidden",
  "/stats",
  "Collections ChromaDB",
  "rag_francais_premiere",
  "rag_maths_premiere",
  "rag_education",
  "rag_web3",
  "rag_divers",
  "http://ingestor:8001",
];

const PAGES = [
  {
    navigation: "Dashboard",
    screenshot: "01-dashboard.png",
    expected: [
      "Dashboard RAG v2",
      "Catalogue scolaire Nexus Réussite",
      "Déclarées",
      "Instanciées",
      "Non instanciées",
      "Quarantaine",
      "Tableau du catalogue",
    ],
  },
  {
    navigation: "Recherche",
    screenshot: "02-recherche.png",
    expected: [
      "Recherche RAG v2",
      "Seules les collections instanciées et interrogeables (retrievable) sont proposées.",
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
      "Métadonnées générées côté serveur",
      "needs_review",
      "Drive v2 non activé",
    ],
  },
  {
    navigation: "Administration",
    screenshot: "04-administration.png",
    expected: [
      "Administration RAG v2",
      "Catalogue v2 complet",
      "Collections instanciées",
      "Collections déclarées non instanciées",
      "Collections retrievable",
      "Quarantaine",
      "Contrôles de cohérence",
    ],
  },
];

const consoleLogs = [];
const networkEvents = [];
const networkFailures = [];
const blockedRequests = [];
const pageFailures = [];
const responseDiagnostics = [];

function isRelevant(url) {
  try {
    return new URL(url).host === UI_HOST;
  } catch {
    return false;
  }
}

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
    if (isRelevant(request.url())) {
      networkFailures.push({
        page: pageName,
        method: request.method(),
        error: request.failure()?.errorText || "request failed",
        url: request.url(),
      });
    }
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
  networkEvents.push(event);
  if (response.status() >= 400) {
    networkFailures.push(event);
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
      // Une chaîne dans un bundle JavaScript n'est pas du contenu rendu : la
      // conserver comme diagnostic, sans la confondre avec une erreur HTTP.
      event.forbiddenResponseText = forbidden;
    }
  } catch (error) {
    networkFailures.push({
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
    await route.abort("blockedbyclient");
  });
}

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
      throw new Error(`${scenario.navigation}: libellé attendu absent : ${expected}`);
    }
  }
  for (const forbidden of FORBIDDEN_RENDERED_TEXT) {
    if (body.includes(forbidden)) {
      throw new Error(`${scenario.navigation}: contenu interdit affiché : ${forbidden}`);
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
    await page.screenshot({
      path: path.join(RESULTS_DIR, scenario.screenshot),
      fullPage: true,
    });
    await page.close();
  }
}

function writeArtifacts() {
  fs.mkdirSync(RESULTS_DIR, { recursive: true });
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
    path.join(RESULTS_DIR, "network-failures.json"),
    `${JSON.stringify(networkFailures, null, 2)}\n`,
    "utf8",
  );
  fs.writeFileSync(
    path.join(RESULTS_DIR, "blocked-requests.json"),
    `${JSON.stringify(blockedRequests, null, 2)}\n`,
    "utf8",
  );
}

async function main() {
  fs.mkdirSync(RESULTS_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await guardRequests(context);

  try {
    for (const scenario of PAGES) {
      try {
        await verifyPage(context, scenario);
      } catch (error) {
        pageFailures.push(error instanceof Error ? error.message : String(error));
      }
    }
  } finally {
    await Promise.allSettled(responseDiagnostics);
    await context.close();
    await browser.close();
    writeArtifacts();
  }

  const consoleErrors = consoleLogs.filter(
    (entry) =>
      entry.type === "error" &&
      // Le garde-fou bloque volontairement toute télémétrie d'un tiers.
      // Ce bruit navigateur n'est pas une erreur de l'UI RAG observée.
      !entry.text.includes("ERR_BLOCKED_BY_CLIENT"),
  );
  const failures = [
    ...pageFailures,
    ...blockedRequests
      .filter((entry) => isRelevant(entry.url))
      .map((entry) => `requête non read-only bloquée : ${entry.method} ${entry.url}`),
    ...networkFailures.map((entry) => `échec réseau : ${JSON.stringify(entry)}`),
    ...consoleErrors.map((entry) => `erreur console : ${entry.text}`),
  ];
  if (failures.length > 0) {
    throw new Error(`Échec E2E LOT 27 P3:\n- ${failures.join("\n- ")}`);
  }

  console.log(`E2E LOT 27 P3 read-only OK — résultats : ${RESULTS_DIR}`);
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
