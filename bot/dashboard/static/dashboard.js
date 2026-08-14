/**
 * dashboard.js — Real-time Client logic for ALGOX Multi-Tenant SaaS
 */

let currentTab = 'dashboard';
let userIsAdmin = false;
let hasCredentials = false;

// ── Helpers ─────────────────────────────────────────────────────────────────

function fmt(n, dp = 2) {
  if (n == null || isNaN(n)) return '—';
  return parseFloat(n).toFixed(dp);
}

function fmtPnl(n) {
  if (n == null) return '—';
  const v = parseFloat(n);
  return (v >= 0 ? '+' : '') + v.toFixed(2);
}

// ── Trade card builder ───────────────────────────────────────────────────────

function buildCard(t) {
  const dir       = t.direction.toLowerCase();        // 'long' or 'short'
  const pnlSign   = t.pnl >= 0 ? 'pos' : 'neg';
  const pnlVal    = (t.pnl >= 0 ? '+' : '') + fmt(t.pnl, 2);

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
        <span class="level-price">${fmt(t.entry_price)}</span>
      </div>
      <div class="level-row">
        <span class="level-label">SL (-1R)</span>
        <span class="level-price" style="color:var(--red);">${fmt(t.direction === 'LONG' ? t.entry_price * 0.995 : t.entry_price * 1.005)}</span>
      </div>
      <div class="level-row">
        <span class="level-label">TP (+1R)</span>
        <span class="level-price" style="color:var(--green);">${fmt(t.direction === 'LONG' ? t.entry_price * 1.005 : t.entry_price * 0.995)}</span>
      </div>
    </div>

    <div class="card-state">
      <span class="state-badge">ACTIVE (1:1 Target)</span>
      <span>Qty: ${t.qty}</span>
    </div>
  </div>`;
}

// ── History row builder ──────────────────────────────────────────────────────

function buildHistRow(h) {
  const isWin  = h.outcome.includes('WIN');
  const dirCls = h.direction.toLowerCase();
  const pnlCls = h.pnl >= 0 ? 'pnl-pos' : 'pnl-neg';
  
  // Format Postgres timestamp
  const dateStr = h.closed_at ? new Date(h.closed_at).toLocaleString() : '—';

  return `<tr>
    <td><b>${h.symbol}</b></td>
    <td class="badge-${dirCls}">${h.direction}</td>
    <td>${fmt(h.entry_price)}</td>
    <td>${fmt(h.close_price)}</td>
    <td class="${isWin ? 'badge-win' : 'badge-sl'}">${h.outcome}</td>
    <td class="${pnlCls}">${fmtPnl(h.pnl)}</td>
    <td style="color:var(--text-muted); font-size:11px;">${dateStr}</td>
  </tr>`;
}

// ── Fetch Main State ─────────────────────────────────────────────────────────

function fetchState() {
  fetch('/api/state')
    .then(res => res.json())
    .then(data => {
      // Balance Display
      document.getElementById('balance').textContent = data.has_credentials 
        ? `$${fmt(data.balance, 2)} USDT` 
        : 'Connect Account Keys';

      // Active trades grid
      const grid = document.getElementById('tradesGrid');
      if (!data.trades || data.trades.length === 0) {
        grid.innerHTML = '<div class="empty-state">No open positions. Waiting for signal…</div>';
      } else {
        grid.innerHTML = data.trades.map(t => {
          const dir       = t.direction.toLowerCase();
          const pnlSign   = t.pnl >= 0 ? 'pos' : 'neg';
          const pnlVal    = (t.pnl >= 0 ? '+' : '') + fmt(t.pnl, 2);
          
          // Estimate levels (SL = 0.5%, TP = 0.5%)
          const slPrice = t.direction === 'LONG' ? t.entry_price * 0.995 : t.entry_price * 1.005;
          const tpPrice = t.direction === 'LONG' ? t.entry_price * 1.005 : t.entry_price * 0.995;

          return `
          <div class="trade-card ${dir}">
            <div class="card-header">
              <span class="card-symbol">${t.symbol}</span>
              <span class="card-dir ${dir}">${t.direction}</span>
            </div>
            <div class="card-pnl ${pnlSign}">${pnlVal} USDT</div>
            <div class="card-levels">
              <div class="level-row">
                <span class="level-label">ENTRY</span>
                <span class="level-price">${fmt(t.entry_price)}</span>
              </div>
              <div class="level-row">
                <span class="level-label">SL (-1R)</span>
                <span class="level-price" style="color:var(--red);">${fmt(slPrice)}</span>
              </div>
              <div class="level-row">
                <span class="level-label">TP (+1R)</span>
                <span class="level-price" style="color:var(--green);">${fmt(tpPrice)}</span>
              </div>
            </div>
            <div class="card-state">
              <span class="state-badge">MONITORING</span>
              <span>Qty: ${t.qty}</span>
            </div>
          </div>`;
        }).join('');
      }

      // History table
      const tbody = document.getElementById('histBody');
      if (!data.history || data.history.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-row">No closed trades yet</td></tr>';
      } else {
        tbody.innerHTML = data.history.map(buildHistRow).join('');
      }
    })
    .catch(err => console.error("Error fetching state:", err));
}

// ── Credentials management & Onboarding Wizard ───────────────────────────────

let currentStep = 1;

function showStep(stepNum) {
  currentStep = stepNum;
  
  // Update step indicators
  const dots = document.querySelectorAll('.step-dot');
  dots.forEach(dot => {
    const step = parseInt(dot.getAttribute('data-step'));
    if (step === stepNum) {
      dot.classList.add('active');
    } else {
      dot.classList.remove('active');
    }
  });

  // Update step containers visibility
  const steps = document.querySelectorAll('.onboarding-step');
  steps.forEach(step => {
    const stepId = step.id;
    if (stepId === `onboarding-step-${stepNum}`) {
      step.style.display = 'block';
    } else {
      step.style.display = 'none';
    }
  });
}

function nextStep(stepNum) {
  showStep(stepNum);
}

function prevStep(stepNum) {
  showStep(stepNum);
}

function skipToStep(stepNum) {
  showStep(stepNum);
}

function checkCredentialsStatus() {
  const statusDiv = document.getElementById('credentials-status');
  const disconnectSec = document.getElementById('disconnect-section');
  const activeKeySpan = document.getElementById('active-api-key');
  const sidebar = document.querySelector('.sidebar');
  const indicator = document.getElementById('onboarding-indicator');

  fetch('/api/credentials')
    .then(res => res.json())
    .then(data => {
      hasCredentials = data.has_credentials;
      if (hasCredentials) {
        statusDiv.style.display = "none";
        if (indicator) indicator.style.display = "none";
        document.querySelectorAll('.onboarding-step').forEach(el => el.style.display = 'none');
        disconnectSec.style.display = "block";
        activeKeySpan.textContent = data.api_key;
        if (sidebar) sidebar.style.display = 'none';
      } else {
        statusDiv.style.display = "block";
        statusDiv.innerHTML = "Bybit Demo Account API keys not connected yet.";
        statusDiv.className = "status-alert info";
        if (indicator) indicator.style.display = "flex";
        disconnectSec.style.display = "none";
        if (sidebar) sidebar.style.display = 'block';
        showStep(currentStep);
      }
    })
    .catch(err => {
      statusDiv.style.display = "block";
      statusDiv.innerHTML = "Error reading credentials status.";
      statusDiv.className = "status-alert error";
    });
}

document.getElementById('credentials-form').addEventListener('submit', function(e) {
  e.preventDefault();
  const api_key = document.getElementById('api_key').value;
  const api_secret = document.getElementById('api_secret').value;
  
  const statusDiv = document.getElementById('credentials-status');
  statusDiv.style.display = "block";
  statusDiv.innerHTML = "Connecting & Verifying Bybit Demo Keys...";
  statusDiv.className = "status-alert info";

  fetch('/api/credentials', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key, api_secret })
  })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        document.getElementById('api_key').value = '';
        document.getElementById('api_secret').value = '';
        currentStep = 1; // Reset to step 1 for future
        checkCredentialsStatus();
        fetchState();
      } else {
        statusDiv.style.display = "block";
        statusDiv.innerHTML = `❌ Verification failed: ${data.error}`;
        statusDiv.className = "status-alert error";
      }
    })
    .catch(err => {
      statusDiv.style.display = "block";
      statusDiv.innerHTML = `❌ Connection error: ${err}`;
      statusDiv.className = "status-alert error";
    });
});

document.getElementById('btn-disconnect').addEventListener('click', function() {
  if (!confirm("Are you sure you want to disconnect your Bybit API keys? Your running bot will stop placing new orders.")) return;
  
  fetch('/api/credentials', { method: 'DELETE' })
    .then(res => res.json())
    .then(data => {
      currentStep = 1;
      checkCredentialsStatus();
      fetchState();
    });
});

// ── Tab Management ───────────────────────────────────────────────────────────

function switchTab(tabName) {
  currentTab = tabName;
  
  document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
  const activeBtn = document.getElementById(`btn-${tabName}`);
  if (activeBtn) activeBtn.classList.add('active');

  document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));
  const activePane = document.getElementById(`tab-${tabName}`);
  if (activePane) activePane.classList.add('active');

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
  const form = document.getElementById('settings-form');
  if (!form) return;
  form.innerHTML = '<div class="empty-state">Loading settings...</div>';

  fetch('/api/settings')
    .then(res => res.json())
    .then(data => {
      userIsAdmin = data.is_admin;
      const cfg = data.config;
      
      // Update Admin tab visibility
      const adminBtn = document.getElementById('btn-logs');
      if (adminBtn) {
        adminBtn.style.display = userIsAdmin ? 'block' : 'none';
      }

      let html = '';
      // Leverage and Risk Controls (applicable to all users)
      const settings = data.user_settings;
      html += `
        <div style="grid-column: 1/-1; margin-bottom: 8px; font-weight:700; color:var(--text-white);">📈 Trading Risk Setup</div>
        
        <div class="input-group">
          <label>Risk Mode</label>
          <select id="set-risk-mode" onchange="toggleRiskModeHelp()">
            <option value="PERCENT" ${settings.risk_mode === 'PERCENT' ? 'selected' : ''}>Percentage (%) of balance</option>
            <option value="PERCENT_FIXED" ${settings.risk_mode === 'PERCENT_FIXED' ? 'selected' : ''}>Percentage (%) of Fixed Capital</option>
            <option value="USD" ${settings.risk_mode === 'USD' ? 'selected' : ''}>Fixed USD ($) Amount</option>
          </select>
        </div>
        
        <div class="input-group">
          <label id="risk-amount-label">Risk Value</label>
          <input type="number" step="any" id="set-risk-amount" value="${settings.risk_amount}" min="0.1" required />
        </div>
        
        <div class="input-group" id="fixed-capital-group">
          <label>Fixed Capital Base ($ USD)</label>
          <input type="number" id="set-fixed-capital" value="${settings.fixed_capital}" min="1" required />
        </div>
        
        <div class="input-group" style="grid-column: 1/-1;">
          <label>Leverage (x)</label>
          <input type="number" id="set-leverage" value="${settings.leverage}" min="1" max="50" required />
        </div>
      `;

      if (userIsAdmin) {
        // Admin user: Can edit full key configs
        html += `<div style="grid-column: 1/-1; margin-bottom: 20px; font-weight:700; color:var(--blue);">🔑 SYSTEM ADMINISTRATOR CONFIGURATION</div>`;
        for (const [cat, submap] of Object.entries(cfg)) {
          html += `
            <div class="admin-config-card" style="grid-column: 1/-1; background:var(--surface2); padding:20px; border-radius:var(--radius-sm); border:1px solid var(--border); margin-bottom:16px;">
              <h4 style="text-transform:uppercase; color:var(--text-white); margin-bottom:12px;">${cat}</h4>
              <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px;">
          `;
          for (const [subkey, subval] of Object.entries(submap)) {
            const inputId = `admin-${cat}-${subkey}`;
            let inputHtml = '';
            if (typeof subval === 'boolean') {
              inputHtml = `
                <select id="${inputId}">
                  <option value="true" ${subval ? 'selected' : ''}>True</option>
                  <option value="false" ${!subval ? 'selected' : ''}>False</option>
                </select>
              `;
            } else if (Array.isArray(subval)) {
              inputHtml = `<input type="text" id="${inputId}" value="${subval.join(', ')}" />`;
            } else if (typeof subval === 'number') {
              inputHtml = `<input type="number" step="any" id="${inputId}" value="${subval}" />`;
            } else {
              inputHtml = `<input type="text" id="${inputId}" value="${subval}" />`;
            }
            html += `
              <div class="input-group">
                <label>${subkey.replace(/_/g, ' ')}</label>
                ${inputHtml}
              </div>
            `;
          }
          html += `</div></div>`;
        }
      }
      if (hasCredentials) {
        html += `
          <div style="grid-column: 1 / -1; border-top: 1px solid var(--border); padding-top: 24px; margin-top: 24px; text-align: center;">
            <p style="color:var(--text-muted); font-size:12px; margin-bottom:12px;">Your account keys are active. If you want to connect a different account, disconnect them below.</p>
            <button type="button" class="btn-danger" style="width: auto; padding: 10px 24px; display: inline-block;" onclick="disconnectFromSettings()">Disconnect Bybit Keys</button>
          </div>
        `;
      }

      html += `
        <button type="submit" class="btn-primary" style="grid-column: 1/-1;">💾 Save Configuration</button>
        <div id="settings-status" style="grid-column: 1/-1; text-align:center; font-weight:600; font-size:12px; margin-top:10px;"></div>
      `;
      form.innerHTML = html;
      toggleRiskModeHelp();
    });
}

function toggleRiskModeHelp() {
  const modeSelect = document.getElementById('set-risk-mode');
  const label = document.getElementById('risk-amount-label');
  const capGroup = document.getElementById('fixed-capital-group');
  if (modeSelect) {
    if (label) {
      label.textContent = modeSelect.value === 'USD' ? 'Risk Amount ($ USD)' : 'Risk Percentage (%)';
    }
    if (capGroup) {
      capGroup.style.display = modeSelect.value === 'PERCENT_FIXED' ? 'block' : 'none';
    }
  }
}

function disconnectFromSettings() {
  if (!confirm("Are you sure you want to disconnect your Bybit API keys? Your running bot will stop placing new orders.")) return;
  
  fetch('/api/credentials', { method: 'DELETE' })
    .then(res => res.json())
    .then(data => {
      checkCredentialsStatus();
      fetchState();
      fetchSettings();
    });
}

document.getElementById('settings-form').addEventListener('submit', function(e) {
  e.preventDefault();
  const statusDiv = document.getElementById('settings-status');
  statusDiv.textContent = "Saving...";
  statusDiv.style.color = "var(--text-muted)";
  
  const payload = {
    leverage: parseInt(document.getElementById('set-leverage').value),
    risk_mode: document.getElementById('set-risk-mode').value,
    risk_amount: parseFloat(document.getElementById('set-risk-amount').value),
    fixed_capital: parseFloat(document.getElementById('set-fixed-capital').value)
  };

  if (userIsAdmin) {
    payload.config = {};
    const inputs = document.querySelectorAll('[id^="admin-"]');
    inputs.forEach(input => {
      const parts = input.id.split('-');
      const cat = parts[1];
      const subkey = parts[2];
      
      if (!payload.config[cat]) payload.config[cat] = {};
      
      let val = input.value;
      if (val === 'true') val = true;
      else if (val === 'false') val = false;
      else if (!isNaN(val) && val.trim() !== '') val = Number(val);
      
      payload.config[cat][subkey] = val;
    });
  }

  fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
    .then(res => res.json())
    .then(data => {
      if (data.status === 'success') {
        statusDiv.textContent = "✅ Settings saved successfully!";
        statusDiv.style.color = "var(--green)";
        setTimeout(() => statusDiv.textContent = "", 3000);
      } else {
        statusDiv.textContent = `❌ Error: ${data.message}`;
        statusDiv.style.color = "var(--red)";
      }
    })
    .catch(err => {
      statusDiv.textContent = `❌ Connection Error: ${err}`;
      statusDiv.style.color = "var(--red)";
    });
});

function fetchLogs() {
  const pre = document.getElementById('logPre');
  if (!pre) return;
  fetch('/api/logs')
    .then(res => res.json())
    .then(data => {
      pre.textContent = data.logs || 'No logs available.';
    });
}

// ── Startup Loops ────────────────────────────────────────────────────────────

// Run initial pulls
checkCredentialsStatus();
fetchState();

// Poll state every 5 seconds
setInterval(fetchState, 5000);
