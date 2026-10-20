// Network-free checks of the originating tab's refresh/heartbeat lifecycle.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../web/main.js', import.meta.url), 'utf8').replace("import './style.css'", '')
const storage = new Map()
let nextJob = 0
const tick = () => new Promise(resolve => setImmediate(resolve))

async function page() {
  const elements = new Map(), handlers = {}, calls = [], streams = [], intervals = new Map()
  const element = key => {
    if (!elements.has(key)) elements.set(key, { value: 'apple', textContent: '', disabled: false })
    return elements.get(key)
  }
  const context = {
    console, TextEncoder, TextDecoder, URL,
    document: { querySelector: element },
    sessionStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    window: { addEventListener: (type, handler) => { handlers[type] = handler }, location: { reload() {} } },
    navigator: { sendBeacon: url => { calls.push(['beacon', url]); return true } },
    fetch: async (url, options = {}) => {
      calls.push([options.method ?? 'GET', url])
      const data = url === '/api/jobs' ? { id: `job${++nextJob}` } : url.endsWith('/heartbeat') ? { state: 'running' } : { ok: true }
      return { ok: true, json: async () => data }
    },
    EventSource: class {
      constructor(url) { this.url = url; streams.push(this) }
      close() { this.closed = true }
    },
    setTimeout: () => 1, clearTimeout() {},
    setInterval: (handler, ms) => { intervals.set(handler, ms); return handler },
    clearInterval: handler => intervals.delete(handler),
  }
  vm.runInNewContext(source, context)
  await tick()
  return { elements, handlers, calls, streams, intervals }
}

const first = await page()
await first.elements.get('#convert').onclick()
assert.equal(first.elements.get('#convert').disabled, true)
assert.equal(first.elements.get('#convert').textContent, 'Converting…')
assert.equal(storage.get('conversion'), 'job1')
assert.equal([...first.intervals.values()][0], 5000)
await [...first.intervals.keys()][0]()
assert(first.calls.some(([, url]) => url === '/api/jobs/job1/heartbeat'))
first.handlers.pagehide()
assert(first.calls.some(([method, url]) => method === 'beacon' && url === '/api/jobs/job1/cancel'))
assert.equal(first.streams[0].closed, true)
assert.equal(first.intervals.size, 0)

const refreshed = await page()
await refreshed.elements.get('#convert').onclick()
assert(refreshed.calls.findIndex(([, url]) => url === '/api/jobs/job1/cancel') < refreshed.calls.findIndex(([, url]) => url === '/api/jobs'))
assert.equal(storage.get('conversion'), 'job2')
refreshed.streams[0].onmessage({ data: JSON.stringify({ type: 'cancelled' }) })
assert.equal(storage.has('conversion'), false)
assert.equal(refreshed.elements.get('#convert').textContent, 'Convert →')
assert.match(refreshed.elements.get('#error').textContent, /cancelled/)
console.log('Frontend refresh, cancellation, and heartbeat checks passed')
