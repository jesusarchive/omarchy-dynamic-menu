// Item matching as in suckless dmenu's match(), kept Qt-free so node can test it.
//
// The input is split on spaces and an item must contain every word. The
// function returns three groups in stdin order: items equal to the whole
// input, then items starting with the first word, then the rest. Empty input
// matches everything.

function contains(haystack, needle, caseInsensitive) {
  if (caseInsensitive) return haystack.toLowerCase().indexOf(needle.toLowerCase()) !== -1
  return haystack.indexOf(needle) !== -1
}

function startsWith(haystack, needle, caseInsensitive) {
  if (caseInsensitive) return haystack.toLowerCase().indexOf(needle.toLowerCase()) === 0
  return haystack.indexOf(needle) === 0
}

function equals(a, b, caseInsensitive) {
  return caseInsensitive ? a.toLowerCase() === b.toLowerCase() : a === b
}

// Returns the indices of the matching items, in display order.
function match(items, text, caseInsensitive) {
  var input = String(text || "")
  var tokens = input.split(" ").filter(function(token) { return token.length > 0 })
  var exact = []
  var prefix = []
  var substring = []

  for (var i = 0; i < items.length; i++) {
    var item = String(items[i])
    var all = true
    for (var t = 0; t < tokens.length; t++) {
      if (!contains(item, tokens[t], caseInsensitive)) {
        all = false
        break
      }
    }
    if (!all) continue

    if (tokens.length === 0 || equals(input, item, caseInsensitive)) exact.push(i)
    else if (startsWith(item, tokens[0], caseInsensitive)) prefix.push(i)
    else substring.push(i)
  }

  return exact.concat(prefix, substring)
}

if (typeof module !== "undefined") {
  module.exports = {
    match: match
  }
}
