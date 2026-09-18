const test = require("node:test")
const assert = require("node:assert")
const Engine = require("../Engine.js")
const { match } = require("../Match.js")

// Every character is 10px wide and lrpad is 10, so TEXTW("ab") = 30.
function menu(items, options) {
  return Engine.create(items, Object.assign({
    textw: (s) => s.length * 10 + 10,
    lrpad: 10,
    mw: 1000,
    match: match
  }, options))
}

function key(state, name, mods) {
  return Engine.keypress(state, Object.assign({ key: name, text: "" }, mods))
}

function type(state, text) {
  for (const ch of text) Engine.keypress(state, { key: "", text: ch })
}

const sel = (s) => (s.sel >= 0 ? s.items[s.matches[s.sel]] : null)

test("Return prints the selection and exits 0", () => {
  const s = menu(["foo", "bar"])
  assert.deepStrictEqual(key(s, "Return"), { output: "foo", exit: 0, paste: null })
})

test("Return with no match prints the typed text", () => {
  const s = menu(["foo"])
  type(s, "notify-send hi")
  assert.strictEqual(key(s, "Return").output, "notify-send hi")
})

test("Shift+Return prints the typed text even when something matches", () => {
  const s = menu(["foobar"])
  type(s, "foo")
  assert.strictEqual(key(s, "Return", { shift: true }).output, "foo")
})

test("Ctrl+Return prints, stays open and marks the item", () => {
  const s = menu(["a", "b"])
  const r = key(s, "Return", { ctrl: true })
  assert.deepStrictEqual(r, { output: "a", exit: null, paste: null })
  assert.strictEqual(s.out[0], true)
  const layout = Engine.layout(s)
  key(s, "Right")
  assert.strictEqual(Engine.layout(s).boxes.find((b) => b.text === "a").scheme, "out")
  assert.strictEqual(layout.boxes.find((b) => b.text === "a").scheme, "sel")
})

test("Ctrl+J and Ctrl+M are Return, Ctrl+Shift+J is Shift+Return", () => {
  const s = menu(["foobar"])
  type(s, "foo")
  assert.deepStrictEqual(key(s, "j", { ctrl: true }), { output: "foobar", exit: 0, paste: null })
  assert.strictEqual(key(s, "m", { ctrl: true }).exit, 0)
  assert.strictEqual(key(s, "J", { ctrl: true, shift: true }).output, "foo")
})

test("Escape, Ctrl+C, Ctrl+G and Ctrl+[ exit 1", () => {
  for (const [name, mods] of [["Escape", {}], ["c", { ctrl: true }], ["g", { ctrl: true }], ["bracketleft", { ctrl: true }]]) {
    assert.strictEqual(key(menu(["a"]), name, mods).exit, 1, name)
  }
})

test("Tab copies the selection into the input", () => {
  const s = menu(["firefox", "chromium"])
  type(s, "fi")
  key(s, "Tab")
  assert.strictEqual(s.text, "firefox")
  assert.strictEqual(s.cursor, 7)
})

test("Left moves the text cursor on the first item, otherwise the selection", () => {
  const s = menu(["ab", "abc"])
  type(s, "ab")
  key(s, "Right") // cursor at end: moves selection
  assert.strictEqual(sel(s), "abc")
  key(s, "Left") // selection has a left neighbour: moves selection
  assert.strictEqual(sel(s), "ab")
  key(s, "Left") // first item: moves the cursor
  assert.strictEqual(s.cursor, 1)
  key(s, "Right") // cursor not at end: moves the cursor
  assert.strictEqual(s.cursor, 2)
})

test("with -l, Left and Right only move the text cursor", () => {
  const s = menu(["ab", "abc"], { lines: 5 })
  type(s, "ab")
  key(s, "Right")
  assert.strictEqual(sel(s), "ab")
  key(s, "Down")
  assert.strictEqual(sel(s), "abc")
  key(s, "Left")
  assert.strictEqual(s.cursor, 1)
  assert.strictEqual(sel(s), "abc")
})

test("editing: Backspace, Delete, Ctrl+U, Ctrl+K, Ctrl+W, Ctrl+A/E", () => {
  const s = menu([])
  type(s, "git log --all")
  key(s, "w", { ctrl: true })
  assert.strictEqual(s.text, "git log ")
  key(s, "w", { ctrl: true })
  assert.strictEqual(s.text, "git ")
  key(s, "a", { ctrl: true })
  assert.strictEqual(s.cursor, 0)
  key(s, "Delete")
  assert.strictEqual(s.text, "it ")
  key(s, "f", { ctrl: true })
  key(s, "k", { ctrl: true })
  assert.strictEqual(s.text, "i")
  key(s, "e", { ctrl: true })
  type(s, "xy")
  key(s, "BackSpace")
  assert.strictEqual(s.text, "ix")
  key(s, "b", { ctrl: true })
  key(s, "u", { ctrl: true })
  assert.deepStrictEqual([s.text, s.cursor], ["x", 0])
})

test("word jumps with Ctrl+Left/Right and Alt+B/F", () => {
  const s = menu([])
  type(s, "one two  three")
  key(s, "Left", { ctrl: true })
  assert.strictEqual(s.cursor, 9)
  key(s, "b", { alt: true })
  assert.strictEqual(s.cursor, 4)
  key(s, "Right", { ctrl: true })
  assert.strictEqual(s.cursor, 7)
  key(s, "f", { alt: true })
  assert.strictEqual(s.cursor, 14)
})

test("unhandled Ctrl and Alt combinations do nothing", () => {
  const s = menu(["a"])
  key(s, "x", { ctrl: true, text: "" })
  key(s, "A", { ctrl: true, shift: true })
  key(s, "x", { alt: true, text: "x" })
  assert.strictEqual(s.text, "")
})

test("control characters are not inserted", () => {
  const s = menu([])
  Engine.keypress(s, { key: "", text: "\t" })
  Engine.keypress(s, { key: "", text: "" })
  assert.strictEqual(s.text, "")
})

test("paste inserts up to the first newline", () => {
  const s = menu([])
  assert.strictEqual(key(s, "y", { ctrl: true }).paste, "primary")
  assert.strictEqual(key(s, "Y", { ctrl: true, shift: true }).paste, "clipboard")
  Engine.paste(s, "first\nsecond")
  assert.strictEqual(s.text, "first")
})

test("horizontal pages: Down crosses pages, arrows show, PgUp/PgDn flip", () => {
  // mw 200, no prompt: inputw 66, "<" and ">" 20 each, so n = 94.
  // Each 3-letter item is 40 wide: two fit on a page.
  const s = menu(["aaa", "bbb", "ccc", "ddd", "eee"], { mw: 200 })
  assert.deepStrictEqual([s.curr, s.next], [0, 2])
  let boxes = Engine.layout(s).boxes
  assert.deepStrictEqual(boxes.filter((b) => b.kind === "arrow").map((b) => b.text), [">"])
  key(s, "Down")
  key(s, "Down")
  assert.deepStrictEqual([sel(s), s.curr, s.next], ["ccc", 2, 4])
  boxes = Engine.layout(s).boxes
  assert.deepStrictEqual(boxes.filter((b) => b.kind === "arrow").map((b) => b.text), ["<", ">"])
  key(s, "Next")
  assert.deepStrictEqual([sel(s), s.curr, s.next], ["eee", 4, -1])
  key(s, "Prior")
  assert.deepStrictEqual([sel(s), s.curr], ["ccc", 2])
  key(s, "Up")
  assert.deepStrictEqual([sel(s), s.curr], ["bbb", 0])
})

test("End jumps to the last item with the last page filled; Home goes back", () => {
  const s = menu(["aaa", "bbb", "ccc", "ddd", "eee"], { mw: 200 })
  key(s, "End")
  assert.deepStrictEqual([sel(s), s.curr, s.next], ["eee", 3, -1])
  key(s, "Home")
  assert.deepStrictEqual([sel(s), s.curr], ["aaa", 0])
})

test("End moves the cursor to the end of the text first", () => {
  const s = menu(["abc", "abd"])
  type(s, "ab")
  key(s, "Home") // first item already selected: cursor to start
  assert.strictEqual(s.cursor, 0)
  key(s, "End")
  assert.deepStrictEqual([s.cursor, sel(s)], [2, "abc"])
  key(s, "End")
  assert.strictEqual(sel(s), "abd")
})

test("vertical list pages by lines; lines is capped at the item count", () => {
  const s = menu(["a", "b", "c", "d", "e"], { lines: 2 })
  assert.deepStrictEqual([s.curr, s.next], [0, 2])
  key(s, "Down")
  key(s, "Down")
  assert.deepStrictEqual([sel(s), s.curr, s.next], ["c", 2, 4])
  assert.strictEqual(menu(["a", "b"], { lines: 10 }).lines, 2)
  assert.strictEqual(Engine.layout(menu(["a"], { lines: 3 })).rows, 2)
})

test("layout: prompt, input a third wide, items after it", () => {
  const s = menu(["aa", "bb"], { prompt: "Run", mw: 900 })
  const { boxes } = Engine.layout(s)
  // promptw = TEXTW("Run") - lrpad/4 = 40 - 2
  assert.deepStrictEqual(boxes[0], { kind: "prompt", text: "Run", x: 0, y: 0, width: 38, scheme: "sel" })
  assert.deepStrictEqual(boxes[1], { kind: "input", text: "", x: 38, y: 0, width: 300, scheme: "norm" })
  // items start after the input and the "<" slot
  assert.strictEqual(boxes[2].x, 38 + 300 + 20)
  assert.strictEqual(boxes[2].scheme, "sel")
})

test("layout: the input takes the full width when nothing matches", () => {
  const s = menu(["aa"], { prompt: "Run", mw: 900 })
  type(s, "zz")
  const input = Engine.layout(s).boxes.find((b) => b.kind === "input")
  assert.strictEqual(input.width, 900 - 38)
})

test("cursor position uses the full input width minus the suffix", () => {
  const widths = { "": 10, A: 30, V: 20, AV: 35 }
  const s = menu([], { textw: (text) => widths[text], lrpad: 10 })
  s.text = "AV"
  s.cursor = 1

  assert.strictEqual(Engine.layout(s).cursor.x, 19)
})

test("long items are clamped to the space left", () => {
  const s = menu(["x".repeat(200)], { mw: 400 })
  const it = Engine.layout(s).boxes.find((b) => b.kind === "item")
  // mw - x - TEXTW(">"), with x = inputw 133 + "<" 20
  assert.strictEqual(it.width, 400 - 153 - 20)
})

test("surrogate pairs are stepped over as one character", () => {
  const s = menu([])
  type(s, "a😀")
  key(s, "BackSpace")
  assert.strictEqual(s.text, "a")
})

test("readstdin splits lines like dmenu", () => {
  assert.deepStrictEqual(Engine.readstdin(""), [])
  assert.deepStrictEqual(Engine.readstdin("a\nb\n"), ["a", "b"])
  assert.deepStrictEqual(Engine.readstdin("a\nb"), ["a", "b"])
  assert.deepStrictEqual(Engine.readstdin("a\n\nb\n"), ["a", "", "b"])
  assert.deepStrictEqual(Engine.readstdin("\n"), [""])
  assert.deepStrictEqual(Engine.readstdin("a\r\n"), ["a\r"])
})
