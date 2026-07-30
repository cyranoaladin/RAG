const { defineConfig } = require("playwright/test");

module.exports = defineConfig({
  testDir: ".",
  testMatch: "rag-v2-prod-readonly.js",
  timeout: 60_000,
  use: { headless: true },
});
