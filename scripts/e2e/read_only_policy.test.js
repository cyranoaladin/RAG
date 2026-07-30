"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const { assertReadOnlyRequest } = require("./read_only_policy");

const origins = {
  ui: "https://ui.example.test",
  api: "https://api.example.test",
};

test("autorise les ressources GET de l'interface", () => {
  assert.doesNotThrow(() =>
    assertReadOnlyRequest({
      method: "GET",
      url: "https://ui.example.test/static/app.js",
      origins,
    }),
  );
});

test("autorise uniquement les routes API de lecture de l'élève", () => {
  assert.doesNotThrow(() =>
    assertReadOnlyRequest({
      method: "GET",
      url: "https://api.example.test/collections/v2",
      origins,
    }),
  );
  assert.doesNotThrow(() =>
    assertReadOnlyRequest({
      method: "POST",
      url: "https://api.example.test/search/v2",
      origins,
    }),
  );
});

test("bloque structurellement toute écriture", () => {
  assert.throws(
    () =>
      assertReadOnlyRequest({
        method: "POST",
        url: "https://api.example.test/ingest/v2/upload-files",
        origins,
      }),
    /requête interdite/i,
  );
});
