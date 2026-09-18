// dmenu's input handling and layout, ported from suckless dmenu 5.4 (dmenu.c)
// and kept Qt-free so node can test it. Function names follow dmenu.c.
//
// The state holds positions into `matches` where dmenu holds item pointers;
// -1 stands for NULL. `textw(str)` must return the width of str plus lrpad,
// like dmenu's TEXTW().

var WORD_DELIMITERS = " "

// readstdin(): one item per line, with the newline stripped. A final line
// without a newline is still an item; empty lines are items too.
function readstdin(text) {
  var s = String(text || "")
  if (s === "") return []
  var lines = s.split("\n")
  if (s.charAt(s.length - 1) === "\n") lines.pop()
  return lines
}

function create(items, options) {
  var opts = options || {}
  var state = {
    items: items.map(String),
    out: {},
    text: "",
    cursor: 0,
    matches: [],
    sel: -1,
    curr: -1,
    next: -1,
    prev: -1,
    // readstdin(): lines = MIN(lines, number of items)
    lines: Math.max(0, Math.min(opts.lines || 0, items.length)),
    caseInsensitive: opts.caseInsensitive === true,
    prompt: String(opts.prompt || ""),
    textw: opts.textw || function(str) { return str.length },
    lrpad: opts.lrpad || 0,
    mw: opts.mw || 0,
    match: opts.match
  }
  match(state)
  return state
}

function item(state, position) {
  return state.items[state.matches[position]]
}

function promptw(state) {
  return state.prompt ? state.textw(state.prompt) - Math.floor(state.lrpad / 4) : 0
}

function inputw(state) {
  return Math.floor(state.mw / 3)
}

function textwClamp(state, str, n) {
  return Math.min(state.textw(str), n)
}

function calcoffsets(state) {
  var count = state.matches.length
  if (state.curr < 0) {
    state.next = state.prev = -1
    return
  }

  var n = state.lines > 0
    ? state.lines
    : state.mw - (promptw(state) + inputw(state) + state.textw("<") + state.textw(">"))

  // which items begin the next page and the previous page
  var i = 0
  for (state.next = state.curr; state.next < count; state.next++)
    if ((i += state.lines > 0 ? 1 : textwClamp(state, item(state, state.next), n)) > n)
      break
  if (state.next >= count) state.next = -1

  i = 0
  for (state.prev = state.curr; state.prev > 0; state.prev--)
    if ((i += state.lines > 0 ? 1 : textwClamp(state, item(state, state.prev - 1), n)) > n)
      break
}

function match(state) {
  state.matches = state.match(state.items, state.text, state.caseInsensitive)
  state.curr = state.sel = state.matches.length > 0 ? 0 : -1
  calcoffsets(state)
}

// Positive n inserts str at the cursor, negative n deletes n characters left
// of it.
function insert(state, str, n) {
  if (n > 0) {
    state.text = state.text.slice(0, state.cursor) + str + state.text.slice(state.cursor)
  } else {
    state.text = state.text.slice(0, state.cursor + n) + state.text.slice(state.cursor)
  }
  state.cursor += n
  match(state)
}

// dmenu steps over UTF-8 continuation bytes; JS strings are UTF-16, so step
// over surrogate pairs instead.
function nextrune(state, inc) {
  var n = state.cursor + inc
  var code = state.text.charCodeAt(n)
  if (inc < 0 && n > 0 && code >= 0xdc00 && code <= 0xdfff) n--
  if (inc > 0 && code >= 0xdc00 && code <= 0xdfff) n++
  return Math.max(0, Math.min(state.text.length, n))
}

function isDelimiter(ch) {
  return ch !== undefined && ch !== "" && WORD_DELIMITERS.indexOf(ch) !== -1
}

function movewordedge(state, dir) {
  var text = state.text
  if (dir < 0) {
    while (state.cursor > 0 && isDelimiter(text[nextrune(state, -1)]))
      state.cursor = nextrune(state, -1)
    while (state.cursor > 0 && !isDelimiter(text[nextrune(state, -1)]))
      state.cursor = nextrune(state, -1)
  } else {
    while (state.cursor < text.length && isDelimiter(text[state.cursor]))
      state.cursor = nextrune(state, +1)
    while (state.cursor < text.length && !isDelimiter(text[state.cursor]))
      state.cursor = nextrune(state, +1)
  }
}

// paste(): insert the selection up to its first newline.
function paste(state, str) {
  var s = String(str || "")
  var newline = s.indexOf("\n")
  if (newline !== -1) s = s.slice(0, newline)
  if (s.length > 0) insert(state, s, s.length)
}

// ev: { key, text, ctrl, shift, alt }. `key` is a keysym-like name: "Return",
// "Escape", "Tab", "BackSpace", "Delete", "Home", "End", "Left", "Right",
// "Up", "Down", "Prior", "Next", "bracketleft", or a letter that is uppercase
// when Shift is held. Anything else is "".
//
// Returns { output, exit, paste }: a line to print (or null), an exit status
// (or null to stay open), and which selection to paste ("primary",
// "clipboard" or null).
function keypress(state, ev) {
  var result = { output: null, exit: null, paste: null }
  var ksym = ev.key
  var ctrl = ev.ctrl === true
  var shift = ev.shift === true
  var count = state.matches.length

  if (ctrl) {
    switch (ksym) {
    case "a": ksym = "Home"; break
    case "b": ksym = "Left"; break
    case "c": ksym = "Escape"; break
    case "d": ksym = "Delete"; break
    case "e": ksym = "End"; break
    case "f": ksym = "Right"; break
    case "g": ksym = "Escape"; break
    case "h": ksym = "BackSpace"; break
    case "i": ksym = "Tab"; break
    case "j":
    case "J":
    case "m":
    case "M": ksym = "Return"; ctrl = false; break
    case "n": ksym = "Down"; break
    case "p": ksym = "Up"; break

    case "k": // delete right
      state.text = state.text.slice(0, state.cursor)
      match(state)
      return result
    case "u": // delete left
      insert(state, null, -state.cursor)
      return result
    case "w": // delete word
      while (state.cursor > 0 && isDelimiter(state.text[nextrune(state, -1)]))
        insert(state, null, nextrune(state, -1) - state.cursor)
      while (state.cursor > 0 && !isDelimiter(state.text[nextrune(state, -1)]))
        insert(state, null, nextrune(state, -1) - state.cursor)
      return result
    case "y": // paste selection
    case "Y":
      result.paste = shift ? "clipboard" : "primary"
      return result
    case "Left":
      movewordedge(state, -1)
      return result
    case "Right":
      movewordedge(state, +1)
      return result
    case "Return":
      break
    case "bracketleft":
      result.exit = 1
      return result
    default:
      return result
    }
  } else if (ev.alt === true) {
    switch (ksym) {
    case "b":
      movewordedge(state, -1)
      return result
    case "f":
      movewordedge(state, +1)
      return result
    case "g": ksym = "Home"; break
    case "G": ksym = "End"; break
    case "h": ksym = "Up"; break
    case "j": ksym = "Next"; break
    case "k": ksym = "Prior"; break
    case "l": ksym = "Down"; break
    default:
      return result
    }
  }

  switch (ksym) {
  case "Delete":
    if (state.cursor >= state.text.length) return result
    state.cursor = nextrune(state, +1)
    // fallthrough
  case "BackSpace":
    if (state.cursor === 0) return result
    insert(state, null, nextrune(state, -1) - state.cursor)
    break
  case "End":
    if (state.cursor < state.text.length) {
      state.cursor = state.text.length
      break
    }
    if (state.next >= 0) {
      // jump to end of list and position items in reverse
      state.curr = count - 1
      calcoffsets(state)
      state.curr = state.prev
      calcoffsets(state)
      while (state.next >= 0 && state.curr + 1 < count) {
        state.curr++
        calcoffsets(state)
      }
    }
    state.sel = count - 1
    break
  case "Escape":
    result.exit = 1
    break
  case "Home":
    if (state.sel === (count > 0 ? 0 : -1)) {
      state.cursor = 0
      break
    }
    state.sel = state.curr = 0
    calcoffsets(state)
    break
  case "Left":
    if (state.cursor > 0 && (state.sel < 0 || state.sel === 0 || state.lines > 0)) {
      state.cursor = nextrune(state, -1)
      break
    }
    if (state.lines > 0) return result
    // fallthrough
  case "Up":
    if (state.sel > 0) {
      state.sel--
      if (state.sel + 1 === state.curr) {
        state.curr = state.prev
        calcoffsets(state)
      }
    }
    break
  case "Next":
    if (state.next < 0) return result
    state.sel = state.curr = state.next
    calcoffsets(state)
    break
  case "Prior":
    if (state.prev < 0) return result
    state.sel = state.curr = state.prev
    calcoffsets(state)
    break
  case "Return":
    result.output = state.sel >= 0 && !shift ? item(state, state.sel) : state.text
    if (!ctrl) {
      result.exit = 0
    } else if (state.sel >= 0) {
      state.out[state.matches[state.sel]] = true
    }
    break
  case "Right":
    if (state.cursor < state.text.length) {
      state.cursor = nextrune(state, +1)
      break
    }
    if (state.lines > 0) return result
    // fallthrough
  case "Down":
    if (state.sel >= 0 && state.sel + 1 < count) {
      state.sel++
      if (state.sel === state.next) {
        state.curr = state.next
        calcoffsets(state)
      }
    }
    break
  case "Tab":
    if (state.sel < 0) return result
    state.text = item(state, state.sel)
    state.cursor = state.text.length
    match(state)
    break
  default:
    // insert: printable text only
    if (ev.text && ev.text.charCodeAt(0) >= 32 && ev.text.charCodeAt(0) !== 127)
      insert(state, ev.text, ev.text.length)
    break
  }

  return result
}

// drawmenu(), as a list of boxes for the view to render. `x`, `y` and `width`
// are pixels; `height` is in rows (bh). `scheme` is "norm", "sel" or "out".
function layout(state) {
  var boxes = []
  var x = 0
  var y = 0
  var mw = state.mw
  var count = state.matches.length

  function scheme(position) {
    if (position === state.sel) return "sel"
    if (state.out[state.matches[position]]) return "out"
    return "norm"
  }

  var pw = promptw(state)
  if (pw > 0) {
    boxes.push({ kind: "prompt", text: state.prompt, x: 0, y: 0, width: pw, scheme: "sel" })
    x = pw
  }

  // input field
  var w = state.lines > 0 || count === 0 ? mw - x : inputw(state)
  boxes.push({ kind: "input", text: state.text, x: x, y: 0, width: w, scheme: "norm" })

  // dmenu measures the whole input and subtracts the suffix. This preserves
  // the cursor position produced by the font shaper around the split.
  var curpos = state.textw(state.text) - state.textw(state.text.slice(state.cursor)) + Math.floor(state.lrpad / 2) - 1
  var cursor = { x: x + curpos, visible: curpos < w }

  if (state.lines > 0) {
    // vertical list
    var end = state.next >= 0 ? state.next : count
    for (var i = state.curr; i >= 0 && i < end; i++) {
      y += 1
      boxes.push({ kind: "item", text: item(state, i), x: x, y: y, width: mw - x, scheme: scheme(i) })
    }
  } else if (count > 0) {
    // horizontal list
    x += inputw(state)
    var arrow = state.textw("<")
    if (state.curr > 0)
      boxes.push({ kind: "arrow", text: "<", x: x, y: 0, width: arrow, scheme: "norm" })
    x += arrow
    var stop = state.next >= 0 ? state.next : count
    for (var j = state.curr; j < stop; j++) {
      var iw = textwClamp(state, item(state, j), mw - x - state.textw(">"))
      boxes.push({ kind: "item", text: item(state, j), x: x, y: 0, width: iw, scheme: scheme(j) })
      x += iw
    }
    if (state.next >= 0) {
      var right = state.textw(">")
      boxes.push({ kind: "arrow", text: ">", x: mw - right, y: 0, width: right, scheme: "norm" })
    }
  }

  return { boxes: boxes, cursor: cursor, rows: state.lines + 1 }
}

// Recompute pages after the bar width changes.
function resize(state, mw) {
  state.mw = mw
  if (state.curr >= 0) calcoffsets(state)
}

if (typeof module !== "undefined") {
  module.exports = {
    readstdin: readstdin,
    create: create,
    keypress: keypress,
    paste: paste,
    layout: layout,
    resize: resize
  }
}
