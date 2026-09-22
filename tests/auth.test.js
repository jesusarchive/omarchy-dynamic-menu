const test = require("node:test")
const assert = require("node:assert/strict")
const crypto = require("node:crypto")
const fs = require("node:fs")
const vm = require("node:vm")
const Auth = require("../Auth.js")

// Run the vendored code without Node's crypto/module globals, as QML does.
const context = vm.createContext({})
vm.runInContext(fs.readFileSync(require.resolve("../vendor/Sha256.js"), "utf8"), context)
const hmac = context.sha256.hmac
const token = "a".repeat(32), secret = "b".repeat(64), nonce = "c".repeat(64)
const fresh = () => Auth.create(token, secret, hmac)
const wireHello = (state, challenge = nonce) => JSON.stringify({type: "challenge", nonce: challenge,
  mac: Auth.helloMac(state, "server", challenge)}) + "\n"
const ready = () => {
  const state = fresh()
  Auth.feed(state, wireHello(state), () => {}, () => {})
  return state
}
const request = (state, seq, body, direction = "request") =>
  seq + ":" + Auth.frameMac(state, direction, seq, body) + ":" + body + "\n"

test("QML HMAC implementation passes RFC 4231 SHA-256 vectors", () => {
  const vectors = [
    [Array(20).fill(0x0b), "Hi There", "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7"],
    [Array.from(Buffer.from("Jefe")), "what do ya want for nothing?", "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"],
    [Array(131).fill(0xaa), "Test Using Larger Than Block-Size Key - Hash Key First",
      "60e431591ee0b67f0d8a26aacbf5b77f8e0bc6213728c5140546040f0ee37f54"]
  ]
  for (const [key, text, expected] of vectors) assert.equal(hmac(key, text), expected)
})

test("QML HMAC agrees with Node crypto across block sizes and Unicode", () => {
  for (const length of [0, 1, 55, 56, 63, 64, 65, 8192, 49152]) {
    const key = crypto.randomBytes(32), text = "x".repeat(length) + "🐈"
    assert.equal(hmac(Array.from(key), text), crypto.createHmac("sha256", key).update(text).digest("hex"))
  }
})

test("mutual challenge-response validates the server before revealing a proof", () => {
  const state = fresh(), writes = []
  const hello = wireHello(state)
  for (const ch of hello) Auth.feed(state, ch, text => writes.push(JSON.parse(text)), () => assert.fail())
  assert.equal(state.ready, true)
  assert.deepEqual(writes, [{type: "proof", mac: Auth.helloMac(state, "client", nonce)}])
  assert.ok(!writes[0].mac.includes(secret))
  for (const bad of [hello.replace(nonce, "d".repeat(64)), hello.replace(/"mac":"[^"]+"/, '"mac":"' + "0".repeat(64) + '"'),
    '{"type":"challenge"}\n', '{"type":"output","text":"injected"}\n']) {
    assert.throws(() => Auth.feed(fresh(), bad, () => assert.fail("unverified server received proof"), () => assert.fail()))
  }
})

test("signed frames preserve literal Unicode text and have request/reply separation", () => {
  const state = ready(), received = []
  const body = Auth.asciiJSON({type: "items", text: "🐈 'quotes' $(literal)\n"})
  const wire = request(state, 0, body)
  for (let i = 0; i < wire.length; i += 7)
    Auth.feed(state, wire.slice(i, i + 7), () => assert.fail(), text => received.push(JSON.parse(text)))
  assert.deepEqual(received, [{type: "items", text: "🐈 'quotes' $(literal)\n"}])
  const reply = Auth.sign(state, {type: "output", text: "literal"})
  assert.throws(() => Auth.feed(ready(), reply, () => assert.fail(), () => assert.fail("reflected reply accepted")))
})

test("tampering, replay, reordering, another request, and another connection are rejected", () => {
  const body = '{"type":"begin"}'
  const state = ready(), wire = request(state, 0, body)
  Auth.feed(state, wire, () => {}, () => {})
  assert.throws(() => Auth.feed(state, wire, () => {}, () => assert.fail("replay accepted")))
  const otherRequest = ready(); otherRequest.token = "d".repeat(32)
  const otherConnection = ready(); otherConnection.nonce = "e".repeat(64)
  const wrongKey = ready(); wrongKey.key[0] ^= 1
  for (const bad of [wire.replace("begin", "output"), request(ready(), 1, body),
    request(otherRequest, 0, body), request(otherConnection, 0, body), request(wrongKey, 0, body)])
    assert.throws(() => Auth.feed(ready(), bad, () => {}, () => assert.fail("forgery accepted")))
})

test("handshake and authenticated buffers are bounded; closed requests cannot sign", () => {
  assert.throws(() => Auth.feed(fresh(), "x".repeat(513), () => {}, () => {}))
  assert.throws(() => Auth.feed(ready(), "x".repeat(65537), () => {}, () => {}))
  const state = ready()
  Auth.clear(state)
  assert.ok(state.key.every(byte => byte === 0))
  assert.throws(() => Auth.sign(state, {type: "exit", status: 0}))
  assert.throws(() => Auth.feed(state, wireHello(fresh()), () => {}, () => {}))
})
