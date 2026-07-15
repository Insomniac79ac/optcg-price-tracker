#!/usr/bin/env node
/**
 * Production environment validation for the Next.js app - the frontend
 * counterpart to services/api/app/core/env_validation.py (and its worker
 * mirror). Run via `npm run check-env`, or with an explicit phase so it
 * only checks what's actually available at that point in the build/start
 * lifecycle:
 *
 *   node scripts/check-env.js build   Docker build stage. NEXT_PUBLIC_*
 *                                     vars are inlined into the client
 *                                     bundle by `next build` and so must be
 *                                     checked here, but API_INTERNAL_URL is
 *                                     a runtime-only server env var not set
 *                                     yet at this point.
 *   node scripts/check-env.js start   Container start (`next start`) -
 *                                     everything, including API_INTERNAL_URL.
 *
 * Secret-like NEXT_PUBLIC_* variable names are always a hard failure in
 * production, at either phase - Next.js inlines every NEXT_PUBLIC_* var
 * into the client-side JS bundle verbatim, so one that looks like a
 * token/secret/password/key is a real credential leak, not a style nit.
 */

const SECRET_NAME_PATTERN = /(TOKEN|SECRET|PASSWORD|KEY)/i;

function isProductionEnv(env) {
  const value = (env.APP_ENV || env.NODE_ENV || "").trim().toLowerCase();
  return value === "production";
}

function checkNoPublicSecrets(env) {
  const offenders = Object.keys(env)
    .filter((key) => key.startsWith("NEXT_PUBLIC_"))
    .filter((key) => SECRET_NAME_PATTERN.test(key))
    .filter((key) => env[key]);

  if (offenders.length > 0) {
    return {
      name: "no_public_secrets",
      ok: false,
      message:
        "The following NEXT_PUBLIC_* variables look like secrets and are inlined into " +
        `the client bundle: ${offenders.join(", ")}. Rename them without the NEXT_PUBLIC_ ` +
        "prefix and read them only from server-side code (e.g. a Next.js API route).",
    };
  }
  return {
    name: "no_public_secrets",
    ok: true,
    message: "No secret-like NEXT_PUBLIC_* variables found.",
  };
}

function checkVarPresent(env, name) {
  if (!env[name] || !env[name].trim()) {
    return { name: `${name.toLowerCase()}_present`, ok: false, message: `${name} is not set.` };
  }
  return { name: `${name.toLowerCase()}_present`, ok: true, message: `${name} is configured.` };
}

function runChecks(env, phase) {
  const checks = [checkNoPublicSecrets(env), checkVarPresent(env, "NEXT_PUBLIC_API_URL")];
  if (phase !== "build") {
    checks.push(checkVarPresent(env, "API_INTERNAL_URL"));
  }
  return checks;
}

function main() {
  const phase = process.argv[2] || "start";
  const env = process.env;
  const isProduction = isProductionEnv(env);
  const checks = runChecks(env, phase);

  let hasFailure = false;
  for (const check of checks) {
    if (check.ok) {
      console.log(`[check-env] PASS ${check.name}: ${check.message}`);
      continue;
    }
    if (isProduction) {
      hasFailure = true;
      console.error(`[check-env] FAIL ${check.name}: ${check.message}`);
    } else {
      console.warn(`[check-env] WARN ${check.name}: ${check.message}`);
    }
  }

  if (hasFailure) {
    console.error(`[check-env] Production environment validation failed (phase=${phase}).`);
    process.exitCode = 1;
    return;
  }
  console.log(
    `[check-env] Environment validation passed ` +
      `(phase=${phase}, app_env=${isProduction ? "production" : "development"}).`,
  );
}

if (require.main === module) {
  main();
}

module.exports = { isProductionEnv, checkNoPublicSecrets, checkVarPresent, runChecks };
