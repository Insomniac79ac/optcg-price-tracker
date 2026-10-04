const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

function sourceCommit(repoRoot, env = process.env) {
  const supplied = env.VERCEL_GIT_COMMIT_SHA || env.GIT_COMMIT;
  if (supplied) {
    if (!/^[0-9a-f]{40}$/.test(supplied)) throw new Error("Build source SHA must be a full Git commit");
    return supplied;
  }
  if (env.VERCEL === "1") throw new Error("Vercel build requires VERCEL_GIT_COMMIT_SHA");
  try {
    return execFileSync("git", ["rev-parse", "HEAD"], { cwd: repoRoot, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
  } catch {
    return "unknown"; // Local tarball/test fixtures only; never accepted for staging verification.
  }
}

/** Build tooling only. The route imports the generated constant, never this file. */
function generateBuildVersion(repoRoot = path.resolve(__dirname, "../../..")) {
  const versionPath = path.join(repoRoot, "VERSION");
  let version;
  try {
    version = fs.readFileSync(versionPath, "utf8").trim();
  } catch (cause) {
    throw new Error(`Cannot generate web build version: repo-root VERSION is required at ${versionPath}`, { cause });
  }
  if (!version || /[\r\n]/.test(version)) {
    throw new Error(`Cannot generate web build version: ${versionPath} must contain one nonempty line`);
  }
  const output = path.join(repoRoot, "apps/web/src/generated/buildVersion.ts");
  const source = `// Generated at build time by scripts/generate-build-version.js.\nexport const buildVersion = ${JSON.stringify(version)};\nexport const buildCommit = ${JSON.stringify(sourceCommit(repoRoot))};\n`;
  // Avoid unnecessary writes while Next loads its config more than once.
  if (!fs.existsSync(output) || fs.readFileSync(output, "utf8") !== source) {
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, source);
  }
  return version;
}

if (require.main === module) generateBuildVersion();
module.exports = { generateBuildVersion, sourceCommit };
