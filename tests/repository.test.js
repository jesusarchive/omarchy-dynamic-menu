const test = require("node:test")
const assert = require("node:assert")
const fs = require("node:fs")
const path = require("node:path")

const root = path.resolve(__dirname, "..")
const scripts = ["dmenu", "dmenu_path", "dmenu_run", "link-commands"]

test("manifest names an overlay entry point that exists", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(root, "manifest.json"), "utf8"))

  assert.strictEqual(manifest.schemaVersion, 1)
  assert.match(manifest.id, /^[a-z0-9]+(?:[.-][a-z0-9]+)+$/)
  assert.ok(manifest.kinds.includes("overlay"))
  assert.ok(manifest.entryPoints.overlay)
  assert.ok(fs.statSync(path.join(root, manifest.entryPoints.overlay)).isFile())
})

test("command scripts are executable", () => {
  for (const script of scripts) {
    const mode = fs.statSync(path.join(root, "bin", script)).mode
    assert.notStrictEqual(mode & 0o111, 0, script)
  }
})
