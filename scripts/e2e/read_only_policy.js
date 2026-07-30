"use strict";

const SAFE_UI_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const READ_ONLY_API_ROUTES = new Map([
  ["GET", new Set(["/collections/v2"])],
  ["POST", new Set(["/search/v2"])],
]);

function assertReadOnlyRequest({ method, url, origins }) {
  const requestUrl = new URL(url);
  const normalizedMethod = method.toUpperCase();

  if (requestUrl.origin === origins.ui && SAFE_UI_METHODS.has(normalizedMethod)) {
    return;
  }

  const allowedRoutes = READ_ONLY_API_ROUTES.get(normalizedMethod);
  if (
    requestUrl.origin === origins.api &&
    allowedRoutes &&
    allowedRoutes.has(requestUrl.pathname)
  ) {
    return;
  }

  throw new Error(`requête interdite par le harnais read-only: ${normalizedMethod} ${requestUrl.href}`);
}

module.exports = { assertReadOnlyRequest };
