const test = require("node:test")
const assert = require("node:assert/strict")
const fs = require("node:fs")
const path = require("node:path")
const vm = require("node:vm")
const Engine = require("../Engine.js")
const { match } = require("../Match.js")

// Execute the actual QML functions with process/window objects replaced by spies.
const qml = fs.readFileSync(path.join(__dirname, "../DynamicMenu.qml"), "utf8")
function context() {
  const writes = []
  const root = { activeToken: "", opened: false, menu: null, revision: 0, transportPath: "/plugin/bin/menu-transport.py" }
  const timer = () => ({ restart() {}, stop() {} })
  const ctx = vm.createContext({ root, Engine, writes,
    transport: { running: false, write: value => writes.push(JSON.parse(value)) },
    pasteProc: { running: false, requestToken: "" },
    startupTimer: timer(), shutdownTimer: timer(),
    Style: { font: { menuFamily: "monospace", body: 14 } },
    Qt: { font: value => value }
  })
  for (const name of ["open", "printLine", "finish", "hideMenu", "transportStopped", "parseFont"]) {
    const start = qml.indexOf("  function " + name + "(")
    const end = qml.indexOf("\n  }", start) + 4
    vm.runInContext(qml.slice(start, end), ctx)
    root[name] = ctx[name]
  }
  const start = qml.indexOf("      onStreamFinished: {", qml.indexOf("id: pasteProc"))
  const end = qml.indexOf("\n      }", start)
  const body = qml.slice(start + "      onStreamFinished: {".length, end)
  vm.runInContext("function pasteComplete(text) {" + body + "\n}", ctx)
  return ctx
}

test("QML rejects malformed payloads and legacy arbitrary paths without side effects", () => {
  const ctx = context()
  for (const payload of ["", "null", "[]", "1", "{", '{}', '{"token":"../../etc/passwd"}',
    JSON.stringify({ token: "a".repeat(32), doneFile: "/arbitrary/file" }),
    JSON.stringify({ token: "a".repeat(32) + "\n" })]) {
    ctx.root.open(payload)
    assert.equal(ctx.root.activeToken, "")
    assert.equal(ctx.transport.running, false)
    assert.equal(ctx.writes.length, 0)
  }
})

test("QML accepts only a token and cannot replace an active request", () => {
  const ctx = context()
  const first = "a".repeat(32)
  ctx.root.open(JSON.stringify({ token: first }))
  assert.equal(ctx.root.activeToken, first)
  assert.deepEqual(Array.from(ctx.transport.command), ["python3", "-I", ctx.root.transportPath, "serve", first])
  ctx.root.open(JSON.stringify({ token: "b".repeat(32) }))
  assert.equal(ctx.root.activeToken, first)
  assert.equal(ctx.writes.length, 0)
})

test("QML sends literal output before exit and hide recursion cannot send twice", () => {
  const ctx = context()
  ctx.root.open(JSON.stringify({ token: "a".repeat(32) }))
  ctx.root.shell = { hide: () => ctx.root.finish(1) }
  ctx.root.printLine("quotes ' \" $()")
  ctx.root.finish(0)
  assert.deepEqual(ctx.writes, [{ type: "output", text: "quotes ' \" $()" }, { type: "exit", status: 0 }])
  ctx.root.transportStopped()
  assert.equal(ctx.root.activeToken, "")
  assert.equal(ctx.root.opened, false)
  assert.equal(ctx.writes.length, 2)
})

test("a delayed paste cannot enter a different request or a closed menu", () => {
  const ctx = context()
  ctx.root.activeToken = "b".repeat(32)
  ctx.root.opened = true
  ctx.root.menu = Engine.create([], { match })
  ctx.pasteProc.requestToken = "a".repeat(32)
  ctx.pasteComplete("secret")
  assert.equal(ctx.root.menu.text, "")
  ctx.pasteProc.requestToken = ctx.root.activeToken
  ctx.pasteComplete("intended")
  assert.equal(ctx.root.menu.text, "intended")
  ctx.root.opened = false
  ctx.pasteComplete("secret")
  assert.equal(ctx.root.menu.text, "intended")
})

test("font overrides have finite size bounds", () => {
  const ctx = context()
  assert.equal(ctx.root.parseFont("x:pixelsize=1000000000").pixelSize, 96)
  assert.equal(ctx.root.parseFont("x:size=1000000000").pointSize, 72)
  assert.equal(ctx.root.parseFont("x:pixelsize=Infinity").pixelSize, 14)
})

test("input growth is bounded and rejected paste leaves the cursor intact", () => {
  const state = Engine.create([], { match })
  Engine.paste(state, "x".repeat(8192))
  const cursor = state.cursor
  Engine.paste(state, "y")
  assert.equal(state.text.length, 8192)
  assert.equal(state.cursor, cursor)
})

test("Ctrl+W rescans the item list once per word, including Unicode and trailing spaces", () => {
  let scans = 0
  const state = Engine.create(["item"], { match: (...args) => { scans++; return match(...args) } })
  Engine.paste(state, "keep " + "🐈".repeat(2000) + "   ")
  scans = 0
  Engine.keypress(state, { key: "w", ctrl: true })
  assert.equal(state.text, "keep ")
  assert.equal(state.cursor, 5)
  assert.equal(scans, 1)
})
