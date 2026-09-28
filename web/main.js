import './style.css'

const app = document.querySelector('#app')
async function api(url, options = {}) {
  const response = await fetch(url, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } })
  if (!response.ok) {
    let body = {}
    try { body = await response.json() } catch {}
    throw Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`)
  }
  return response
}

function showLogin(error = '') {
  app.innerHTML = `<main class="login"><h1>Vocabulary Deck Generator</h1><form id="login"><label>Username<input name="username" autocomplete="username" required></label><label>Password<input name="password" type="password" autocomplete="current-password" required></label><button>Log in</button><p role="alert" id="error"></p></form></main>`
  document.querySelector('#error').textContent = error
  document.querySelector('#login').onsubmit = async event => {
    event.preventDefault()
    const form = new FormData(event.target)
    try {
      const response = await api('/api/login', { method: 'POST', body: JSON.stringify(Object.fromEntries(form)) })
      showEditor((await response.json()).username)
    } catch (err) { document.querySelector('#error').textContent = err.message }
  }
}

function showEditor(user) {
  app.innerHTML = `<header><h1>Vocabulary Deck Generator</h1><div><span id="user"></span> <button id="logout" class="secondary">Log out</button></div></header><main><div class="layout"><section><h2>Vocabulary editor</h2><p>One word or phrase per line. Drop a UTF-8 .txt file here to replace the text.</p><textarea id="editor" aria-label="Vocabulary words" placeholder="apple\nbook\ncat"></textarea></section><div class="actions"><button id="convert" disabled>Convert →</button></div><section><h2>Preview</h2><p><strong id="count">0</strong> / 100 words</p><p id="preview" aria-live="polite">Enter vocabulary to begin.</p><p role="alert" id="error"></p></section></div><section class="status"><h2>Progress</h2><progress id="progress" value="0" max="100"></progress><pre id="log" aria-live="polite"></pre></section></main>`
  document.querySelector('#user').textContent = user
  const editor = document.querySelector('#editor'), convert = document.querySelector('#convert')
  const error = document.querySelector('#error'), log = document.querySelector('#log'), bar = document.querySelector('#progress')
  let busy = false, count = 0, revision = 0, timer
  const update = () => {
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
        document.querySelector('#preview').textContent = result.words.length ? result.words.join(', ') : 'Enter vocabulary to begin.'
        error.textContent = count > 100 ? 'Maximum 100 unique words' : ''
        convert.disabled = busy || !count || count > 100
      } catch (err) { if (current === revision) { count = 0; error.textContent = err.message } }
    }, 180)
  }
  editor.oninput = update
  editor.ondragover = event => { event.preventDefault() }
  editor.ondrop = async event => {
    event.preventDefault()
    const file = event.dataTransfer.files[0]
    if (!file || !file.name.toLowerCase().endsWith('.txt')) { error.textContent = 'Drop a .txt file'; return }
    if (file.size > 32000) { error.textContent = 'Input is too large'; return }
    try {
      editor.value = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer())
      update()
    } catch { error.textContent = 'File must be UTF-8' }
  }
  document.querySelector('#logout').onclick = async () => { await api('/api/logout', { method: 'POST' }); showLogin() }
  convert.onclick = async () => {
    busy = true; convert.disabled = true; bar.value = 5; log.textContent = ''; error.textContent = ''
    try {
      const response = await api('/api/jobs', { method: 'POST', body: JSON.stringify({ text: editor.value }) })
      const { id } = await response.json()
      const stream = new EventSource(`/api/jobs/${id}/events`)
      stream.onmessage = async event => {
        const status = JSON.parse(event.data)
        bar.value = status.percent ?? bar.value
        if (status.type === 'line') { log.textContent += `${status.text}\n`; log.scrollTop = log.scrollHeight }
        if (status.type === 'failed') { stream.close(); busy = false; update(); error.textContent = 'Conversion failed. Try again.' }
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
          busy = false; update()
        }
      }
      stream.onerror = () => { stream.close(); busy = false; update(); error.textContent = 'Connection lost. Try again.' }
    } catch (err) { busy = false; update(); error.textContent = err.message }
  }
  update()
}

api('/api/me').then(r => r.json()).then(data => showEditor(data.username)).catch(() => showLogin())
