/**
 * Storeglance Agent Chatbot Widget — Embeddable Chat Bubble
 * ═══════════════════════════════════════════════════════
 * Drop-in chatbot widget for any website.
 *
 * Usage (anonymous — no memory):
 *   <script src="http://your-api.com/bot/widget.js" data-token="ag_bot_xxxxx"></script>
 *
 * Usage (logged-in — memory enabled per user):
 *   <script src="http://your-api.com/bot/widget.js"
 *           data-token="ag_bot_xxxxx"
 *           data-user-id="user_42"></script>
 *
 * Features:
 *   - Floating chat bubble (bottom-right)
 *   - Premium glassmorphism chat panel
 *   - SSE streaming with markdown support
 *   - Session persistence via localStorage
 *   - Auto-sends current page URL with every message
 *   - Loads bot config (name, welcome, theme) from API
 *   - Memory isolation: anonymous=no memory, logged-in=user-scoped memory
 */
(function () {
  'use strict';

  // ── Config ────────────────────────────────────────────────────────
  const script = document.currentScript || document.querySelector('script[src*="/bot/widget.js"]');
  const BOT_TOKEN = script?.getAttribute('data-token') || '';
  let API_BASE = script?.getAttribute('data-api') || script?.src?.replace(/\/bot\/widget\.js.*$/, '') || '';
  if (API_BASE && !API_BASE.endsWith('/api')) {
    API_BASE += '/api';
  }
  const SESSION_KEY = 'ag_bot_session_' + BOT_TOKEN.slice(-8);

  // Memory isolation: data-user-id is set by the host site AFTER user login.
  // If absent (anonymous), the bot runs without memory.
  // If present (logged-in), bot memory is scoped to this user ID.
  const USER_ID = script?.getAttribute('data-user-id') || null;

  // Tenant routing: the bot's owning tenant is baked into the widget's OWN src URL
  // at embed time — e.g. <script src=".../bot/widget.js?tenant=acme.storeglanceai.com">.
  // The widget reads it from its script src (so it's provided once, at download, and
  // persists for the widget's lifetime) and sends it as X-Tenant-Domain on every call.
  // The widget runs cross-site (Host = api host), so without this the agent-api would
  // resolve the default tenant and look the bot up in the wrong DB. ?tenant= is
  // primary; data-tenant is an accepted fallback. Absent → default (single-tenant).
  const TENANT_DOMAIN = (function () {
    try {
      const fromSrc = new URL(script.src, location.href).searchParams.get('tenant');
      if (fromSrc) return fromSrc;
    } catch (e) { /* ignore */ }
    return script?.getAttribute('data-tenant') || '';
  })();
  function withTenant(h) {
    if (TENANT_DOMAIN) h['X-Tenant-Domain'] = TENANT_DOMAIN;
    return h;
  }

  if (!BOT_TOKEN) {
    console.error('[Storeglance Bot] Missing data-token attribute');
    return;
  }

  // ── Session Management ────────────────────────────────────────────
  function getSessionId() {
    let sid = localStorage.getItem(SESSION_KEY);
    if (!sid) {
      sid = 'sess_' + Math.random().toString(36).substr(2, 12) + Date.now().toString(36);
      localStorage.setItem(SESSION_KEY, sid);
    }
    return sid;
  }

  // ── Simple Markdown Renderer ──────────────────────────────────────
  // XSS-safe, line-based markdown renderer. Escapes first, then emits only a
  // known set of tags; lists are grouped into real <ul>/<ol>, links are limited
  // to http(s)/mailto and get rel="noopener noreferrer".
  function _mdInline(s) {
    return s
      .replace(/`([^`]+)`/g, '<code style="background:rgba(139,92,246,0.2);padding:2px 6px;border-radius:4px;font-size:13px">$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\*([^*]+)\*/g, '<em>$1</em>')
      .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (m, t, u) {
        return (/^(https?:|mailto:)/i.test(u) && u.indexOf('"') < 0)
          ? '<a href="' + u + '" target="_blank" rel="noopener noreferrer" style="color:#8b5cf6;text-decoration:underline">' + t + '</a>' : m;
      });
  }
  function renderMarkdown(text) {
    if (!text) return '';
    var lines = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').split('\n');
    var out = [], i = 0;
    while (i < lines.length) {
      var line = lines[i];
      if (/^```/.test(line)) {
        var buf = []; i++;
        while (i < lines.length && !/^```\s*$/.test(lines[i])) { buf.push(lines[i]); i++; }
        i++; out.push('<pre style="background:#1e1e2e;border-radius:8px;padding:12px;overflow-x:auto;font-size:13px;margin:8px 0"><code>' + buf.join('\n') + '</code></pre>'); continue;
      }
      var h = line.match(/^(#{1,3})\s+(.+)$/);
      if (h) { var lv = h[1].length + 1, fs = lv === 2 ? 16 : (lv === 3 ? 15 : 14); out.push('<h' + lv + ' style="margin:12px 0 4px;font-size:' + fs + 'px;font-weight:700">' + _mdInline(h[2]) + '</h' + lv + '>'); i++; continue; }
      if (/^&gt;\s?/.test(line)) {
        var q = []; while (i < lines.length && /^&gt;\s?/.test(lines[i])) { q.push(_mdInline(lines[i].replace(/^&gt;\s?/, ''))); i++; }
        out.push('<blockquote style="margin:6px 0;padding:2px 10px;border-left:3px solid rgba(139,92,246,0.4);opacity:0.85">' + q.join('<br>') + '</blockquote>'); continue;
      }
      if (/^\s*[-*]\s+/.test(line)) {
        var ul = []; while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) { ul.push('<li style="margin:2px 0">' + _mdInline(lines[i].replace(/^\s*[-*]\s+/, '')) + '</li>'); i++; }
        out.push('<ul style="margin:4px 0;padding-left:20px">' + ul.join('') + '</ul>'); continue;
      }
      if (/^\s*\d+\.\s+/.test(line)) {
        var ol = []; while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) { ol.push('<li style="margin:2px 0">' + _mdInline(lines[i].replace(/^\s*\d+\.\s+/, '')) + '</li>'); i++; }
        out.push('<ol style="margin:4px 0;padding-left:20px">' + ol.join('') + '</ol>'); continue;
      }
      if (/^\s*$/.test(line)) { i++; continue; }
      var p = [];
      while (i < lines.length && !/^\s*$/.test(lines[i]) && !/^```/.test(lines[i]) &&
             !/^(#{1,3})\s/.test(lines[i]) && !/^\s*[-*]\s+/.test(lines[i]) &&
             !/^\s*\d+\.\s+/.test(lines[i]) && !/^&gt;\s?/.test(lines[i])) {
        p.push(_mdInline(lines[i])); i++;
      }
      out.push('<p style="margin:0 0 8px">' + p.join('<br>') + '</p>');
    }
    return out.join('');
  }

  // ── Build UI ──────────────────────────────────────────────────────
  let isOpen = false;
  let botConfig = { name: 'Assistant', welcome_message: 'Hi! How can I help?', theme_color: '#6D28D9' };
  let messages = [];

  // Inject styles
  const style = document.createElement('style');
  style.textContent = `
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    #ag-bot-container * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', -apple-system, sans-serif; }

    #ag-bot-bubble {
      position: fixed; bottom: 24px; right: 24px; z-index: 99999;
      width: 60px; height: 60px; border-radius: 50%;
      background: linear-gradient(135deg, var(--ag-theme, #6D28D9), #4c1d95);
      box-shadow: 0 8px 32px rgba(109, 40, 217, 0.4), 0 0 0 0 rgba(109, 40, 217, 0.3);
      cursor: pointer; display: flex; align-items: center; justify-content: center;
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      animation: ag-pulse 2s infinite;
    }
    #ag-bot-bubble:hover { transform: scale(1.1); box-shadow: 0 12px 40px rgba(109, 40, 217, 0.5); }
    #ag-bot-bubble svg { width: 28px; height: 28px; fill: white; }
    @keyframes ag-pulse {
      0%, 100% { box-shadow: 0 8px 32px rgba(109, 40, 217, 0.4), 0 0 0 0 rgba(109, 40, 217, 0.3); }
      50% { box-shadow: 0 8px 32px rgba(109, 40, 217, 0.4), 0 0 0 12px rgba(109, 40, 217, 0); }
    }

    #ag-bot-panel {
      position: fixed; bottom: 96px; right: 24px; z-index: 99999;
      width: 400px; max-width: calc(100vw - 32px); height: 560px; max-height: calc(100vh - 120px);
      border-radius: 20px; overflow: hidden;
      background: linear-gradient(145deg, rgba(15,15,25,0.96), rgba(20,10,40,0.98));
      backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
      border: 1px solid rgba(139, 92, 246, 0.2);
      box-shadow: 0 25px 60px rgba(0,0,0,0.5), 0 0 1px rgba(139,92,246,0.3);
      display: flex; flex-direction: column;
      transform: translateY(20px) scale(0.95); opacity: 0; pointer-events: none;
      transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
    }
    #ag-bot-panel.open { transform: translateY(0) scale(1); opacity: 1; pointer-events: all; }

    .ag-header {
      padding: 16px 20px; display: flex; align-items: center; gap: 12px;
      background: linear-gradient(135deg, rgba(109,40,217,0.15), rgba(76,29,149,0.1));
      border-bottom: 1px solid rgba(139,92,246,0.15);
    }
    .ag-header-avatar {
      width: 36px; height: 36px; border-radius: 50%;
      background: linear-gradient(135deg, var(--ag-theme, #6D28D9), #4c1d95);
      display: flex; align-items: center; justify-content: center;
      font-size: 16px; color: white; font-weight: 700; flex-shrink: 0;
    }
    .ag-header-info { flex: 1; }
    .ag-header-name { color: #f1f5f9; font-size: 15px; font-weight: 600; }
    .ag-header-status { color: #22c55e; font-size: 11px; font-weight: 500; display: inline-flex; align-items: center; gap: 5px; }
    .ag-header-status::before {
      content: ''; width: 6px; height: 6px; border-radius: 50%; background: #22c55e;
      box-shadow: 0 0 0 0 rgba(34,197,94,0.5); animation: ag-status-pulse 2s infinite;
    }
    @keyframes ag-status-pulse {
      0%, 100% { box-shadow: 0 0 0 0 rgba(34,197,94,0.5); }
      50% { box-shadow: 0 0 0 4px rgba(34,197,94,0); }
    }
    .ag-header-close {
      width: 32px; height: 32px; border-radius: 8px; border: none;
      background: rgba(255,255,255,0.05); color: #94a3b8; cursor: pointer;
      display: flex; align-items: center; justify-content: center; font-size: 18px;
      transition: all 0.2s;
    }
    .ag-header-close:hover { background: rgba(255,255,255,0.1); color: #f1f5f9; }

    .ag-messages {
      flex: 1; overflow-y: auto; padding: 16px 16px 8px;
      scroll-behavior: smooth;
    }
    .ag-messages::-webkit-scrollbar { width: 4px; }
    .ag-messages::-webkit-scrollbar-track { background: transparent; }
    .ag-messages::-webkit-scrollbar-thumb { background: rgba(139,92,246,0.3); border-radius: 4px; }

    .ag-msg {
      margin-bottom: 12px; display: flex;
      animation: ag-fadeIn 0.4s cubic-bezier(0.22, 1, 0.36, 1) both;
    }
    .ag-msg.user { justify-content: flex-end; }
    .ag-msg-bubble {
      max-width: 85%; padding: 10px 14px; border-radius: 16px;
      font-size: 14px; line-height: 1.6; word-wrap: break-word;
      box-shadow: 0 2px 10px rgba(0,0,0,0.18);
    }
    .ag-msg.assistant .ag-msg-bubble {
      background: rgba(30, 30, 50, 0.8);
      border: 1px solid rgba(139, 92, 246, 0.1);
      color: #e2e8f0; border-bottom-left-radius: 4px;
    }
    .ag-msg.user .ag-msg-bubble {
      background: linear-gradient(135deg, var(--ag-theme, #6D28D9), #5b21b6);
      color: white; border-bottom-right-radius: 4px;
      box-shadow: 0 4px 16px rgba(109,40,217,0.32);
    }
    @keyframes ag-fadeIn {
      from { opacity: 0; transform: translateY(10px) scale(0.98); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }

    .ag-thinking {
      display: flex; gap: 4px; padding: 4px 0;
    }
    .ag-thinking span {
      width: 6px; height: 6px; border-radius: 50%;
      background: #8b5cf6; opacity: 0.4;
      animation: ag-think 1.4s infinite;
    }
    .ag-thinking span:nth-child(2) { animation-delay: 0.2s; }
    .ag-thinking span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes ag-think {
      0%, 80%, 100% { opacity: 0.4; transform: scale(1); }
      40% { opacity: 1; transform: scale(1.3); }
    }

    .ag-input-area {
      padding: 12px 16px; border-top: 1px solid rgba(139,92,246,0.1);
      background: rgba(10,10,20,0.5);
    }
    .ag-input-row { display: flex; gap: 8px; align-items: flex-end; }
    .ag-input {
      flex: 1; padding: 10px 14px; border-radius: 12px;
      background: rgba(30,30,50,0.8); border: 1px solid rgba(139,92,246,0.15);
      color: #f1f5f9; font-size: 14px; outline: none; resize: none;
      min-height: 40px; max-height: 100px; font-family: inherit;
      transition: border-color 0.2s;
    }
    .ag-input:focus { border-color: rgba(139,92,246,0.6); box-shadow: 0 0 0 3px rgba(139,92,246,0.18); }
    .ag-input::placeholder { color: #64748b; }
    .ag-send {
      width: 40px; height: 40px; border-radius: 12px; border: none;
      background: linear-gradient(135deg, var(--ag-theme, #6D28D9), #5b21b6);
      color: white; cursor: pointer; display: flex; align-items: center; justify-content: center;
      transition: all 0.2s cubic-bezier(0.4,0,0.2,1); flex-shrink: 0;
      box-shadow: 0 4px 14px rgba(109,40,217,0.35);
    }
    .ag-send:hover { transform: translateY(-2px) scale(1.05); box-shadow: 0 6px 20px rgba(109,40,217,0.5); }
    .ag-send:active { transform: scale(0.95); }
    .ag-send:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
    .ag-send svg { width: 18px; height: 18px; fill: white; }

    .ag-powered {
      text-align: center; padding: 6px; font-size: 10px; color: #475569;
      background: rgba(10,10,20,0.3);
    }
    .ag-powered a { color: #8b5cf6; text-decoration: none; }

    @media (max-width: 480px) {
      #ag-bot-panel { width: calc(100vw - 16px); right: 8px; bottom: 88px; height: calc(100vh - 100px); border-radius: 16px; }
      #ag-bot-bubble { bottom: 16px; right: 16px; }
    }
  `;
  document.head.appendChild(style);

  // Create container
  const container = document.createElement('div');
  container.id = 'ag-bot-container';
  document.body.appendChild(container);

  // Create bubble
  const bubble = document.createElement('div');
  bubble.id = 'ag-bot-bubble';
  bubble.innerHTML = '<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/></svg>';
  container.appendChild(bubble);

  // Create panel
  const panel = document.createElement('div');
  panel.id = 'ag-bot-panel';
  panel.innerHTML = `
    <div class="ag-header">
      <div class="ag-header-avatar">A</div>
      <div class="ag-header-info">
        <div class="ag-header-name" id="ag-bot-name">Assistant</div>
        <div class="ag-header-status">Online</div>
      </div>
      <button class="ag-header-close" id="ag-close">✕</button>
    </div>
    <div class="ag-messages" id="ag-messages"></div>
    <div class="ag-input-area">
      <div class="ag-input-row">
        <textarea class="ag-input" id="ag-input" placeholder="Type a message..." rows="1"></textarea>
        <button class="ag-send" id="ag-send">
          <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
        </button>
      </div>
    </div>
    <div class="ag-powered">Powered by <a href="https://storeglance.com" target="_blank" rel="noopener">Storeglance</a></div>
  `;
  container.appendChild(panel);

  // ── References ────────────────────────────────────────────────────
  const messagesEl = document.getElementById('ag-messages');
  const inputEl = document.getElementById('ag-input');
  const sendBtn = document.getElementById('ag-send');
  const closeBtn = document.getElementById('ag-close');
  const nameEl = document.getElementById('ag-bot-name');

  // ── Toggle ────────────────────────────────────────────────────────
  bubble.addEventListener('click', () => {
    isOpen = !isOpen;
    panel.classList.toggle('open', isOpen);
    if (isOpen && messages.length === 0) {
      addMessage('assistant', botConfig.welcome_message);
      inputEl.focus();
    }
  });
  closeBtn.addEventListener('click', () => {
    isOpen = false;
    panel.classList.remove('open');
  });

  // ── Auto-resize textarea ──────────────────────────────────────────
  inputEl.addEventListener('input', () => {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 100) + 'px';
  });

  // ── Send Message ──────────────────────────────────────────────────
  let isSending = false;

  function sendMessage() {
    const text = inputEl.value.trim();
    if (!text || isSending) return;

    isSending = true;
    sendBtn.disabled = true;
    inputEl.value = '';
    inputEl.style.height = 'auto';

    addMessage('user', text);
    addThinking();

    // Build request body — userId only included when user is logged in
    const chatBody = {
      message: text,
      sessionId: getSessionId(),
      pageUrl: window.location.href,
    };
    // Only send userId if the host site set data-user-id (logged-in user)
    // Anonymous visitors get NO memory capture
    if (USER_ID) chatBody.userId = USER_ID;

    // SSE streaming call
    fetch(API_BASE + '/v1/bot/chat', {
      method: 'POST',
      headers: withTenant({
        'Content-Type': 'application/json',
        'X-Bot-Token': BOT_TOKEN,
      }),
      body: JSON.stringify(chatBody),
    })
    .then(response => {
      if (!response.ok) throw new Error('Chat request failed');
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let assistantText = '';
      let assistantBubble = null;
      let pendingSources = [];

      function processStream() {
        reader.read().then(({ done, value }) => {
          if (done) {
            isSending = false;
            sendBtn.disabled = false;
            inputEl.focus();
            return;
          }

          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split('\n');

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const dataStr = line.slice(6).trim();
            if (dataStr === '[DONE]') continue;

            try {
              const data = JSON.parse(dataStr);

              if (data.event === 'message.delta' && data.content) {
                if (!assistantBubble) {
                  removeThinking();
                  assistantBubble = addMessage('assistant', '');
                }
                assistantText += data.content;
                assistantBubble.innerHTML = renderMarkdown(assistantText);
                scrollToBottom();
              }

              if (data.event === 'activity') {
                // Ephemeral pre-tool status (Layer 0) — show under the dots,
                // keep it short and friendly (no raw model narration).
                setThinkingLabel('Working…');
              }
              if (data.event === 'tool.start') {
                // Friendly "working on it" indicator (no raw tool internals).
                setThinkingLabel('Searching…');
              }
              if (data.event === 'tool.end') {
                setThinkingLabel('');
              }

              if (data.event === 'citations' && Array.isArray(data.sources)) {
                // Accumulate sources to render as trust chips after the answer.
                data.sources.forEach(function (s) {
                  if (s && s.title) pendingSources.push(s);
                });
              }

              if (data.event === 'message.end') {
                if (!assistantBubble) {
                  removeThinking();
                  assistantBubble = addMessage('assistant', '');
                }
                assistantText = data.content || assistantText;
                assistantBubble.innerHTML = renderMarkdown(assistantText);
                if (pendingSources.length) {
                  renderCitations(assistantBubble, pendingSources);
                  pendingSources = [];
                }
                messages.push({ role: 'assistant', content: assistantText });
                scrollToBottom();
              }

              if (data.event === 'approval.request' && data.approvalId) {
                // The bot wants to run an irreversible action — ask the visitor.
                removeThinking();
                renderApprovalPrompt(data.approvalId, data.toolName, data.toolArgs);
              }

              if (data.event === 'error') {
                removeThinking();
                addMessage('assistant', data.message || 'An error occurred.');
              }
            } catch (e) { /* ignore parse errors for incomplete chunks */ }
          }

          processStream();
        });
      }

      processStream();
    })
    .catch(err => {
      console.error('[Storeglance Bot]', err);
      removeThinking();
      addMessage('assistant', 'Sorry, I couldn\'t connect to the server. Please try again.');
      isSending = false;
      sendBtn.disabled = false;
    });
  }

  sendBtn.addEventListener('click', sendMessage);
  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // ── UI Helpers ────────────────────────────────────────────────────
  function addMessage(role, text) {
    const msgDiv = document.createElement('div');
    msgDiv.className = 'ag-msg ' + role;
    const bubbleDiv = document.createElement('div');
    bubbleDiv.className = 'ag-msg-bubble';
    bubbleDiv.innerHTML = renderMarkdown(text);
    msgDiv.appendChild(bubbleDiv);
    messagesEl.appendChild(msgDiv);
    scrollToBottom();

    if (role === 'user') {
      messages.push({ role, content: text });
    }
    return bubbleDiv;
  }

  function addThinking() {
    const div = document.createElement('div');
    div.className = 'ag-msg assistant';
    div.id = 'ag-thinking';
    div.innerHTML = '<div class="ag-msg-bubble"><div class="ag-thinking"><span></span><span></span><span></span></div></div>';
    messagesEl.appendChild(div);
    scrollToBottom();
  }

  function removeThinking() {
    const el = document.getElementById('ag-thinking');
    if (el) el.remove();
  }

  // Friendly status under the typing dots while a tool runs ("Searching…").
  function setThinkingLabel(label) {
    const el = document.getElementById('ag-thinking');
    if (!el) return;
    let lbl = el.querySelector('.ag-thinking-label');
    if (label) {
      if (!lbl) {
        lbl = document.createElement('span');
        lbl.className = 'ag-thinking-label';
        lbl.style.cssText = 'font-size:12px;opacity:0.6;margin-left:8px;';
        const bubble = el.querySelector('.ag-thinking');
        if (bubble && bubble.parentNode) bubble.parentNode.appendChild(lbl);
      }
      lbl.textContent = label;
    } else if (lbl) {
      lbl.remove();
    }
  }

  // Trust chips: which knowledge sources backed the answer.
  function renderCitations(bubbleEl, sources) {
    if (!bubbleEl || !sources || !sources.length) return;
    const wrap = document.createElement('div');
    wrap.style.cssText = 'display:flex;flex-wrap:wrap;gap:5px;margin-top:8px;padding-top:6px;border-top:1px solid rgba(127,127,127,0.18);';
    const lbl = document.createElement('span');
    lbl.textContent = 'Sources';
    lbl.style.cssText = 'font-size:10px;font-weight:600;text-transform:uppercase;opacity:0.5;';
    wrap.appendChild(lbl);
    sources.slice(0, 5).forEach(function (s) {
      const chip = document.createElement('span');
      chip.textContent = s.title;
      chip.title = s.snippet || s.sourcePath || s.title;
      chip.style.cssText = 'font-size:11px;padding:2px 8px;border-radius:999px;background:rgba(127,127,127,0.12);border:1px solid rgba(127,127,127,0.2);max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
      wrap.appendChild(chip);
    });
    bubbleEl.appendChild(wrap);
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  // ── Human-in-the-loop approval prompt ─────────────────────────────
  function renderApprovalPrompt(approvalId, toolName, toolArgs) {
    const wrap = document.createElement('div');
    wrap.className = 'ag-msg assistant';
    wrap.id = 'ag-approval-' + approvalId;

    const argsText = toolArgs ? JSON.stringify(toolArgs) : '';
    const bubble = document.createElement('div');
    bubble.className = 'ag-msg-bubble';
    bubble.style.border = '1px solid #f0b429';
    bubble.style.background = 'rgba(240,180,41,0.10)';
    bubble.innerHTML =
      '<div style="font-weight:600;margin-bottom:4px;">⚠️ Approval required</div>' +
      '<div style="font-size:0.9em;">The assistant wants to run <code>' +
      escapeHtml(toolName || 'an action') + '</code>.' +
      (argsText ? '<pre style="white-space:pre-wrap;font-size:0.78em;background:rgba(0,0,0,0.05);' +
        'padding:6px;border-radius:6px;margin:6px 0 0;max-height:120px;overflow:auto;">' +
        escapeHtml(argsText.slice(0, 300)) + '</pre>' : '') +
      '</div>';

    const actions = document.createElement('div');
    actions.style.cssText = 'display:flex;gap:8px;margin-top:10px;';
    const approveBtn = document.createElement('button');
    approveBtn.textContent = 'Approve';
    approveBtn.style.cssText = 'flex:0 0 auto;border:none;border-radius:6px;padding:6px 14px;' +
      'background:#1a7f37;color:#fff;font-weight:600;cursor:pointer;';
    const denyBtn = document.createElement('button');
    denyBtn.textContent = 'Deny';
    denyBtn.style.cssText = 'flex:0 0 auto;border:none;border-radius:6px;padding:6px 14px;' +
      'background:#cf222e;color:#fff;font-weight:600;cursor:pointer;';

    approveBtn.onclick = function () { resolveApproval(approvalId, true, wrap); };
    denyBtn.onclick = function () { resolveApproval(approvalId, false, wrap); };

    actions.appendChild(approveBtn);
    actions.appendChild(denyBtn);
    bubble.appendChild(actions);
    wrap.appendChild(bubble);
    messagesEl.appendChild(wrap);
    scrollToBottom();
  }

  function resolveApproval(approvalId, approved, wrapEl) {
    // Disable the buttons immediately to prevent double-clicks
    if (wrapEl) {
      wrapEl.querySelectorAll('button').forEach(function (b) { b.disabled = true; });
    }
    fetch(API_BASE + '/v1/bot/approvals/' + encodeURIComponent(approvalId), {
      method: 'POST',
      headers: withTenant({ 'Content-Type': 'application/json', 'X-Bot-Token': BOT_TOKEN }),
      body: JSON.stringify({ approved: approved }),
    })
    .then(function () {
      if (wrapEl) {
        const note = approved ? '✅ Approved' : '⛔ Denied';
        wrapEl.querySelector('.ag-msg-bubble').innerHTML =
          '<div style="font-size:0.9em;color:#555;">' + note + '</div>';
      }
      // The agent resumes after the decision; show the thinking indicator again.
      if (approved) addThinking();
    })
    .catch(function (err) { console.error('[Storeglance Bot] approval failed', err); });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // ── Load Bot Config ───────────────────────────────────────────────
  fetch(API_BASE + '/v1/bot/config', {
    headers: withTenant({ 'X-Bot-Token': BOT_TOKEN }),
  })
  .then(r => r.json())
  .then(config => {
    botConfig = config;
    nameEl.textContent = config.name || 'Assistant';
    if (config.theme_color) {
      document.documentElement.style.setProperty('--ag-theme', config.theme_color);
    }
    // Avatar: prefer the tenant logo (absolute master TenantLogo URL the config
    // now carries), fall back to the bot-name initial. Same branding source as the
    // web app + Teams package, so the widget shows the tenant logo, not just "A".
    const avatar = container.querySelector('.ag-header-avatar');
    if (avatar) {
      if (config.logo_url) {
        avatar.textContent = '';
        avatar.style.background = '#fff';
        const img = document.createElement('img');
        img.src = config.logo_url;
        img.alt = config.org_name || config.name || 'Logo';
        img.style.cssText = 'width:100%;height:100%;border-radius:50%;object-fit:cover;';
        img.onerror = () => {
          avatar.removeChild(img);
          avatar.style.background = '';
          if (config.name) avatar.textContent = config.name[0].toUpperCase();
        };
        avatar.appendChild(img);
      } else if (config.name) {
        avatar.textContent = config.name[0].toUpperCase();
      }
    }
  })
  .catch(err => console.warn('[Storeglance Bot] Could not load config:', err));

  // ── Load Existing History ─────────────────────────────────────────
  fetch(API_BASE + '/v1/bot/history/' + getSessionId(), {
    headers: withTenant({ 'X-Bot-Token': BOT_TOKEN }),
  })
  .then(r => r.ok ? r.json() : null)
  .then(data => {
    if (data && data.messages && data.messages.length > 0) {
      messages = data.messages;
      // Render existing messages
      for (const msg of data.messages) {
        addMessage(msg.role, msg.content);
      }
    }
  })
  .catch(() => { /* No history, that's fine */ });

})();
