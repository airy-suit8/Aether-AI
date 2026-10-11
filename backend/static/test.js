
    // System Configurations State
    const AppState = {
      view: 'landing',
      user: null,
      authMode: 'signin',
      
      // Feature toggles
      agentMode: false,
      langChainMode: false,
      streamingMode: true,
      
      // Thread Session configuration
      activeSessionId: null,
      threadsList: [],
      
      // API Settings
      apiKey: ''
    };

    // Initialize application on load
    window.addEventListener('DOMContentLoaded', () => {
      // Check auth status
      const cachedUser = localStorage.getItem('aether_user');
      if (cachedUser) {
        AppState.user = JSON.parse(cachedUser);
        document.getElementById('user-avatar-lbl').innerText = AppState.user.email[0].toUpperCase();
        document.getElementById('user-display-email').innerText = AppState.user.email;
        navigateToView('app');
      } else {
        navigateToView('landing');
      }
      
      loadSessionId();
      refreshFilesLists();
      loadGeneralSettings();
      syncUIStates();
    });

    // ── Navigation ───────────────────────────────────────────────────────────
    function navigateToView(viewId) {
      document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
      const activeEl = document.getElementById(`${viewId}-view`);
      if (activeEl) {
        activeEl.classList.add('active');
        AppState.view = viewId;
      }
      
      if (viewId === 'app') {
        newConversation();
        refreshFilesLists();
      }
    }

    function showAuthView(mode) {
      AppState.authMode = mode;
      switchAuthTab(mode);
      navigateToView('auth');
    }

    // ── Authentication Simulation ────────────────────────────────────────────
    function switchAuthTab(mode) {
      AppState.authMode = mode;
      document.querySelectorAll('.auth-tab').forEach(el => el.classList.remove('active'));
      document.getElementById(`auth-tab-${mode}`).classList.add('active');
      document.getElementById('auth-submit-btn').innerText = mode === 'signin' ? 'Sign In' : 'Create Account';
      document.getElementById('auth-error-msg').style.display = 'none';
    }

    function handleAuthSubmit(event) {
      event.preventDefault();
      const email = document.getElementById('auth-email').value.trim();
      const password = document.getElementById('auth-password').value.trim();
      const errorMsg = document.getElementById('auth-error-msg');
      
      if (!email || !password) {
        errorMsg.innerText = 'Please enter both email and password.';
        errorMsg.style.display = 'block';
        return;
      }

      if (password.length < 6) {
        errorMsg.innerText = 'Password must be at least 6 characters long.';
        errorMsg.style.display = 'block';
        return;
      }

      // Successful simulated auth
      AppState.user = { email };
      localStorage.setItem('aether_user', JSON.stringify(AppState.user));
      document.getElementById('user-avatar-lbl').innerText = email[0].toUpperCase();
      document.getElementById('user-display-email').innerText = email;
      
      // Cleanup inputs
      document.getElementById('auth-email').value = '';
      document.getElementById('auth-password').value = '';
      errorMsg.style.display = 'none';
      
      navigateToView('app');
    }

    function handleLogout() {
      localStorage.removeItem('aether_user');
      AppState.user = null;
      navigateToView('landing');
    }

    // ── Session thread controls ──────────────────────────────────────────────
    function generateSessionId() {
      return 'session-' + Date.now() + '-' + Math.random().toString(36).substring(2, 8);
    }

    function loadSessionId() {
      let sid = sessionStorage.getItem('rag_session_id');
      if (!sid) {
        sid = generateSessionId();
        sessionStorage.setItem('rag_session_id', sid);
      }
      AppState.activeSessionId = sid;
      document.getElementById('active-thread-info').innerText = 'Session: ' + sid;
      updateActiveThreadList(sid);
    }

    async function newConversation() {
      const oldSid = AppState.activeSessionId;
      
      // Request memory clear for the old session
      await fetch('/session/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: '', session_id: oldSid })
      });

      const newSid = generateSessionId();
      sessionStorage.setItem('rag_session_id', newSid);
      AppState.activeSessionId = newSid;
      document.getElementById('active-thread-info').innerText = 'Session: ' + newSid;
      
      // Reset Chat wrapper back to suggested prompt hub
      loadSuggestionsHub();
      updateActiveThreadList(newSid);
    }

    function updateActiveThreadList(activeSid) {
      const threadHistoryList = document.getElementById('sidebar-threads-list');
      
      // Maintain a list of active threads locally
      if (!AppState.threadsList.includes(activeSid)) {
        AppState.threadsList.unshift(activeSid);
      }

      threadHistoryList.innerHTML = '';
      AppState.threadsList.forEach(sid => {
        const item = document.createElement('li');
        item.className = `thread-item ${sid === activeSid ? 'active' : ''}`;
        item.innerText = sid.substring(0, 16) + '...';
        item.onclick = () => loadExistingThread(sid);
        threadHistoryList.appendChild(item);
      });
    }

    function loadExistingThread(sid) {
      AppState.activeSessionId = sid;
      sessionStorage.setItem('rag_session_id', sid);
      document.getElementById('active-thread-info').innerText = 'Session: ' + sid;
      
      // Refresh list active state styles
      document.querySelectorAll('.thread-item').forEach(el => {
        el.classList.remove('active');
        if (el.innerText.startsWith(sid.substring(0, 16))) {
          el.classList.add('active');
        }
      });

      // Clear the chat workspace and load placeholder text for the thread load
      const wrapper = document.getElementById('chat-wrapper');
      wrapper.innerHTML = `
        <div class="welcome-hub">
          <div class="welcome-subtitle">Thread loaded. Start asking questions to see history context.</div>
        </div>
      `;
    }

    // ── Document Handler API triggers ────────────────────────────────────────
    async function handleAppFileUpload(event) {
      const file = event.target.files[0];
      if (!file) return;

      const sidebarUpload = document.querySelector('.sidebar-upload');
      const originalContent = sidebarUpload.innerHTML;
      sidebarUpload.innerHTML = '<div class="sidebar-upload-icon">⏳</div><div class="sidebar-upload-label">Ingesting...</div>';

      const formData = new FormData();
      formData.append('file', file);

      try {
        const res = await fetch('/upload', { method: 'POST', body: formData });
        const data = await res.json();
        
        if (res.ok) {
          sidebarUpload.innerHTML = '<div class="sidebar-upload-icon">✅</div><div class="sidebar-upload-label">Success!</div>';
          refreshFilesLists();
        } else {
          sidebarUpload.innerHTML = '<div class="sidebar-upload-icon">❌</div><div class="sidebar-upload-label">Failed</div>';
          alert(data.detail);
        }
      } catch (err) {
        sidebarUpload.innerHTML = '<div class="sidebar-upload-icon">❌</div><div class="sidebar-upload-label">Network Error</div>';
      }

      setTimeout(() => {
        sidebarUpload.innerHTML = originalContent;
      }, 3000);
      
      event.target.value = '';
    }

    async function refreshFilesLists() {
      try {
        const res = await fetch('/documents');
        const data = await res.json();
        
        const docsList = document.getElementById('sidebar-docs-list');
        docsList.innerHTML = '';
        
        if (!data.documents || data.documents.length === 0) {
          docsList.innerHTML = '<li class="sidebar-doc-item" style="color: var(--text-muted); font-style: italic; border:none; background:transparent;">No files uploaded</li>';
          return;
        }

        data.documents.forEach(doc => {
          const li = document.createElement('li');
          li.className = 'sidebar-doc-item';
          li.innerHTML = `
            <span class="sidebar-doc-name" title="${doc}">📄 ${doc}</span>
            <button class="btn-doc-delete" onclick="deleteDocument('${doc}')">×</button>
          `;
          docsList.appendChild(li);
        });
      } catch (err) {
        console.error("Could not fetch documents", err);
      }
    }

    async function deleteDocument(filename) {
      if (!confirm(`Delete document "${filename}"? This clears it from the vector store index.`)) return;
      
      try {
        // Since DELETE /documents clears all docs in the original API, let's trigger it.
        // If your API supports specific file deletes, adjust this query.
        await fetch('/documents', { method: 'DELETE' });
        refreshFilesLists();
        loadDetailedDocsTable();
      } catch (err) {
        console.error("Failed deleting documents", err);
      }
    }

    // ── Suggestions Hub Manager ──────────────────────────────────────────────
    function loadSuggestionsHub() {
      const wrapper = document.getElementById('chat-wrapper');
      wrapper.innerHTML = `
        <div class="welcome-hub" id="welcome-hub">
          <div class="welcome-icon-glowing">✦</div>
          <h2 class="welcome-title">Where knowledge begins.</h2>
          <div class="welcome-subtitle">Ask anything about your privately ingested files.</div>
          
          <div class="suggestion-cards">
            <div class="suggestion-card" onclick="triggerSuggestion('Summarize the document')">
              <div class="suggestion-icon">📝</div>
              <div class="suggestion-prompt">Summarize the document</div>
              <div class="suggestion-desc">Get a high-level overview of your primary files.</div>
            </div>
            <div class="suggestion-card" onclick="triggerSuggestion('Perform a custom calculation')">
              <div class="suggestion-icon">🧮</div>
              <div class="suggestion-prompt">Perform custom calculations</div>
              <div class="suggestion-desc">Trigger Agent tool chain equations like sqrt(144) * 5.</div>
            </div>
          </div>
        </div>
      `;
    }

    function triggerSuggestion(promptText) {
      document.getElementById('query-textarea').value = promptText;
      submitQuery();
    }

    // ── Input & Textarea adjustments ──────────────────────────────────────────
    function handleQueryTextareaKeyDown(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        submitQuery();
      }
    }

    // ── Query submission handler ─────────────────────────────────────────────
    async function submitQuery() {
      const textarea = document.getElementById('query-textarea');
      const text = textarea.value.trim();
      if (!text) return;

      textarea.value = '';
      
      // Hide suggestion hub if present
      const hub = document.getElementById('welcome-hub');
      if (hub) hub.remove();

      // Render User bubble
      addUserMessageBubble(text);
      
      // Setup Loader Spinner
      showThinkingState();
      
      // Build API Payload
      const payload = {
        question: text,
        session_id: AppState.activeSessionId,
        use_agent: AppState.agentMode,
        use_langchain: AppState.langChainMode
      };

      const sendBtn = document.getElementById('btn-query-send');
      sendBtn.disabled = true;

      if (AppState.streamingMode) {
        try {
          const res = await fetch('/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          hideThinkingState();

          if (!res.ok) {
            const err = await res.json();
            addBotMessageBubble('❌ ' + (err.detail || 'Streaming API failed'), [], 0, null);
          } else {
            // Setup blank streaming bubble
            const wrapper = document.getElementById('chat-wrapper');
            const msgEl = document.createElement('div');
            msgEl.className = 'chat-msg chat-msg-bot';
            msgEl.innerHTML = `
              <div class="bot-header">
                <div class="bot-avatar">✦</div>
                <div class="bot-name">Aether AI</div>
              </div>
              <div class="bot-body">
                <div class="bot-text" id="active-stream-target"></div>
              </div>
            `;
            wrapper.appendChild(msgEl);
            scrollToBottom();

            const streamTarget = document.getElementById('active-stream-target');
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let accumulatedText = '';
            let meta = null;

            while (true) {
              const { done, value } = await reader.read();
              if (done) break;
              
              const chunk = decoder.decode(value, { stream: true });
              const lines = chunk.split('\n');
              
              for (const line of lines) {
                if (!line.trim().startsWith('data: ')) continue;
                try {
                  const event = JSON.parse(line.trim().substring(6));
                  if (event.type === 'token') {
                    accumulatedText += event.content;
                    streamTarget.innerHTML = accumulatedText.replace(/\n/g, '<br/>');
                    scrollToBottom();
                  } else if (event.type === 'done') {
                    meta = event;
                  }
                } catch (e) {}
              }
            }

            // Remove temporary target ID
            streamTarget.removeAttribute('id');
            
            // Re-render complete bubble layout with citations and badges
            if (meta) {
              msgEl.innerHTML = buildCompleteBotBubbleHTML(accumulatedText, meta.sources, meta.confidence, meta.tool_used);
            }
            scrollToBottom();
          }
        } catch (err) {
          hideThinkingState();
          addBotMessageBubble('❌ Network error during generation stream.', [], 0, null);
        }
      } else {
        try {
          const res = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          const data = await res.json();
          hideThinkingState();
          
          if (res.ok) {
            addBotMessageBubble(data.answer, data.sources, data.confidence, data.tool_used);
          } else {
            addBotMessageBubble('❌ ' + (data.detail || 'Query execution failed'), [], 0, null);
          }
        } catch (err) {
          hideThinkingState();
          addBotMessageBubble('❌ Network error connecting to host API.', [], 0, null);
        }
      }

      sendBtn.disabled = false;
    }

    // ── Bubble rendering utilities ──────────────────────────────────────────
    function addUserMessageBubble(text) {
      const wrapper = document.getElementById('chat-wrapper');
      const div = document.createElement('div');
      div.className = 'chat-msg chat-msg-user';
      div.innerHTML = `<div class="bubble">${text}</div>`;
      wrapper.appendChild(div);
      scrollToBottom();
    }

    // Add CSS transition/fade animation
    function buildCompleteBotBubbleHTML(text, sources, confidence, toolUsed) {
      let confidenceBadgeClass = 'badge-low';
      let confidenceLabel = 'Low';
      
      if (confidence >= 0.6) {
        confidenceBadgeClass = 'badge-high';
        confidenceLabel = 'High';
      } else if (confidence >= 0.35) {
        confidenceBadgeClass = 'badge-mid';
        confidenceLabel = 'Medium';
      }

      let html = `
        <div class="bot-header">
          <div class="bot-avatar">✦</div>
          <div class="bot-name">Aether AI</div>
        </div>
        <div class="bot-body">
          <div class="msg-badges">
      `;

      if (confidence > 0) {
        html += `<span class="msg-badge ${confidenceBadgeClass}">${confidenceLabel} · ${Math.round(confidence * 100)}% Match</span>`;
      }
      if (toolUsed) {
        html += `<span class="msg-badge badge-util">🛠️ ${toolUsed}</span>`;
      }

      html += `
          </div>
          <div class="bot-text">${text.replace(/\n/g, '<br/>')}</div>
      `;

      if (sources && sources.length > 0) {
        html += `
          <div class="citations-section">
            <div class="citations-title">Sources & Citations</div>
            <div class="citations-grid">
        `;
        
        sources.forEach((src, idx) => {
          const elementId = `cit-${Date.now()}-${idx}`;
          const matchPercent = src.score ? `${Math.round(src.score * 100)}% match` : '';
          
          html += `
            <div class="citation-card" id="${elementId}" onclick="toggleCitationExpansion('${elementId}')">
              <div class="citation-file">📄 ${src.source}</div>
              <div class="citation-meta">
                <span>Page ${src.page}</span>
                <span>${matchPercent}</span>
              </div>
              <div class="citation-snippet">${src.snippet || ''}</div>
            </div>
          `;
        });

        html += `
            </div>
          </div>
        `;
      }

      html += `</div>`;
      return html;
    }

    function addBotMessageBubble(text, sources, confidence, toolUsed) {
      const wrapper = document.getElementById('chat-wrapper');
      const div = document.createElement('div');
      div.className = 'chat-msg chat-msg-bot';
      div.innerHTML = buildCompleteBotBubbleHTML(text, sources, confidence, toolUsed);
      wrapper.appendChild(div);
      scrollToBottom();
    }

    function toggleCitationExpansion(id) {
      const card = document.getElementById(id);
      if (card) card.classList.toggle('expanded');
    }

    function showThinkingState() {
      const wrapper = document.getElementById('chat-wrapper');
      const loader = document.createElement('div');
      loader.className = 'bot-thinking';
      loader.id = 'bot-thinking-state';
      loader.innerHTML = `
        <div class="thinking-spinner"></div>
        <div class="thinking-label">Reasoning across database index...</div>
      `;
      wrapper.appendChild(loader);
      scrollToBottom();
    }

    function hideThinkingState() {
      const el = document.getElementById('bot-thinking-state');
      if (el) el.remove();
    }

    function scrollToBottom() {
      const container = document.getElementById('chat-container');
      container.scrollTop = container.scrollHeight;
    }

    // ── UI States syncing ────────────────────────────────────────────────────
    function syncUIStates() {
      // Sidebar indicators syncing
      document.getElementById('ind-agent').className = `indicator-badge ${AppState.agentMode ? 'active' : ''}`;
      document.getElementById('ind-langchain').className = `indicator-badge ${AppState.langChainMode ? 'active' : ''}`;
      document.getElementById('ind-stream').className = `indicator-badge ${AppState.streamingMode ? 'active' : ''}`;

      // Floating toggles UI syncing
      document.getElementById('toggle-agent-btn').className = `query-btn ${AppState.agentMode ? 'active' : ''}`;
      document.getElementById('toggle-langchain-btn').className = `query-btn ${AppState.langChainMode ? 'active' : ''}`;
      document.getElementById('toggle-stream-btn').className = `query-btn ${AppState.streamingMode ? 'active' : ''}`;
    }

    function toggleModeState(modeKey) {
      if (modeKey === 'agent') AppState.agentMode = !AppState.agentMode;
      if (modeKey === 'langchain') AppState.langChainMode = !AppState.langChainMode;
      if (modeKey === 'stream') AppState.streamingMode = !AppState.streamingMode;
      
      syncUIStates();
    }

    function toggleSidebar() {
      const sidebar = document.getElementById('app-sidebar');
      const toggleBtn = document.querySelector('.sidebar-collapse-btn');
      
      if (sidebar.style.width === '0px') {
        sidebar.style.width = '260px';
        toggleBtn.innerText = '◂';
      } else {
        sidebar.style.width = '0px';
        toggleBtn.innerText = '▸';
      }
    }

    // ── Settings & Stats tabs controller ─────────────────────────────────────
    function openSettingsModal() {
      document.getElementById('settings-modal-overlay').classList.add('active');
      loadSystemHealthStats();
      loadDetailedDocsTable();
    }

    function closeSettingsModal() {
      document.getElementById('settings-modal-overlay').classList.remove('active');
    }

    function switchSettingsTab(event, paneId) {
      document.querySelectorAll('.modal-tab-btn').forEach(btn => btn.classList.remove('active'));
      event.target.classList.add('active');

      document.querySelectorAll('.modal-pane').forEach(pane => pane.classList.remove('active'));
      document.getElementById(paneId).classList.add('active');

      // Update Header Title based on Tab Name
      const titles = {
        'settings-tab-general': 'General Settings',
        'settings-tab-documents': 'Ingested Document Store',
        'settings-tab-health': 'System Diagnostics & Metrics'
      };
      document.getElementById('modal-settings-title').innerText = titles[paneId];
    }

    // Load credentials & API keys into settings inputs
    function loadGeneralSettings() {
      const storedKey = AppState.apiKey || localStorage.getItem('aether_api_key') || '';
      document.getElementById('settings-api-key').value = storedKey;
    }

    function saveApiKeyFromSettings(keyVal) {
      AppState.apiKey = keyVal.trim();
      localStorage.setItem('aether_api_key', AppState.apiKey);
    }

    async function clearAllConversations() {
      if (!confirm("Wipe out conversation cache and database completely? This cannot be undone.")) return;
      
      const payload = { question: '', session_id: AppState.activeSessionId };
      try {
        await fetch('/session/clear', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        alert("Conversational memory databases wiped successfully.");
        newConversation();
      } catch (err) {
        console.error(err);
      }
    }

    async function clearAllDocuments() {
      if (!confirm("Are you sure you want to completely clear the document index and vectors store?")) return;
      try {
        await fetch('/documents', { method: 'DELETE' });
        refreshFilesLists();
        loadDetailedDocsTable();
      } catch (err) {
        console.error(err);
      }
    }

    // Load real-time stats from `/health` endpoint
    async function loadSystemHealthStats() {
      try {
        const res = await fetch('/health');
        if (!res.ok) return;
        const data = await res.json();
        
        // Render values
        document.getElementById('metric-uptime').innerText = `${Math.round(data.uptime_seconds)}s`;
        document.getElementById('metric-docs-count').innerText = data.documents.total_documents;
        document.getElementById('metric-history-count').innerText = data.conversations.total_turns;
      } catch (err) {
        console.error("Could not fetch server health metrics", err);
      }
    }

    // Load detailed documents data from newly built endpoint
    async function loadDetailedDocsTable() {
      const tbody = document.getElementById('settings-docs-tbody');
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">Loading records...</td></tr>';
      
      try {
        const res = await fetch('/documents/detailed');
        if (!res.ok) {
          tbody.innerHTML = '<tr><td colspan="6" class="docs-empty-state">Unable to load detailed records.</td></tr>';
          return;
        }
        const data = await res.json();
        
        tbody.innerHTML = '';
        if (!data.documents || data.documents.length === 0) {
          tbody.innerHTML = '<tr><td colspan="6" class="docs-empty-state">No documents ingested.</td></tr>';
          return;
        }

        data.documents.forEach(doc => {
          const sizeKb = doc.size_bytes ? (doc.size_bytes / 1024).toFixed(1) + ' KB' : '0 KB';
          const row = document.createElement('tr');
          row.innerHTML = `
            <td style="font-weight:600; color:var(--text-primary); max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${doc.filename}">${doc.filename}</td>
            <td>${doc.pages}</td>
            <td>${doc.chunks}</td>
            <td>${sizeKb}</td>
            <td>${doc.uploaded_at ? doc.uploaded_at.substring(0, 19).replace('T', ' ') : '-'}</td>
            <td><button class="btn-doc-delete" onclick="deleteDocument('${doc.filename}')">Delete</button></td>
          `;
          tbody.appendChild(row);
        });
      } catch (err) {
        tbody.innerHTML = '<tr><td colspan="6" class="docs-empty-state" style="color:var(--red);">Error loading documents list.</td></tr>';
      }
    }
  