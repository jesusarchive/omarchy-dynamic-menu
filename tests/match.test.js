const test = require("node:test")
const assert = require("node:assert")
const { match } = require("../Match.js")

function pick(items, text, caseInsensitive) {
  return match(items, text, caseInsensitive).map((i) => items[i])
}

test("empty input matches everything in stdin order", () => {
  assert.deepStrictEqual(pick(["b", "a", "c"], ""), ["b", "a", "c"])
  assert.deepStrictEqual(pick(["b", "a"], "   "), ["b", "a"])
})

test("exact, then prefix, then substring", () => {
  const items = ["libfirefox", "firefox-esr", "firefox", "xfire"]
  assert.deepStrictEqual(pick(items, "fire"), ["firefox-esr", "firefox", "libfirefox", "xfire"])
  assert.deepStrictEqual(pick(items, "firefox"), ["firefox", "firefox-esr", "libfirefox"])
})

test("every word has to appear, in any order", () => {
  const items = ["git log", "git status", "log git", "status"]
  assert.deepStrictEqual(pick(items, "log git"), ["log git", "git log"])
  assert.deepStrictEqual(pick(items, "git zzz"), [])
})

test("prefix is judged on the first word only", () => {
  // Both contain "b" and "xa"; only "bxa" starts with the first word.
  const items = ["xa b", "bxa"]
  assert.deepStrictEqual(pick(items, "b xa"), ["bxa", "xa b"])
})

test("exact compares the whole input, spaces included", () => {
  const items = ["foo  bar", "foo bar"]
  assert.deepStrictEqual(pick(items, "foo bar"), ["foo bar", "foo  bar"])
})

test("case-sensitive by default, -i folds case", () => {
  const items = ["Firefox", "firefox"]
  assert.deepStrictEqual(pick(items, "fire"), ["firefox"])
  assert.deepStrictEqual(pick(items, "FIREFOX", true), ["Firefox", "firefox"])
  assert.deepStrictEqual(pick(["xFire", "fire"], "FI", true), ["fire", "xFire"])
})
