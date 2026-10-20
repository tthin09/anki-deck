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

function showEditor() {
  app.innerHTML = `<div class="page"><aside class="rail"><h1>Vocabulary<br>Deck Generator</h1><label for="editor">Your words</label><textarea id="editor" spellcheck="false" aria-describedby="hint" placeholder="apple\nbook\ncat"></textarea><p class="hint" id="hint">Paste a list, comma-separated words or spreadsheet rows. Max 100. Drop a .txt file to replace.</p><button id="convert" disabled>Convert →</button><p role="alert" id="error"></p></aside><main class="table"><div class="meta"><span class="count"><b id="count">0</b> cards</span><span class="cap">of 100</span><progress id="progress" value="0" max="100" aria-label="Conversion progress"></progress></div><div id="preview" class="cards" aria-live="polite"></div><details class="build-log"><summary>Build log</summary><pre id="log" aria-live="polite"></pre></details></main></div>`
  const editor = document.querySelector('#editor'), convert = document.querySelector('#convert')
  const error = document.querySelector('#error'), log = document.querySelector('#log'), bar = document.querySelector('#progress'), preview = document.querySelector('#preview')
  let busy = false, count = 0, revision = 0, timer
  // Each word becomes a card; --i/--n let the CSS light cards up as progress reaches them.
  const showCards = words => {
    preview.replaceChildren(...words.map((word, i) => {
      const card = document.createElement('div')
      card.className = 'card'
      card.textContent = word
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
        count = result.count
        document.querySelector('#count').textContent = count
        showCards(result.words)
        error.textContent = result.error || (count > 100 ? 'Maximum 100 unique words' : message)
        convert.disabled = busy || !count || count > 100 || !!result.error
      } catch (err) {
        if (current !== revision) return
        count = 0
        document.querySelector('#count').textContent = 0
        showCards([])
        error.textContent = err.message
      }
    }, 180)
  }
  editor.oninput = () => update()
  editor.ondragover = event => { event.preventDefault() }
  editor.ondrop = async event => {
    event.preventDefault()
    const file = event.dataTransfer.files[0]
    if (!file || !file.name.toLowerCase().endsWith('.txt')) { error.textContent = 'Drop a .txt file'; return }
    if (file.size >= 8192) { error.textContent = 'Input is too large'; return }
    try {
      editor.value = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer())
      update()
    } catch { error.textContent = 'File must be UTF-8' }
  }
  convert.onclick = async () => {
    busy = true; app.dataset.busy = true; editor.readOnly = true; document.querySelector('.build-log').open = true; app.style.setProperty('--p', 5); convert.disabled = true; bar.value = 5; log.textContent = ''; error.textContent = ''
    convert.textContent = 'Converting…'
    const finish = message => {
      stopTracking()
      busy = false
      app.dataset.busy = false
      editor.readOnly = false
      convert.textContent = 'Convert →'
      error.textContent = message
      update(message)
    }
    try {
      await recovery
      const body = JSON.stringify({ text: editor.value })
      if (new TextEncoder().encode(body).length >= 8192) throw Error('Request body must be fewer than 8192 bytes')
      const response = await api('/api/jobs', { method: 'POST', body })
      const { id } = await response.json()
      activeJob = id
      sessionStorage.setItem('conversion', id)
      const stream = activeStream = new EventSource(`/api/jobs/${id}/events`)
      heartbeatTimer = setInterval(async () => {
        try {
          const state = await (await api(`/api/jobs/${id}/heartbeat`, { method: 'POST' })).json()
          if (activeJob === id && state.state === 'cancelled') finish('Conversion cancelled. You can try again.')
        } catch {
          if (activeJob === id) {
            api(`/api/jobs/${id}/cancel`, { method: 'POST' }).catch(() => {})
            finish('Connection lost. Conversion cancelled.')
          }
        }
      }, 5000)
      stream.onmessage = async event => {
        if (activeJob !== id) return
        const status = JSON.parse(event.data)
        bar.value = status.percent ?? bar.value
        app.style.setProperty('--p', bar.value)
        if (status.type === 'line') { log.textContent += `${status.text}\n`; log.scrollTop = log.scrollHeight }
        if (status.type === 'failed') finish('Conversion failed. Try again.')
        if (status.type === 'cancelled') finish('Conversion cancelled. You can try again.')
        if (status.type === 'done') {
          stream.close()
          try {
            const packageResponse = await api(`/api/jobs/${id}/download`)
            const blob = await packageResponse.blob()
            const url = URL.createObjectURL(blob)
            const link = document.createElement('a')
            link.href = url
            link.download = packageResponse.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1] ?? `vocabulary-${id}.apkg`
            link.click()
            setTimeout(() => URL.revokeObjectURL(url), 60000)
          } catch (err) { error.textContent = err.message }
          finish(error.textContent)
        }
      }
      stream.onerror = () => {
        if (activeJob !== id) return
        api(`/api/jobs/${id}/cancel`, { method: 'POST' }).catch(() => {})
        finish('Connection lost. Conversion cancelled. Try again.')
      }
    } catch (err) { finish(err.message) }
  }
  update()
}

showEditor()
