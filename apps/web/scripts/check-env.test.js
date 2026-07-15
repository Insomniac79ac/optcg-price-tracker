const test = require("node:test");
const assert = require("node:assert/strict");

const { isProductionEnv, checkNoPublicSecrets, checkVarPresent, runChecks } = require("./check-env");

test("isProductionEnv is true only when APP_ENV/NODE_ENV is production", () => {
  assert.equal(isProductionEnv({ APP_ENV: "production" }), true);
  assert.equal(isProductionEnv({ NODE_ENV: "production" }), true);
  assert.equal(isProductionEnv({ APP_ENV: "development" }), false);
  assert.equal(isProductionEnv({}), false);
});

test("checkNoPublicSecrets passes when no NEXT_PUBLIC_* var looks like a secret", () => {
  const result = checkNoPublicSecrets({ NEXT_PUBLIC_API_URL: "https://api.example.com" });
  assert.equal(result.ok, true);
});

test("checkNoPublicSecrets catches NEXT_PUBLIC_ADMIN_TOKEN", () => {
  const result = checkNoPublicSecrets({ NEXT_PUBLIC_ADMIN_TOKEN: "abc123" });
  assert.equal(result.ok, false);
  assert.match(result.message, /NEXT_PUBLIC_ADMIN_TOKEN/);
});

test("checkNoPublicSecrets catches SECRET/PASSWORD/KEY variants case-insensitively", () => {
  // Next.js only inlines vars whose name starts with the exact-case
  // "NEXT_PUBLIC_" prefix, so the case-insensitivity here is about the
  // TOKEN/SECRET/PASSWORD/KEY suffix, not the prefix itself.
  for (const name of ["NEXT_PUBLIC_APP_SECRET", "NEXT_PUBLIC_DB_password", "NEXT_PUBLIC_API_KEY"]) {
    const result = checkNoPublicSecrets({ [name]: "value" });
    assert.equal(result.ok, false, `expected ${name} to be flagged`);
  }
});

test("checkNoPublicSecrets ignores empty secret-like vars", () => {
  const result = checkNoPublicSecrets({ NEXT_PUBLIC_ADMIN_TOKEN: "" });
  assert.equal(result.ok, true);
});

test("checkVarPresent fails when unset or blank", () => {
  assert.equal(checkVarPresent({}, "NEXT_PUBLIC_API_URL").ok, false);
  assert.equal(checkVarPresent({ NEXT_PUBLIC_API_URL: "   " }, "NEXT_PUBLIC_API_URL").ok, false);
  assert.equal(
    checkVarPresent({ NEXT_PUBLIC_API_URL: "https://api.example.com" }, "NEXT_PUBLIC_API_URL").ok,
    true,
  );
});

test("runChecks skips API_INTERNAL_URL during the build phase", () => {
  const checks = runChecks({ NEXT_PUBLIC_API_URL: "https://api.example.com" }, "build");
  assert.ok(!checks.some((c) => c.name === "api_internal_url_present"));
});

test("runChecks includes API_INTERNAL_URL during the start phase", () => {
  const checks = runChecks(
    { NEXT_PUBLIC_API_URL: "https://api.example.com", API_INTERNAL_URL: "http://api:8000" },
    "start",
  );
  const apiInternal = checks.find((c) => c.name === "api_internal_url_present");
  assert.ok(apiInternal);
  assert.equal(apiInternal.ok, true);
});

test("runChecks flags a missing API_INTERNAL_URL at start phase", () => {
  const checks = runChecks({ NEXT_PUBLIC_API_URL: "https://api.example.com" }, "start");
  const apiInternal = checks.find((c) => c.name === "api_internal_url_present");
  assert.equal(apiInternal.ok, false);
});
