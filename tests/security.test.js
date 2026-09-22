const test = require("node:test")
const assert = require("node:assert/strict")
const fs = require("node:fs")
const path = require("node:path")
const vm = require("node:vm")
const Engine = require("../Engine.js")
const Auth = require("../Auth.js")
const Sha256 = { sha256: require("../vendor/Sha256.js") }
const secret = "c".repeat(64)
const Protocol = require("../Protocol.js")
const { match } = require("../Match.js")

// Execute the actual QML functions with process/window objects replaced by spies.
const qml = fs.readFileSync(path.join(__dirname, "../DynamicMenu.qml"), "utf8")
function context() {
  const writes = []
  const root = { activeToken: "", opened: false, menu: null, revision: 0, transportPath: "/plugin/bin/menu-transport.py" }
  const timer = () => ({ running: false, restart() { this.running = true }, stop() { this.running = false } })
  const ctx = vm.createContext({ root, Engine, Protocol, Auth, Sha256, writes,
    Quickshell: { env: () => "/run/user/test" },
    transport: { connected: false, flush() {}, destroy() { this.destroyed = true }, write: value => writes.push(JSON.parse(value.replace(/^\d+:[0-9a-f]{64}:/, ""))) },
    pasteProc: { running: false, requestToken: "" },
    startupTimer: timer(), shutdownTimer: timer(),
    Style: { font: { menuFamily: "monospace", body: 14 } },
    Qt: { font: value => value }
  })
  ctx.transportComponent = { createObject: () => ctx.transport }
  ctx.logic = {}
  for (const name of ["open", "printLine", "finish", "hideMenu", "transportStopped", "parseFont"]) {
    const start = qml.indexOf("    function " + name + "(", qml.indexOf("    id: logic"))
    const end = qml.indexOf("\n    }", start) + 6
    vm.runInContext(qml.slice(start, end), ctx)
    root[name] = ctx[name]
    ctx.logic[name] = ctx[name]
  }
  const start = qml.indexOf("      onStreamFinished: {", qml.indexOf("id: pasteProc"))
  const end = qml.indexOf("\n      }", start)
  const body = qml.slice(start + "      onStreamFinished: {".length, end)
  vm.runInContext("function pasteComplete(text) {" + body + "\n}", ctx)
  return ctx
}

function authenticate(ctx) {
  const state = ctx.root.authentication
  const nonce = "d".repeat(64)
  Auth.feed(state, JSON.stringify({type: "challenge", nonce,
    mac: Auth.helloMac(state, "server", nonce)}) + "\n", () => {}, () => {})
}

test("QML rejects malformed payloads and legacy arbitrary paths without side effects", () => {
  const ctx = context()
  for (const payload of ["", "null", "[]", "1", "{", '{}', '{"token":"../../etc/passwd"}',
    JSON.stringify({ token: "a".repeat(32), doneFile: "/arbitrary/file" }),
    JSON.stringify({ token: "a".repeat(32) + "\n", secret }),
    JSON.stringify({ token: "../" + "a".repeat(32), secret }),
    JSON.stringify({ token: "a".repeat(32) }),
    JSON.stringify({ token: "a".repeat(32), secret: "a".repeat(63) }),
    JSON.stringify({ token: "a".repeat(32), secret: "a".repeat(64) + "\n" })]) {
    ctx.root.open(payload)
    assert.equal(ctx.root.activeToken, "")
    assert.equal(ctx.transport.connected, false)
    assert.equal(ctx.writes.length, 0)
  }
})

test("QML requires private bootstrap fields and cannot replace an active request", () => {
  const ctx = context()
  const first = "a".repeat(32)
  ctx.root.open(JSON.stringify({ token: first, secret }))
  assert.equal(ctx.root.activeToken, first)
  assert.equal(ctx.transport.path, "/run/user/test/omarchy-dynamic-menu/" + first + "/socket")
  assert.equal(ctx.transport.connected, true)
  ctx.root.open(JSON.stringify({ token: "b".repeat(32), secret }))
  assert.equal(ctx.root.activeToken, first)
  assert.equal(ctx.writes.length, 0)
})

test("QML sends literal output before exit and hide recursion cannot send twice", () => {
  const ctx = context()
  ctx.root.open(JSON.stringify({ token: "a".repeat(32), secret }))
  authenticate(ctx)
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


test("horizontal pages stay bounded with long prompts, empty items and tiny screens", () => {
  for (const width of [1, 20, 1728]) {
    for (const measure of [() => 0, s => s.length * 10 + 20]) {
      const state = Engine.create(Array(20000).fill(""), {
        prompt: "p".repeat(1024), mw: width, lrpad: 20, textw: measure, match
      })
      for (const key of [null, "Next", "End", "Prior", "Home"]) {
        if (key) Engine.keypress(state, { key })
        const boxes = Engine.layout(state).boxes
        assert.ok(boxes.filter(b => b.kind === "item").length <= 50)
        assert.ok(boxes.every(b => b.width >= 0))
      }
    }
  }
})

test("repeated query tokens scan each item once and case folding is not repeated", () => {
  const original = String.prototype.indexOf
  let searches = 0
  String.prototype.indexOf = function(...args) { searches++; return original.apply(this, args) }
  try {
    assert.equal(match(Array(20000).fill("x".repeat(98) + "a"), "a ".repeat(4096), true).length, 20000)
  } finally { String.prototype.indexOf = original }
  assert.ok(searches <= 40000)
  assert.deepEqual(match(["anything"], Array.from({length: 65}, (_, i) => "word" + i).join(" ")), [])
})


test("QML bounds queued output and destroys a stalled socket at its shutdown deadline", () => {
  const ctx = context()
  ctx.root.open(JSON.stringify({ token: "a".repeat(32), secret }))
  authenticate(ctx)
  ctx.root.printedBytes = 2 * 1024 * 1024 - 2
  ctx.root.printLine("x")
  ctx.root.printLine("overflow")
  assert.deepEqual(ctx.writes, [{type: "output", text: "x"}, {type: "exit", status: 1}])
  ctx.root.transportStopped()
  assert.equal(ctx.transport.destroyed, true)
  assert.equal(ctx.root.transport, null)
  assert.equal(ctx.root.activeToken, "")
})


test("synchronous socket disconnect cannot leave a timer that closes the next menu", () => {
  const ctx = context()
  ctx.root.open(JSON.stringify({ token: "a".repeat(32), secret }))
  Object.defineProperty(ctx.transport, "connected", {
    set(value) { if (!value) ctx.root.transportStopped() },
    get() { return false }
  })
  ctx.root.finish(0)
  assert.equal(ctx.shutdownTimer.running, false)
  assert.equal(ctx.root.transport, null)
  ctx.root.open(JSON.stringify({ token: "b".repeat(32), secret }))
  assert.equal(ctx.root.activeToken, "b".repeat(32))
  assert.equal(ctx.shutdownTimer.running, false)
})


test("the host dispatcher can reach only open and close, never internal output methods", () => {
  const publicMethods = [...qml.matchAll(/^  function (\w+)\(/gm)].map(match => match[1])
  assert.deepEqual(publicMethods, ["open", "close"])
  assert.ok(qml.includes("logic.printLine(result.output)"))
})
