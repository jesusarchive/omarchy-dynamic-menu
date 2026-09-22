// Bounded ASCII JSON frames from the caller. No paths or commands are accepted.
var MAX_BYTES = 2 * 1024 * 1024
var MAX_FRAME = 65536

function utf8Length(text) {
  return unescape(encodeURIComponent(text)).length
}

function options(value) {
  if (!value || Array.isArray(value) || typeof value !== "object"
      || utf8Length(JSON.stringify(value)) > 4096) throw new Error("invalid options")
  var strings = ["barPosition", "prompt", "font", "normBg", "normFg", "selBg", "selFg"]
  Object.keys(value).forEach(function(key) {
    var v = value[key]
    if (strings.indexOf(key) !== -1) {
      if (typeof v !== "string" || v.length > (key === "prompt" ? 1024 : 256))
        throw new Error("invalid option string")
    } else if (key === "lines" || key === "monitor") {
      if (!Number.isInteger(v) || v < -2147483648 || v > 2147483647)
        throw new Error("invalid option number")
    } else if (key === "bottom" || key === "caseInsensitive") {
      if (typeof v !== "boolean") throw new Error("invalid option boolean")
    } else throw new Error("unknown option")
  })
  return value
}

function create(token) {
  return { token: token, pending: "", options: null, chunks: [], bytes: 0, frames: 0, ended: false }
}

function frame(state, data) {
  if (++state.frames > 1026 || state.ended) throw new Error("unexpected frame")
  var message = JSON.parse(data)
  if (!message || Array.isArray(message) || typeof message !== "object") throw new Error("invalid frame")
  if (!state.options) {
    if (message.type !== "begin" || message.token !== state.token) throw new Error("wrong request")
    state.options = options(message.options)
  } else if (message.type === "items") {
    if (typeof message.text !== "string" || !message.text.length || message.text.length > 8192
        || message.text.indexOf("\0") !== -1) throw new Error("invalid items")
    state.bytes += utf8Length(message.text)
    if (state.bytes > MAX_BYTES) throw new Error("too much input")
    state.chunks.push(message.text)
  } else if (message.type === "end") {
    var text = state.chunks.join("")
    var lines = text ? text.split("\n") : []
    if (lines.length && lines[lines.length - 1] === "") lines.pop()
    if (lines.length > 20000) throw new Error("too many items")
    for (var i = 0; i < lines.length; i++)
      if (utf8Length(lines[i]) > 8192) throw new Error("item too long")
    state.ended = true
    state.chunks = []
    return { type: "ready", token: state.token, options: state.options, text: text }
  } else throw new Error("unexpected frame")
  return null
}

function feed(state, chunk) {
  // SplitParser uses raw reads, so it never accumulates an unbounded line.
  if (chunk.length > MAX_BYTES * 6 + 65536 || /[^\x00-\x7f]/.test(chunk))
    throw new Error("invalid wire data")
  var start = 0
  var result = null
  do {
    var end = chunk.indexOf("\n", start)
    var part = chunk.slice(start, end < 0 ? chunk.length : end)
    if (state.pending.length + part.length > MAX_FRAME) throw new Error("frame too large")
    state.pending += part
    if (end < 0) break
    var ready = frame(state, state.pending)
    state.pending = ""
    if (ready) result = ready
    start = end + 1
  } while (start < chunk.length)
  if (state.ended && state.pending) throw new Error("trailing data")
  return result
}

if (typeof module !== "undefined") module.exports = { create: create, feed: feed, utf8Length: utf8Length }
