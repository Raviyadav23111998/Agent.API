/**
 * Agent Embed — unified embeddable runtime (chat + copilot).
 * ════════════════════════════════════════════════════════════════════════
 * One line on any site:
 *   <script src="https://YOUR-API/v1/embed/embed.js" data-key="ag_pk_xxx"></script>
 *
 * • Shadow-DOM UI (isolated from the host page CSS/JS; the host snapshot can't
 *   see the widget because Shadow DOM hides it from document.querySelectorAll).
 * • Connects to /v1/embed/ws, handshakes with the publishable key + origin.
 * • mode='chat'  → answer-only.
 * • mode='copilot' → also drives the host page (page_* tool_requests execute
 *   here, on the host DOM, and return results).
 * • window.AgentEmbed.identify({userId, hmac}) for verified end-users.
 */
(function () {
  "use strict";
  var script = document.currentScript ||
    (function () { var s = document.querySelectorAll('script[data-key]'); return s[s.length - 1]; })();
  if (!script) return;
  var KEY = script.getAttribute('data-key') || '';
  if (!KEY) { console.error('[AgentEmbed] missing data-key'); return; }
  // API base: explicit data-api, else derived from the script's own URL by
  // stripping the /bot/embed.js suffix.  Works for BOTH layouts:
  //   tenant-direct: host/bot/embed.js   → host          (+ /api → host/api)
  //   central GW:    host/api/agent/bot/embed.js → host/api/agent
  var API = (function () {
    if (script.getAttribute('data-api')) return script.getAttribute('data-api');
    try {
      var u = new URL(script.src);
      var p = u.pathname.replace(/\/bot\/embed\.js.*$/, '');
      // If stripping left us with nothing (tenant-direct: /bot/embed.js → ''),
      // fall back to origin + '/api' (nginx proxies /api → backend).
      return u.origin + (p || '/api');
    } catch (e) { return location.origin + '/api'; }
  })().replace(/\/$/, '');

  // Tenant routing: when embedded cross-site (host ≠ tenant), the Origin header
  // is the HOST site's domain (e.g. shop.example.com), NOT the agent tenant's
  // domain.  ?tenant= in the script src (or data-tenant attr) tells the API
  // which tenant DB to use.  Widget.js sends X-Tenant-Domain on HTTP calls; for
  // WebSocket (no custom headers from JS) we append ?tenantDomain= to the URL,
  // which TenantResolutionMiddleware reads first.
  var TENANT_DOMAIN = (function () {
    try {
      var fromSrc = new URL(script.src, location.href).searchParams.get('tenant');
      if (fromSrc) return fromSrc;
    } catch (e) { /* ignore */ }
    return script.getAttribute('data-tenant') || '';
  })();
  var WS_URL = API.replace(/^http/, 'ws') + '/v1/embed/ws'
             + (TENANT_DOMAIN ? '?tenantDomain=' + encodeURIComponent(TENANT_DOMAIN) : '');

  var state = { ws: null, ready: false, mode: 'chat', open: false, busy: false,
                identity: null, convId: null, current: null };

  // Stable per-browser session id (survives refresh) so the server reuses the
  // SAME conversation/agent on reconnect — fixes "everything is lost on refresh".
  function clientSession() {
    var k = 'ag_embed_sid_' + KEY.slice(0, 16);
    try {
      var v = localStorage.getItem(k);
      if (!v) { v = 's_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 9); localStorage.setItem(k, v); }
      return v;
    } catch (e) { return 's_' + Math.random().toString(36).slice(2, 9); }
  }

  // ── Shadow-DOM UI ───────────────────────────────────────────────────
  var hostEl = document.createElement('div');
  document.body.appendChild(hostEl);
  var root = hostEl.attachShadow({ mode: 'open' });
  root.innerHTML =
    '<style>' +
    ':host{all:initial}' +
    '.fab{position:fixed;right:22px;bottom:22px;width:54px;height:54px;border-radius:50%;border:none;cursor:pointer;background:linear-gradient(135deg,#6366f1,#8b5cf6);box-shadow:0 6px 20px rgba(99,102,241,.45);color:#fff;font-size:22px;z-index:2147483646;transition:transform .25s cubic-bezier(.4,0,.2,1),box-shadow .25s cubic-bezier(.4,0,.2,1)}' +
    '.fab:hover{transform:translateY(-2px) scale(1.08);box-shadow:0 10px 28px rgba(99,102,241,.55)}' +
    '.fab:active{transform:scale(.96)}' +
    '.panel{position:fixed;right:22px;bottom:84px;width:370px;max-width:92vw;height:560px;max-height:80vh;background:#fff;border-radius:16px;box-shadow:0 18px 50px rgba(0,0,0,.25);display:none;flex-direction:column;overflow:hidden;font-family:-apple-system,Segoe UI,Roboto,sans-serif;z-index:2147483646;transform:translateY(16px) scale(.97);opacity:0;transition:transform .32s cubic-bezier(.22,1,.36,1),opacity .32s ease}' +
    '.panel.open{display:flex;transform:translateY(0) scale(1);opacity:1}' +
    '.hd{padding:13px 16px;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;display:flex;align-items:center;justify-content:space-between}' +
    '.hd b{font-size:15px}.hd .x{cursor:pointer;opacity:.85;font-size:16px;transition:opacity .2s}.hd .x:hover{opacity:1}' +
    '.sub{font-size:11px;opacity:.9;display:inline-flex;align-items:center;gap:5px}' +
    '.sub::before{content:"";width:6px;height:6px;border-radius:50%;background:#4ade80;box-shadow:0 0 0 0 rgba(74,222,128,.6);animation:agdot 2s infinite}' +
    '@keyframes agdot{0%,100%{box-shadow:0 0 0 0 rgba(74,222,128,.6)}50%{box-shadow:0 0 0 4px rgba(74,222,128,0)}}' +
    '.msgs{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px;background:#f8fafc}' +
    '.m{max-width:85%;padding:9px 12px;border-radius:12px;font-size:14px;line-height:1.5;white-space:pre-wrap;word-break:break-word;box-shadow:0 1px 4px rgba(0,0,0,.06);animation:agmsgin .4s cubic-bezier(.22,1,.36,1) both}' +
    '@keyframes agmsgin{from{opacity:0;transform:translateY(8px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}' +
    '.m.u{align-self:flex-end;background:linear-gradient(135deg,#6366f1,#7c3aed);color:#fff;border-bottom-right-radius:4px;box-shadow:0 3px 12px rgba(99,102,241,.3)}' +
    '.m.a{align-self:flex-start;background:#fff;color:#0f172a;border:1px solid #e2e8f0;border-bottom-left-radius:4px}' +
    '.status{padding:3px 14px;font-size:12px;color:#64748b;font-style:italic}' +
    '.in{display:flex;gap:8px;padding:11px;border-top:1px solid #e2e8f0;background:#fff}' +
    '.in textarea{flex:1;resize:none;border:1px solid #e2e8f0;border-radius:10px;padding:9px 11px;font:inherit;font-size:14px;max-height:90px;outline:none;transition:border-color .2s,box-shadow .2s}' +
    '.in textarea:focus{border-color:#8b5cf6;box-shadow:0 0 0 3px rgba(139,92,246,.16)}' +
    '.in button{width:38px;border:none;border-radius:10px;background:linear-gradient(135deg,#6366f1,#7c3aed);color:#fff;font-size:15px;cursor:pointer;box-shadow:0 3px 10px rgba(99,102,241,.32);transition:transform .2s,box-shadow .2s}' +
    '.in button:hover{transform:translateY(-2px);box-shadow:0 6px 16px rgba(99,102,241,.45)}' +
    '.in button:active{transform:scale(.95)}' +
    '.approval{max-width:90%;padding:10px 14px;border-radius:12px;background:#fffbeb;border:1px solid #f59e0b;align-self:flex-start;font-size:13px;line-height:1.5}' +
    '.approval .atitle{font-weight:600;color:#92400e;margin-bottom:6px}' +
    '.approval .abtn{display:inline-block;padding:5px 14px;margin:4px 6px 0 0;border:none;border-radius:8px;font-size:13px;cursor:pointer}' +
    '.approval .abtn.yes{background:#22c55e;color:#fff}' +
    '.approval .abtn.no{background:#ef4444;color:#fff}' +
    '.m.a{white-space:normal}' +
    '.m.a p{margin:0 0 8px}.m.a p:last-child{margin-bottom:0}' +
    '.m.a h2,.m.a h3,.m.a h4{margin:10px 0 4px;font-weight:700;line-height:1.3}' +
    '.m.a h2{font-size:16px}.m.a h3{font-size:15px}.m.a h4{font-size:14px}' +
    '.m.a ul,.m.a ol{margin:4px 0;padding-left:20px}.m.a li{margin:2px 0}' +
    '.m.a a{color:#6366f1;text-decoration:underline}' +
    '.m.a blockquote{margin:6px 0;padding:2px 10px;border-left:3px solid #c7d2fe;color:#475569}' +
    '.ag-ic{background:rgba(99,102,241,.12);padding:1px 5px;border-radius:4px;font-family:ui-monospace,Menlo,monospace;font-size:12.5px}' +
    '.ag-code{background:#1e1e2e;color:#e2e8f0;border-radius:8px;padding:10px 12px;overflow-x:auto;margin:8px 0}' +
    '.ag-code code{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;white-space:pre}' +
    '.ag-typing{display:inline-flex;gap:4px;align-items:center;padding:4px 2px}' +
    '.ag-typing i{width:6px;height:6px;border-radius:50%;background:#94a3b8;display:inline-block;animation:agbounce 1.2s infinite}' +
    '.ag-typing i:nth-child(2){animation-delay:.2s}.ag-typing i:nth-child(3){animation-delay:.4s}' +
    '@keyframes agbounce{0%,60%,100%{transform:translateY(0);opacity:.5}30%{transform:translateY(-4px);opacity:1}}' +
    '</style>' +
    '<button class="fab" id="fab">✨</button>' +
    '<div class="panel" id="panel">' +
      '<div class="hd"><div><b id="ttl">Assistant</b><div class="sub" id="sub">online</div></div><span class="x" id="x">✕</span></div>' +
      '<div class="msgs" id="msgs"></div>' +
      '<div class="status" id="st"></div>' +
      '<div class="in"><textarea id="ta" rows="1" placeholder="Type a message…"></textarea><button id="send">➤</button></div>' +
    '</div>';

  var $ = function (id) { return root.getElementById(id); };
  $('fab').onclick = toggle; $('x').onclick = toggle;
  $('send').onclick = function () { sendText($('ta').value); };
  $('ta').addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendText($('ta').value); }
  });

  function toggle() {
    state.open = !state.open;
    $('panel').classList.toggle('open', state.open);
    if (state.open && !state.ws) connect();
  }
  // ── Minimal, XSS-safe markdown renderer (escape-first, line-based) ──────
  function _esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function _inline(s) {
    return s
      .replace(/`([^`]+)`/g, '<code class="ag-ic">$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\*([^*]+)\*/g, '<em>$1</em>')
      .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (m, t, u) {
        // Only http(s)/mailto links; url is already HTML-escaped. Reject quotes.
        return (/^(https?:|mailto:)/i.test(u) && u.indexOf('"') < 0)
          ? '<a href="' + u + '" target="_blank" rel="noopener noreferrer">' + t + '</a>' : m;
      });
  }
  function renderMarkdown(text) {
    if (!text) return '';
    var lines = _esc(text).split('\n'), out = [], i = 0;
    while (i < lines.length) {
      var line = lines[i];
      if (/^```/.test(line)) {                       // fenced code
        var buf = []; i++;
        while (i < lines.length && !/^```\s*$/.test(lines[i])) { buf.push(lines[i]); i++; }
        i++; out.push('<pre class="ag-code"><code>' + buf.join('\n') + '</code></pre>'); continue;
      }
      var h = line.match(/^(#{1,3})\s+(.+)$/);
      if (h) { var lv = h[1].length + 1; out.push('<h' + lv + '>' + _inline(h[2]) + '</h' + lv + '>'); i++; continue; }
      if (/^&gt;\s?/.test(line)) {                   // blockquote
        var q = []; while (i < lines.length && /^&gt;\s?/.test(lines[i])) { q.push(_inline(lines[i].replace(/^&gt;\s?/, ''))); i++; }
        out.push('<blockquote>' + q.join('<br>') + '</blockquote>'); continue;
      }
      if (/^\s*[-*]\s+/.test(line)) {                 // unordered list
        var ul = []; while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) { ul.push('<li>' + _inline(lines[i].replace(/^\s*[-*]\s+/, '')) + '</li>'); i++; }
        out.push('<ul>' + ul.join('') + '</ul>'); continue;
      }
      if (/^\s*\d+\.\s+/.test(line)) {                // ordered list
        var ol = []; while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) { ol.push('<li>' + _inline(lines[i].replace(/^\s*\d+\.\s+/, '')) + '</li>'); i++; }
        out.push('<ol>' + ol.join('') + '</ol>'); continue;
      }
      if (/^\s*$/.test(line)) { i++; continue; }      // blank
      var p = [];                                     // paragraph
      while (i < lines.length && !/^\s*$/.test(lines[i]) && !/^```/.test(lines[i]) &&
             !/^(#{1,3})\s/.test(lines[i]) && !/^\s*[-*]\s+/.test(lines[i]) &&
             !/^\s*\d+\.\s+/.test(lines[i]) && !/^&gt;\s?/.test(lines[i])) {
        p.push(_inline(lines[i])); i++;
      }
      out.push('<p>' + p.join('<br>') + '</p>');
    }
    return out.join('');
  }

  function addMsg(role, text) {
    var d = document.createElement('div'); d.className = 'm ' + (role === 'user' ? 'u' : 'a');
    // User text is shown verbatim (textContent = safe); assistant answers render
    // markdown (renderMarkdown escapes first, so it is XSS-safe).
    if (role === 'user') d.textContent = text; else d.innerHTML = renderMarkdown(text);
    $('msgs').appendChild(d); $('msgs').scrollTop = $('msgs').scrollHeight;
    return d;
  }
  function setStatus(s) { $('st').textContent = s || ''; }

  // Typing indicator shown in the status row while the assistant works.
  function showTyping() { $('st').innerHTML = '<span class="ag-typing"><i></i><i></i><i></i></span>'; }

  // ── WebSocket ───────────────────────────────────────────────────────
  function connect() {
    // Don't stack sockets: if one is already connecting/open, reuse it.
    if (state.ws && (state.ws.readyState === 0 || state.ws.readyState === 1)) return;
    state.ws = new WebSocket(WS_URL);
    state.ws.onopen = function () {
      var auth = { type: 'auth', key: KEY, origin: location.origin, sessionId: clientSession() };
      if (state.identity) auth.identity = state.identity;
      state.ws.send(JSON.stringify(auth));
      state.reconnectDelay = 1000;            // reset backoff after a clean open
      // Keepalive: reverse proxies reap idle WebSockets after ~30-60s. A light
      // app-level ping keeps the path warm so the socket survives BETWEEN
      // messages (server answers pong; the UI ignores both). Without this the
      // idle socket dropped and, with no reconnect, the next message hung.
      clearInterval(state.pingTimer);
      state.pingTimer = setInterval(function () {
        if (state.ws && state.ws.readyState === 1) state.ws.send(JSON.stringify({ type: 'ping' }));
      }, 15000);
    };
    state.ws.onmessage = onMessage;
    state.ws.onclose = function () {
      state.ready = false; state.ws = null;
      clearInterval(state.pingTimer);
      // Auto-reconnect with capped backoff so a transient drop or a server
      // restart self-heals. (The old behaviour left ws=null with no recovery,
      // so a dropped socket meant the widget went silent until a page reload.)
      state.reconnectDelay = Math.min((state.reconnectDelay || 1000) * 1.5, 15000);
      clearTimeout(state.reconnectTimer);
      state.reconnectTimer = setTimeout(connect, state.reconnectDelay);
    };
    state.ws.onerror = function () { setStatus('connection error'); };
  }

  function onMessage(ev) {
    var m; try { m = JSON.parse(ev.data); } catch (e) { return; }
    if (m.type === 'auth_ok') {
      state.ready = true; state.mode = m.mode || 'chat';
      state.egressRedact = m.egressRedact !== undefined ? m.egressRedact : (m.mode === 'copilot');
      return;
    }
    if (m.type === 'mode') {
      // Live chat↔copilot switch pushed by the server (admin changed the
      // integration's mode). Update behaviour without a reconnect.
      state.mode = m.mode || 'chat';
      state.egressRedact = m.egressRedact !== undefined ? m.egressRedact : (state.mode === 'copilot');
      setStatus(state.mode === 'copilot' ? 'Copilot mode' : 'Chat mode');
      return;
    }
    if (m.type === 'error') { setStatus(''); if (state.current) state.current.textContent = '⚠ ' + (m.message || 'error'); state.busy = false; return; }
    if (m.type === 'tool_request') { return execTool(m); }
    if (m.type !== 'event') return;
    switch (m.event) {
      case 'message.start':
        if (!state.current) { state.current = addMsg('a', ''); state.currentText = ''; }
        break;
      case 'message.delta':
        if (state.current) {
          state.currentText = (state.currentText || '') + (m.content || '');
          state.current.innerHTML = renderMarkdown(state.currentText);
          $('msgs').scrollTop = $('msgs').scrollHeight;
        }
        setStatus('');
        break;
      case 'activity': showTyping(); break;   // ephemeral pre-tool status (Layer 0)
      case 'tool.start': setStatus('Working on the page…'); break;
      case 'tool.end': setStatus(''); break;
      case 'message.end':
        if (state.current && m.content) {
          state.currentText = m.content;
          state.current.innerHTML = renderMarkdown(state.currentText);
        }
        break;
      case 'done': state.busy = false; state.current = null; state.currentText = ''; setStatus(''); break;
      case 'status': setStatus(m.state || ''); break;
      case 'approval.request': addApprovalCard(m.approvalId, m.action, m.target); break;
    }
  }

  function sendText(text) {
    text = (text || '').trim(); if (!text || state.busy) return;
    // (Re)connect if the socket is missing, closing, or closed.
    if (!state.ws || state.ws.readyState > 1) connect();
    var waited = 0;
    var trySend = function () {
      if (!state.ready || !state.ws || state.ws.readyState !== 1) {
        waited += 150;
        if (waited > 4000) setStatus('reconnecting…');  // tell the user instead of hanging silently
        if (!state.ws || state.ws.readyState > 1) connect();
        return setTimeout(trySend, 150);
      }
      addMsg('user', text); $('ta').value = ''; state.busy = true; state.current = null; state.currentText = ''; showTyping();
      state.ws.send(JSON.stringify({ type: 'chat', message: text, conversationId: state.convId, context: { nav: scanNavigation() } }));
    };
    trySend();
  }

  // ── HITL Approval Card (Phase 4) ─────────────────────────────────────────
  function addApprovalCard(approvalId, action, target) {
    var card = document.createElement('div'); card.className = 'approval';
    card.innerHTML =
      '<div class="atitle">⚠️ Confirmation Required</div>' +
      '<div>' + (target ? 'The assistant wants to <b>' + action + '</b> "' + target + '".' : 'The assistant wants to perform an action.') + '</div>' +
      '<button class="abtn yes" id="ap_y_' + approvalId + '">Allow</button>' +
      '<button class="abtn no" id="ap_n_' + approvalId + '">Deny</button>';
    $('msgs').appendChild(card); $('msgs').scrollTop = $('msgs').scrollHeight;
    // Wire buttons
    card.querySelector('.abtn.yes').onclick = function () {
      state.ws.send(JSON.stringify({ type: 'approval_response', approvalId: approvalId, approved: true }));
      card.innerHTML = '<div class="atitle">✅ Action approved</div>'; setStatus('Executing…');
    };
    card.querySelector('.abtn.no').onclick = function () {
      state.ws.send(JSON.stringify({ type: 'approval_response', approvalId: approvalId, approved: false }));
      card.innerHTML = '<div class="atitle">❌ Action denied</div>';
    };
  }

  // ── Page engine (copilot) — runs on the HOST document ────────────────
  // ONE addressing model: elements are targeted by their human LABEL
  // (page_observe lists them; page_act acts on them). No ids to track.
  function visible(el) {
    if (!el.isConnected) return false;
    var s = getComputedStyle(el); if (s.display === 'none' || s.visibility === 'hidden') return false;
    var r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0;
  }
  function labelOf(el, kind) {
    if (kind === 'button' || kind === 'link') return (el.textContent || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 80);
    var a = el.getAttribute('aria-label'); if (a) return a.slice(0, 80);
    var id = el.getAttribute('id'); if (id) { var l = document.querySelector('label[for="' + (window.CSS ? CSS.escape(id) : id) + '"]'); if (l) return l.textContent.trim().slice(0, 80); }
    var wl = el.closest('label'); if (wl) return wl.textContent.trim().slice(0, 80);
    return (el.getAttribute('placeholder') || el.getAttribute('name') || '').slice(0, 80);
  }
  function kindOf(el) {
    var t = el.tagName.toLowerCase();
    if (t === 'textarea') return 'textarea'; if (t === 'select') return 'select';
    if (t === 'a') return 'link'; if (t === 'button') return 'button';
    if (el.getAttribute('role') === 'button' || el.hasAttribute('tabindex')) return 'button';
    if (t === 'input') { var it = el.type; if (it === 'checkbox') return 'checkbox'; if (it === 'submit' || it === 'button') return 'button'; if (it === 'hidden') return null; return 'text'; }
    return null;
  }
  function settle(ms) { return new Promise(function (r) { setTimeout(r, ms || 250); }); }
  function setNative(el, v) {
    var proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    var setter = Object.getOwnPropertyDescriptor(proto, 'value').set; setter.call(el, v);
    el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  // ── Semantic model (page_observe / page_act) — target by LABEL, no ids ──
  function elementsFor(action) {
    var sel = action === 'click'
      ? 'button,a,[role=button],[role=menuitem],[role=tab],[role=link],input[type=submit],input[type=button],[tabindex]:not([tabindex="-1"])'
      : 'input:not([type=hidden]),textarea,select';
    return [].slice.call(document.querySelectorAll(sel)).filter(visible);
  }
  function findByLabel(target, action) {
    var t = (target || '').trim().toLowerCase(); if (!t) return null;
    var labeled = elementsFor(action).map(function (el) {
      return { el: el, label: (labelOf(el, action === 'click' ? 'button' : 'text') || '').toLowerCase() };
    }).filter(function (x) { return x.label; });
    var pick = labeled.filter(function (x) { return x.label === t; })[0]
            || labeled.filter(function (x) { return x.label.indexOf(t) === 0; })[0]
            || labeled.filter(function (x) { return x.label.indexOf(t) >= 0; })[0]
            || labeled.filter(function (x) { return t.indexOf(x.label) >= 0; })[0];
    return pick && pick.el;
  }
  // Static navigation map — visible sidebar/nav links + routes. Sent once per
  // message so the agent can page_navigate(route) directly instead of exploring.
  function scanNavigation() {
    var out = {}, res = [];
    var anchors = [].slice.call(document.querySelectorAll(
      'nav a[href], aside a[href], .sidebar a[href], [role=navigation] a[href]'));
    anchors.forEach(function (a) {
      if (!visible(a)) return;
      var label = (a.textContent || a.getAttribute('aria-label') || '')
        .replace(/\s+/g, ' ').trim().slice(0, 60);
      var route = '';
      try { route = new URL(a.href, location.origin).pathname; }
      catch (e) { route = a.getAttribute('href') || ''; }
      if (!label || route.charAt(0) !== '/') return;
      var k = label + '|' + route;
      if (!out[k]) { out[k] = 1; res.push({ label: label, route: route }); }
    });
    return res;
  }
  function observeText() {
    var lines = [], seen = new Set();
    elementsFor('input').forEach(function (el) {
      if (seen.has(el)) return; seen.add(el);
      var k = kindOf(el); if (!k) return; var lbl = labelOf(el, k); if (!lbl) return;
      var v = (k === 'select')
        ? ' options: ' + [].map.call(el.options, function (o) { return o.text.trim(); }).slice(0, 30).join(' | ')
        : (el.type === 'password' ? (el.value ? ' = ••••' : '')
          : (el.value ? ' = ' + JSON.stringify((state.egressRedact && (k === 'text' || k === 'textarea')) ? '•••' : el.value.slice(0, 40)) : ''));
      lines.push('  ' + k + ' "' + lbl + '"' + (el.required ? ' (required)' : '') + v);
    });
    var seenL = {};
    elementsFor('click').forEach(function (el) {
      if (seen.has(el)) return; var lbl = labelOf(el, 'button'); if (!lbl || seenL[lbl]) return;
      // Skip chart/SVG noise — labels containing CSS syntax are never real nav items.
      if (/[{}:;]/.test(lbl)) return;
      seenL[lbl] = 1;
      lines.push('  ' + (el.tagName.toLowerCase() === 'a' ? 'link' : 'button') + ' "' + lbl + '"');
    });
    return 'Page: ' + location.pathname + ' — "' + document.title + '"\n' +
           lines.length + ' elements:\n' + lines.join('\n');
  }
  async function pageAct(steps) {
    if (typeof steps === 'string') { try { steps = JSON.parse(steps); } catch (e) { return 'FAILED: `steps` must be a JSON array.'; } }
    if (!Array.isArray(steps)) return 'FAILED: `steps` must be an array of {do,target,value}.';
    var out = [];
    for (var i = 0; i < steps.length; i++) {
      var s = steps[i] || {}, doo = String(s.do || s.action || '').toLowerCase(), tgt = s.target || s.label || '', val = s.value;
      var action = (doo === 'click') ? 'click' : 'input';
      var el = findByLabel(tgt, action);
      if (!el) { out.push('✗ ' + doo + ' "' + tgt + '": not found'); break; }
      try {
        if (doo === 'fill') {
          // Never autonomously type credentials. The copilot must not enter a
          // password on the user's behalf — ask the user to type it themselves.
          if (el instanceof HTMLInputElement && (el.type === 'password' || /password|passcode/i.test(el.autocomplete || ''))) {
            out.push('✗ "' + tgt + '" is a password field — for security the copilot cannot type passwords. Ask the user to enter it.');
          }
          else if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) { setNative(el, val == null ? '' : String(val)); out.push('✓ filled "' + tgt + '"'); }
          else out.push('✗ "' + tgt + '" is not a text field');
        } else if (doo === 'select') {
          var o = [].slice.call(el.options || []).filter(function (x) { var xt = x.text.trim().toLowerCase(); return xt === String(val).toLowerCase() || xt.indexOf(String(val).toLowerCase()) >= 0; })[0];
          if (o) { el.value = o.value; el.dispatchEvent(new Event('change', { bubbles: true })); out.push('✓ selected "' + o.text.trim() + '"'); } else out.push('✗ no option "' + val + '"');
        } else if (doo === 'check') {
          el.checked = !(val === false || val === 'false'); el.dispatchEvent(new Event('change', { bubbles: true })); out.push('✓ ' + (el.checked ? 'checked' : 'unchecked') + ' "' + tgt + '"');
        } else if (doo === 'click') {
          el.scrollIntoView({ block: 'center' }); el.click(); await settle(450); out.push('✓ clicked "' + tgt + '"');
        } else out.push('✗ unknown action "' + doo + '"');
      } catch (e) { out.push('✗ ' + doo + ' "' + tgt + '": ' + (e && e.message || e)); break; }
    }
    return out.join('\n') + '\n\n' + observeText();
  }
  // ── Page tool handlers — one function per tool, no if/else ladder ─────
  function pageNavigate(a) {
    // SPA-SAFE navigation — NEVER full-reload (a reload kills this WS and
    // orphans the agent). Prefer clicking the host's own in-app link (its router
    // handles it); else pushState + popstate. Only different-origin routes do a
    // real navigation.
    var route = a.route || a.url || a.path || '';
    try {
      var dest = new URL(route, location.origin);
      if (dest.origin !== location.origin) { location.assign(dest.href); return Promise.resolve('OK navigating (external) ' + route); }
      var path = dest.pathname.replace(/\/+$/, '');
      var link = [].slice.call(document.querySelectorAll('a[href]')).filter(function (x) {
        try { var u = new URL(x.href, location.origin); return u.origin === location.origin && u.pathname.replace(/\/+$/, '') === path; } catch (e) { return false; }
      })[0];
      if (link) { link.click(); }
      else { history.pushState({}, '', dest.pathname + dest.search); window.dispatchEvent(new PopStateEvent('popstate')); }
      return settle(550).then(function () { return 'OK navigated to ' + location.pathname + '\n' + observeText(); });
    } catch (e) { return Promise.resolve('FAILED navigate: ' + (e && e.message || e)); }
  }

  // The dispatch table. Adding a page tool is ONE entry here — never a new
  // branch. Mirrors the server-side ToolRegistry's lookup dispatch.
  var PAGE_TOOLS = {
    page_observe: async function (a) { await settle(200); return observeText(); },
    page_act: function (a) { return pageAct(a.steps); },
    page_read: function (a) { var el0 = document.querySelector('main,[role=main]') || document.body; return 'Page text:\n' + (el0.innerText || '').trim().slice(0, 4000); },
    page_wait: async function (a) { await settle(400); return 'OK settled'; },
    page_navigate: function (a) { return pageNavigate(a); },
  };
  async function execTool(m) {
    var name = m.toolName, a = m.toolArgs || {};
    try {
      var handler = PAGE_TOOLS[name];
      var res = handler ? await handler(a) : 'FAILED: unknown page tool ' + name;
      state.ws.send(JSON.stringify({ type: 'tool_result', requestId: m.requestId, result: String(res) }));
    } catch (e) {
      state.ws.send(JSON.stringify({ type: 'tool_error', requestId: m.requestId, error: String(e && e.message || e) }));
    }
  }

  // ── Public API ──────────────────────────────────────────────────────
  window.AgentEmbed = {
    open: function () { if (!state.open) toggle(); },
    close: function () { if (state.open) toggle(); },
    sendMessage: function (t) { this.open(); sendText(t); },
    identify: function (i) { state.identity = i; },
  };
})();
