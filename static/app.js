// State management
let state = {
    flows: [],
    runs: [],
    activeFlowId: null,
    activeRunId: null
};

// Elements
const els = {
    btnSettings: document.getElementById('btn-settings'),
    settingsModal: document.getElementById('settings-modal'),
    closeSettings: document.getElementById('close-settings'),
    saveSettings: document.getElementById('save-settings'),
    settingProvider: document.getElementById('setting-provider'),
    settingApiKey: document.getElementById('setting-api-key'),
    settingBaseUrl: document.getElementById('setting-base-url'),
    settingModel: document.getElementById('setting-model'),
    
    inputUrl: document.getElementById('input-url'),
    inputGoal: document.getElementById('input-goal'),
    btnDiscover: document.getElementById('btn-discover'),
    flowsList: document.getElementById('flows-list'),
    
    flowEmptyState: document.getElementById('flow-empty-state'),
    flowDetailCard: document.getElementById('flow-detail-card'),
    detailFlowName: document.getElementById('detail-flow-name'),
    detailFrameworkBadge: document.getElementById('detail-framework-badge'),
    detailUrl: document.getElementById('detail-url'),
    detailCreated: document.getElementById('detail-created'),
    stepsContainer: document.getElementById('steps-container'),
    
    tabBtnScript: document.getElementById('tab-btn-script'),
    codeEditorBlock: document.getElementById('code-editor-block'),
    btnRegenerateScript: document.getElementById('btn-regenerate-script'),
    btnRunFlow: document.getElementById('btn-run-flow'),
    btnFixRun: document.getElementById('btn-fix-run'),
    chkHeadless: document.getElementById('chk-headless'),
    
    runsList: document.getElementById('runs-list'),
    runEmptyState: document.getElementById('run-empty-state'),
    runDetailCard: document.getElementById('run-detail-card'),
    runStatusBadge: document.getElementById('run-status-badge'),
    runMetaInfo: document.getElementById('run-meta-info'),
    linkLog: document.getElementById('link-log'),
    linkDom: document.getElementById('link-dom'),
    
    visualRegressionSection: document.getElementById('visual-regression-section'),
    btnPromoteBaseline: document.getElementById('btn-promote-baseline'),
    btnViewDiff: document.getElementById('btn-view-diff'),
    
    diagnosisPanel: document.getElementById('diagnosis-panel'),
    diagErrorType: document.getElementById('diag-error-type'),
    diagStep: document.getElementById('diag-step'),
    diagDesc: document.getElementById('diag-desc'),
    diagAlternatives: document.getElementById('diag-alternatives'),
    
    diffModal: document.getElementById('diff-modal'),
    closeDiff: document.getElementById('close-diff'),
    imgBaseline: document.getElementById('img-baseline'),
    imgCurrent: document.getElementById('img-current'),
    imgDiff: document.getElementById('img-diff'),
    
    loadingOverlay: document.getElementById('loading-overlay'),
    loadingText: document.getElementById('loading-text')
};

// Init app
document.addEventListener('DOMContentLoaded', () => {
    initDarkMode();
    loadSettings();
    bindEvents();
    fetchFlows();
    fetchRuns();
});

// Dark mode
function initDarkMode() {
    const isDark = localStorage.getItem('darkMode') === 'true';
    applyDark(isDark, false);
}

function applyDark(dark, reHighlight = true) {
    // Toggle on <html> so html.dark overrides :root variables (same element, higher specificity)
    document.documentElement.classList.toggle('dark', dark);

    const icon = document.getElementById('dark-mode-icon');
    if (icon) icon.className = dark ? 'fa-solid fa-sun' : 'fa-solid fa-moon';

    const lightTheme = document.getElementById('hljs-light');
    const darkTheme  = document.getElementById('hljs-dark');
    if (lightTheme) lightTheme.disabled = dark;
    if (darkTheme)  darkTheme.disabled  = !dark;

    if (reHighlight && window.hljs) {
        document.querySelectorAll('code[data-highlighted]').forEach(el => {
            el.removeAttribute('data-highlighted');
            window.hljs.highlightElement(el);
        });
    }
}

// Load Settings from LocalStorage
function loadSettings() {
    els.settingProvider.value = localStorage.getItem('provider') || 'openai';
    els.settingApiKey.value = localStorage.getItem('apiKey') || '';
    els.settingBaseUrl.value = localStorage.getItem('baseUrl') || '';
    if (els.settingModel) els.settingModel.value = localStorage.getItem('model') || '';
    toggleBaseUrlField();
}

function toggleBaseUrlField() {
    const isOpenRouter = els.settingProvider.value === 'openrouter';
    document.getElementById('group-base-url').style.display = isOpenRouter ? 'block' : 'none';
    if (isOpenRouter && !els.settingBaseUrl.value) {
        els.settingBaseUrl.value = 'https://openrouter.ai/api/v1';
    }
}

// Get API Request Headers
function getHeaders() {
    const headers = {
        'Content-Type': 'application/json',
        'X-API-Key': localStorage.getItem('apiKey') || ''
    };
    const provider = localStorage.getItem('provider');
    if (provider) headers['X-API-Provider'] = provider;
    
    const baseUrl = localStorage.getItem('baseUrl');
    if (baseUrl) headers['X-API-Base-Url'] = baseUrl;

    const model = localStorage.getItem('model');
    if (model) headers['X-API-Model'] = model;

    return headers;
}

// Bind UI events
function bindEvents() {
    // Dark mode toggle
    document.getElementById('btn-dark-mode').addEventListener('click', () => {
        const isDark = !document.documentElement.classList.contains('dark');
        localStorage.setItem('darkMode', isDark);
        applyDark(isDark);
    });

    // Settings modal
    els.btnSettings.addEventListener('click', () => els.settingsModal.style.display = 'flex');
    els.closeSettings.addEventListener('click', () => els.settingsModal.style.display = 'none');
    els.saveSettings.addEventListener('click', () => {
        localStorage.setItem('provider', els.settingProvider.value);
        localStorage.setItem('apiKey', els.settingApiKey.value);
        localStorage.setItem('baseUrl', els.settingBaseUrl.value);
        if (els.settingModel) localStorage.setItem('model', els.settingModel.value.trim());
        els.settingsModal.style.display = 'none';
        showToast('Settings saved.');
    });
    els.settingProvider.addEventListener('change', toggleBaseUrlField);
    
    // Discovery
    els.btnDiscover.addEventListener('click', triggerDiscovery);
    
    // Tab switching
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
            
            btn.classList.add('active');
            const tabId = btn.getAttribute('data-tab');
            document.getElementById(tabId).style.display = 'flex';
            
            if (tabId === 'tab-script') {
                openScriptTab();
            }
        });
    });
    
    // Script & execution actions
    els.btnRegenerateScript.addEventListener('click', () => generateScript());
    els.btnRunFlow.addEventListener('click', () => executeFlow(false));
    els.btnFixRun.addEventListener('click', () => executeFlow(true));
    
    // Baseline & visual diff modal
    els.btnPromoteBaseline.addEventListener('click', setBaseline);
    els.btnViewDiff.addEventListener('click', openDiffModal);
    els.closeDiff.addEventListener('click', () => els.diffModal.style.display = 'none');
}

// Loading Spinner Helpers
function showLoading(text) {
    els.loadingText.textContent = text;
    els.loadingOverlay.style.display = 'flex';
}

function hideLoading() {
    els.loadingOverlay.style.display = 'none';
}

// Escape text for safe insertion into innerHTML.
function esc(s) {
    return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Show an in-app toast notification (top-center, under the header). Replaces the
// native browser alert(). `type` is optional: 'success' | 'error' | 'info'.
function showToast(msg, type) {
    const container = document.getElementById('toast-container');
    if (!container) { console.log(msg); return; }

    if (!type) {
        type = /\b(fail|failed|failure|error|invalid|missing|unable|denied|empty|not found|already|40\d|500)\b/i.test(msg)
            ? 'error' : 'success';
    }

    const icon = type === 'error' ? 'fa-circle-exclamation'
               : type === 'info' ? 'fa-circle-info'
               : 'fa-circle-check';

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `<i class="fa-solid ${icon}"></i><span></span>` +
                      `<button class="toast-close" aria-label="Dismiss">&times;</button>`;
    toast.querySelector('span').textContent = msg;   // textContent = no HTML injection
    container.appendChild(toast);

    // animate in
    requestAnimationFrame(() => toast.classList.add('show'));

    let removed = false;
    const remove = () => {
        if (removed) return;
        removed = true;
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 320);
    };
    toast.querySelector('.toast-close').addEventListener('click', remove);
    setTimeout(remove, 3800);
}

// Fetch Flows List
async function fetchFlows() {
    try {
        const res = await fetch('/api/flows');
        state.flows = await res.json();
        renderFlows();
    } catch (e) {
        console.error('Error fetching flows:', e);
    }
}

// Fetch Runs List
async function fetchRuns() {
    try {
        const res = await fetch('/api/runs');
        state.runs = await res.json();
        renderRuns();
    } catch (e) {
        console.error('Error fetching runs:', e);
    }
}

// Render Flows to DOM
function renderFlows() {
    if (state.flows.length === 0) {
        els.flowsList.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-folder-open"></i>
                <p>No flows discovered yet.</p>
            </div>`;
        return;
    }
    
    els.flowsList.innerHTML = state.flows.map(flow => `
        <div class="flow-item ${state.activeFlowId === flow.flow_id ? 'active' : ''}" onclick="selectFlow('${flow.flow_id}')">
            <h3>${flow.flow_name}</h3>
            <p>${flow.url}</p>
        </div>
    `).join('');
}

// Render Runs to DOM
function renderRuns() {
    if (state.runs.length === 0) {
        els.runsList.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-history"></i>
                <p>No runs recorded yet.</p>
            </div>`;
        return;
    }
    
    els.runsList.innerHTML = state.runs.map(run => {
        const date = new Date(run.timestamp).toLocaleTimeString();
        let badgeClass = run.status;
        return `
            <div class="run-item ${state.activeRunId === run.run_id ? 'active' : ''}" onclick="selectRun('${run.run_id}')">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <h3>Run #${run.run_id.substring(0, 8)}</h3>
                    <span class="status-badge ${badgeClass}">${run.status}</span>
                </div>
                <p>Flow: ${state.flows.find(f => f.flow_id === run.flow_id)?.flow_name || 'Unknown'}</p>
                <p style="display:flex; justify-content:space-between;">
                    <span>Duration: ${(run.duration_ms / 1000).toFixed(1)}s</span>
                    <span>${date}</span>
                </p>
            </div>
        `;
    }).join('');
}

// Render just the steps list for a flow (reusable without resetting tabs/header).
function renderSteps(flow) {
    const steps = (flow.steps || []).filter(s => s && (s.action || s.description || s.selector || s.value));
    els.stepsContainer.innerHTML = steps.map((step, i) => {
        const action = esc(step.action || 'step');
        const desc = step.description ? `<p>${esc(step.description)}</p>` : '';
        const selector = step.selector ? `<span class="step-selector">${esc(step.selector)}</span>` : '';
        const value = step.value ? `<div class="step-value">Value: <strong>${esc(step.value)}</strong></div>` : '';
        return `
        <div class="step-card">
            <div class="step-num">${step.step_id || (i + 1)}</div>
            <div class="step-details">
                <h4>${action}</h4>
                ${desc}${selector}${value}
            </div>
        </div>`;
    }).join('');
}

// Select a Flow
function selectFlow(flowId) {
    state.activeFlowId = flowId;
    renderFlows();

    // Reset the self-heal button until this flow has a failing run.
    setFixButtonEnabled(false);

    const flow = state.flows.find(f => f.flow_id === flowId);
    if (!flow) return;

    els.flowEmptyState.style.display = 'none';
    els.flowDetailCard.style.display = 'flex';

    els.detailFlowName.textContent = flow.flow_name;
    els.detailUrl.textContent = flow.url;
    els.detailUrl.href = flow.url;
    els.detailCreated.textContent = `Discovered at: ${new Date(flow.created_at).toLocaleString()}`;

    renderSteps(flow);

    // Reset tabs
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelector('.tab-btn[data-tab="tab-steps"]').classList.add('active');
    document.getElementById('tab-steps').style.display = 'flex';
    document.getElementById('tab-script').style.display = 'none';
}

// Trigger E2E Flow Discovery
async function triggerDiscovery() {
    const url = els.inputUrl.value.strip ? els.inputUrl.value.strip() : els.inputUrl.value;
    const goal = els.inputGoal.value.strip ? els.inputGoal.value.strip() : els.inputGoal.value;
    
    if (!url || !goal) {
        showToast('Please enter both Starting URL and Goal description.');
        return;
    }
    
    if (!localStorage.getItem('apiKey')) {
        showToast('Please configure your API Key in the API Settings first.');
        els.settingsModal.style.display = 'flex';
        return;
    }
    
    showLoading('Discovering user flows...');
    
    try {
        const response = await fetch('/api/flows/discover', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ url, goal })
        });
        
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to discover flow');
        }
        
        const flow = await response.json();
        showToast('Flow discovered successfully!');
        await fetchFlows();
        selectFlow(flow.flow_id);
    } catch (e) {
        showToast(e.message);
    } finally {
        hideLoading();
    }
}

// Set the code editor content. When `highlight` is true and highlight.js is
// available, apply Python syntax highlighting.
function setCode(text, highlight) {
    els.codeEditorBlock.removeAttribute('data-highlighted');
    els.codeEditorBlock.className = 'language-python';
    els.codeEditorBlock.textContent = text;
    if (highlight && window.hljs) {
        try { window.hljs.highlightElement(els.codeEditorBlock); } catch (e) { /* ignore */ }
    }
}

// Opening the "Generated Script" tab: show the saved script if it exists,
// otherwise generate it on the fly (this tab replaces the old Generate button).
async function openScriptTab() {
    const flowId = state.activeFlowId;
    if (!flowId) return;
    try {
        setCode('# Loading script...', false);
        const res = await fetch(`/api/flows/${flowId}/script`);
        const data = await res.json();
        if (data.exists && data.code) {
            setCode(data.code, true);
        } else {
            // Not generated yet → generate now.
            await generateScript();
        }
    } catch (e) {
        setCode('# Failed to load code.', false);
    }
}

// Generate (or regenerate) the Playwright script and show it in the editor.
async function generateScript() {
    const flowId = state.activeFlowId;
    if (!flowId) return;

    if (!localStorage.getItem('apiKey')) {
        showToast('Please configure your API Key in API Settings first.');
        els.settingsModal.style.display = 'flex';
        setCode('# Set your API key in API Settings, then reopen this tab to generate.', false);
        return;
    }

    showLoading('Generating Playwright script...');
    setCode('# Generating script…', false);
    try {
        const res = await fetch(`/api/flows/${flowId}/generate`, {
            method: 'POST',
            headers: getHeaders()
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to generate script');
        }
        const data = await res.json();
        setCode(data.code || '# (empty script returned)', true);
        showToast('Script generated successfully!');
    } catch (e) {
        setCode('# Generation failed: ' + e.message, false);
        showToast(e.message);
    } finally {
        hideLoading();
    }
}

// Execute Flow Test Run.
// repair=false -> "Run Automation": execute the script once, no self-healing.
// repair=true  -> "Fix Script & Run": diagnose, patch, and re-run (self-healing).
async function executeFlow(repair = false) {
    if (!state.activeFlowId) {
        showToast('Select a flow first.', 'info');
        return;
    }

    if (!localStorage.getItem('apiKey')) {
        showToast('Please configure your API Key in API Settings first.', 'error');
        els.settingsModal.style.display = 'flex';
        return;
    }

    showLoading(repair
        ? 'Diagnosing failure, patching script & re-running...'
        : 'Running automation...');

    try {
        const res = await fetch('/api/runs', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({
                flow_id: state.activeFlowId,
                browser: 'chromium',
                // Default to headed so the UI run matches a manual run (many sites
                // block headless). The user can opt into headless via the checkbox.
                headless: els.chkHeadless ? els.chkHeadless.checked : false,
                // Plain run does no repair; "Fix Script & Run" enables self-healing.
                max_repair_attempts: repair ? 3 : 0
            })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Execution failed');
        }

        const report = await res.json();
        showToast(`Execution finished with status: ${report.status}`);

        // Enable "Fix Script & Run" only when the run did not pass.
        setFixButtonEnabled(report.status !== 'pass');

        await fetchRuns();
        selectRun(report.run_id);

        // After a repair run, re-fetch the flow so the steps panel reflects any
        // selector changes made by the adaptive repair agent.
        if (repair && state.activeFlowId) {
            try {
                const flowRes = await fetch(`/api/flows/${state.activeFlowId}`);
                if (flowRes.ok) {
                    const updatedFlow = await flowRes.json();
                    const idx = state.flows.findIndex(f => f.flow_id === updatedFlow.flow_id);
                    if (idx !== -1) state.flows[idx] = updatedFlow;
                    // Only re-render steps if the Flow Steps tab is active.
                    const stepsTabVisible = document.getElementById('tab-steps').style.display !== 'none';
                    if (stepsTabVisible) {
                        renderSteps(updatedFlow);
                    }
                    // If the script tab is open, reload the patched script content too.
                    const scriptTabVisible = document.getElementById('tab-script').style.display !== 'none';
                    if (scriptTabVisible) {
                        openScriptTab();
                    }
                }
            } catch (e) {
                console.error('Failed to refresh flow steps after repair:', e);
            }
        }
    } catch (e) {
        showToast(e.message);
    } finally {
        hideLoading();
    }
}

// Enable/disable the "Fix Script & Run" button.
function setFixButtonEnabled(enabled) {
    if (els.btnFixRun) els.btnFixRun.disabled = !enabled;
}

// Select a Run from History
async function selectRun(runId) {
    state.activeRunId = runId;
    renderRuns();
    
    const run = state.runs.find(r => r.run_id === runId);
    if (!run) return;
    
    els.runEmptyState.style.display = 'none';
    els.runDetailCard.style.display = 'flex';
    
    els.runStatusBadge.textContent = run.status;
    els.runStatusBadge.className = `status-badge ${run.status}`;
    
    const date = new Date(run.timestamp).toLocaleString();
    els.runMetaInfo.innerHTML = `
        <p><strong>Run ID:</strong> ${run.run_id}</p>
        <p><strong>Browser:</strong> ${run.browser}</p>
        <p><strong>Duration:</strong> ${(run.duration_ms / 1000).toFixed(2)}s</p>
        <p><strong>Timestamp:</strong> ${date}</p>
    `;
    
    // Setup artifact links
    els.linkLog.href = `/artifacts/${runId}/run.log`;
    els.linkDom.href = `/artifacts/${runId}/dom_snapshot.html`;
    
    // Reset displays
    els.diagnosisPanel.style.display = 'none';
    els.visualRegressionSection.style.display = 'none';
    els.btnViewDiff.style.display = 'none';
    
    // Check for baseline screenshot availability
    if (run.artifacts.screenshot) {
        els.visualRegressionSection.style.display = 'block';
        // Verify baseline exists for flow
        checkBaseline(run.flow_id);
    }
    
    // Load diagnosis if failure occurred
    if (run.status === 'fail') {
        fetchDiagnosis(runId);
    }
}

// Fetch Self-Healing Diagnosis
async function fetchDiagnosis(runId) {
    try {
        const res = await fetch(`/api/runs/${runId}/diagnosis`);
        const diag = await res.json();
        if (diag) {
            els.diagnosisPanel.style.display = 'block';
            els.diagErrorType.textContent = diag.error_type;
            els.diagStep.textContent = diag.affected_step;
            els.diagDesc.textContent = diag.explanation;
            els.diagAlternatives.textContent = diag.suggested_alternatives.join('\n') || 'None';
        }
    } catch (e) {
        console.error('Error fetching diagnosis:', e);
    }
}

// Check Baseline
async function checkBaseline(flowId) {
    try {
        const res = await fetch(`/api/regression/${flowId}`);
        const data = await res.json();
        if (data.status === 'active') {
            els.btnViewDiff.style.display = 'inline-flex';
        }
    } catch (e) {
        console.error('Error checking baseline:', e);
    }
}

// Set baseline screenshot
async function setBaseline() {
    if (!state.activeRunId) return;
    const run = state.runs.find(r => r.run_id === state.activeRunId);
    
    try {
        const res = await fetch('/api/regression/baseline', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                flow_id: run.flow_id,
                run_id: run.run_id
            })
        });
        
        if (res.ok) {
            showToast('Baseline screenshot set successfully!');
            checkBaseline(run.flow_id);
        }
    } catch (e) {
        showToast('Failed to set baseline.');
    }
}

// Open Visual Diff comparator modal
async function openDiffModal() {
    if (!state.activeRunId) return;
    const run = state.runs.find(r => r.run_id === state.activeRunId);
    
    try {
        const bRes = await fetch(`/api/regression/${run.flow_id}`);
        const baseline = await bRes.json();
        
        els.imgBaseline.src = baseline.baseline_path;
        els.imgCurrent.src = `/artifacts/${run.run_id}/screenshot.png`;
        els.imgDiff.src = `/artifacts/${run.run_id}/visual_diff.png`;
        
        els.diffModal.style.display = 'flex';
    } catch (e) {
        showToast('Error loading visual diff screenshots.');
    }
}
