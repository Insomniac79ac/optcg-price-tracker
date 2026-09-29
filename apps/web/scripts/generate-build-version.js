const fs = require("node:fs");
const path = require("node:path");

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
  const source = `// Generated from repo-root VERSION by scripts/generate-build-version.js.\nexport const buildVersion = ${JSON.stringify(version)};\n`;
  // Avoid unnecessary writes while Next loads its config more than once.
  if (!fs.existsSync(output) || fs.readFileSync(output, "utf8") !== source) {
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, source);
  }
  return version;
}

if (require.main === module) generateBuildVersion();
module.exports = { generateBuildVersion };
