// HMAC-SHA-256 protocol. The private bootstrap supplies a fresh 256-bit key.
// HMAC itself is provided by the vendored js-sha256 implementation.
var PREFIX = "omarchy-dynamic-menu-v1\n"
var HEX = /^[0-9a-f]{64}$/

function create(token, secret, hmac) {
  if (!/^[0-9a-f]{32}$/.test(token) || !HEX.test(secret)) throw new Error("invalid bootstrap")
  var key = []
  for (var i = 0; i < secret.length; i += 2) key.push(parseInt(secret.slice(i, i + 2), 16))
  return { token: token, key: key, hmac: hmac, nonce: "", pending: "", ready: false,
           receiveSeq: 0, sendSeq: 0, closed: false }
}

function equal(a, b) {
  if (typeof a !== "string" || !HEX.test(a) || !HEX.test(b)) return false
  var difference = 0
  for (var i = 0; i < 64; i++) difference |= a.charCodeAt(i) ^ b.charCodeAt(i)
  return difference === 0
}

function helloMac(state, role, nonce) {
  return state.hmac(state.key, PREFIX + state.token + "\n" + role + "-hello\n" + nonce)
}

function frameMac(state, direction, sequence, payload) {
  return state.hmac(state.key, PREFIX + state.token + "\n" + state.nonce + "\n"
                   + direction + "\n" + sequence + "\n" + payload)
}

function asciiJSON(value) {
  return JSON.stringify(value).replace(/[\u007f-\uffff]/g, function(ch) {
    return "\\u" + ("0000" + ch.charCodeAt(0).toString(16)).slice(-4)
  })
}

function sign(state, message) {
  if (!state.ready || state.closed || state.sendSeq >= 2147483647) throw new Error("inactive authentication")
  var payload = asciiJSON(message)
  var sequence = state.sendSeq++
  return sequence + ":" + frameMac(state, "reply", sequence, payload) + ":" + payload + "\n"
}

function feed(state, chunk, write, receive) {
  if (state.closed || chunk.length > 2 * 1024 * 1024 * 6 + 65536 || /[^\x00-\x7f]/.test(chunk))
    throw new Error("invalid wire data")
  var start = 0
  do {
    if (state.closed) return
    var end = chunk.indexOf("\n", start)
    var part = chunk.slice(start, end < 0 ? chunk.length : end)
    if (state.pending.length + part.length > (state.ready ? 65536 : 512)) throw new Error("frame too large")
    state.pending += part
    if (end < 0) break
    var line = state.pending
    state.pending = ""
    if (!state.ready) {
      var hello = JSON.parse(line)
      if (!hello || Object.keys(hello).length !== 3 || hello.type !== "challenge"
          || typeof hello.nonce !== "string" || !HEX.test(hello.nonce)
          || !equal(hello.mac, helloMac(state, "server", hello.nonce))) throw new Error("server authentication failed")
      state.nonce = hello.nonce
      state.ready = true
      write(asciiJSON({ type: "proof", mac: helloMac(state, "client", state.nonce) }) + "\n")
    } else {
      var fields = /^(0|[1-9][0-9]{0,9}):([0-9a-f]{64}):(.*)$/.exec(line)
      if (!fields || Number(fields[1]) !== state.receiveSeq
          || !equal(fields[2], frameMac(state, "request", state.receiveSeq, fields[3])))
        throw new Error("request authentication failed")
      state.receiveSeq++
      receive(fields[3])
    }
    start = end + 1
  } while (start < chunk.length)
}

function clear(state) {
  if (!state) return
  state.key.fill(0)
  state.pending = ""
  state.nonce = ""
  state.ready = false
  state.closed = true
}

if (typeof module !== "undefined") module.exports = { create: create, sign: sign, feed: feed,
  clear: clear, helloMac: helloMac, frameMac: frameMac, asciiJSON: asciiJSON }
