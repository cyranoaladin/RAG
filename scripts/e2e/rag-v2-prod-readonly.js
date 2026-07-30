#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { chromium, request } = require("playwright");
const { assertReadOnlyRequest } = require("./read_only_policy");

const UI_URL = process.env.RAG_E2E_UI_URL;
const API_URL = process.env.RAG_E2E_API_URL;
const STUDENT_TOKEN = process.env.RAG_E2E_STUDENT_TOKEN;
const RESULTS_DIR = process.env.E2E_RESULTS;

for (const [name, value] of Object.entries({ UI_URL, API_URL, STUDENT_TOKEN, RESULTS_DIR })) {
  if (!value) {
    throw new Error(`${name} est obligatoire pour l'E2E production read-only`);
  }
}

const origins = {
  ui: new URL(UI_URL).origin,
  api: new URL(API_URL).origin,
};
const blockedRequests = [];
const browserFailures = [];

function writeDiagnostics() {
  fs.writeFileSync(
    path.join(RESULTS_DIR, "read-only-diagnostics.json"),
    JSON.stringify({ blockedRequests, browserFailures }, null, 2),
    "utf8",
  );
}

async function readOnlyApiRequest(apiContext, method, pathname, body) {
  const url = new URL(pathname, API_URL).href;
  assertReadOnlyRequest({ method, url, origins });
  const response = await apiContext.fetch(url, {
    method,
    data: body,
    headers: { Authorization: `Bearer ${STUDENT_TOKEN}` },
  });
  if (!response.ok()) {
    throw new Error(`API élève en lecture refusée: ${method} ${pathname} (${response.status()})`);
  }
  return response.json();
}

async function verifyStudentReadAccess() {
  const apiContext = await request.newContext();
  try {
    const catalogue = await readOnlyApiRequest(apiContext, "GET", "/collections/v2");
    const collection = catalogue.collections?.[0]?.name;
    if (typeof collection !== "string" || collection.length === 0) {
      throw new Error("Aucune collection interrogeable pour le rôle élève");
    }
    await readOnlyApiRequest(apiContext, "POST", "/search/v2", {
      q: "Définition pédagogique de test",
      collection,
      k: 1,
    });
  } finally {
    await apiContext.dispose();
  }
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

async function verifySidebar(context) {
  for (const [index, label] of ["Dashboard", "Recherche", "Administration"].entries()) {
    const page = await context.newPage();
    try {
      await page.goto(UI_URL, { waitUntil: "domcontentloaded", timeout: 30_000 });
      await navigate(page, label);
      await page.screenshot({
        path: path.join(RESULTS_DIR, `${String(index + 1).padStart(2, "0")}-${label.toLowerCase()}.png`),
        fullPage: true,
      });
    } catch (error) {
      browserFailures.push(`${label}: ${error instanceof Error ? error.message : String(error)}`);
      throw error;
    } finally {
      await page.close();
    }
  }
}

async function main() {
  fs.mkdirSync(RESULTS_DIR, { recursive: true });
  await verifyStudentReadAccess();

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  await context.route("**/*", async (route) => {
    const requestData = route.request();
    try {
      assertReadOnlyRequest({
        method: requestData.method(),
        url: requestData.url(),
        origins,
      });
      await route.continue();
    } catch (error) {
      blockedRequests.push({ method: requestData.method(), url: requestData.url() });
      await route.abort("blockedbyclient");
      throw error;
    }
  });

  try {
    await verifySidebar(context);
    if (blockedRequests.length > 0) {
      throw new Error("Le harnais a bloqué une requête hors liste blanche");
    }
  } finally {
    await context.close();
    await browser.close();
    writeDiagnostics();
  }
}

main().catch((error) => {
  writeDiagnostics();
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
