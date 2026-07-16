/**
 * dashboard.js — Real-time Socket.IO client for ALGOX dashboard
 */

const socket = io();

// ── Helpers ─────────────────────────────────────────────────────────────────

function fmt(n, dp = 4) {
  if (n == null || isNaN(n)) return '—';
  return parseFloat(n).toFixed(dp);
}

function fmtPnl(n) {
  if (n == null) return '—';
  const v = parseFloat(n);
  return (v >= 0 ? '+' : '') + v.toFixed(4);
}

function fmtUptime(sec) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

function stateLabel(state) {
  const map = {
     0:    'FLAT',
     1.0:  'ACTIVE → watching 1.5R',
     1.5:  'SL at BE → watching 2R',
     2.0:  'SL at 1.5R → watching 3R',
    '-1.0':'ACTIVE → watching 1.5R',
    '-1.5':'SL at BE → watching 2R',
    '-2.0':'SL at 1.5R → watching 3R',
  };
  return map[state] || String(state);
}

// ── Trade card builder ───────────────────────────────────────────────────────

function buildCard(t) {
  const dir       = t.direction.toLowerCase();        // 'long' or 'short'
  const pnlSign   = t.pnl >= 0 ? 'pos' : 'neg';
  const pnlVal    = (t.pnl >= 0 ? '+' : '') + fmt(t.pnl, 4);

  // For the level progress bars we compute how far price is between
  // SL and 3R (we don't have live price here, so we show proportional markers)
  const range   = Math.abs(t.r3 - t.sl);
  const pct     = (v) => range === 0 ? 0 : Math.min(100, Math.max(0,
    Math.abs(v - t.sl) / range * 100
  ));

  return `
  <div class="trade-card ${dir}" id="card-${t.symbol}">
    <div class="card-header">
      <span class="card-symbol">${t.symbol}</span>
      <span class="card-dir ${dir}">${t.direction}</span>
    </div>

    <div class="card-pnl ${pnlSign}">${pnlVal} USDT</div>

    <div class="card-levels">
      <div class="level-row">
        <span class="level-label">ENTRY</span>
        <div class="level-bar-wrap">
          <div class="level-bar r2-bar" style="width:${pct(t.entry)}%"></div>
        </div>
        <span class="level-price">${fmt(t.entry)}</span>
      </div>
      <div class="level-row">
        <span class="level-label">1.5R</span>
        <div class="level-bar-wrap">
          <div class="level-bar r1-5-bar" style="width:${pct(t.r1_5)}%"></div>
        </div>
        <span class="level-price">${fmt(t.r1_5)}</span>
      </div>
      <div class="level-row">
        <span class="level-label">2R</span>
        <div class="level-bar-wrap">
          <div class="level-bar r2-bar" style="width:${pct(t.r2)}%"></div>
        </div>
        <span class="level-price">${fmt(t.r2)}</span>
      </div>
      <div class="level-row">
        <span class="level-label">3R TP</span>
        <div class="level-bar-wrap">
          <div class="level-bar r3-bar" style="width:${pct(t.r3)}%"></div>
        </div>
        <span class="level-price">${fmt(t.r3)}</span>
      </div>
      <div class="level-row">
        <span class="level-label">SL</span>
        <div class="level-bar-wrap">
          <div class="level-bar sl-bar" style="width:${pct(t.sl)}%"></div>
        </div>
        <span class="level-price">${fmt(t.sl)}</span>
      </div>
    </div>

    <div class="card-state">
      <span class="state-badge">${stateLabel(t.state)}</span>
      <span>Qty: ${t.qty}</span>
    </div>
  </div>`;
}

// ── History row builder ──────────────────────────────────────────────────────

function buildHistRow(h) {
  const isWin  = h.outcome.includes('WIN');
  const dirCls = h.direction.toLowerCase();
  const pnlCls = h.pnl >= 0 ? 'pnl-pos' : 'pnl-neg';
  const dur    = h.duration < 60
    ? `${h.duration}s`
    : `${Math.floor(h.duration/60)}m`;

  return `<tr>
    <td>${h.symbol}</td>
    <td class="badge-${dirCls}">${h.direction}</td>
    <td>${fmt(h.entry)}</td>
    <td>${fmt(h.close)}</td>
    <td class="${isWin ? 'badge-win' : 'badge-sl'}">${h.outcome}</td>
    <td class="${pnlCls}">${fmtPnl(h.pnl)}</td>
    <td>${dur}</td>
  </tr>`;
}

// ── Socket handlers ──────────────────────────────────────────────────────────

socket.on('connect', () => {
  const pill = document.getElementById('statusPill');
  pill.classList.add('live');
  document.getElementById('statusText').textContent = 'Live';
});

socket.on('disconnect', () => {
  const pill = document.getElementById('statusPill');
  pill.classList.remove('live');
  document.getElementById('statusText').textContent = 'Disconnected';
});

socket.on('update', (data) => {
  // Header stats
  document.getElementById('balance').textContent = `$${(data.balance || 0).toFixed(2)}`;
  document.getElementById('uptime').textContent   = fmtUptime(data.uptime || 0);
  document.getElementById('activeCount').textContent = (data.trades || []).length;

  // Active trade cards
  const grid = document.getElementById('tradesGrid');
  if (!data.trades || data.trades.length === 0) {
    grid.innerHTML = '<div class="empty-state">No open positions. Waiting for signal…</div>';
  } else {
    grid.innerHTML = data.trades.map(buildCard).join('');
  }

  // History table
  const tbody = document.getElementById('histBody');
  const hist  = (data.history || []).slice().reverse(); // newest first
  if (hist.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-row">No history yet</td></tr>';
  } else {
    tbody.innerHTML = hist.map(buildHistRow).join('');
  }
});

// ── Tab Management ───────────────────────────────────────────────────────────

let currentTab = 'dashboard';

function switchTab(tabName) {
  currentTab = tabName;
  
  // Update button active states
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.remove('active');
  });
  const activeBtn = document.getElementById(`btn-${tabName}`);
  if (activeBtn) activeBtn.classList.add('active');

  // Update pane active states
  document.querySelectorAll('.tab-pane').forEach(pane => {
    pane.classList.remove('active');
  });
  const activePane = document.getElementById(`tab-${tabName}`);
  if (activePane) activePane.classList.add('active');

  // Fetch data if needed
  if (tabName === 'logs') {
    fetchLogs();
  } else if (tabName === 'settings') {
    fetchSettings();
  }
}

function fetchLogs() {
  const pre = document.getElementById('logPre');
  if (!pre) return;
  
  fetch('/api/logs')
    .then(res => res.json())
    .then(data => {
      pre.textContent = data.logs || 'No logs available.';
      // Scroll to bottom of log container
      const container = document.querySelector('.log-container');
      if (container) {
        container.scrollTop = container.scrollHeight;
      }
    })
    .catch(err => {
      pre.textContent = `Error loading logs: ${err}`;
    });
}

function fetchSettings() {
  const container = document.getElementById('settingsContainer');
  if (!container) return;
  container.innerHTML = '<div class="empty-state">Fetching settings...</div>';

  fetch('/api/settings')
    .then(res => res.json())
    .then(data => {
      let html = '';
      
      const categories = {
        "trading": "📈 Trading Configuration",
        "strategy": "⚙️ Strategy Settings",
        "exchange": "🔑 Exchange Setup (Read-Only)",
        "telegram": "🔔 Telegram Alerts (Read-Only)",
        "dashboard": "🖥️ Dashboard Settings"
      };

      for (const [key, title] of Object.entries(categories)) {
        if (!data[key]) continue;
        
        const isReadOnly = key === 'exchange' || key === 'telegram';
        
        html += `
        <div class="settings-card">
          <div class="settings-card-title">${title}</div>
          <div class="settings-list">
        `;
        
        for (const [subkey, val] of Object.entries(data[key])) {
          const keyLabel = subkey.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
          const inputId = `setting-${key}-${subkey}`;
          
          let inputHtml = '';
          if (isReadOnly) {
            inputHtml = `<span class="settings-val">${val}</span>`;
          } else {
            if (typeof val === 'boolean') {
              inputHtml = `
                <select class="setting-input" id="${inputId}">
                  <option value="true" ${val ? 'selected' : ''}>True</option>
                  <option value="false" ${!val ? 'selected' : ''}>False</option>
                </select>
              `;
            } else if (Array.isArray(val)) {
              inputHtml = `<input type="text" class="setting-input" id="${inputId}" value="${val.join(', ')}" />`;
            } else if (typeof val === 'number') {
              inputHtml = `<input type="number" step="any" class="setting-input" id="${inputId}" value="${val}" />`;
            } else {
              inputHtml = `<input type="text" class="setting-input" id="${inputId}" value="${val}" />`;
            }
          }
          
          html += `
            <div class="settings-item">
              <span class="settings-key">${keyLabel}</span>
              ${inputHtml}
            </div>
          `;
        }
        
        html += `
          </div>
        </div>
        `;
      }
      
      // Add Save Settings button at the footer
      html += `
        <div class="settings-footer" style="grid-column: 1 / -1; display:flex; flex-direction:column; gap:10px; align-items:center; margin-top:10px; width:100%;">
          <button class="btn-refresh" style="background:var(--blue); color:#090c14; border-color:var(--blue); width:200px; font-weight:700; height:40px; font-size:14px;" onclick="saveSettings()">💾 Save Settings</button>
          <div id="settingsStatus" style="font-size:13px; font-weight:600;"></div>
        </div>
      `;
      
      container.innerHTML = html;
    })
    .catch(err => {
      container.innerHTML = `<div class="empty-state" style="color:var(--red)">Error loading settings: ${err}</div>`;
    });
}

function saveSettings() {
  const statusDiv = document.getElementById('settingsStatus');
  if (!statusDiv) return;
  statusDiv.textContent = 'Saving...';
  statusDiv.style.color = 'var(--text-dim)';

  const payload = {
    trading: {},
    strategy: {},
    dashboard: {}
  };

  const inputs = document.querySelectorAll('[id^="setting-"]');
  inputs.forEach(input => {
    const parts = input.id.split('-');
    const category = parts[1];
    const subkey = parts[2];
    
    let val = input.value;
    if (val === 'true') val = true;
    else if (val === 'false') val = false;
    else if (!isNaN(val) && val.trim() !== '') val = Number(val);
    
    payload[category][subkey] = val;
  });

  fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
    .then(res => res.json())
    .then(data => {
      if (data.status === 'success') {
        statusDiv.textContent = '✅ Settings saved successfully!';
        statusDiv.style.color = 'var(--green)';
        setTimeout(() => { statusDiv.textContent = ''; }, 3000);
      } else {
        statusDiv.textContent = `❌ Error: ${data.message}`;
        statusDiv.style.color = 'var(--red)';
      }
    })
    .catch(err => {
      statusDiv.textContent = `❌ Error: ${err}`;
      statusDiv.style.color = 'var(--red)';
    });
}

// Auto-refresh logs every 5 seconds if logs tab is active
setInterval(() => {
  if (currentTab === 'logs') {
    fetchLogs();
  }
}, 5000);

