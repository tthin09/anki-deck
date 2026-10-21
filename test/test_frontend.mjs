// Network-free checks of the originating tab's refresh/heartbeat lifecycle and of picking senses.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../web/main.js', import.meta.url), 'utf8').replace("import './style.css'", '')
const storage = new Map()
let nextJob = 0
const tick = () => new Promise(resolve => setImmediate(resolve))

function node(fields = {}) {
  const classes = new Set()
  return {
    value: '', textContent: '', disabled: false, hidden: false, dataset: {}, children: [], attributes: {},
    style: { setProperty() {} },
    classList: { add: name => classes.add(name), remove: name => classes.delete(name), contains: name => classes.has(name),
      toggle: (name, on = !classes.has(name)) => { on ? classes.add(name) : classes.delete(name); return on } },
    set className(value) { classes.clear(); value.split(' ').filter(Boolean).forEach(name => classes.add(name)) },
    append(...children) { this.children.push(...children) },
    replaceChildren(...children) { this.children = children },
    setAttribute(name, value) { this.attributes[name] = value },
    ...fields,
  }
}

async function page() {
  const elements = new Map(), handlers = {}, calls = [], streams = [], intervals = new Map()
  const element = key => {
    if (!elements.has(key)) elements.set(key, node({ value: 'apple' }))
    return elements.get(key)
  }
  const context = {
    console, TextEncoder, TextDecoder, URL,
    document: { querySelector: element, createElement: () => node() },
    sessionStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    window: { addEventListener: (type, handler) => { handlers[type] = handler }, location: { reload() {} } },
    navigator: { sendBeacon: url => { calls.push(['beacon', url]); return true } },
    fetch: async (url, options = {}) => {
      calls.push([options.method ?? 'GET', url, options.body])
      const data = url === '/api/preview' ? { words: ['apple'], count: 1, error: '' }
        : ['/api/research', '/api/jobs'].includes(url) ? { id: `job${++nextJob}` }
        : url.endsWith('/heartbeat') ? { state: 'running' } : { ok: true }
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

// Research runs as a job: heartbeat while it runs, cancelled when the tab goes away.
const first = await page()
await first.elements.get('#convert').onclick()
assert.equal(first.elements.get('#convert').disabled, true)
assert.equal(first.elements.get('#convert').textContent, 'Đang tìm…')
assert.equal(storage.get('conversion'), 'job1')
assert.equal([...first.intervals.values()][0], 5000)
await [...first.intervals.keys()][0]()
assert(first.calls.some(([, url]) => url === '/api/jobs/job1/heartbeat'))
first.handlers.pagehide()
assert(first.calls.some(([method, url]) => method === 'beacon' && url === '/api/jobs/job1/cancel'))
assert.equal(first.streams[0].closed, true)
assert.equal(first.intervals.size, 0)

// A refreshed tab cancels the previous job before starting another.
const refreshed = await page()
await refreshed.elements.get('#convert').onclick()
assert(refreshed.calls.findIndex(([, url]) => url === '/api/jobs/job1/cancel') < refreshed.calls.findIndex(([, url]) => url === '/api/research'))
assert.equal(storage.get('conversion'), 'job2')
await refreshed.streams[0].onmessage({ data: JSON.stringify({ type: 'cancelled' }) })
assert.equal(storage.has('conversion'), false)
assert.equal(refreshed.elements.get('#convert').textContent, 'Tìm từ')
assert.match(refreshed.elements.get('#error').textContent, /Cancelled/)

// Picking: the first sense of each entry starts selected; only selected senses are converted.
const picking = await page()
await picking.elements.get('#convert').onclick()
const sense = (part_of_speech, vietnamese_meaning) => ({ part_of_speech, vietnamese_meaning, example_sentence: 'A <b>fine</b>.' })
await picking.streams[0].onmessage({ data: JSON.stringify({ type: 'done', percent: 100, result: [
  { input: 'fine', entry: 'fine', corrected: false, senses: [sense('adj', 'ổn'), sense('n', 'tiền phạt')] },
  { input: 'asdfgh', entry: 'asdfgh', corrected: false, senses: [] },
  { input: 'recieve', entry: 'receive', corrected: true, senses: [sense('v', 'nhận')] },
] }) })
const convert = picking.elements.get('#convert'), cards = picking.elements.get('#preview').children
assert.equal(convert.textContent, 'Tạo bộ thẻ')
assert.equal(picking.elements.get('#editor').readOnly, true)
assert.equal(picking.elements.get('#edit').hidden, false)
assert.equal(picking.elements.get('#count').textContent, 2)
const notice = picking.elements.get('#notice').children
assert.equal(notice[0], 'Tôi tìm được các từ sau có nhiều hơn một nghĩa: ')
assert.equal(notice[2].textContent, 'fine')
assert.equal(notice.at(-1), '. Hãy chọn các từ bạn muốn thêm vào Anki bên dưới.')
assert.equal(cards.length, 4)
assert.equal(cards[0].children[0].textContent, 'fine (adj)')
assert.equal(cards[1].classList.contains('off'), true)
assert.equal(cards[2].classList.contains('missing'), true)
assert.equal(cards[3].classList.contains('fixed'), true)
assert.match(cards[3].children[2].children[0].textContent, /Bạn ghi nhầm thành recieve, tôi đã tự sửa lại thành receive/)
cards[1].onclick()
cards[3].onclick()
assert.equal(picking.elements.get('#count').textContent, 2)
await convert.onclick()
const [, , body] = picking.calls.find(([, url]) => url === '/api/jobs')
assert.deepEqual(JSON.parse(body), { research: 'job3', senses: [[0, 0], [0, 1]] })
await picking.streams[1].onmessage({ data: JSON.stringify({ type: 'failed' }) })
assert.equal(convert.textContent, 'Tạo bộ thẻ')
picking.elements.get('#edit').onclick()
assert.equal(convert.textContent, 'Tìm từ')
assert.equal(picking.elements.get('#editor').readOnly, false)
console.log('Frontend research, picking, cancellation, and heartbeat checks passed')
