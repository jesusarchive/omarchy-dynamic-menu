// Item matching as in suckless dmenu's match(), kept Qt-free so node can test it.
//
// The input is split on spaces and an item must contain every word. The
// function returns three groups in stdin order: items equal to the whole
// input, then items starting with the first word, then the rest. Empty input
// matches everything.

// Returns the indices of the matching items, in display order.
function match(items, text, caseInsensitive) {
  var input = String(text || "")
  if (caseInsensitive) input = input.toLowerCase()
  var seen = Object.create(null)
  var tokens = input.split(" ").filter(function(token) {
    if (!token.length || seen[token]) return false
    seen[token] = true
    return true
  })
  // Keep search work bounded. Typed text still works with Shift+Return.
  if (tokens.length > 64) return []
  var exact = []
  var prefix = []
  var substring = []

  for (var i = 0; i < items.length; i++) {
    var item = String(items[i])
    if (caseInsensitive) item = item.toLowerCase()
    var all = true
    for (var t = 0; t < tokens.length; t++) {
      if (item.indexOf(tokens[t]) === -1) {
        all = false
        break
      }
    }
    if (!all) continue

    if (tokens.length === 0 || input === item) exact.push(i)
    else if (item.indexOf(tokens[0]) === 0) prefix.push(i)
    else substring.push(i)
  }

  return exact.concat(prefix, substring)
}

if (typeof module !== "undefined") {
  module.exports = {
    match: match
  }
}
