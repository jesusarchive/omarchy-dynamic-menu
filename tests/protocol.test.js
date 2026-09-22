const test = require("node:test")
const assert = require("node:assert/strict")
const Protocol = require("../Protocol.js")
const token = "a".repeat(32)
const wire = message => JSON.stringify(message).replace(/[\u007f-\uffff]/g,
  ch => "\\u" + ch.charCodeAt(0).toString(16).padStart(4, "0")) + "\n"
const begin = options => wire({ type: "begin", token, options: options || {} })
const items = text => wire({ type: "items", text })
const end = wire({ type: "end" })

test("actual QML parser preserves Unicode and literal text across arbitrary wire splits", () => {
  const text = "alpha\n🐈 'quotes' $(nothing)\n"
  const data = begin({ prompt: "Pick" }) + items(text) + end
  for (const size of [1, 2, 13, data.length]) {
    const state = Protocol.create(token)
    let result
    for (let i = 0; i < data.length; i += size)
      result = Protocol.feed(state, data.slice(i, i + size)) || result
    assert.equal(result.text, text)
    assert.equal(result.options.prompt, "Pick")
  }
})

test("QML parser rejects paths, wrong IDs, unknown options and malformed values", () => {
  for (const data of ["null\n", "[]\n", "{\n", items("early"),
    wire({ type: "begin", token: "b".repeat(32), options: {} }),
    begin({ itemsFile: "/etc/passwd" }), begin({ lines: true }),
    begin({ font: "x".repeat(257) }), begin({ prompt: "x".repeat(1025) }),
    begin({ lines: 2 ** 31 }), begin({ bottom: 1 })]) {
    assert.throws(() => Protocol.feed(Protocol.create(token), data))
  }
})

test("QML parser rejects oversized unterminated frames without growing its buffer", () => {
  const state = Protocol.create(token)
  Protocol.feed(state, "x".repeat(65536))
  assert.throws(() => Protocol.feed(state, "x"))
  assert.equal(state.pending.length, 65536)
})

test("QML parser rejects excess items, overlong lines, NUL, invalid Unicode and repeat requests", () => {
  for (const chunks of [
    ["\n".repeat(8192), "\n".repeat(8192), "\n".repeat(4096)],
    ["x".repeat(8192), "x"], ["\0"], ["\ud800"]
  ]) {
    const state = Protocol.create(token)
    assert.throws(() => Protocol.feed(state, begin() + chunks.map(items).join("") + end))
  }
  for (const extra of [begin(), items("late"), end, "junk"]) {
    const state = Protocol.create(token)
    Protocol.feed(state, begin() + end)
    assert.throws(() => Protocol.feed(state, extra))
  }
})

test("QML parser limits total bytes and frame count independently", () => {
  const state = Protocol.create(token)
  Protocol.feed(state, begin())
  // Short enough lines, but too many bytes in aggregate.
  const chunk = "x".repeat(4095) + "\n"
  for (let i = 0; i < 512; i++) Protocol.feed(state, items(chunk))
  assert.throws(() => Protocol.feed(state, items("x")))
  const fragmented = Protocol.create(token)
  Protocol.feed(fragmented, begin())
  assert.throws(() => {
    for (let i = 0; i < 1100; i++) Protocol.feed(fragmented, items("x"))
  })
})

test("QML parser accepts the maximum item count and rejects non-ASCII wire bytes", () => {
  const state = Protocol.create(token)
  Protocol.feed(state, begin())
  for (let i = 0; i < 5; i++) Protocol.feed(state, items("x\n".repeat(4000)))
  assert.equal(Protocol.feed(state, end).text.length, 40000)
  assert.throws(() => Protocol.feed(Protocol.create(token), "🐈"))
})
