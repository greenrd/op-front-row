const state = {
  status: null,
  threads: [],
  source: null,
  selected: new Set(),
  summary: null,
  summarising: false,
  loadingThreads: false,
  threadsError: null,
  settings: null,
};

const view = document.getElementById('view');
const banner = document.getElementById('banner');

// ---------- helpers ----------
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmtDate = (iso) => new Date(iso).toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  let body = null;
  try { body = await res.json(); } catch { /* no body */ }
  if (!res.ok) {
    const err = new Error(body?.detail || res.statusText);
    err.status = res.status;
    throw err;
  }
  return body;
}

function showBanner(html, kind = '') {
  banner.innerHTML = html;
  banner.className = 'banner ' + kind;
}
function hideBanner() { banner.className = 'banner hidden'; }

function route() {
  const hash = location.hash || '#/';
  const [path, query] = hash.slice(1).split('?');
  return { path: path || '/', params: new URLSearchParams(query || '') };
}
function navigate(hash) { location.hash = hash; }

function allViewerMessages() {
  return state.threads.flatMap((t) => t.messages.filter((m) => !m.from_me));
}
function messageById(id) {
  for (const t of state.threads) for (const m of t.messages) if (m.id === id) return { thread: t, message: m };
  return null;
}

// ---------- data ----------
async function loadStatus() {
  state.status = await api('/api/status');
  const acct = document.getElementById('account');
  if (state.status.demo_mode) acct.textContent = 'Demo data';
  else if (state.status.import_mode) acct.textContent = 'Imported DMs' + (state.status.ig_username ? ' · @' + state.status.ig_username : '');
  else if (state.status.instagram_configured) acct.textContent = state.status.ig_username ? '@' + state.status.ig_username : 'Instagram connected';
  else acct.textContent = 'Instagram not connected';
}

async function loadThreads() {
  state.loadingThreads = true;
  state.threadsError = null;
  render();
  try {
    const data = await api('/api/threads?days=7');
    state.threads = data.threads;
    state.source = data.source;
    state.selected = new Set(allViewerMessages().map((m) => m.id));
  } catch (e) {
    state.threads = [];
    state.threadsError = e.message;
  } finally {
    state.loadingThreads = false;
    render();
  }
}

async function summarise() {
  if (!state.status.llm_configured) {
    showBanner('Add your LLM endpoint and API key before summarising. <a href="#/settings">Open Settings</a>');
    navigate('#/settings');
    return;
  }
  state.summarising = true;
  state.summary = null;
  navigate('#/summary');
  render();
  try {
    state.summary = await api('/api/summarise', { method: 'POST', body: JSON.stringify({ message_ids: [...state.selected] }) });
    hideBanner();
  } catch (e) {
    if (e.status === 428) { navigate('#/settings'); }
    showBanner(esc(e.message), 'error');
  } finally {
    state.summarising = false;
    render();
  }
}

// ---------- views ----------
function renderInbox(params) {
  const total = allViewerMessages().length;
  const selectedCount = state.selected.size;
  let html = `
    <h1>Inbox – last 7 days</h1>
    <p class="sub">Viewer messages are ticked by default. Untick anything you don't want included, then press Summarise.</p>
    <div class="toolbar row">
      <button id="reload">Reload</button>
      <button id="select-all" class="link">Select all</button>
      <button id="select-none" class="link">Select none</button>
      <span class="count">${selectedCount} of ${total} messages selected${state.source === 'demo' ? ' · demo data' : state.source === 'import' ? ' · imported DMs' : ''}</span>
      <span class="spacer"></span>
      <button id="summarise" class="primary" ${selectedCount === 0 || state.summarising ? 'disabled' : ''}>${state.summarising ? '<span class="spinner"></span>Summarising…' : 'Summarise'}</button>
    </div>`;

  if (state.loadingThreads) {
    html += `<div class="empty"><span class="spinner"></span>Fetching DM threads…</div>`;
  } else if (state.threadsError) {
    html += `<div class="card"><p class="err">${esc(state.threadsError)}</p><p><a href="#/settings">Go to Settings</a> to connect Instagram or enable demo mode.</p></div>`;
  } else if (!state.status.demo_mode && !state.status.import_mode && !state.status.instagram_configured) {
    html += `<div class="card"><p>Instagram is not connected yet.</p><p><a href="#/settings">Go to Settings</a> to log in with Instagram, paste an access token, import DMs, or enable demo mode.</p></div>`;
  } else if (state.threads.length === 0) {
    html += `<div class="empty">No DM threads with messages in the last 7 days.${state.source === 'instagram' ? ' If Meta\'s API returns nothing for your account, you can <a href="#/settings">import your DMs</a> instead.' : ''}</div>`;
  } else {
    for (const t of state.threads) {
      const viewerMsgs = t.messages.filter((m) => !m.from_me);
      const checked = viewerMsgs.filter((m) => state.selected.has(m.id)).length;
      const threadState = checked === 0 ? '' : checked === viewerMsgs.length ? 'checked' : 'checked data-indeterminate="1"';
      html += `
        <section class="card thread" id="thread-${esc(t.id)}">
          <div class="thread-head">
            <input type="checkbox" data-thread="${esc(t.id)}" ${threadState} ${viewerMsgs.length === 0 ? 'disabled' : ''} title="Select all messages in this thread" />
            <span class="who">@${esc(t.participant_username || t.participant_id)}</span>
            <span class="when">${t.messages.length} message${t.messages.length === 1 ? '' : 's'} · last ${fmtDate(t.updated_time)}</span>
            <span class="spacer"></span>
            ${t.participant_username ? `<a href="https://www.instagram.com/${encodeURIComponent(t.participant_username)}/" target="_blank" rel="noopener" class="ext">Profile ↗</a>` : ''}
          </div>
          ${t.messages.map((m) => renderMessage(m, t)).join('')}
        </section>`;
    }
  }
  view.innerHTML = html;

  document.getElementById('reload').onclick = loadThreads;
  document.getElementById('select-all').onclick = () => { state.selected = new Set(allViewerMessages().map((m) => m.id)); render(); };
  document.getElementById('select-none').onclick = () => { state.selected = new Set(); render(); };
  document.getElementById('summarise').onclick = summarise;
  view.querySelectorAll('input[data-msg]').forEach((cb) => {
    cb.onchange = () => { cb.checked ? state.selected.add(cb.dataset.msg) : state.selected.delete(cb.dataset.msg); render(); };
  });
  view.querySelectorAll('input[data-thread]').forEach((cb) => {
    if (cb.dataset.indeterminate) cb.indeterminate = true;
    cb.onchange = () => {
      const t = state.threads.find((x) => x.id === cb.dataset.thread);
      for (const m of t.messages) if (!m.from_me) cb.checked ? state.selected.add(m.id) : state.selected.delete(m.id);
      render();
    };
  });

  const focus = params.get('msg');
  if (focus) {
    const el = document.getElementById('msg-' + focus);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('highlight');
      setTimeout(() => el.classList.remove('highlight'), 2500);
    }
    history.replaceState(null, '', '#/');
  }
}

function renderMessage(m, t) {
  const cls = ['msg', m.from_me ? 'me' : '', !m.from_me && !state.selected.has(m.id) ? 'unchecked' : ''].join(' ');
  const checkbox = m.from_me
    ? '<span style="width:18px"></span>'
    : `<input type="checkbox" data-msg="${esc(m.id)}" ${state.selected.has(m.id) ? 'checked' : ''} />`;
  return `
    <div class="${cls}" id="msg-${esc(m.id)}">
      ${checkbox}
      <div class="body">
        <div class="meta">${m.from_me ? 'You' : '@' + esc(m.sender_username || m.sender_id)} · ${fmtDate(m.created_time)}</div>
        <div>${esc(m.text)}</div>
      </div>
    </div>`;
}

function renderSummary() {
  let html = `<h1>Video ideas from your DMs</h1>`;
  if (state.summarising) {
    html += `<p class="sub">Asking the LLM to identify, deduplicate and summarise questions and suggestions…</p><div class="empty"><span class="spinner"></span>Summarising ${state.selected.size} messages…</div>`;
  } else if (!state.summary) {
    html += `<p class="sub">No summary yet.</p><div class="empty">Go to the <a href="#/">Inbox</a>, pick the messages you want, and press Summarise.</div>`;
  } else {
    const s = state.summary;
    html += `<p class="sub">${esc(s.overview)} <span class="count">(${s.messages_considered} viewer messages · ${esc(s.model)})</span></p>
      <div class="row" style="margin-bottom:16px"><button id="resummarise" class="primary">Re-run summary</button><a href="#/" style="margin-left:8px">Back to inbox</a></div>`;
    if (s.items.length === 0) html += `<div class="empty">The LLM found no questions or suggestions in the selected messages.</div>`;
    for (const it of s.items) {
      html += `
        <section class="card summary-item">
          <div class="badge"><span class="num">${it.count}</span><span class="lbl">${it.count === 1 ? 'viewer' : 'viewers'}</span></div>
          <div>
            <h3>${esc(it.title)} <span class="kind ${esc(it.kind)}">${esc(it.kind)}</span></h3>
            <div>${esc(it.summary)}</div>
            <div class="sources">
              ${it.message_ids.map((id) => renderSource(id)).join('')}
            </div>
          </div>
        </section>`;
    }
  }
  view.innerHTML = html;
  const btn = document.getElementById('resummarise');
  if (btn) btn.onclick = summarise;
}

function renderSource(id) {
  const found = messageById(id);
  if (!found) return `<div class="source">Message ${esc(id)} (no longer loaded)</div>`;
  const { message: m, thread: t } = found;
  const profile = t.participant_username ? `<a class="ext" href="https://www.instagram.com/${encodeURIComponent(t.participant_username)}/" target="_blank" rel="noopener">Instagram ↗</a>` : '';
  return `<div class="source">
      <a href="#/?msg=${encodeURIComponent(id)}" title="Open this message in the inbox"><span class="q">“${esc(m.text)}”</span></a>
      <span class="by">— @${esc(m.sender_username || m.sender_id)}, ${fmtDate(m.created_time)}</span>${profile}
    </div>`;
}

async function renderSettings(params) {
  if (!state.settings) state.settings = await api('/api/settings');
  const s = state.settings;
  const st = state.status;
  const error = params.get('error');
  const canOAuth = s.ig_app_id && s.ig_app_secret && s.public_base_url;
  view.innerHTML = `
    <h1>Settings</h1>
    <p class="sub">Settings are stored locally in <code>data/settings.json</code> on the server.</p>
    ${error ? `<div class="card"><p class="err">${esc(error)}</p></div>` : ''}

    <form id="llm-form" class="card">
      <h2 style="margin-top:0">LLM (OpenAI-compatible)</h2>
      <label class="field"><span>Endpoint base URL</span><input name="llm_base_url" placeholder="https://api.openai.com/v1" value="${esc(s.llm_base_url)}" /></label>
      <label class="field"><span>API key</span><input name="llm_api_key" type="password" placeholder="${s.llm_api_key ? 'stored (' + esc(s.llm_api_key) + ') – paste to replace' : 'sk-…'}" autocomplete="off" /></label>
      <label class="field"><span>Model</span><input name="llm_model" placeholder="gpt-4o-mini" value="${esc(s.llm_model)}" /></label>
      <div class="row"><button class="primary" type="submit">Save LLM settings</button><span id="llm-msg" class="count">${s.llm_configured ? '<span class="ok">Configured</span>' : '<span class="err">Not configured – required for Summarise</span>'}</span></div>
    </form>

    <form id="ig-form" class="card">
      <h2 style="margin-top:0">Instagram Professional account</h2>
      <p class="help">Status: ${s.instagram_configured ? `<span class="ok">connected${s.ig_username ? ' as @' + esc(s.ig_username) : ''}</span>` : '<span class="err">not connected</span>'}</p>
      <h3>Option A – Log in with Instagram</h3>
      <p class="help">Create a Meta app with the <em>Instagram API with Instagram Login</em> product, add <code>&lt;public base URL&gt;/api/instagram/callback</code> as a valid OAuth redirect URI, and make sure your account is an Instagram Professional (Business/Creator) account.</p>
      <label class="field"><span>Instagram App ID</span><input name="ig_app_id" value="${esc(s.ig_app_id)}" /></label>
      <label class="field"><span>Instagram App Secret</span><input name="ig_app_secret" type="password" placeholder="${s.ig_app_secret ? 'stored (' + esc(s.ig_app_secret) + ') – paste to replace' : ''}" autocomplete="off" /></label>
      <label class="field"><span>Public base URL of this app (https, e.g. your ngrok URL)</span><input name="public_base_url" placeholder="https://xxxx.ngrok.app" value="${esc(s.public_base_url)}" /></label>
      <h3>Option B – Paste an access token</h3>
      <p class="help">Preferred: an Instagram Login token (starts with <code>IGAA</code>) from the app dashboard → Instagram → <em>API setup with Instagram login</em> → Generate token, with <code>instagram_business_basic</code> and <code>instagram_business_manage_messages</code>. A Facebook token (starts with <code>EAA</code>, scopes <code>instagram_basic</code>/<code>instagram_manage_messages</code>) also works if it can access a Facebook Page linked to the Instagram account.</p>
      <label class="field"><span>Access token</span><input name="ig_access_token" type="password" placeholder="${s.ig_access_token ? 'stored (' + esc(s.ig_access_token) + ') – paste to replace' : 'IGAA… or EAA…'}" autocomplete="off" /></label>
      <div class="row">
        <button class="primary" type="submit">Save Instagram settings</button>
        <a href="/api/instagram/login" id="ig-login"><button type="button" ${canOAuth ? '' : 'disabled title="Save App ID, App Secret and Public base URL first"'}>Log in with Instagram</button></a>
        <button type="button" id="ig-verify" ${s.instagram_configured ? '' : 'disabled'}>Verify token</button>
        <button type="button" id="ig-disconnect" class="danger" ${s.instagram_configured ? '' : 'disabled'}>Disconnect</button>
        <span id="ig-msg" class="count"></span>
      </div>
    </form>

    <div class="card" id="import-card">
      <h2 style="margin-top:0">Import DMs (no API needed)</h2>
      <p class="help">Status: ${st.import_mode ? `<span class="ok">using ${st.imported_threads} imported thread${st.imported_threads === 1 ? '' : 's'}</span>` : st.imported_threads ? `${st.imported_threads} thread${st.imported_threads === 1 ? '' : 's'} imported (not active)` : 'nothing imported'}</p>
      <h3>Option 1 – Instagram data export</h3>
      <p class="help">Instagram app → Settings → Your activity → <em>Download your information</em> → Download or transfer information → select <em>Messages</em> → format <strong>JSON</strong>. Upload the resulting zip (or a single <code>message_1.json</code>).</p>
      <label class="field"><span>Your display name as it appears in the export (optional – auto-detected as the participant common to all threads)</span><input id="export-owner" placeholder="Robin Green" /></label>
      <div class="row">
        <input type="file" id="export-file" accept=".zip,.json,application/zip,application/json" />
        <button type="button" id="export-upload" class="primary">Upload export</button>
        <span id="export-msg" class="count"></span>
      </div>
      <h3>Option 2 – Paste messages</h3>
      <p class="help">One message per line as <code>@username: text</code>; leave a blank line between threads. Lines from <code>@${esc(s.ig_username || 'me')}</code> or <code>me:</code> count as your own replies.</p>
      <textarea id="paste-text" rows="7" placeholder="@viewer1: Could you do a video on evaluating RAG pipelines?&#10;me: Great idea, noted!&#10;&#10;@viewer2: How do I pitch an AI budget to my board?"></textarea>
      <div class="row">
        <button type="button" id="paste-import" class="primary">Import pasted messages</button>
        <button type="button" id="import-clear" class="danger" ${st.imported_threads ? '' : 'disabled'}>Clear import & go back to Instagram</button>
        <span id="paste-msg" class="count"></span>
      </div>
    </div>

    <div class="card">
      <h2 style="margin-top:0">Demo mode</h2>
      <label class="check"><input type="checkbox" id="demo" ${s.demo_mode ? 'checked' : ''} /> Use built-in sample DM threads instead of Instagram</label>
      <p class="help">Handy for trying the summariser before Instagram is connected.</p>
    </div>`;

  document.getElementById('llm-form').onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    await saveSettings(Object.fromEntries(fd.entries()));
    document.getElementById('llm-msg').innerHTML = state.settings.llm_configured ? '<span class="ok">Saved – configured</span>' : '<span class="err">Saved, but endpoint or key is empty</span>';
  };
  document.getElementById('ig-form').onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const token = fd.get('ig_access_token').trim();
    await saveSettings(Object.fromEntries(fd.entries()));
    document.getElementById('ig-msg').textContent = token
      ? `Saved – new token stored (${state.settings.ig_access_token})`
      : 'Saved (token unchanged)';
  };
  document.getElementById('ig-verify').onclick = async () => {
    const msg = document.getElementById('ig-msg');
    msg.innerHTML = '<span class="spinner"></span>Checking…';
    try {
      state.settings = await api('/api/instagram/verify', { method: 'POST' });
      await loadStatus();
      render();
    } catch (err) { msg.innerHTML = `<span class="err">${esc(err.message)}</span>`; }
  };
  document.getElementById('ig-disconnect').onclick = async () => {
    state.settings = await api('/api/instagram/disconnect', { method: 'POST' });
    state.threads = []; state.selected = new Set();
    await loadStatus();
    render();
  };
  document.getElementById('demo').onchange = async (e) => {
    await saveSettings({ demo_mode: e.target.checked });
    state.threads = []; state.selected = new Set(); state.summary = null;
  };

  const afterImport = async (r, msgEl) => {
    state.threads = []; state.selected = new Set(); state.summary = null;
    state.settings = null;
    await loadStatus();
    showBanner(`Imported ${r.messages} messages in ${r.threads} threads (${r.recent_messages} within the last ${r.days} days). <a href="#/">Open Inbox</a>`, 'ok');
    render();
  };
  document.getElementById('export-upload').onclick = async () => {
    const msg = document.getElementById('export-msg');
    const file = document.getElementById('export-file').files[0];
    if (!file) { msg.innerHTML = '<span class="err">Choose a file first</span>'; return; }
    msg.innerHTML = '<span class="spinner"></span>Parsing…';
    try {
      const res = await fetch('/api/import/export', { method: 'POST', body: file, headers: { 'Content-Type': 'application/octet-stream', 'X-Owner-Name': encodeURIComponent(document.getElementById('export-owner').value.trim()) } });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.detail || res.statusText);
      await afterImport(body, msg);
    } catch (err) { msg.innerHTML = `<span class="err">${esc(err.message)}</span>`; }
  };
  document.getElementById('paste-import').onclick = async () => {
    const msg = document.getElementById('paste-msg');
    const text = document.getElementById('paste-text').value;
    if (!text.trim()) { msg.innerHTML = '<span class="err">Paste some messages first</span>'; return; }
    msg.innerHTML = '<span class="spinner"></span>Importing…';
    try {
      const r = await api('/api/import/text', { method: 'POST', body: JSON.stringify({ text }) });
      await afterImport(r, msg);
    } catch (err) { msg.innerHTML = `<span class="err">${esc(err.message)}</span>`; }
  };
  document.getElementById('import-clear').onclick = async () => {
    state.settings = await api('/api/import', { method: 'DELETE' });
    state.threads = []; state.selected = new Set(); state.summary = null;
    await loadStatus();
    render();
  };
}

async function saveSettings(update) {
  state.settings = await api('/api/settings', { method: 'PUT', body: JSON.stringify(update) });
  await loadStatus();
  if (state.status.llm_configured) hideBanner();
  render();
}

// ---------- router ----------
function render() {
  const { path, params } = route();
  document.querySelectorAll('[data-nav]').forEach((a) => a.classList.toggle('active', a.dataset.nav === (path === '/' ? 'inbox' : path.slice(1))));
  if (path === '/settings') renderSettings(params);
  else if (path === '/summary') renderSummary();
  else renderInbox(params);
}

window.addEventListener('hashchange', async () => {
  const { path } = route();
  if (path === '/settings') state.settings = null;
  if (path === '/' && state.threads.length === 0 && !state.loadingThreads) {
    await loadStatus();
    if (state.status.demo_mode || state.status.import_mode || state.status.instagram_configured) { await loadThreads(); return; }
  }
  render();
});

(async function init() {
  await loadStatus();
  if (!state.status.llm_configured) {
    showBanner('Welcome! Add your LLM endpoint and API key in <a href="#/settings">Settings</a> to enable summarising.');
    if (route().path !== '/settings') navigate('#/settings');
  }
  if (route().path === '/' || route().path === '/summary') {
    const canLoad = state.status.demo_mode || state.status.import_mode || state.status.instagram_configured;
    if (canLoad) await loadThreads();
  }
  render();
})();
