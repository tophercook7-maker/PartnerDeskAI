// PartnerDesk Hub — minimal vanilla JS front end.

function _escape(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderRecentPosts(posts) {
    const el = document.getElementById('recent-posts');
    if (!posts || posts.length === 0) {
        el.innerHTML = '<li class="muted">No posts yet.</li>';
        return;
    }
    // Only known statuses get colored badges; anything else falls back
    // to the draft style so a stray value never breaks rendering.
    const knownStatus = new Set(['draft', 'approved', 'rejected']);
    el.innerHTML = posts.map(p => {
        const cls = knownStatus.has(p.status) ? p.status : 'draft';
        const topic = p.topic ? _escape(p.topic) : '(no topic)';
        return `<li data-id="${p.id}">#${p.id} ${_escape(p.platform)} — ${topic}` +
               ` <span class="status-badge status-${cls}">${_escape(p.status)}</span></li>`;
    }).join('');
}


// --- Draft preview modal -------------------------------------------------

let _currentPreviewId = null;

function openPreview(postId) {
    _currentPreviewId = postId;
    const overlay = document.getElementById('preview-overlay');
    document.getElementById('preview-platform').textContent = '…';
    document.getElementById('preview-topic').textContent = '…';
    document.getElementById('preview-status').textContent = '…';
    document.getElementById('preview-created').textContent = '…';
    document.getElementById('preview-content').textContent = 'Loading…';
    overlay.classList.add('open');
    overlay.setAttribute('aria-hidden', 'false');

    fetch(`/api/posts/${encodeURIComponent(postId)}`)
        .then(r => {
            if (!r.ok) throw new Error('http ' + r.status);
            return r.json();
        })
        .then(d => {
            document.getElementById('preview-platform').textContent = d.platform;
            document.getElementById('preview-topic').textContent = d.topic || '(no topic)';
            document.getElementById('preview-status').textContent = d.status;
            document.getElementById('preview-created').textContent = d.created_at;
            document.getElementById('preview-content').textContent = d.content || '(empty)';
        })
        .catch(() => {
            document.getElementById('preview-content').textContent =
                'Could not load draft preview.';
        });
}

function closePreview() {
    _currentPreviewId = null;
    const overlay = document.getElementById('preview-overlay');
    overlay.classList.remove('open');
    overlay.setAttribute('aria-hidden', 'true');
}

async function setPostStatus(newStatus) {
    if (_currentPreviewId == null) return;
    const id = _currentPreviewId;
    setBusy(true);
    document.getElementById('cmd-status').textContent =
        `Setting post #${id} to ${newStatus}…`;
    document.getElementById('cmd-output').textContent = '';
    try {
        const r = await fetch(`/api/posts/${encodeURIComponent(id)}/status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus }),
        });
        if (!r.ok) {
            const errText = await r.text();
            showCmd(`Set status (${newStatus})`,
                    { exit_code: r.status, stdout: '', stderr: errText });
            return;
        }
        const d = await r.json();
        showCmd(`Set status (${newStatus})`, {
            exit_code: 0,
            stdout: `Post #${d.id} ${d.platform} → ${d.status}\nTopic: ${d.topic}\n` +
                    `Approval updates the local database and post history only; ` +
                    `it does not post publicly.`,
            stderr: '',
        });
        closePreview();
        await refreshAll();
    } catch (err) {
        document.getElementById('cmd-status').textContent =
            'Status update failed: ' + err;
    } finally {
        setBusy(false);
    }
}

document.getElementById('preview-approve').addEventListener('click', () => {
    if (!confirm('Approve this draft? This does not post it publicly.')) return;
    setPostStatus('approved');
});

document.getElementById('preview-reject').addEventListener('click', () => {
    if (!confirm('Reject this draft?')) return;
    setPostStatus('rejected');
});

document.getElementById('preview-close').addEventListener('click', closePreview);
document.getElementById('preview-overlay').addEventListener('click', (e) => {
    // Close when the backdrop itself is clicked, not the panel inside it.
    if (e.target.id === 'preview-overlay') closePreview();
});
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closePreview();
});

// Event delegation: any <li data-id="…"> inside #recent-posts opens preview.
document.getElementById('recent-posts').addEventListener('click', (e) => {
    const li = e.target.closest('li[data-id]');
    if (!li) return;
    openPreview(li.dataset.id);
});

async function loadStatus() {
    const r = await fetch('/api/status');
    const d = await r.json();
    document.getElementById('parker-pending').textContent = d.review.pending_drafts;
    document.getElementById('parker-warnings').textContent = d.review.drafts_with_warnings;
    document.getElementById('parker-next').textContent = d.next_action;
    renderRecentPosts(d.recent_posts || []);
}

async function loadSummary() {
    const r = await fetch('/api/summary');
    const d = await r.json();
    document.getElementById('summary-meta').textContent =
        d.exists ? `summaries/${d.date}.md` : `No summary for ${d.date}`;
    document.getElementById('summary').textContent = d.content;
}

function renderApprovedHistory(items) {
    const el = document.getElementById('approved-history');
    if (!items || items.length === 0) {
        el.innerHTML = '<li class="muted">No approved history yet.</li>';
        return;
    }
    el.innerHTML = items.map(h => {
        // posted_date is "YYYY-MM-DD HH:MM:SS" — show just the date portion.
        const date = (h.posted_date || '').slice(0, 10);
        return `<li>${_escape(h.platform)} — ${_escape(h.topic)} — ${_escape(date)}</li>`;
    }).join('');
}

async function loadHistory() {
    try {
        const r = await fetch('/api/history?limit=20');
        if (!r.ok) throw new Error('http ' + r.status);
        const d = await r.json();
        renderApprovedHistory(d.items || []);
    } catch (err) {
        document.getElementById('approved-history').innerHTML =
            '<li class="muted">Could not load history.</li>';
    }
}

function _renderCountList(elId, items, primaryKey) {
    const el = document.getElementById(elId);
    if (!items || items.length === 0) {
        el.innerHTML = '<li class="muted">none</li>';
        return;
    }
    el.innerHTML = items.map(i =>
        `<li>${_escape(i[primaryKey])} — ${i.count}</li>`
    ).join('');
}

function renderAnalytics(d) {
    const empty = document.getElementById('analytics-empty');
    const body = document.getElementById('analytics-body');
    if (!d || !d.total) {
        empty.style.display = '';
        body.style.display = 'none';
        return;
    }
    empty.style.display = 'none';
    body.style.display = '';
    document.getElementById('analytics-meta').textContent =
        `Last ${d.days} days — ${d.total} approved`;

    _renderCountList('analytics-topics',    d.by_topic,    'topic');
    _renderCountList('analytics-platforms', d.by_platform, 'platform');

    const combos = document.getElementById('analytics-combos');
    if (!d.by_topic_platform || d.by_topic_platform.length === 0) {
        combos.innerHTML = '<li class="muted">none</li>';
    } else {
        combos.innerHTML = d.by_topic_platform.map(i =>
            `<li>${_escape(i.topic)} — ${_escape(i.platform)} — ${i.count}</li>`
        ).join('');
    }
}

async function loadAnalytics() {
    try {
        const r = await fetch('/api/history/analytics?days=30');
        if (!r.ok) throw new Error('http ' + r.status);
        const d = await r.json();
        renderAnalytics(d);
    } catch (err) {
        document.getElementById('analytics-meta').textContent =
            'Could not load analytics.';
    }
}

async function loadLogs() {
    const r = await fetch('/api/logs/latest');
    const d = await r.json();
    if (d.path) {
        document.getElementById('log-path').textContent =
            `${d.path} (modified ${d.modified})`;
        document.getElementById('log-tail').textContent = d.lines.join('\n');
    } else {
        document.getElementById('log-path').textContent = d.message || '';
        document.getElementById('log-tail').textContent = '';
    }
}

async function refreshAll() {
    document.getElementById('cmd-status').textContent = 'Reloading…';
    try {
        await Promise.all([
            loadStatus(), loadSummary(), loadLogs(),
            loadHistory(), loadAnalytics(),
        ]);
        document.getElementById('cmd-status').textContent = 'Hub refreshed.';
    } catch (err) {
        document.getElementById('cmd-status').textContent = 'Refresh failed: ' + err;
    }
}

function setBusy(busy) {
    document.querySelectorAll('button').forEach(b => b.disabled = busy);
}

function showCmd(label, data) {
    document.getElementById('cmd-status').textContent =
        `${label} — exit ${data.exit_code}`;
    let out = '';
    if (data.stdout) out += '=== stdout ===\n' + data.stdout;
    if (data.stderr) out += (out ? '\n' : '') + '=== stderr ===\n' + data.stderr;
    document.getElementById('cmd-output').textContent = out;
}

document.getElementById('btn-refresh').addEventListener('click', refreshAll);

document.getElementById('btn-run').addEventListener('click', async () => {
    if (!confirm('This will call OpenAI and generate new drafts. Continue?')) return;
    setBusy(true);
    document.getElementById('cmd-status').textContent =
        'Running daily ops (this may take ~10 seconds)…';
    document.getElementById('cmd-output').textContent = '';
    try {
        const r = await fetch('/api/run/daily-ops', { method: 'POST' });
        const d = await r.json();
        showCmd('Run Daily Ops', d);
        await refreshAll();
    } catch (err) {
        document.getElementById('cmd-status').textContent = 'Run failed: ' + err;
    } finally {
        setBusy(false);
    }
});

document.getElementById('btn-skip').addEventListener('click', async () => {
    setBusy(true);
    document.getElementById('cmd-status').textContent =
        'Refreshing summary and snapshot (no OpenAI call)…';
    document.getElementById('cmd-output').textContent = '';
    try {
        const r = await fetch('/api/run/refresh', { method: 'POST' });
        const d = await r.json();
        showCmd('Refresh Summary Only', d);
        await refreshAll();
    } catch (err) {
        document.getElementById('cmd-status').textContent = 'Refresh failed: ' + err;
    } finally {
        setBusy(false);
    }
});

// Initial load on page open.
refreshAll();
