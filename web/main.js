import './style.css'

const app = document.querySelector('#app')
let activeJob = null, activeStream = null, heartbeatTimer = null
const previousJob = sessionStorage.getItem('conversion')
const recovery = previousJob ? api(`/api/jobs/${previousJob}/cancel`, { method: 'POST' }).catch(() => {}).finally(() => sessionStorage.removeItem('conversion')) : Promise.resolve()

function stopTracking() {
  clearInterval(heartbeatTimer)
  activeStream?.close()
  activeStream = null
  activeJob = null
  sessionStorage.removeItem('conversion')
}

window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload() })
window.addEventListener('pagehide', () => {
  if (activeJob) {
    const url = `/api/jobs/${activeJob}/cancel`
    if (!navigator.sendBeacon(url)) fetch(url, { method: 'POST', keepalive: true }).catch(() => {})
    clearInterval(heartbeatTimer)
    activeStream?.close()
  }
})
async function api(url, options = {}) {
  const response = await fetch(url, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } })
  if (!response.ok) {
    let body = {}
    try { body = await response.json() } catch {}
    throw Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`)
  }
  return response
}

function el(tag, className, text) {
  const node = document.createElement(tag)
  if (className) node.className = className
  if (text !== undefined) node.textContent = text
  return node
}

function showEditor() {
  app.innerHTML = `<div class="page"><aside class="rail"><h1>Vocabulary<br>Deck Generator</h1><label for="editor">Your words</label><textarea id="editor" spellcheck="false" aria-describedby="hint" placeholder="apple\nbook\nas well as"></textarea><p class="hint" id="hint">Nhập vào danh sách các từ, hoặc kéo thả file Notepad vào đây</p><button id="edit" class="edit" type="button" hidden>← Sửa từ</button><button id="convert" disabled>Tìm từ</button><p role="alert" id="error"></p></aside><main class="table"><div class="meta"><span class="count"><b id="count">0</b> cards</span><span class="cap" id="cap">of 100</span><progress id="progress" value="0" max="100" aria-label="Progress"></progress></div><p id="notice" aria-live="polite"></p><div id="preview" class="cards" aria-live="polite"></div><details class="build-log"><summary>Build log</summary><pre id="log" aria-live="polite"></pre></details></main></div>`
  const editor = document.querySelector('#editor'), convert = document.querySelector('#convert'), edit = document.querySelector('#edit')
  const error = document.querySelector('#error'), notice = document.querySelector('#notice'), log = document.querySelector('#log'), bar = document.querySelector('#progress'), preview = document.querySelector('#preview')
  // research: { id, entries, cards: [{ key, node }] in display order, selected: Set of "entry,sense" keys }
  let busy = false, count = 0, revision = 0, timer, research = null
  const setCount = value => { count = value; document.querySelector('#count').textContent = value }
  // Each word becomes a card; --i/--n let the CSS light cards up as progress reaches them.
  const showCards = words => {
    preview.replaceChildren(...words.map((word, i) => {
      const card = el('div', 'card', word)
      card.style.setProperty('--i', i)
      card.style.setProperty('--r', `${(word.length * 7) % 9 - 4}deg`)
      return card
    }))
    preview.style.setProperty('--n', words.length)
  }
  const update = (message = '') => {
    convert.disabled = true
    const current = ++revision
    clearTimeout(timer)
    timer = setTimeout(async () => {
      try {
        const response = await api('/api/preview', { method: 'POST', body: JSON.stringify({ text: editor.value }) })
        const result = await response.json()
        if (current !== revision) return
        setCount(result.count)
        showCards(result.words)
        error.textContent = result.error || (count > 100 ? 'Maximum 100 unique words' : message)
        convert.disabled = busy || !count || count > 100 || !!result.error
      } catch (err) {
        if (current !== revision) return
        setCount(0)
        showCards([])
        error.textContent = err.message
      }
    }, 180)
  }
  const toInput = (message = '') => {
    research = null
    editor.readOnly = false
    editor.classList.remove('locked')
    edit.hidden = true
    notice.replaceChildren()
    convert.textContent = 'Tìm từ'
    document.querySelector('#cap').textContent = 'of 100'
    update(message)
  }
  const toPicking = () => {
    editor.readOnly = true
    editor.classList.add('locked')
    edit.hidden = false
    convert.textContent = 'Tạo bộ thẻ'
    document.querySelector('#cap').textContent = 'selected'
    setCount(research.selected.size)
    convert.disabled = !count
  }
  // One card per sense; an entry's first sense starts selected.
  const showSenses = () => {
    research.cards = []
    let group = 0
    const nodes = research.entries.flatMap((item, e) => {
      const g = item.senses.length > 1 ? group++ : 0
      if (!item.senses.length) {
        const card = el('div', 'card sense missing')
        card.append(el('span', 'head', item.input), el('i', 'meaning', 'Không tìm thấy nghĩa'))
        return [card]
      }
      return item.senses.map((sense, s) => {
        const key = `${e},${s}`, card = el('button', 'card sense')
        card.type = 'button'
        card.style.setProperty('--r', `${(item.entry.length * 7 + s * 3) % 9 - 4}deg`)
        // --g: the senses of one word blink together, one word after another
        if (item.senses.length > 1) { card.classList.add('multi'); card.style.setProperty('--g', g) }
        if (item.corrected) card.classList.add('fixed')
        const tip = el('span', 'tip')
        if (item.corrected) tip.append(el('span', 'fix', `Bạn ghi nhầm thành ${item.input}, tôi đã tự sửa lại thành ${item.entry}`))
        const example = el('span')
        example.innerHTML = sense.example_sentence  // the server allow-lists <b>, <i> and <br> only
        tip.append(example)
        card.append(el('span', 'head', sense.part_of_speech ? `${item.entry} (${sense.part_of_speech})` : item.entry),
          el('i', 'meaning', sense.vietnamese_meaning), tip)
        const paint = () => {
          card.classList.toggle('off', !research.selected.has(key))
          card.setAttribute('aria-pressed', String(research.selected.has(key)))
        }
        card.onclick = () => {
          if (busy) return
          research.selected.has(key) ? research.selected.delete(key) : research.selected.add(key)
          paint()
          setCount(research.selected.size)
          convert.disabled = !count
        }
        paint()
        research.cards.push({ key, node: card })
        return card
      })
    })
    preview.replaceChildren(...nodes)
    const multi = research.entries.filter(item => item.senses.length > 1)
    notice.replaceChildren(...(multi.length ? ['Tôi tìm được các từ sau có nhiều hơn một nghĩa: ',
      ...multi.flatMap((item, i) => [i ? ', ' : '', el('b', '', item.entry)]),
      '. Hãy chọn các từ bạn muốn thêm vào Anki bên dưới.'] : []))
  }
  const download = async id => {
    const packageResponse = await api(`/api/jobs/${id}/download`)
    const blob = await packageResponse.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = packageResponse.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1] ?? `vocabulary-${id}.apkg`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  }
  // Runs a research or conversion job; after(ok, message) restores the screen when it ends.
  const runJob = async (url, payload, working, onDone, after) => {
    busy = true; app.dataset.busy = true; editor.readOnly = true; edit.disabled = true; document.querySelector('.build-log').open = true; app.style.setProperty('--p', 5); convert.disabled = true; bar.value = 5; log.textContent = ''; error.textContent = ''
    convert.textContent = working
    const finish = (ok, message) => {
      stopTracking()
      busy = false
      app.dataset.busy = false
      edit.disabled = false
      after(ok, message)
      error.textContent = message
    }
    try {
      await recovery
      const body = JSON.stringify(payload)
      if (new TextEncoder().encode(body).length >= 8192) throw Error('Request body must be fewer than 8192 bytes')
      const response = await api(url, { method: 'POST', body })
      const { id } = await response.json()
      activeJob = id
      sessionStorage.setItem('conversion', id)
      const stream = activeStream = new EventSource(`/api/jobs/${id}/events`)
      heartbeatTimer = setInterval(async () => {
        try {
          const state = await (await api(`/api/jobs/${id}/heartbeat`, { method: 'POST' })).json()
          if (activeJob === id && state.state === 'cancelled') finish(false, 'Cancelled. You can try again.')
        } catch {
          if (activeJob === id) {
            api(`/api/jobs/${id}/cancel`, { method: 'POST' }).catch(() => {})
            finish(false, 'Connection lost. Cancelled.')
          }
        }
      }, 5000)
      stream.onmessage = async event => {
        if (activeJob !== id) return
        const status = JSON.parse(event.data)
        bar.value = status.percent ?? bar.value
        app.style.setProperty('--p', bar.value)
        if (status.type === 'line') { log.textContent += `${status.text}\n`; log.scrollTop = log.scrollHeight }
        if (status.type === 'failed') finish(false, 'Failed. Try again.')
        if (status.type === 'cancelled') finish(false, 'Cancelled. You can try again.')
        if (status.type === 'done') {
          stream.close()
          let message = ''
          try { await onDone(id, status) } catch (err) { message = err.message }
          finish(true, message)
        }
      }
      stream.onerror = () => {
        if (activeJob !== id) return
        api(`/api/jobs/${id}/cancel`, { method: 'POST' }).catch(() => {})
        finish(false, 'Connection lost. Cancelled. Try again.')
      }
    } catch (err) { finish(false, err.message) }
  }
  editor.oninput = () => update()
  editor.ondragover = event => { event.preventDefault() }
  editor.ondrop = async event => {
    event.preventDefault()
    if (editor.readOnly) return
    const file = event.dataTransfer.files[0]
    if (!file || !file.name.toLowerCase().endsWith('.txt')) { error.textContent = 'Drop a .txt file'; return }
    if (file.size >= 8192) { error.textContent = 'Input is too large'; return }
    try {
      editor.value = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer())
      update()
    } catch { error.textContent = 'File must be UTF-8' }
  }
  edit.onclick = () => { if (!busy) toInput() }
  convert.onclick = () => {
    if (!research) {
      return runJob('/api/research', { text: editor.value }, 'Đang tìm…', (id, status) => {
        research = { id, entries: status.result, selected: new Set(status.result.flatMap((item, e) => item.senses.length ? [`${e},0`] : [])) }
      }, (ok, message) => ok && research ? (showSenses(), toPicking()) : toInput(message))
    }
    // Conversion: only the selected senses, in display order, light up as the deck builds.
    const chosen = research.cards.filter(card => research.selected.has(card.key))
    chosen.forEach((card, i) => card.node.style.setProperty('--i', i))
    preview.style.setProperty('--n', chosen.length)
    return runJob('/api/jobs', { research: research.id, senses: chosen.map(card => card.key.split(',').map(Number)) },
      'Đang tạo…', download, () => toPicking())
  }
  update()
}

showEditor()
