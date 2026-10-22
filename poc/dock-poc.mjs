// Proof of concept: talk to an Elgato Stream Deck Network Dock directly over TCP.
// Protocol reference: Julusian/node-elgato-stream-deck (packages/tcp, packages/core), MIT.
//
// Usage: node dock-poc.mjs <dock-ip> [seconds]
//
// Flow:
//   1. Connect to the dock (port 5343, "Cora" framing), answer keepalives
//   2. Ask the dock for its info (0x80) and the attached deck (0x1c -> vendor/product/serial/tcp port)
//   3. Connect to the deck's own TCP port, set brightness, paint every key
//   4. Print key presses and toggle the colour of a pressed key

import net from 'node:net'
import jpeg from 'jpeg-js'

const HOST = process.argv[2] ?? '172.16.254.112'
const RUN_SECONDS = Number(process.argv[3] ?? 60)
const DOCK_PORT = 5343

const CORA_MAGIC = Buffer.from([0x43, 0x93, 0x8a, 0x41])
const FLAG_VERBATIM = 0x8000
const FLAG_ACK_NAK = 0x0200
const OP_WRITE = 0x00
const OP_SEND_REPORT = 0x01
const OP_GET_REPORT = 0x02

// 15 key Gen2 decks (Original v2 / MK.2): 5x3, 72x72 JPEG, rotated 180°
const GEN2_15KEY = { cols: 5, rows: 3, keySize: 72, keyDataOffset: 3 }
const KNOWN_DECKS = {
	0x006d: 'Stream Deck Original v2',
	0x0080: 'Stream Deck MK.2',
	0x00a5: 'Stream Deck MK.2 (Scissor)',
	0x00b9: 'Stream Deck MK.2 Module',
}

const log = (...args) => console.log(new Date().toISOString().slice(11, 23), ...args)

class CoraSocket {
	constructor(name, host, port) {
		this.name = name
		this.pending = new Map() // command byte -> resolve
		this.onInput = null
		this.buf = Buffer.alloc(0)
		this.sock = net.connect({ host, port })
		this.sock.setNoDelay(true)
		this.ready = new Promise((resolve, reject) => {
			this._resolveReady = resolve
			this.sock.once('error', reject)
		})
		this.sock.on('data', (d) => this.#onData(d))
		this.sock.on('close', () => log(`[${this.name}] socket closed`))
		this.sock.on('error', (e) => log(`[${this.name}] socket error`, e.message))
	}

	#onData(data) {
		this.buf = Buffer.concat([this.buf, data])
		for (;;) {
			const start = this.buf.indexOf(CORA_MAGIC)
			if (start === -1) {
				if (this.buf.length) log(`[${this.name}] non-Cora data`, this.buf.subarray(0, 16).toString('hex'))
				this.buf = this.buf.subarray(-4)
				return
			}
			if (start > 0) this.buf = this.buf.subarray(start)
			if (this.buf.length < 16) return
			const len = this.buf.readUInt32LE(12)
			if (this.buf.length < 16 + len) return
			const msg = {
				flags: this.buf.readUInt16LE(4),
				hidOp: this.buf.readUInt8(6),
				messageId: this.buf.readUInt32LE(8),
				payload: Buffer.from(this.buf.subarray(16, 16 + len)),
			}
			this.buf = this.buf.subarray(16 + len)
			this.#onMessage(msg)
		}
	}

	#onMessage(msg) {
		const p = msg.payload
		if (p.length > 4 && p[0] === 0x01 && p[1] === 0x0a) {
			// Keepalive: ACK it, first one means "connected"
			const ack = Buffer.alloc(32)
			ack[0] = 0x03
			ack[1] = 0x1a
			ack[2] = p[5]
			this.send(FLAG_ACK_NAK, msg.hidOp, msg.messageId, ack)
			if (this._resolveReady) {
				log(`[${this.name}] connected (keepalive, connection #${p[5]})`)
				this._resolveReady()
				this._resolveReady = null
			}
			return
		}

		// Matching of GET_REPORT replies, same rules as the reference implementation
		let key
		if (p[0] === 0x01 && p[1] === 0x0b) key = 0x1c
		else if (p[0] === 0x01) {
			this.onInput?.(p.subarray(1))
			return
		} else if (msg.flags & FLAG_VERBATIM) key = p[0]
		else key = p[1]

		const resolve = this.pending.get(key)
		if (resolve) {
			this.pending.delete(key)
			resolve(p)
		} else {
			log(`[${this.name}] unhandled flags=0x${msg.flags.toString(16)} op=${msg.hidOp}`, p.subarray(0, 24).toString('hex'))
		}
	}

	send(flags, hidOp, messageId, payload) {
		const header = Buffer.alloc(16)
		CORA_MAGIC.copy(header, 0)
		header.writeUInt16LE(flags, 4)
		header.writeUInt8(hidOp, 6)
		header.writeUInt32LE(messageId, 8)
		header.writeUInt32LE(payload.length, 12)
		this.sock.write(Buffer.concat([header, payload]))
	}

	getReport(command, toHost) {
		return new Promise((resolve, reject) => {
			this.pending.set(command, resolve)
			setTimeout(() => {
				if (this.pending.delete(command)) reject(new Error(`[${this.name}] timeout on report 0x${command.toString(16)}`))
			}, 5000)
			const id = Math.floor(Math.random() * 0xffffff)
			if (toHost) this.send(0, OP_GET_REPORT, id, Buffer.from([0x03, command]))
			else this.send(FLAG_VERBATIM, OP_GET_REPORT, id, Buffer.from([command]))
		})
	}

	sendFeatureReport(data) {
		this.send(FLAG_VERBATIM, OP_SEND_REPORT, 0, Buffer.from(data))
	}

	writeReports(buffers) {
		for (const b of buffers) this.send(FLAG_VERBATIM, OP_WRITE, 0, Buffer.from(b))
	}

	close() {
		this.sock.destroy()
	}
}

function parseDevice2Info(p) {
	if (p[4] !== 0x02) return null
	const serialRaw = p.subarray(94, 125)
	const nul = serialRaw.indexOf(0)
	return {
		vendorId: p.readUInt16LE(26),
		productId: p.readUInt16LE(28),
		serial: serialRaw.subarray(0, nul === -1 ? undefined : nul).toString('ascii'),
		tcpPort: p.readUInt16LE(126),
	}
}

// Render a solid key with a simple centred "digit-ish" block so orientation is visible
function renderKey(size, [r, g, b], marker) {
	const rgba = Buffer.alloc(size * size * 4)
	for (let y = 0; y < size; y++) {
		for (let x = 0; x < size; x++) {
			// White bar in the top-left corner shows whether the 180° rotation is right
			const isMarker = marker && y < size / 6 && x < size / 2
			const i = (y * size + x) * 4
			rgba[i] = isMarker ? 255 : r
			rgba[i + 1] = isMarker ? 255 : g
			rgba[i + 2] = isMarker ? 255 : b
			rgba[i + 3] = 255
		}
	}
	// Gen2 15 key panels expect the image flipped on both axes
	const flipped = Buffer.alloc(rgba.length)
	for (let y = 0; y < size; y++) {
		for (let x = 0; x < size; x++) {
			rgba.copy(flipped, ((size - 1 - y) * size + (size - 1 - x)) * 4, (y * size + x) * 4, (y * size + x) * 4 + 4)
		}
	}
	return jpeg.encode({ data: flipped, width: size, height: size }, 90).data
}

function gen2ImageReports(keyIndex, jpegBytes) {
	const PACKET = 1024
	const HEADER = 8
	const out = []
	let remaining = jpegBytes.length
	for (let part = 0; remaining > 0; part++) {
		const count = Math.min(remaining, PACKET - HEADER)
		const pkt = Buffer.alloc(PACKET)
		pkt[0] = 0x02
		pkt[1] = 0x07
		pkt[2] = keyIndex
		pkt[3] = remaining <= PACKET - HEADER ? 1 : 0
		pkt.writeUInt16LE(count, 4)
		pkt.writeUInt16LE(part, 6)
		const offset = jpegBytes.length - remaining
		jpegBytes.copy(pkt, HEADER, offset, offset + count)
		remaining -= count
		out.push(pkt)
	}
	return out
}

function hsvToRgb(h) {
	const f = (n) => {
		const k = (n + h / 60) % 6
		return Math.round(255 * (1 - Math.max(0, Math.min(k, 4 - k, 1))))
	}
	return [f(5), f(3), f(1)]
}

async function main() {
	log(`Connecting to dock ${HOST}:${DOCK_PORT}`)
	const dock = new CoraSocket('dock', HOST, DOCK_PORT)
	await withTimeout(dock.ready, 8000, 'no keepalive from dock (is another client connected?)')

	const info = await dock.getReport(0x80, true)
	log(`[dock] info vendor=0x${info.readUInt16LE(12).toString(16)} product=0x${info.readUInt16LE(14).toString(16)}`)
	try {
		const fw = await dock.getReport(0x83, true)
		log(`[dock] firmware ${fw.subarray(8, 16).toString('ascii')}`)
		const sn = await dock.getReport(0x84, true)
		log(`[dock] serial ${sn.subarray(4, 4 + sn[3]).toString('ascii')}`)
	} catch (e) {
		log('[dock] optional info failed:', e.message)
	}

	const child = parseDevice2Info(await dock.getReport(0x1c, true))
	if (!child) throw new Error('No Stream Deck attached to the dock')
	const model = KNOWN_DECKS[child.productId] ?? 'unknown'
	log(`[dock] attached: ${model} (vid=0x${child.vendorId.toString(16)} pid=0x${child.productId.toString(16)}) serial=${child.serial} tcpPort=${child.tcpPort}`)
	if (!KNOWN_DECKS[child.productId]) log('WARNING: not a known 15 key Gen2 deck, images/input may be wrong')

	const deck = new CoraSocket('deck', HOST, child.tcpPort)
	await withTimeout(deck.ready, 8000, 'no keepalive from deck port')

	try {
		const fw = await deck.getReport(0x05, false)
		log(`[deck] firmware ${fw.subarray(6, fw[1] + 2).toString('ascii')}`)
	} catch (e) {
		log('[deck] firmware query failed:', e.message)
	}

	const brightness = Buffer.alloc(32)
	brightness[0] = 0x03
	brightness[1] = 0x08
	brightness[2] = 70
	deck.sendFeatureReport(brightness)
	log('[deck] brightness 70%')

	const { cols, rows, keySize, keyDataOffset } = GEN2_15KEY
	const keyCount = cols * rows
	const colours = Array.from({ length: keyCount }, (_, i) => hsvToRgb((i * 360) / keyCount))
	const toggled = new Array(keyCount).fill(false)

	const paint = (i) => {
		const colour = toggled[i] ? [255, 255, 255] : colours[i]
		deck.writeReports(gen2ImageReports(i, renderKey(keySize, colour, !toggled[i])))
	}
	const t0 = Date.now()
	for (let i = 0; i < keyCount; i++) paint(i)
	log(`[deck] painted ${keyCount} keys in ${Date.now() - t0} ms (white bar = top-left of each key)`)

	const state = new Array(keyCount).fill(false)
	deck.onInput = (data) => {
		if (data[0] !== 0x00) {
			log('[deck] non-button input', data.subarray(0, 16).toString('hex'))
			return
		}
		for (let i = 0; i < keyCount; i++) {
			const pressed = Boolean(data[keyDataOffset + i])
			if (pressed === state[i]) continue
			state[i] = pressed
			log(`[deck] key ${i} (row ${Math.floor(i / cols)}, col ${i % cols}) ${pressed ? 'DOWN' : 'UP'}`)
			if (pressed) {
				toggled[i] = !toggled[i]
				paint(i)
			}
		}
	}

	log(`Press some keys. Running for ${RUN_SECONDS}s ...`)
	await new Promise((r) => setTimeout(r, RUN_SECONDS * 1000))

	// Back to the Elgato logo
	const reset = Buffer.alloc(32)
	reset[0] = 0x03
	reset[1] = 0x02
	deck.sendFeatureReport(reset)
	await new Promise((r) => setTimeout(r, 300))
	deck.close()
	dock.close()
	log('Done')
}

function withTimeout(promise, ms, message) {
	return Promise.race([promise, new Promise((_, reject) => setTimeout(() => reject(new Error(message)), ms))])
}

main().catch((e) => {
	console.error('FAILED:', e.message)
	process.exit(1)
})
