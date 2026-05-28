// PartnerDesk Hub — minimal vanilla JS front end.

function _escape(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _fmtEdited(v) {
    // posted_date / edited_at look like "YYYY-MM-DD HH:MM:SS" — trim to minutes.
    return v ? String(v).slice(0, 16) : 'never';
}

// Cache of the latest /api/status recent_posts so the filters can re-render
// without re-fetching when the user types.
let _recentPosts = [];

function _matchesFilters(post, search, platform, status) {
    if (platform && post.platform !== platform) return false;
    if (status   && post.status   !== status)   return false;
    if (search) {
        const haystack = `${post.id} ${post.platform || ''} ${post.topic || ''} ${post.status || ''}`.toLowerCase();
        if (!haystack.includes(search.toLowerCase())) return false;
    }
    return true;
}

function _getFilteredRecentPosts() {
    const search   = document.getElementById('filter-search').value.trim();
    const platform = document.getElementById('filter-platform').value;
    const status   = document.getElementById('filter-status').value;
    return _recentPosts.filter(p => _matchesFilters(p, search, platform, status));
}

function applyRecentFilters() {
    const counter = document.getElementById('filter-count');
    const total   = _recentPosts.length;

    // No data yet — let renderRecentPosts show its empty state.
    if (total === 0) {
        counter.textContent = 'Showing 0 of 0';
        renderRecentPosts(_recentPosts);
        return;
    }

    const filtered = _getFilteredRecentPosts();
    counter.textContent = `Showing ${filtered.length} of ${total}`;

    if (filtered.length === 0) {
        document.getElementById('recent-posts').innerHTML =
            '<li class="muted">No matching Parker work.</li>';
        return;
    }
    renderRecentPosts(filtered);
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
        return (
            `<li data-id="${p.id}">` +
              `<span class="row-main">` +
                `#${p.id} ${_escape(p.platform)} — ${topic} ` +
                `<span class="status-badge status-${cls}">${_escape(p.status)}</span>` +
              `</span>` +
              `<span class="row-actions">` +
                `<button class="row-action row-approve" data-action="approve" ` +
                  `data-id="${p.id}" aria-label="Approve draft ${p.id}" ` +
                  `title="Approve">✓</button>` +
                `<button class="row-action row-reject" data-action="reject" ` +
                  `data-id="${p.id}" aria-label="Reject draft ${p.id}" ` +
                  `title="Reject">✗</button>` +
              `</span>` +
            `</li>`
        );
    }).join('');
}


// --- Draft preview modal -------------------------------------------------

let _currentPreviewId = null;

// Edit-mode toggle. Default = read-only: <pre> visible, Edit/Approve/Reject
// visible. Edit mode: <textarea> visible, Save/Cancel visible; Approve/Reject
// hidden so they can't be clicked over unsaved edits. Close stays in both.
function _setPreviewEditMode(editing) {
    document.getElementById('preview-content').style.display        = editing ? 'none' : '';
    document.getElementById('preview-content-editor').style.display = editing ? ''     : 'none';
    document.getElementById('preview-edit').style.display    = editing ? 'none' : '';
    document.getElementById('preview-save').style.display    = editing ? ''     : 'none';
    document.getElementById('preview-cancel').style.display  = editing ? ''     : 'none';
    document.getElementById('preview-approve').style.display = editing ? 'none' : '';
    document.getElementById('preview-reject').style.display  = editing ? 'none' : '';
}

function openPreview(postId) {
    _currentPreviewId = postId;
    _setPreviewEditMode(false);
    const overlay = document.getElementById('preview-overlay');
    document.getElementById('preview-platform').textContent = '…';
    document.getElementById('preview-topic').textContent = '…';
    document.getElementById('preview-status').textContent = '…';
    document.getElementById('preview-created').textContent = '…';
    document.getElementById('preview-edited').textContent = '…';
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
            document.getElementById('preview-edited').textContent = _fmtEdited(d.edited_at);
            document.getElementById('preview-content').textContent = d.content || '(empty)';
        })
        .catch(() => {
            document.getElementById('preview-content').textContent =
                'Could not load draft preview.';
        });
}

function closePreview() {
    _currentPreviewId = null;
    _setPreviewEditMode(false);
    const overlay = document.getElementById('preview-overlay');
    overlay.classList.remove('open');
    overlay.setAttribute('aria-hidden', 'true');
}

// Shared single-post status setter — used by the modal Approve/Reject buttons
// AND the per-row ✓ / ✗ buttons. Returns true on success so the caller can
// decide what to do next (the modal closes itself; the row handler doesn't).
async function _postSinglePostStatus(postId, newStatus, label) {
    setBusy(true);
    document.getElementById('cmd-status').textContent =
        `Setting post #${postId} to ${newStatus}…`;
    document.getElementById('cmd-output').textContent = '';
    try {
        const r = await fetch(`/api/posts/${encodeURIComponent(postId)}/status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus }),
        });
        if (!r.ok) {
            const errText = await r.text();
            showCmd(label, { exit_code: r.status, stdout: '', stderr: errText });
            return false;
        }
        const d = await r.json();
        const footer =
            newStatus === 'approved'
              ? 'Approval updates the local database and post history only; it does not post publicly.'
              : (newStatus === 'rejected'
                    ? 'Rejected drafts stay in the database; they will not be approved.'
                    : (newStatus === 'posted'
                          ? 'Marked as posted locally. This does not publish anything; it only updates the local SQLite status.'
                          : ''));
        const stdout = `Post #${d.id} ${d.platform} → ${d.status}\nTopic: ${d.topic}` +
                       (footer ? '\n' + footer : '');
        showCmd(label, { exit_code: 0, stdout, stderr: '' });
        return true;
    } catch (err) {
        document.getElementById('cmd-status').textContent =
            'Status update failed: ' + err;
        return false;
    } finally {
        setBusy(false);
    }
}

async function setPostStatus(newStatus) {
    if (_currentPreviewId == null) return;
    const id = _currentPreviewId;
    const ok = await _postSinglePostStatus(id, newStatus, `Set status (${newStatus})`);
    if (ok) {
        closePreview();
        await refreshAll();
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

document.getElementById('preview-edit').addEventListener('click', () => {
    // Seed the textarea with the currently displayed content so the user
    // starts from what they see, not a stale value.
    const current = document.getElementById('preview-content').textContent;
    document.getElementById('preview-content-editor').value = current;
    _setPreviewEditMode(true);
    document.getElementById('preview-content-editor').focus();
});

document.getElementById('preview-cancel').addEventListener('click', () => {
    // No revert needed — the <pre> still shows the unedited content.
    _setPreviewEditMode(false);
});

document.getElementById('preview-save').addEventListener('click', async () => {
    if (_currentPreviewId == null) return;
    const id = _currentPreviewId;
    const newContent = document.getElementById('preview-content-editor').value;
    if (!newContent.trim()) {
        document.getElementById('cmd-status').textContent =
            'Content cannot be empty.';
        return;
    }
    if (!confirm('Save changes to this draft?')) return;

    setBusy(true);
    document.getElementById('cmd-status').textContent =
        `Saving edits to post #${id}…`;
    document.getElementById('cmd-output').textContent = '';
    try {
        const r = await fetch(`/api/posts/${encodeURIComponent(id)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: newContent }),
        });
        if (!r.ok) {
            const errText = await r.text();
            showCmd(`Edit #${id}`,
                    { exit_code: r.status, stdout: '', stderr: errText });
            return;
        }
        const d = await r.json();
        // Update the displayed content and edited-at with the server's
        // response (so we reflect whatever the database actually stored).
        document.getElementById('preview-content').textContent = d.content;
        document.getElementById('preview-edited').textContent  = _fmtEdited(d.edited_at);
        showCmd(`Edit #${id}`, {
            exit_code: 0,
            stdout: `Saved edits to post #${d.id}.\n` +
                    'Editing only updates the local SQLite content field; ' +
                    'it does not approve, copy, or post publicly.',
            stderr: '',
        });
        _setPreviewEditMode(false);
        await refreshAll();
    } catch (err) {
        document.getElementById('cmd-status').textContent =
            'Save failed: ' + err;
    } finally {
        setBusy(false);
    }
});

document.getElementById('preview-close').addEventListener('click', closePreview);
document.getElementById('preview-overlay').addEventListener('click', (e) => {
    // Close when the backdrop itself is clicked, not the panel inside it.
    if (e.target.id === 'preview-overlay') closePreview();
});
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closePreview();
});

// Event delegation on #recent-posts.
// Row action buttons (✓/✗) take precedence over the row's preview click —
// clicking the button must not also open the modal.
document.getElementById('recent-posts').addEventListener('click', async (e) => {
    const action = e.target.closest('button[data-action]');
    if (action) {
        e.stopPropagation();
        const id = action.dataset.id;
        const isApprove = action.dataset.action === 'approve';
        const newStatus = isApprove ? 'approved' : 'rejected';
        const confirmMsg = isApprove
            ? `Approve draft #${id}? This does not post publicly.`
            : `Reject draft #${id}?`;
        if (!confirm(confirmMsg)) return;
        const ok = await _postSinglePostStatus(
            id, newStatus, `Row ${isApprove ? 'approve' : 'reject'} #${id}`
        );
        if (ok) await refreshAll();
        return;
    }
    const li = e.target.closest('li[data-id]');
    if (!li) return;
    openPreview(li.dataset.id);
});

// Filter inputs re-render the list using the cached data — no fetch.
document.getElementById('filter-search').addEventListener('input',  applyRecentFilters);
document.getElementById('filter-platform').addEventListener('change', applyRecentFilters);
document.getElementById('filter-status').addEventListener('change',   applyRecentFilters);

// Shared driver for the "Approve all visible" / "Reject all visible" buttons.
// `opts` carries the user-facing copy so each button can stay short.
async function _setVisibleStatus(targetStatus, opts) {
    const visible = _getFilteredRecentPosts();
    if (visible.length === 0) {
        document.getElementById('cmd-status').textContent = opts.emptyMsg;
        document.getElementById('cmd-output').textContent = '';
        return;
    }
    const prompt = opts.confirmMsg.replace('{N}', visible.length);
    if (!confirm(prompt)) return;

    setBusy(true);
    document.getElementById('cmd-status').textContent =
        `${opts.label} — ${visible.length} draft(s)…`;
    document.getElementById('cmd-output').textContent = '';
    try {
        const r = await fetch('/api/posts/batch/status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ids: visible.map(p => p.id),
                status: targetStatus,
            }),
        });
        if (!r.ok) {
            const errText = await r.text();
            showCmd(opts.label,
                    { exit_code: r.status, stdout: '', stderr: errText });
            return;
        }
        const d = await r.json();
        const lines = [
            `Updated ${d.updated_count} draft(s): [${d.updated_ids.join(', ')}]`,
        ];
        if (d.missing_count > 0) {
            lines.push(`Missing ${d.missing_count} id(s): [${d.missing_ids.join(', ')}]`);
        }
        lines.push(opts.successFooter);
        showCmd(opts.label,
                { exit_code: 0, stdout: lines.join('\n'), stderr: '' });
        await refreshAll();
    } catch (err) {
        document.getElementById('cmd-status').textContent =
            `${opts.label} failed: ` + err;
    } finally {
        setBusy(false);
    }
}

document.getElementById('approve-visible').addEventListener('click', () =>
    _setVisibleStatus('approved', {
        label:         'Approve visible',
        emptyMsg:      'No visible drafts to approve.',
        confirmMsg:    'Approve {N} visible draft(s)? This does not post publicly.',
        successFooter: 'Approval updates the local database and post history ' +
                       'only; it does not post publicly.',
    })
);

document.getElementById('reject-visible').addEventListener('click', () =>
    _setVisibleStatus('rejected', {
        label:         'Reject visible',
        emptyMsg:      'No visible drafts to reject.',
        confirmMsg:    'Reject {N} visible draft(s)? Rejected drafts stay in ' +
                       'the database but will not be approved.',
        successFooter: 'Rejected drafts stay in the database; they will not ' +
                       'be approved.',
    })
);

async function loadStatus() {
    const r = await fetch('/api/status');
    const d = await r.json();
    document.getElementById('parker-pending').textContent = d.review.pending_drafts;
    document.getElementById('parker-warnings').textContent = d.review.drafts_with_warnings;
    document.getElementById('parker-next').textContent = d.next_action;
    _recentPosts = d.recent_posts || [];
    // Re-applies whatever filters the user has set; their input values
    // are preserved across refresh because the DOM is not torn down.
    applyRecentFilters();
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

// --- Ready to Post queue -------------------------------------------------

// Approved posts come down with content so the Copy button can hand the
// body to the clipboard without an extra fetch per row.
let _readyPosts = [];

function renderReady(posts) {
    const el = document.getElementById('ready-list');
    if (!posts || posts.length === 0) {
        el.innerHTML = '<li class="muted">No approved drafts yet.</li>';
        return;
    }
    el.innerHTML = posts.map(p => {
        const topic = p.topic ? _escape(p.topic) : '(no topic)';
        const editedBadge = p.edited_at
            ? ` <span class="edited-badge" title="Last edited ${_escape(_fmtEdited(p.edited_at))}">edited</span>`
            : '';
        // Real-publish buttons are conditional per platform.
        let publishBtn = '';
        if (p.platform === 'LinkedIn') {
            publishBtn = `<button class="row-action danger" data-action="post-linkedin" ` +
                         `data-id="${p.id}">Post to LinkedIn</button>`;
        } else if (p.platform === 'Facebook') {
            publishBtn = `<button class="row-action danger" data-action="post-facebook" ` +
                         `data-id="${p.id}">Post to Facebook</button>`;
        }
        return (
            `<li data-id="${p.id}">` +
              `<span class="row-main">` +
                `#${p.id} ${_escape(p.platform)} — ${topic} ` +
                `<span class="status-badge status-approved">approved</span>` +
                editedBadge +
              `</span>` +
              `<span class="row-actions">` +
                `<button class="row-action" data-action="copy" ` +
                  `data-id="${p.id}">Copy Post Text</button>` +
                publishBtn +
                `<button class="row-action" data-action="mark-posted" ` +
                  `data-id="${p.id}">Mark Posted</button>` +
              `</span>` +
            `</li>`
        );
    }).join('');
}

async function loadReady() {
    try {
        const r = await fetch('/api/posts/ready');
        if (!r.ok) throw new Error('http ' + r.status);
        const d = await r.json();
        _readyPosts = d.items || [];
        renderReady(_readyPosts);
    } catch (err) {
        document.getElementById('ready-list').innerHTML =
            '<li class="muted">Could not load ready queue.</li>';
    }
}

document.getElementById('ready-list').addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-action]');
    if (!btn) return;
    e.stopPropagation();
    const id = btn.dataset.id;

    if (btn.dataset.action === 'copy') {
        const post = _readyPosts.find(p => String(p.id) === String(id));
        if (!post) {
            document.getElementById('cmd-status').textContent =
                'Post not found in ready cache — try Refresh Hub.';
            return;
        }
        const text = post.content || '';
        try {
            await navigator.clipboard.writeText(text);
            document.getElementById('cmd-status').textContent = 'Copied post text.';
            document.getElementById('cmd-output').textContent =
                `Copied #${post.id} ${post.platform} (${text.length} chars)\n` +
                'Copying does not post publicly. Paste it into the target ' +
                'platform when you are ready.';
        } catch (err) {
            document.getElementById('cmd-status').textContent =
                'Clipboard write failed: ' + err;
        }
        return;
    }

    if (btn.dataset.action === 'mark-posted') {
        if (!confirm('Mark this post as posted? This only updates local tracking.')) {
            return;
        }
        const ok = await _postSinglePostStatus(id, 'posted', `Mark posted #${id}`);
        if (ok) {
            document.getElementById('cmd-status').textContent =
                `Marked #${id} as posted.`;
            await refreshAll();
        }
        return;
    }

    if (btn.dataset.action === 'post-linkedin') {
        await _publishPost(id, 'linkedin', 'LinkedIn');
        return;
    }
    if (btn.dataset.action === 'post-facebook') {
        await _publishPost(id, 'facebook', 'Facebook');
        return;
    }
});

// Shared publish driver — used by Post-to-LinkedIn and Post-to-Facebook
// buttons. Identical confirm/fetch/render plumbing keeps both flows in
// one place so error handling stays consistent.
async function _publishPost(postId, platformKey, platformLabel) {
    if (!confirm(`Post this to ${platformLabel} now? This will publish publicly.`)) {
        return;
    }
    setBusy(true);
    document.getElementById('cmd-status').textContent =
        `Posting #${postId} to ${platformLabel}…`;
    document.getElementById('cmd-output').textContent = '';
    try {
        const r = await fetch(`/api/posts/${encodeURIComponent(postId)}/publish`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ platform: platformKey }),
        });
        // Validation errors return HTTPException -> {"detail": "..."}.
        // The social_posters helper returns {ok, message, ...} as 200.
        const d = await r.json();
        if (r.ok && d.ok) {
            const lines = [d.message];
            if (d.post_urn) lines.push(`LinkedIn URN: ${d.post_urn}`);
            if (d.id)       lines.push(`Post id: ${d.id}`);
            showCmd(`Publish #${postId} (${platformLabel})`,
                    { exit_code: 0, stdout: lines.join('\n'), stderr: '' });
            await refreshAll();
        } else {
            const errMsg = d.message || d.detail || `HTTP ${r.status}`;
            showCmd(`Publish #${postId} (${platformLabel})`,
                    { exit_code: r.ok ? 1 : r.status, stdout: '', stderr: errMsg });
        }
    } catch (err) {
        document.getElementById('cmd-status').textContent =
            'Publish failed: ' + err;
    } finally {
        setBusy(false);
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
            loadHistory(), loadAnalytics(), loadReady(),
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
