const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { generateBuildVersion } = require("./generate-build-version");

function fixture(t, version = "4.5.6\n") {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "atlas-build-version-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, "apps/web/scripts"), { recursive: true });
  if (version !== null) fs.writeFileSync(path.join(root, "VERSION"), version);
  return root;
}

test("generates only the trimmed root version, ignoring package version and environment", (t) => {
  const root = fixture(t, " 4.5.6\n");
  fs.writeFileSync(path.join(root, "apps/web/package.json"), '{"version":"99.0.0"}');
  assert.equal(generateBuildVersion(root), "4.5.6");
  const output = fs.readFileSync(path.join(root, "apps/web/src/generated/buildVersion.ts"), "utf8");
  assert.match(output, /export const buildVersion = "4\.5\.6";/);
  assert.doesNotMatch(output, /99\.0\.0|process\.env|Date/);
});

test("refreshes a stale generated module when root VERSION changes", (t) => {
  const root = fixture(t);
  generateBuildVersion(root);
  fs.writeFileSync(path.join(root, "VERSION"), "4.5.7\n");
  generateBuildVersion(root);
  assert.match(fs.readFileSync(path.join(root, "apps/web/src/generated/buildVersion.ts"), "utf8"), /"4\.5\.7"/);
});

test("repeated generation is deterministic and does not rewrite unchanged output", (t) => {
  const root = fixture(t);
  generateBuildVersion(root);
  const output = path.join(root, "apps/web/src/generated/buildVersion.ts");
  fs.utimesSync(output, 100, 100);
  const before = fs.readFileSync(output);
  generateBuildVersion(root);
  assert.deepEqual(fs.readFileSync(output), before);
  assert.equal(fs.statSync(output).mtimeMs, 100000);
});

test("fails clearly without repo-root VERSION, even if an old generated value exists", (t) => {
  const root = fixture(t);
  generateBuildVersion(root);
  fs.unlinkSync(path.join(root, "VERSION"));
  assert.throws(() => generateBuildVersion(root), /repo-root VERSION is required/);
});

test("rejects empty and multiline VERSION files", (t) => {
  for (const version of ["\n ", "1.0.0\n2.0.0"]) {
    const root = fixture(t, version);
    assert.throws(() => generateBuildVersion(root), /one nonempty line/);
  }
});

test("CLI resolves VERSION relative to the script, independent of working directory", (t) => {
  const root = fixture(t);
  const script = path.join(root, "apps/web/scripts/generate-build-version.js");
  fs.copyFileSync(path.join(__dirname, "generate-build-version.js"), script);
  const result = spawnSync(process.execPath, [script], { cwd: os.tmpdir(), encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  assert.match(fs.readFileSync(path.join(root, "apps/web/src/generated/buildVersion.ts"), "utf8"), /"4\.5\.6"/);
});

test("encodes the value as data rather than executable source", (t) => {
  const root = fixture(t, '1.0.0-"quoted"');
  generateBuildVersion(root);
  const output = fs.readFileSync(path.join(root, "apps/web/src/generated/buildVersion.ts"), "utf8");
  assert.ok(output.includes(JSON.stringify('1.0.0-"quoted"')));
});

function loadNextConfig(root, phase) {
  const web = path.join(root, "apps/web");
  fs.copyFileSync(path.join(__dirname, "generate-build-version.js"), path.join(web, "scripts/generate-build-version.js"));
  fs.copyFileSync(path.join(__dirname, "../next.config.ts"), path.join(web, "next.config.ts"));
  fs.mkdirSync(path.join(web, "src/lib"), { recursive: true });
  fs.copyFileSync(path.join(__dirname, "../src/lib/cspImageOrigin.ts"), path.join(web, "src/lib/cspImageOrigin.ts"));
  fs.copyFileSync(path.join(__dirname, "../src/lib/metadataBots.ts"), path.join(web, "src/lib/metadataBots.ts"));
  fs.symlinkSync(path.resolve(__dirname, "../node_modules"), path.join(web, "node_modules"), "dir");
  const loader = require.resolve("next/dist/server/config");
  return spawnSync(process.execPath, ["-e", `require(${JSON.stringify(loader)}).default(${JSON.stringify(phase)}, ${JSON.stringify(web)}).catch(e => { console.error(e.message); process.exitCode = 1; });`], {
    cwd: web, encoding: "utf8", env: { ...process.env, R2_PUBLIC_BASE_URL: "" },
  });
}

for (const phase of ["phase-production-build", "phase-development-server"]) {
  test(`Next's ${phase} automatically generates a missing module`, (t) => {
    const root = fixture(t);
    const result = loadNextConfig(root, phase);
    assert.equal(result.status, 0, result.stderr);
    assert.match(fs.readFileSync(path.join(root, "apps/web/src/generated/buildVersion.ts"), "utf8"), /"4\.5\.6"/);
  });
}

test("Next build fails when VERSION is absent; runtime config does not need VERSION", (t) => {
  const build = loadNextConfig(fixture(t, null), "phase-production-build");
  assert.notEqual(build.status, 0);
  assert.match(build.stderr + build.stdout, /repo-root VERSION is required/, JSON.stringify(build));
  const runtime = loadNextConfig(fixture(t, null), "phase-production-server");
  assert.equal(runtime.status, 0, runtime.stderr);
});
