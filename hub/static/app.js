// PartnerDesk Hub — minimal vanilla JS front end.

function _escape(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _fmtEdited(v) {
    // posted_date / edited_at look like "YYYY-MM-DD HH:MM:SS" — trim to minutes.
    return v ? String(v).slice(0, 16) : 'never';
}


// --- Mission Control (v5.1) ----------------------------------------------

// Latest payloads from /api/status and /api/partners. Populated by the
// existing loaders so renderMissionControl doesn't re-fetch.
let _lastStatus = null;
let _lastPartners = null;

function _computeMood(status, readyCount) {
    // Priority matches the spec — first matching rule wins.
    if (status && status.health && status.health.status !== 'PASS') {
        return { label: 'Needs attention', cls: 'mood-red' };
    }
    if (status && status.review && status.review.pending_drafts > 0) {
        return { label: 'Needs review', cls: 'mood-yellow' };
    }
    if (readyCount > 0) {
        return { label: 'Ready to publish', cls: 'mood-green' };
    }
    return { label: 'Ready', cls: 'mood-green' };
}

function _statCard(label, value, opts = {}) {
    // opts: { target: 'recent-posts' | 'ready-list' | 'connections-list',
    //         filter: 'status=draft' (or undefined) }
    // Cards with a target render as interactive buttons that scroll
    // (and optionally apply a filter). Cards without one render as
    // plain stats.
    const interactive = !!opts.target;
    const attrs = interactive
        ? ` class="stat-card stat-card-clickable" role="button" tabindex="0"` +
          ` data-mc-target="${_escape(opts.target)}"` +
          (opts.filter ? ` data-mc-filter="${_escape(opts.filter)}"` : '') +
          ` title="Jump to this section"`
        : ` class="stat-card"`;
    return (
        `<div${attrs}>` +
          `<div class="stat-value">${_escape(String(value))}</div>` +
          `<div class="stat-label">${_escape(label)}</div>` +
        `</div>`
    );
}

function _scrollToSection(innerElementId) {
    // Find the inner anchor (a list / ul we already know exists) and
    // scroll its enclosing <section> into view so the section title is
    // visible too. Falls back to the inner element if no section.
    const inner = document.getElementById(innerElementId);
    if (!inner) return;
    const target = inner.closest('section') || inner;
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function _applyMissionControlFilter(filterSpec) {
    // Currently supports a single "key=value" pair targeting the Recent
    // Parker Work filter row. Cleanly extensible if more filter targets
    // get added later.
    if (!filterSpec) return;
    const [key, value] = filterSpec.split('=');
    if (key === 'status') {
        const el = document.getElementById('filter-status');
        if (el) {
            el.value = value || '';
            applyRecentFilters();
        }
    } else if (key === 'platform') {
        const el = document.getElementById('filter-platform');
        if (el) {
            el.value = value || '';
            applyRecentFilters();
        }
    }
}

function _partnerBadgeClass(status) {
    if (status === 'active')  return 'active';
    if (status === 'standby') return 'standby';
    return 'offline';
}

function renderMissionControl() {
    const el = document.getElementById('mission-control');
    if (!el) return;
    // Don't render until we have at least the status payload — otherwise
    // we'd show "0 / 0" and a misleading mood.
    if (!_lastStatus) return;

    const todaysDrafts = (_lastStatus.today && _lastStatus.today.markdown_files) || 0;
    const pending      = (_lastStatus.review && _lastStatus.review.pending_drafts) || 0;
    const readyCount   = _readyPosts.length;
    const conns        = Object.values(_connectionsByPlatform || {});
    const totalConns   = conns.length;
    const verified     = conns.filter(c => c.status === 'verified').length;
    const partners     = _lastPartners || [];
    const mood         = _computeMood(_lastStatus, readyCount);

    const statsHtml = (
        `<div class="mission-stats">` +
          // Today's Drafts -> all recent Parker work, no filter (newest
          // rows are today's anyway since the list is sorted DESC).
          _statCard("Today's Drafts", todaysDrafts,
                    { target: 'recent-posts' }) +
          // Pending Review -> Recent Parker Work + auto-set the status
          // dropdown to "draft" so the visible list matches the count.
          _statCard('Pending Review', pending,
                    { target: 'recent-posts', filter: 'status=draft' }) +
          // Ready to Post -> the dedicated approved queue card.
          _statCard('Ready to Post', readyCount,
                    { target: 'ready-list' }) +
          // Connections Verified -> the connections card so the user
          // can hit Verify on whichever platform isn't green.
          _statCard('Connections Verified', `${verified} / ${totalConns}`,
                    { target: 'connections-list' }) +
        `</div>`
    );

    const stripHtml = partners.length
        ? `<div class="mission-partner-strip">` +
            partners.map(p => {
                const label = p.status[0].toUpperCase() + p.status.slice(1);
                const cls   = _partnerBadgeClass(p.status);
                return (
                    `<span class="partner-strip-item">` +
                      `<strong>${_escape(p.name)}:</strong>` +
                      ` <span class="partner-strip-badge ${cls}">${_escape(label)}</span>` +
                    `</span>`
                );
            }).join('') +
          `</div>`
        : '';

    const moodHtml = (
        `<div class="mission-mood">` +
          `<strong>System Mood:</strong> ` +
          `<span class="${mood.cls}">${_escape(mood.label)}</span>` +
        `</div>`
    );

    // Quick Actions bar — six in-page command buttons. Run Daily Ops
    // and Refresh Summary delegate to the existing top-row buttons so
    // there's only one code path per action.
    const actionsHtml = (
        `<div class="mission-actions">` +
          `<button class="mission-action-btn danger" data-mc-action="run-daily-ops">Run Daily Ops</button>` +
          `<button class="mission-action-btn primary" data-mc-action="refresh-hub">Refresh Hub</button>` +
          `<button class="mission-action-btn" data-mc-action="refresh-summary">Refresh Summary</button>` +
          `<button class="mission-action-btn" data-mc-action="verify-connections">Verify Connections</button>` +
          `<button class="mission-action-btn" data-mc-action="review-drafts">Review Drafts</button>` +
          `<button class="mission-action-btn" data-mc-action="ready-to-post">Ready to Post</button>` +
        `</div>`
    );

    el.innerHTML = statsHtml + stripHtml + moodHtml + actionsHtml;
}

// Delegated click + keyboard handlers for Mission Control. Bound once
// at module load (#mission-control exists in the static template).
// Two interaction types live here:
//   data-mc-target  -> stat cards (navigate / filter, v5.1)
//   data-mc-action  -> quick-action buttons (v5.2)

function _missionControlActivate(target, filter) {
    if (filter) _applyMissionControlFilter(filter);
    _scrollToSection(target);
}

function _missionControlAction(action) {
    // v5.36: call the named action functions directly. Previously
    // these synthesized clicks on top-row buttons (now retired);
    // the underlying logic lives in runDailyOps / refreshAll /
    // refreshSummaryOnly as the canonical handlers.
    if (action === 'run-daily-ops') { runDailyOps(); return; }
    if (action === 'refresh-hub')   { refreshAll(); return; }
    if (action === 'refresh-summary') { refreshSummaryOnly(); return; }
    if (action === 'verify-connections') {
        _scrollToSection('connections-list');
        return;
    }
    if (action === 'review-drafts') {
        _applyMissionControlFilter('status=draft');
        _scrollToSection('recent-posts');
        return;
    }
    if (action === 'ready-to-post') {
        _scrollToSection('ready-list');
        return;
    }
}

document.getElementById('mission-control').addEventListener('click', (e) => {
    const card = e.target.closest('[data-mc-target]');
    if (card) {
        _missionControlActivate(card.dataset.mcTarget, card.dataset.mcFilter);
        return;
    }
    const btn = e.target.closest('[data-mc-action]');
    if (btn) {
        _missionControlAction(btn.dataset.mcAction);
    }
});
document.getElementById('mission-control').addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const card = e.target.closest('[data-mc-target]');
    if (card) {
        e.preventDefault();
        _missionControlActivate(card.dataset.mcTarget, card.dataset.mcFilter);
        return;
    }
    // <button> elements activate on Enter/Space natively, so we don't
    // need to handle data-mc-action here — the click event fires for us.
});

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
        // v6.3: if a posted row has a public URL, show a small
        // "Posted →" receipt link inline (target=_blank, noopener).
        const postedLink = (p.status === 'posted' && p.published_url)
            ? ` <a class="posted-link" href="${_escape(p.published_url)}" `
              + `target="_blank" rel="noopener noreferrer" `
              + `title="View the published post">Posted →</a>`
            : '';
        return (
            `<li data-id="${p.id}">` +
              `<span class="row-main">` +
                `#${p.id} ${_escape(p.platform)} — ${topic} ` +
                `<span class="status-badge status-${cls}">${_escape(p.status)}</span>` +
                postedLink +
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
    // v6.3: hide receipt section by default — only shown if the post
    // has been published AND the API returned receipt fields.
    document.getElementById('preview-receipt').hidden = true;
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
            _renderPreviewReceipt(d);
        })
        .catch(() => {
            document.getElementById('preview-content').textContent =
                'Could not load draft preview.';
        });
}

// v6.3: populate the receipt section if the post has been published.
// Hidden if no receipt data — we never invent fake receipts. The URL
// link is opened with target=_blank rel=noopener so the published
// content can't tamper with the Hub tab.
function _renderPreviewReceipt(d) {
    const receipt = document.getElementById('preview-receipt');
    const hasReceipt = d && d.status === 'posted'
        && (d.published_url || d.published_external_id || d.posted_at);
    if (!hasReceipt) { receipt.hidden = true; return; }
    document.getElementById('preview-posted-at').textContent =
        d.posted_at || '(unknown)';
    document.getElementById('preview-posted-id').textContent =
        d.published_external_id || '(not returned)';
    const a = document.getElementById('preview-posted-url');
    if (d.published_url) {
        a.href = d.published_url;
        a.textContent = d.published_url;
        a.style.display = '';
    } else {
        a.removeAttribute('href');
        a.textContent = '(not available)';
        a.style.display = '';
    }
    document.getElementById('preview-posted-summary').textContent =
        d.published_response_summary || '(none)';
    receipt.hidden = false;
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

// --- Partner Rooms (v4.3) -----------------------------------------------

// Human-readable labels for metric keys. Falls back to a humanized key
// if a future metric isn't listed here, so adding a metric on the
// backend doesn't break rendering.
const _METRIC_LABELS = {
    pending:             'Pending drafts',
    approved:            'Approved',
    posted:              'Posted',
    prospects_tracked:   'Prospects tracked',
    outreach_queue:      'Outreach queue',
    summaries_generated: 'Summaries generated',
    snapshots_archived:  'Snapshots archived',
};

function _humanMetric(key) {
    return _METRIC_LABELS[key] || key.replace(/_/g, ' ');
}

function _partnerInitials(name) {
    return name.split(/\s+/).map(w => w[0] || '').join('').slice(0, 2).toUpperCase();
}

function renderPartners(partners) {
    const el = document.getElementById('partner-rooms');
    if (!partners || partners.length === 0) {
        el.innerHTML = '<div class="muted">No partners.</div>';
        return;
    }
    el.innerHTML = partners.map(p => {
        const statusClass = p.status === 'active'
            ? 'partner-status-active'
            : 'partner-status-standby';
        const statusLabel = p.status[0].toUpperCase() + p.status.slice(1);

        // Metrics grid — each partner exposes its own keys.
        const metricsHtml = Object.entries(p.metrics || {}).map(([k, v]) => {
            // Parker's pending/approved/posted get id hooks so loadStatus
            // and refresh paths can update them in place.
            let valHtml = String(v);
            if (p.key === 'parker') {
                if (k === 'pending')  valHtml = `<span id="parker-pending">${v}</span>`;
                if (k === 'approved') valHtml = `<span id="parker-approved">${v}</span>`;
                if (k === 'posted')   valHtml = `<span id="parker-posted">${v}</span>`;
            }
            return `<div><strong>${_escape(_humanMetric(k))}:</strong> ${valHtml}</div>`;
        }).join('');

        const nextHtml = p.key === 'parker'
            ? `<div class="partner-next"><strong>Next:</strong>` +
              `<pre id="parker-next">…</pre></div>`
            : '';

        const actionsHtml = p.key === 'parker'
            ? `<div class="partner-actions">` +
                `<button data-partner-action="parker-refresh">Refresh</button>` +
                `<button data-partner-action="parker-view-drafts">View drafts</button>` +
              `</div>`
            : `<div class="partner-actions">` +
                `<button disabled>Coming Soon</button>` +
              `</div>`;

        return (
            `<div class="partner-room ${_escape(p.key)}">` +
              `<div class="partner-header">` +
                `<div class="partner-avatar">${_escape(_partnerInitials(p.name))}</div>` +
                `<div>` +
                  `<h3>${_escape(p.name)}</h3>` +
                  `<div class="partner-status ${statusClass}">${_escape(statusLabel)}</div>` +
                `</div>` +
              `</div>` +
              `<div class="partner-role">${_escape(p.role || '')}</div>` +
              `<div class="partner-metrics">${metricsHtml}</div>` +
              nextHtml +
              actionsHtml +
            `</div>`
        );
    }).join('');
}

async function loadPartners() {
    try {
        const r = await fetch('/api/partners');
        if (!r.ok) throw new Error('http ' + r.status);
        const d = await r.json();
        _lastPartners = d.partners || [];  // Mission Control reads this
        renderPartners(_lastPartners);
    } catch (err) {
        document.getElementById('partner-rooms').innerHTML =
            '<div class="muted">Could not load partners.</div>';
    }
}

// Delegate Parker's room buttons. Logan/Olivia buttons are disabled.
document.getElementById('partner-rooms').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-partner-action]');
    if (!btn) return;
    const action = btn.dataset.partnerAction;
    if (action === 'parker-refresh') {
        refreshAll();
    } else if (action === 'parker-view-drafts') {
        const target = document.getElementById('recent-posts');
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
});

async function loadStatus() {
    const r = await fetch('/api/status');
    const d = await r.json();
    _lastStatus = d;  // Mission Control reads this cached payload
    // Parker's pending count & next action live in the partner room now;
    // update them in-place when they exist (post-loadPartners render).
    const pending = document.getElementById('parker-pending');
    if (pending) pending.textContent = d.review.pending_drafts;
    const next = document.getElementById('parker-next');
    if (next) next.textContent = d.next_action;
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

// --- System Activity feed (v5.3) ----------------------------------------

const _ACTIVITY_ICONS = {
    generation: '✨',
    approval:   '✓',
    publish:    '📤',
    refresh:    '🔄',
    connection: '🔗',
    system:     '⚙',
};

// Type-filter chip taxonomy (v5.5). Order matches the chip row left-to-
// right; "all" is always first and always enabled. Keep in sync with
// _ACTIVITY_ICONS — chips show one row per known type so the user can
// see categories even before any event of that type exists.
const _ACTIVITY_TYPES = [
    'all', 'generation', 'approval', 'connection', 'publish', 'refresh', 'system',
];
const _ACTIVITY_TYPE_LABELS = {
    all:        'All',
    generation: 'Generation',
    approval:   'Approval',
    connection: 'Connection',
    publish:    'Publish',
    refresh:    'Refresh',
    system:     'System',
};

// Client-side cache of the most recent /api/activity response and the
// user's current filter selection. Chip clicks re-render from this
// cache — no refetch — so filtering is instant and doesn't generate
// extra server load.
let _activityItems  = [];

// Persist the chip selection in localStorage (v5.7) so the user's
// filter survives page reloads. Validated against _ACTIVITY_TYPES on
// read so a stale or unknown value just falls back to "all". Wrapped
// in try/catch because localStorage throws in private-browsing mode
// and when storage quotas are hit.
const _ACTIVITY_FILTER_KEY = 'partnerdesk.activityFilter';

function _readPersistedActivityFilter() {
    try {
        const saved = localStorage.getItem(_ACTIVITY_FILTER_KEY);
        if (saved && _ACTIVITY_TYPES.includes(saved)) return saved;
    } catch (e) { /* storage blocked — fall through to default */ }
    return 'all';
}

function _writePersistedActivityFilter(value) {
    try { localStorage.setItem(_ACTIVITY_FILTER_KEY, value); }
    catch (e) { /* storage blocked — filter still works in-memory */ }
}

let _activityFilter = _readPersistedActivityFilter();

function _filteredActivityItems() {
    if (_activityFilter === 'all') return _activityItems;
    return _activityItems.filter(it => (it.type || 'system') === _activityFilter);
}

function _renderActivityFilters() {
    const el = document.getElementById('activity-filters');
    if (!el) return;
    // Per-type counts off the cached items. "all" gets the total.
    const counts = { all: _activityItems.length };
    for (const it of _activityItems) {
        const t = it.type || 'system';
        counts[t] = (counts[t] || 0) + 1;
    }
    el.innerHTML = _ACTIVITY_TYPES.map(t => {
        const n      = counts[t] || 0;
        const active = (t === _activityFilter);
        const empty  = (t !== 'all' && n === 0);
        const cls    = ['activity-chip'];
        if (active) cls.push('active');
        if (empty)  cls.push('empty');
        // v5.9: show a "×" shortcut on the active non-"all" chip so the
        // user can reset the filter in one click. Rendered as a <span>
        // (not a nested <button>) to keep HTML valid; the click
        // delegator catches it via closest('.activity-chip-clear').
        const showClear = active && t !== 'all';
        const clearHTML = showClear
            ? `<span class="activity-chip-clear" aria-hidden="true" ` +
              `title="Clear filter (back to All)">×</span>`
            : '';
        return (
            `<button type="button" class="${cls.join(' ')}" ` +
              `data-activity-type="${_escape(t)}"` +
              (empty ? ' disabled aria-disabled="true"' : '') +
              (active ? ' aria-pressed="true"' : ' aria-pressed="false"') +
            `>` +
              _escape(_ACTIVITY_TYPE_LABELS[t] || t) +
              `<span class="activity-chip-count">(${n})</span>` +
              clearHTML +
            `</button>`
        );
    }).join('');
}

function _activityDateLabel(dateStr) {
    // "YYYY-MM-DD" -> "May 27". Built locally (no toLocaleDateString
    // surprises) and timezone-agnostic since we never touch hours.
    const months = ['Jan','Feb','Mar','Apr','May','Jun',
                    'Jul','Aug','Sep','Oct','Nov','Dec'];
    const parts = (dateStr || '').split('-');
    if (parts.length !== 3) return dateStr || '';
    const m = parseInt(parts[1], 10);
    const d = parseInt(parts[2], 10);
    if (!m || !d || m < 1 || m > 12) return dateStr;
    return `${months[m - 1]} ${d}`;
}

function renderActivity(items) {
    const el = document.getElementById('activity-feed');
    if (!items || items.length === 0) {
        // Distinguish "no events at all" from "filter excluded them all"
        // so the user understands why the feed appears empty after a
        // chip click.
        const empty = (_activityFilter === 'all' || _activityItems.length === 0)
            ? 'No recent activity yet.'
            : `No ${_ACTIVITY_TYPE_LABELS[_activityFilter] || _activityFilter} ` +
              `events in the recent activity.`;
        el.innerHTML = `<li class="muted">${_escape(empty)}</li>`;
        return;
    }
    // Compare against the user's local today. The server already
    // formats display_time for the server-side today, but a divider
    // anchored to local date keeps the UI honest if the two ever drift.
    const now = new Date();
    const todayStr = `${now.getFullYear()}-` +
                     `${String(now.getMonth() + 1).padStart(2, '0')}-` +
                     `${String(now.getDate()).padStart(2, '0')}`;

    const parts = [];
    let lastDate = null;
    for (const it of items) {
        // Emit a day divider when the date changes — but skip it for
        // today, since bare "HH:MM" rows already imply "today".
        if (it.date && it.date !== lastDate && it.date !== todayStr) {
            parts.push(
                `<li class="activity-divider">— ${_escape(_activityDateLabel(it.date))} —</li>`
            );
        }
        lastDate = it.date || lastDate;

        const icon = _ACTIVITY_ICONS[it.type] || _ACTIVITY_ICONS.system;
        const typeClass = `activity-type-${_escape(it.type || 'system')}`;
        const timeStr = it.display_time || it.time || '';
        // v6.3: publish events with a known public URL get a "View →"
        // link suffix. The URL is rendered with rel="noopener noreferrer"
        // and target="_blank" so opening it can't tamper with the Hub.
        const linkSuffix = it.url
            ? ` <a class="activity-link" href="${_escape(it.url)}" `
              + `target="_blank" rel="noopener noreferrer">View →</a>`
            : '';
        parts.push(
            `<li class="${typeClass}">` +
              `<span class="activity-time">${_escape(timeStr)}</span>` +
              `<span class="activity-icon">${_escape(icon)}</span>` +
              `<span class="activity-message">${_escape(it.message || '')}${linkSuffix}</span>` +
            `</li>`
        );
    }
    el.innerHTML = parts.join('');
}

async function loadActivity() {
    try {
        const r = await fetch('/api/activity');
        if (!r.ok) throw new Error('http ' + r.status);
        const d = await r.json();
        _activityItems = d.items || [];
        _renderActivityFilters();
        renderActivity(_filteredActivityItems());
    } catch (err) {
        _activityItems = [];
        _renderActivityFilters();
        document.getElementById('activity-feed').innerHTML =
            '<li class="muted">Could not load activity.</li>';
    }
}

// --- Report Center (v5.12) ----------------------------------------------
// Read-only panel surfacing /api/history/analytics with a window
// selector (7/30/90/365 days) and proportional bars per row.

function _renderReportList(items, labeller) {
    // `labeller` may be either a key string (e.g. 'topic') or a
    // function (item) => string. Function form (v5.14) lets the
    // combos card build a compound "topic · platform" label without
    // a second helper.
    if (!items || items.length === 0) {
        return '<li class="muted">No data in this window.</li>';
    }
    const max    = Math.max(...items.map(it => it.count || 0)) || 1;
    const labelOf = typeof labeller === 'function'
        ? labeller
        : (it) => it[labeller];
    return items.map(it => {
        const count = it.count || 0;
        const pct   = Math.round((count / max) * 100);
        const label = labelOf(it) || '(unknown)';
        return (
            `<li style="--bar-width: ${pct}%">` +
              `<span class="label" title="${_escape(label)}">${_escape(label)}</span>` +
              `<span class="count">${count}</span>` +
            `</li>`
        );
    }).join('');
}

function renderReports(data) {
    const headlineEl  = document.getElementById('reports-headline');
    const topicsEl    = document.getElementById('reports-topics');
    const platformsEl = document.getElementById('reports-platforms');
    const combosEl    = document.getElementById('reports-combos');
    if (!data) {
        headlineEl.textContent = 'Could not load reports.';
        headlineEl.classList.add('muted');
        topicsEl.innerHTML    = '<li class="muted">—</li>';
        platformsEl.innerHTML = '<li class="muted">—</li>';
        combosEl.innerHTML    = '<li class="muted">—</li>';
        return;
    }
    const n    = data.total || 0;
    const days = data.days  || 30;
    const noun = n === 1 ? 'approval' : 'approvals';
    const dnoun = days === 1 ? 'day' : 'days';
    headlineEl.textContent = `${n} ${noun} in the last ${days} ${dnoun}`;
    headlineEl.classList.remove('muted');
    topicsEl.innerHTML    = _renderReportList(data.by_topic    || [], 'topic');
    platformsEl.innerHTML = _renderReportList(data.by_platform || [], 'platform');
    combosEl.innerHTML    = _renderReportList(
        data.by_topic_platform || [],
        (it) => `${it.topic || '?'} · ${it.platform || '?'}`,
    );
}

async function loadReports(daysOverride) {
    const select = document.getElementById('reports-days');
    const days   = daysOverride
        || parseInt((select && select.value) || '30', 10)
        || 30;
    try {
        const r = await fetch(`/api/history/analytics?days=${days}`);
        if (!r.ok) throw new Error('http ' + r.status);
        renderReports(await r.json());
    } catch (err) {
        renderReports(null);
    }
}

// Window selector: re-fetch on change (cheap — analytics endpoint is
// already query-only and won't trigger any side effects).
const _reportsSelect = document.getElementById('reports-days');
if (_reportsSelect) {
    _reportsSelect.addEventListener('change', () => loadReports());
}

// --- Report Inbox (v5.15) -----------------------------------------------
// Read-only browser for daily reports written by daily_report.py.
// The list shows file metadata only (name, date, size, mtime); contents
// are fetched on demand when a row is clicked.

let _inboxItems = [];
let _inboxSelected = null;  // currently displayed report filename
let _inboxContent  = '';    // cached raw markdown of the displayed report
                             // (v5.17 — backs the download button without
                             // a refetch on click)

// v5.27: persist the currently-selected report name so reload returns
// the user to the same report. Validated against the strict report-name
// regex so a stale or malformed value can't trigger a fetch of an
// invalid filename. Storage-blocked-safe via try/catch.
const _INBOX_SELECTED_KEY = 'partnerdesk.inboxSelected';
const _INBOX_NAME_RE = /^\d{4}-\d{2}-\d{2}\.md$/;

function _readPersistedInboxSelected() {
    try {
        const saved = localStorage.getItem(_INBOX_SELECTED_KEY);
        if (saved && _INBOX_NAME_RE.test(saved)) return saved;
    } catch (e) { /* storage blocked */ }
    return null;
}
function _writePersistedInboxSelected(name) {
    try {
        if (name) localStorage.setItem(_INBOX_SELECTED_KEY, name);
        else      localStorage.removeItem(_INBOX_SELECTED_KEY);
    } catch (e) { /* storage blocked */ }
}

// v5.28: auto-scroll the most important row into view once per page
// lifetime so the inbox stays usable as the report archive grows.
// Priority is selected → today → first row. The flag prevents
// subsequent renders (refresh, filter change, chip click) from
// fighting the user's scroll position.
let _inboxAutoScrollDone = false;

// v5.29: keyboard navigation. _inboxFocusedIdx is an index into the
// CURRENT filtered items array; -1 means no focus. Visual: `focused`
// class on the matching <li>. Set on click and on ↑/↓; cleared on
// Esc; consumed by Enter to load the focused report.
let _inboxFocusedIdx = -1;

function _autoScrollInboxOnce() {
    if (_inboxAutoScrollDone) return;
    const list = document.getElementById('inbox-list');
    if (!list) return;
    const target = list.querySelector('li.selected')
                || list.querySelector('li.today')
                || list.querySelector('li[data-report]');
    if (!target) return;
    target.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    _inboxAutoScrollDone = true;
}

// v5.32: focus the inbox list once per page lifetime so ↓/j/k work
// immediately without needing to click into the list first. Two safety
// guards: only fire once, and only when nothing else has focus (the
// user might have already clicked into another input). preventScroll
// keeps the focus action from clobbering v5.28's smooth scroll.
let _inboxAutoFocusDone = false;

function _autoFocusInboxOnce() {
    if (_inboxAutoFocusDone) return;
    const ae = document.activeElement;
    if (ae && ae !== document.body) return;
    const list = document.getElementById('inbox-list');
    if (!list) return;
    list.focus({ preventScroll: true });
    _inboxAutoFocusDone = true;
}
// Filter state (v5.18). Pure client-side filter over _inboxItems; no
// refetch on input change. Persisted only in-memory — survives within
// a session but resets on reload (intentional: filters scoped to the
// current visit, not a long-term preference).
let _inboxSearch = '';
let _inboxWindow = 'all';
let _inboxHideEmpty = false;  // v5.20

// v5.21: persist the three inbox filters across page reloads. Validated
// per-field on read so a stale or malformed value just falls back to
// the default. Wrapped in try/catch because localStorage throws in
// private-browsing mode and when storage quotas are hit.
const _INBOX_FILTERS_KEY = 'partnerdesk.inboxFilters';
const _INBOX_WINDOW_VALUES = ['all', '7', '30', '90'];

function _readPersistedInboxFilters() {
    try {
        const raw = localStorage.getItem(_INBOX_FILTERS_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object') return null;
        const out = {};
        if (typeof parsed.search === 'string') out.search = parsed.search;
        if (_INBOX_WINDOW_VALUES.includes(parsed.window)) out.window = parsed.window;
        if (typeof parsed.hideEmpty === 'boolean') out.hideEmpty = parsed.hideEmpty;
        return out;
    } catch (e) { return null; }
}

function _writePersistedInboxFilters() {
    try {
        localStorage.setItem(_INBOX_FILTERS_KEY, JSON.stringify({
            search:    _inboxSearch,
            window:    _inboxWindow,
            hideEmpty: _inboxHideEmpty,
        }));
    } catch (e) { /* storage blocked — filters still work in-memory */ }
}

function _clearPersistedInboxFilters() {
    try { localStorage.removeItem(_INBOX_FILTERS_KEY); }
    catch (e) { /* storage blocked */ }
}

// v5.24: Clear-filters button is only useful when at least one filter
// differs from the defaults. Hiding it when nothing's active keeps the
// filter row visually quiet.
function _isInboxFiltersAtDefault() {
    return _inboxSearch === ''
        && _inboxWindow === 'all'
        && _inboxHideEmpty === false;
}
function _updateClearButtonVisibility() {
    const btn = document.getElementById('inbox-clear');
    if (!btn) return;
    btn.hidden = _isInboxFiltersAtDefault();
}

// Hydrate module state from persistence at load. DOM elements get
// synced further down where the input/select/checkbox handlers bind.
(function _hydrateInboxFilters() {
    const saved = _readPersistedInboxFilters();
    if (!saved) return;
    if ('search'    in saved) _inboxSearch    = saved.search;
    if ('window'    in saved) _inboxWindow    = saved.window;
    if ('hideEmpty' in saved) _inboxHideEmpty = saved.hideEmpty;
})();

function _filteredInboxItems() {
    let out = _inboxItems;
    const q = _inboxSearch.trim().toLowerCase();
    if (q) {
        out = out.filter(it => (it.name || '').toLowerCase().includes(q));
    }
    if (_inboxWindow !== 'all') {
        const n = parseInt(_inboxWindow, 10) || 0;
        if (n > 0) {
            // "Last N days" includes today + the N-1 prior days.
            const cutoff = new Date();
            cutoff.setDate(cutoff.getDate() - (n - 1));
            const cutoffStr = cutoff.toISOString().slice(0, 10);
            out = out.filter(it => (it.date || '') >= cutoffStr);
        }
    }
    if (_inboxHideEmpty) {
        // v5.20: drop days with zero approvals AND zero publishes.
        out = out.filter(it => (it.approvals || 0) > 0 || (it.publishes || 0) > 0);
    }
    return out;
}

function _renderInboxCount(filteredCount) {
    const el = document.getElementById('inbox-count');
    if (!el) return;
    const total = _inboxItems.length;
    if (total === 0) {
        el.textContent = '0 reports';
    } else if (filteredCount === total) {
        el.textContent = `${total} report${total === 1 ? '' : 's'}`;
    } else {
        el.textContent = `Showing ${filteredCount} of ${total}`;
    }
}

function _formatInboxSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function renderInboxList() {
    const el = document.getElementById('inbox-list');
    const filtered = _filteredInboxItems();
    _renderInboxCount(filtered.length);
    _updateClearButtonVisibility();  // v5.24
    // v5.25: compute today's local date (not UTC) so the marker matches
    // when the cron will have written the day's report. Same local-date
    // construction the v5.4 activity feed uses for consistency.
    const _now = new Date();
    const _todayStr = `${_now.getFullYear()}-` +
                      `${String(_now.getMonth() + 1).padStart(2, '0')}-` +
                      `${String(_now.getDate()).padStart(2, '0')}`;
    if (_inboxItems.length === 0) {
        el.innerHTML = '<li class="muted">No reports yet. The cron writes one each morning.</li>';
        return;
    }
    if (filtered.length === 0) {
        // Distinguish "no reports at all" from "filter excluded them all"
        // so the user knows why the list looks empty.
        el.innerHTML = '<li class="muted">No reports match the current filter.</li>';
        return;
    }
    el.innerHTML = filtered.map((it, i) => {
        // v5.19: per-day counts pulled from /api/reports (default to 0
        // for backward compatibility with any cached pre-v5.19 response).
        const approvals = it.approvals || 0;
        const publishes = it.publishes || 0;
        const apN = `${approvals} approval${approvals === 1 ? '' : 's'}`;
        const puN = `${publishes} published`;
        // v5.23: dim the counts line when both totals are zero, so busy
        // days visually pop without filtering.
        const quiet = (approvals === 0 && publishes === 0) ? ' quiet' : '';
        // v5.25: today marker — small suffix + a "today" row class for
        // the left-edge accent. Multiple classes can apply (e.g., the
        // selected row that is also today's row).
        const isToday = (it.date === _todayStr);
        const cls = [];
        if (it.name === _inboxSelected) cls.push('selected');
        if (isToday) cls.push('today');
        if (i === _inboxFocusedIdx) cls.push('focused');  // v5.29
        const todaySuffix = isToday
            ? ' <span class="row-today">· today</span>'
            : '';
        return (
            `<li class="${cls.join(' ')}" data-report="${_escape(it.name)}">` +
              `<strong>${_escape(it.date)}${todaySuffix}</strong>` +
              `<span class="meta${quiet}">${apN} · ${puN}</span>` +
              `<span class="meta">${_formatInboxSize(it.size)} · ${_escape(it.mtime)}</span>` +
            `</li>`
        );
    }).join('');
}

async function loadInbox() {
    try {
        const r = await fetch('/api/reports');
        if (!r.ok) throw new Error('http ' + r.status);
        const d = await r.json();
        _inboxItems = d.items || [];
        renderInboxList();
        // First-visit auto-load. v5.27: prefer the persisted selection
        // if it still exists in the current items list; otherwise fall
        // back to the newest report. Stale persisted names (files that
        // disappeared between sessions) get cleared from storage so
        // they don't pollute future loads.
        if (!_inboxSelected && _inboxItems.length > 0) {
            const persisted = _readPersistedInboxSelected();
            const hit = persisted
                && _inboxItems.some(it => it.name === persisted);
            if (persisted && !hit) {
                _writePersistedInboxSelected(null);
            }
            await loadInboxReport(hit ? persisted : _inboxItems[0].name);
        }
        // v5.28: scroll the priority row into view once we've
        // settled on a selection. Idempotent across this page load —
        // the flag inside _autoScrollInboxOnce ensures subsequent
        // refreshAll() cycles don't yank the user's scroll position.
        _autoScrollInboxOnce();
        // v5.32: give the inbox keyboard focus on first load so the
        // user can use ↓/j/k without clicking first. Also one-shot.
        _autoFocusInboxOnce();
    } catch (err) {
        _inboxItems = [];
        document.getElementById('inbox-list').innerHTML =
            '<li class="muted">Could not load inbox.</li>';
    }
}

// Render the small markdown subset that daily_report.py emits:
// # / ## / ### headers, **bold**, "- " bullets, --- horizontal rule.
// HTML is escaped FIRST so the converter is XSS-safe even if a topic
// or platform label ever contains <, >, or & (defense in depth — the
// generator currently produces plain ASCII, but we don't want to
// silently rely on that).
function _renderInboxMarkdown(text) {
    const bold = (s) => s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    const lines = (text || '').split('\n');
    const out = [];
    let inList = false;
    const closeList = () => {
        if (inList) { out.push('</ul>'); inList = false; }
    };
    for (const raw of lines) {
        const trimmed = raw.trim();
        if (trimmed === '') { closeList(); continue; }
        if (trimmed === '---') {
            closeList();
            out.push('<hr>');
            continue;
        }
        let m;
        if ((m = raw.match(/^###\s+(.+)$/))) {
            closeList();
            out.push(`<h3>${bold(_escape(m[1]))}</h3>`);
            continue;
        }
        if ((m = raw.match(/^##\s+(.+)$/))) {
            closeList();
            out.push(`<h2>${bold(_escape(m[1]))}</h2>`);
            continue;
        }
        if ((m = raw.match(/^#\s+(.+)$/))) {
            closeList();
            out.push(`<h1>${bold(_escape(m[1]))}</h1>`);
            continue;
        }
        if ((m = raw.match(/^-\s+(.+)$/))) {
            if (!inList) { out.push('<ul>'); inList = true; }
            out.push(`<li>${bold(_escape(m[1]))}</li>`);
            continue;
        }
        closeList();
        out.push(`<p>${bold(_escape(raw))}</p>`);
    }
    closeList();
    return out.join('\n');
}

async function loadInboxReport(filename) {
    const preview = document.getElementById('inbox-preview');
    preview.innerHTML = '<div class="muted">Loading…</div>';
    try {
        const r = await fetch(`/api/reports/${encodeURIComponent(filename)}`);
        if (!r.ok) throw new Error('http ' + r.status);
        const d = await r.json();
        _inboxSelected = filename;
        _inboxContent  = d.content || '';
        _writePersistedInboxSelected(filename);  // v5.27
        renderInboxList();
        // v5.17: small toolbar with a Download button above the rendered
        // markdown. Click is handled by the delegator below, reading the
        // cached _inboxContent so we don't refetch on download.
        preview.innerHTML =
            `<div class="inbox-preview-toolbar">` +
              `<button type="button" id="inbox-download-btn" ` +
              `title="Download ${_escape(filename)}">⬇ Download .md</button>` +
            `</div>` +
            _renderInboxMarkdown(_inboxContent);
    } catch (err) {
        preview.innerHTML = '<div class="muted">Could not load report.</div>';
    }
}

// Download button delegator (v5.17). Lives once at module load; new
// renders inherit it without rebinding. Builds a Blob from the cached
// content and triggers a browser download. No re-fetch — the user
// already paid the network cost when they clicked the report.
document.addEventListener('click', (ev) => {
    if (!ev.target.closest('#inbox-download-btn')) return;
    if (!_inboxSelected || !_inboxContent) return;
    const blob = new Blob([_inboxContent], { type: 'text/markdown' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = _inboxSelected;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
});

// Click delegation for the inbox list. Lives on document.addEventListener
// so newly-rendered rows automatically inherit it without per-render
// rebinding.
document.addEventListener('click', (ev) => {
    const li = ev.target.closest('#inbox-list li[data-report]');
    if (!li) return;
    const name = li.dataset.report;
    if (!name) return;
    // v5.29: sync the focus index so subsequent ↑/↓ feel continuous.
    const items = _filteredInboxItems();
    _inboxFocusedIdx = items.findIndex(it => it.name === name);
    if (name !== _inboxSelected) loadInboxReport(name);
});

// v5.29: keyboard navigation for the inbox.
//   ArrowDown / ArrowUp → move focus within the filtered list
//   Enter               → load the focused report
//   Escape              → clear focus and blur the list
//   '/'                 → global hotkey to jump to the inbox search
//                         input (skipped when already typing in any
//                         other input/textarea)
function _isTypingInAnInput(target) {
    if (!target) return false;
    const tag = (target.tagName || '').toLowerCase();
    return tag === 'input' || tag === 'textarea' || target.isContentEditable;
}
function _isInboxKeyboardActive() {
    const section = document.getElementById('report-inbox-section');
    return !!(section && document.activeElement
              && section.contains(document.activeElement));
}
function _scrollFocusedInboxRowIntoView() {
    const li = document.querySelector('#inbox-list li.focused');
    if (li) li.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}
// v5.30: keyboard shortcuts help panel toggle. Called from the '?'
// hotkey, the close button, and backdrop clicks. Hidden state is
// tracked via the native [hidden] attribute (no extra CSS class).
function _toggleShortcutsPanel(show) {
    const panel = document.getElementById('shortcuts-panel');
    if (!panel) return;
    const wantShow = (show === undefined) ? panel.hidden : show;
    panel.hidden = !wantShow;
    panel.setAttribute('aria-hidden', String(!wantShow));
}
// Backdrop + close-button clicks. Inner-card clicks pass through so
// text inside can be selected/copied without dismissing the panel.
document.addEventListener('click', (ev) => {
    const panel = document.getElementById('shortcuts-panel');
    if (!panel || panel.hidden) return;
    if (ev.target.id === 'shortcuts-close' || ev.target === panel) {
        _toggleShortcutsPanel(false);
    }
});

document.addEventListener('keydown', (ev) => {
    // v5.30: '?' toggles the help panel from anywhere (unless typing).
    if (ev.key === '?' && !_isTypingInAnInput(ev.target)) {
        ev.preventDefault();
        _toggleShortcutsPanel();
        return;
    }
    // v5.30: Esc closes the help panel if it's open. Caught BEFORE
    // the inbox Esc handler so the same key doesn't both close the
    // panel and clear inbox focus in one stroke.
    if (ev.key === 'Escape') {
        const panel = document.getElementById('shortcuts-panel');
        if (panel && !panel.hidden) {
            ev.preventDefault();
            _toggleShortcutsPanel(false);
            return;
        }
    }
    // Global hotkey first: '/' anywhere on the page (unless typing
    // into another input) jumps focus to the inbox search input.
    if (ev.key === '/' && !_isTypingInAnInput(ev.target)) {
        const search = document.getElementById('inbox-search');
        if (search) {
            ev.preventDefault();
            search.focus();
            search.select();
        }
        return;
    }
    if (!_isInboxKeyboardActive()) return;
    const items = _filteredInboxItems();
    if (items.length === 0 && ev.key !== 'Escape') return;

    // v5.31: 'j'/'k' alias ArrowDown/ArrowUp (Vim/Gmail style). j and k
    // are real typing characters, so they're ignored when the user is
    // typing in any input — otherwise they'd hijack search keystrokes.
    // Arrow keys don't need the same guard because they have no meaning
    // in single-line inputs.
    const isDown = ev.key === 'ArrowDown'
        || (ev.key === 'j' && !_isTypingInAnInput(ev.target));
    const isUp = ev.key === 'ArrowUp'
        || (ev.key === 'k' && !_isTypingInAnInput(ev.target));

    if (isDown) {
        ev.preventDefault();
        _inboxFocusedIdx = Math.min(
            (_inboxFocusedIdx < 0 ? -1 : _inboxFocusedIdx) + 1,
            items.length - 1,
        );
        renderInboxList();
        _scrollFocusedInboxRowIntoView();
    } else if (isUp) {
        ev.preventDefault();
        _inboxFocusedIdx = Math.max(_inboxFocusedIdx - 1, 0);
        renderInboxList();
        _scrollFocusedInboxRowIntoView();
    } else if (ev.key === 'Enter') {
        if (_inboxFocusedIdx < 0 || _inboxFocusedIdx >= items.length) return;
        ev.preventDefault();
        const target = items[_inboxFocusedIdx];
        if (target) loadInboxReport(target.name);
    } else if (ev.key === 'Escape') {
        ev.preventDefault();
        _inboxFocusedIdx = -1;
        renderInboxList();
        const list = document.getElementById('inbox-list');
        if (list && list === document.activeElement) list.blur();
    }
});

// Filter input bindings (v5.18). Re-render the list on each change;
// renderInboxList already pulls the filtered subset and updates the
// count display.
const _inboxSearchEl = document.getElementById('inbox-search');
if (_inboxSearchEl) {
    _inboxSearchEl.value = _inboxSearch;          // v5.21 hydrate UI
    _inboxSearchEl.addEventListener('input', () => {
        _inboxSearch = _inboxSearchEl.value || '';
        _writePersistedInboxFilters();
        renderInboxList();
    });
}
const _inboxWindowEl = document.getElementById('inbox-window');
if (_inboxWindowEl) {
    _inboxWindowEl.value = _inboxWindow;          // v5.21 hydrate UI
    _inboxWindowEl.addEventListener('change', () => {
        _inboxWindow = _inboxWindowEl.value || 'all';
        _writePersistedInboxFilters();
        renderInboxList();
    });
}
const _inboxHideEmptyEl = document.getElementById('inbox-hide-empty');
if (_inboxHideEmptyEl) {
    _inboxHideEmptyEl.checked = _inboxHideEmpty;  // v5.21 hydrate UI
    _inboxHideEmptyEl.addEventListener('change', () => {
        _inboxHideEmpty = _inboxHideEmptyEl.checked;
        _writePersistedInboxFilters();
        renderInboxList();
    });
}
const _inboxClearEl = document.getElementById('inbox-clear');
if (_inboxClearEl) {
    _inboxClearEl.addEventListener('click', () => {
        // v5.22: reset all three filters to their defaults, clear the
        // persisted state, and re-sync the visible form elements.
        _inboxSearch    = '';
        _inboxWindow    = 'all';
        _inboxHideEmpty = false;
        _clearPersistedInboxFilters();
        if (_inboxSearchEl)    _inboxSearchEl.value    = '';
        if (_inboxWindowEl)    _inboxWindowEl.value    = 'all';
        if (_inboxHideEmptyEl) _inboxHideEmptyEl.checked = false;
        renderInboxList();
    });
}

// Chip click delegator (v5.5). Bound once at module load via event
// delegation, so newly rendered chips inherit the handler without
// per-render rebinding. Empty chips are <button disabled> so clicks on
// them never reach this handler.
document.addEventListener('click', (ev) => {
    // v5.9: explicit clear-filter shortcut on the active chip. Catch
    // this BEFORE the chip-toggle path — otherwise the existing
    // `type === _activityFilter` early-return would swallow the click.
    if (ev.target.closest('.activity-chip-clear')) {
        if (_activityFilter === 'all') return;
        _activityFilter = 'all';
        _writePersistedActivityFilter('all');
        _renderActivityFilters();
        renderActivity(_filteredActivityItems());
        return;
    }
    const chip = ev.target.closest('.activity-chip');
    if (!chip || chip.disabled) return;
    const type = chip.dataset.activityType;
    if (!type || type === _activityFilter) return;
    _activityFilter = type;
    _writePersistedActivityFilter(type);
    _renderActivityFilters();
    renderActivity(_filteredActivityItems());
});


// --- Connections center -------------------------------------------------

// Cache of /api/connections keyed by lowercase platform name so other
// renderers (renderReady) can ask "is this platform connected?" without
// re-fetching. Populated inside loadConnections().
let _connectionsByPlatform = {};

function isPlatformConnected(platform) {
    // v4.9: "connected" now means "verified" — env presence alone is
    // no longer enough to enable a publish button. The server's
    // /api/posts/{id}/publish endpoint enforces the same gate.
    const key = (platform || '').toLowerCase();
    const c = _connectionsByPlatform[key];
    return !!(c && c.status === 'verified');
}

function _publishButtonHTML(postId, platform, actionKey, label) {
    // Defense-in-depth: dim the button when the platform isn't
    // verified. The publish endpoint also refuses with HTTP 400 in
    // that state, so devtools-stripping the attribute doesn't bypass
    // safety.
    const verified      = isPlatformConnected(platform);
    const disabledAttr  = verified ? '' : ' disabled';
    const disabledClass = verified ? '' : ' disabled';
    const titleAttr     = verified
        ? ''
        : ' title="Verify this connection before publishing."';
    return (
        `<button class="row-action danger${disabledClass}" ` +
          `data-action="${actionKey}" data-id="${postId}"${disabledAttr}${titleAttr}>` +
          `${_escape(label)}` +
        `</button>`
    );
}

function renderConnections(items) {
    const el = document.getElementById('connections-list');
    if (!items || items.length === 0) {
        el.innerHTML = '<li class="muted">No platforms configured.</li>';
        return;
    }
    // v4.9: 3-state badge per platform.
    const STATUS_MAP = {
        verified:       { cls: 'status-approved', text: '🟢 Verified' },
        configured:     { cls: 'status-draft',    text: '🟡 Configured' },
        not_configured: { cls: 'status-rejected', text: '🔴 Missing setup' },
    };
    el.innerHTML = items.map(c => {
        const s = STATUS_MAP[c.status] || STATUS_MAP.not_configured;
        const statusClass = s.cls;
        const statusText  = s.text;
        const missingLine = c.missing && c.missing.length
            ? `<div class="connection-missing">Missing: ${c.missing.map(_escape).join(', ')}</div>`
            : '';
        const checkedLine = c.last_verified_at
            ? `<div class="connection-meta">Last checked: ${_escape(c.last_verified_at)}</div>`
            : '';
        const warningLine = c.warning
            ? `<div class="connection-warning">${_escape(c.warning)}</div>`
            : '';
        // v6.4 Meta-prep: when Facebook/Instagram are not configured,
        // surface a one-line hint that the user is likely waiting on
        // Meta app approval. Status itself stays `not_configured` —
        // this is purely a UI message, no backend state change.
        const metaPlatforms = new Set(['Facebook', 'Instagram']);
        const metaWaitLine = (c.status === 'not_configured' && metaPlatforms.has(c.platform))
            ? `<div class="connection-meta connection-meta-pending">` +
              `Waiting for Meta app approval / token. Add the env keys above ` +
              `once your Meta Developer app's Page Posts permission is granted.</div>`
            : '';
        // The Setup Help button opens the platform's setup URL in a
        // new tab. Disabled if /api/connections didn't return a URL.
        const url = c.setup_url || '';
        const setupBtn = url
            ? `<button class="row-action" data-action="open-setup" ` +
              `data-url="${_escape(url)}">Open Setup Help</button>`
            : '';
        // Verify uses the platform key the backend expects ("linkedin",
        // "google_business_profile", …) — convert the display name.
        const platformKey = c.platform.toLowerCase().replace(/ /g, '_');
        const verifyBtn = `<button class="row-action" data-action="verify-connection" ` +
                          `data-platform-key="${_escape(platformKey)}">Verify</button>`;
        return (
            `<li class="connection-row">` +
              `<span class="connection-text">` +
                `${_escape(c.platform)} — ` +
                `<span class="status-badge ${statusClass}">${statusText}</span>` +
                missingLine +
                metaWaitLine +
                checkedLine +
                warningLine +
              `</span>` +
              `<span class="row-actions">` +
                verifyBtn + setupBtn +
              `</span>` +
            `</li>`
        );
    }).join('');
}

// Per-row buttons inside the Connections card. Routes by data-action:
//   open-setup        -> window.open(setup URL) in a new tab (noopener)
//   verify-connection -> POST /api/connections/verify, show result in
//                        the Command Output panel. Never prints tokens.
// v6.7: extracted so the Meta Readiness Center's "Verify now" buttons
// can call the same path as the Connections card without duplicating
// the fetch + cmd-output + refresh logic.
async function verifyConnection(platform) {
    if (!platform) return;
    document.getElementById('cmd-status').textContent =
        `Verifying ${platform}…`;
    document.getElementById('cmd-output').textContent = '';
    try {
        const r = await fetch('/api/connections/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ platform }),
        });
        const d = await r.json();
        if (r.ok) {
            showCmd(`Verify (${platform})`, {
                exit_code: d.ok ? 0 : 1,
                stdout: d.message || '',
                stderr: '',
            });
            // Refresh connections (badges flip) AND ready posts
            // (publish buttons enable/disable based on the new
            // verified state) AND meta-readiness (card badges flip).
            await loadConnections();
            await loadReady();
            await loadMetaReadiness();
        } else {
            showCmd(`Verify (${platform})`, {
                exit_code: r.status,
                stdout: '',
                stderr: d.detail || `HTTP ${r.status}`,
            });
        }
    } catch (err) {
        document.getElementById('cmd-status').textContent =
            'Verify failed: ' + err;
    }
}

document.getElementById('connections-list').addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;

    if (action === 'open-setup') {
        const url = btn.dataset.url;
        if (url) window.open(url, '_blank', 'noopener');
        return;
    }

    if (action === 'verify-connection') {
        await verifyConnection(btn.dataset.platformKey);
        return;
    }
});

// v6.7: same verify-now path for the Meta Readiness Center cards.
// Scoped to #meta-readiness so it doesn't compete with other delegators.
document.getElementById('meta-readiness').addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-action="verify-connection"]');
    if (!btn) return;
    await verifyConnection(btn.dataset.platformKey);
});

async function loadConnections() {
    try {
        const r = await fetch('/api/connections');
        if (!r.ok) throw new Error('http ' + r.status);
        const d = await r.json();
        const conns = d.connections || [];
        // Rebuild the lookup with normalized lowercase keys
        // (e.g. "linkedin", "google business profile") so callers don't
        // need to know about display-name casing.
        _connectionsByPlatform = {};
        for (const c of conns) {
            _connectionsByPlatform[c.platform.toLowerCase()] = c;
        }
        renderConnections(conns);
    } catch (err) {
        document.getElementById('connections-list').innerHTML =
            '<li class="muted">Could not load connections.</li>';
    }
}

// --- v6.7: Meta Readiness Center ----------------------------------------
// Side-by-side cards for Facebook + Instagram showing setup state +
// remaining steps + verify-now button. Data comes from the read-only
// /api/meta/readiness endpoint (env-key NAMES + present/absent only,
// never values).

function renderMetaReadiness(data) {
    const el = document.getElementById('meta-readiness');
    if (!el) return;
    if (!data || Object.keys(data).length === 0) {
        el.innerHTML = '<div class="muted">No Meta platforms configured.</div>';
        return;
    }
    const STATUS_TEXT = {
        verified:       'Verified',
        configured:     'Configured (not verified)',
        not_configured: 'Not configured',
    };
    el.innerHTML = Object.entries(data).map(([slug, p]) => {
        const statusCls = (p.status || 'not_configured').toLowerCase();
        const statusTxt = STATUS_TEXT[statusCls] || statusCls;
        const keysHtml = (p.required_keys || []).map(k => {
            const mark = k.present
                ? '<span class="meta-key-mark meta-key-present">✓</span>'
                : '<span class="meta-key-mark meta-key-missing">✗</span>';
            return `<li>${mark}${_escape(k.key)}</li>`;
        }).join('');
        const stepsHtml = (p.setup_steps || [])
            .map(s => `<li>${_escape(s)}</li>`)
            .join('');
        const lastChecked = p.last_verified_at
            ? `Last verified: ${_escape(p.last_verified_at)}`
            : 'Never verified.';
        const verifyMsg = p.verify_message
            ? `<span class="meta-verify-msg">${_escape(p.verify_message)}</span>`
            : '';
        const docLink = p.doc_url
            ? `<a href="${_escape(p.doc_url)}" target="_blank" rel="noopener noreferrer">Docs ↗</a>`
            : '';
        return (
            `<div class="meta-card" data-platform="${_escape(slug)}">` +
              `<h3>${_escape(p.name)}` +
                `<span class="meta-card-status ${statusCls}">${_escape(statusTxt)}</span>` +
              `</h3>` +
              `<h4>Required env keys</h4>` +
              `<ul class="meta-keys">${keysHtml}</ul>` +
              `<h4>Setup steps</h4>` +
              `<ol class="meta-steps">${stepsHtml}</ol>` +
              `<div class="meta-card-footer">` +
                `<button type="button" class="row-action" ` +
                  `data-action="verify-connection" ` +
                  `data-platform-key="${_escape(slug)}">Verify now</button>` +
                docLink +
                `<span class="meta-verify-msg" title="${_escape(lastChecked)}">${_escape(lastChecked)}</span>` +
              `</div>` +
            `</div>`
        );
    }).join('');
}

async function loadMetaReadiness() {
    try {
        const r = await fetch('/api/meta/readiness');
        if (!r.ok) throw new Error('http ' + r.status);
        renderMetaReadiness(await r.json());
    } catch (err) {
        const el = document.getElementById('meta-readiness');
        if (el) el.innerHTML = '<div class="muted">Could not load Meta readiness.</div>';
    }
}


// --- Control Panel (v5.34) ----------------------------------------------
// One section, 13 buttons, three groups. Most actions delegate to
// existing buttons elsewhere in the page (DRY — keeps the source of
// truth for confirm dialogs / API calls in one place). The rest are
// small custom handlers: scroll-to-section, set-a-filter, or write
// guidance text into #cmd-status.

function _cpStatus(msg) {
    const el = document.getElementById('cmd-status');
    if (el) el.textContent = msg;
}
function _cpStatusHTML(html) {
    const el = document.getElementById('cmd-status');
    if (el) el.innerHTML = html;
}
function _cpScrollToH2(text) {
    for (const h of document.querySelectorAll('section h2')) {
        if (h.textContent.trim() === text) {
            h.closest('section')?.scrollIntoView({ block: 'start', behavior: 'smooth' });
            return true;
        }
    }
    return false;
}
function _cpClickById(id) {
    const btn = document.getElementById(id);
    if (btn) { btn.click(); return true; }
    return false;
}

function _runControlPanelAction(action) {
    switch (action) {
        // --- Hub / System ---
        case 'refresh-hub':
            refreshAll();
            return;
        case 'run-daily-ops':
            // runDailyOps() carries its own OpenAI-call confirm.
            runDailyOps();
            return;
        case 'refresh-summary':
            refreshSummaryOnly();
            return;
        case 'open-latest-report': {
            // Inbox is sorted newest-first → first row is the latest.
            // Clicking it triggers the v5.27 selection path which loads
            // the markdown into the preview.
            _cpScrollToH2('Report Inbox');
            const li = document.querySelector('#inbox-list li[data-report]');
            if (li) li.click();
            else _cpStatus('No reports yet. The cron writes one each morning.');
            return;
        }
        case 'open-logs':
            if (!_cpScrollToH2('Latest Log')) _cpStatus('Logs section not found.');
            return;
        case 'show-diagnostics': {
            // v6.6: run hub_doctor.sh via the diagnostics endpoint and
            // render the (redacted) output in #cmd-output. Does NOT
            // stop/start the Hub. Does NOT post. Read-only.
            _cpStatus('Running Hub diagnostics…');
            const out = document.getElementById('cmd-output');
            if (out) out.textContent = '';
            fetch('/api/hub/diagnostics')
                .then(r => r.json())
                .then(d => {
                    if (out) out.textContent = d.output || '(no output)';
                    _cpStatus(d.ok
                        ? 'Hub diagnostics complete.'
                        : 'Hub diagnostics returned issues — see Command Output.');
                    _cpScrollToH2('Command Output');
                })
                .catch(err => {
                    _cpStatus('Diagnostics fetch failed: ' + err);
                });
            return;
        }
        case 'stop-hub': {
            // v6.5: stop the Hub server. Confirm because this makes the
            // current page unresponsive — every subsequent click and
            // refresh will fail until the server is restarted.
            if (!confirm(
                'Stop the Hub server?\n\n' +
                'After it stops:\n' +
                ' • this page will become unresponsive\n' +
                ' • the Desktop icon, bash automation/open_hub.sh, or ' +
                '   `python3 -m uvicorn hub.app:app --port 8787` will ' +
                '   bring it back up\n\n' +
                'Continue?'
            )) return;
            _cpStatus('Stopping Hub…');
            fetch('/api/hub/stop', { method: 'POST' })
                .then(r => r.json())
                .then(d => {
                    if (d.ok) {
                        _cpStatus(d.message + ' (this tab is now stale.)');
                    } else {
                        _cpStatus('Stop failed: ' + (d.message || '(no message)'));
                    }
                })
                .catch(err => {
                    // If the server died before sending the response,
                    // we get a fetch error here — that's actually
                    // success from the user's perspective.
                    _cpStatus(
                        'Connection lost — Hub probably stopped successfully. ' +
                        'This page is now stale.',
                    );
                });
            return;
        }

        // --- Parker Promo ---
        case 'generate-drafts':
            // No standalone "generate-only" endpoint exists. Daily Ops
            // runs daily_runner (generation) as its first step. The
            // confirm dialog lives inside runDailyOps().
            runDailyOps();
            return;
        case 'review-drafts': {
            // Mirror the v5.1 Mission Control "review-drafts" behavior:
            // set status filter to 'draft' and scroll to Recent Parker Work.
            const statusEl = document.getElementById('filter-status');
            if (statusEl) {
                statusEl.value = 'draft';
                statusEl.dispatchEvent(new Event('change'));
            }
            _cpScrollToH2('Recent Parker Work');
            return;
        }
        case 'ready-to-post':
            _cpScrollToH2('Ready to Post');
            return;
        case 'approve-visible':
            // #approve-visible already has a confirm + bulk API call.
            _cpClickById('approve-visible');
            return;
        case 'reject-visible':
            _cpClickById('reject-visible');
            return;

        // --- Connections ---
        case 'verify-all-connections': {
            // Mission Control has a data-mc-action="verify-connections"
            // button rendered by renderMissionControl. If present, click
            // it (which fires the existing verify flow with confirm).
            const mc = document.querySelector(
                '[data-mc-action="verify-connections"]',
            );
            if (mc) { mc.click(); _cpScrollToH2('Connections'); }
            else _cpStatus(
                'Verify Connections button not available yet. ' +
                'Try again after the Hub finishes loading.',
            );
            return;
        }
        case 'meta-readiness':
            // v6.7: scroll to the Meta Readiness Center section.
            if (!_cpScrollToH2('Meta Readiness Center')) {
                _cpStatus('Meta Readiness section not found.');
            }
            return;
        case 'connect-linkedin': {
            // v6.1: kicks off the OAuth flow. Confirm first because we
            // navigate away from the Hub to LinkedIn and we will write
            // the returned token into .env on this machine.
            if (!confirm(
                'This will redirect you to LinkedIn to authorize ' +
                'PartnerDeskAI. On success, your access token will be ' +
                'stored in .env on this machine (a .env.bak snapshot ' +
                'is also written). The token is never sent anywhere ' +
                'except LinkedIn and this Hub. Continue?'
            )) return;
            // navigate the whole window — the server replies with a 302
            // to LinkedIn, then LinkedIn redirects back to our callback.
            window.location.href = '/api/oauth/linkedin/start';
            return;
        }
        case 'setup-env': {
            // v6.2: guidance-only. The setup wizard is interactive (CLI
            // getpass) so it MUST run in the terminal, never in the
            // browser. No secrets are ever exposed to the browser.
            _cpScrollToH2('Connections');
            _cpStatusHTML(
                'Run <kbd>python3 automation/setup_env.py</kbd> in the terminal ' +
                'to interactively configure <code>.env</code>. The wizard prompts ' +
                'only for missing values, masks existing secrets, never prints ' +
                'new secret values after entry, and writes atomically via ' +
                '<code>env_writer</code> (with a <code>.env.bak</code> snapshot ' +
                'per write). For a one-shot read-only report: ' +
                '<kbd>python3 automation/setup_env.py status</kbd>.',
            );
            return;
        }
        case 'open-connection-help':
            _cpScrollToH2('Connections');
            _cpStatusHTML(
                'Run <kbd>python3 automation/connect_wizard.py</kbd> in the ' +
                'terminal for an interactive OAuth setup walkthrough. ' +
                'For a one-shot status report: ' +
                '<kbd>python3 automation/connect_wizard.py status</kbd>. ' +
                'For a read-only verify probe: ' +
                '<kbd>python3 automation/connect_wizard.py verify</kbd>.',
            );
            return;
        case 'show-missing-setup': {
            const conns = _connectionsByPlatform || {};
            const lines = [];
            for (const [platform, c] of Object.entries(conns)) {
                if (c && c.status === 'not_configured') {
                    const missing = (c.missing || []).join(', ');
                    lines.push(`• ${platform}: ${missing || '(unspecified)'}`);
                }
            }
            _cpScrollToH2('Connections');
            if (lines.length === 0) {
                _cpStatus(
                    'All connections are configured. ' +
                    '(Some may still need a verify probe — use Verify All Connections.)',
                );
            } else {
                _cpStatusHTML(
                    '<strong>Missing env keys per platform:</strong><br>' +
                    lines.map(l => _escape(l)).join('<br>') +
                    '<br><br>Edit <kbd>.env</kbd> in the project root and add ' +
                    'each missing key, then click Refresh Hub.',
                );
            }
            return;
        }
    }
}

// v5.35: brief "got your click" pulse on the clicked CP button. The
// .is-busy class adds opacity + background tint AND pointer-events:none,
// which doubles as a 800ms double-click lockout — useful protection
// for the OpenAI-triggering buttons that call runDailyOps().
function _cpPulse(btn) {
    btn.classList.add('is-busy');
    if (btn._cpPulseTimer) clearTimeout(btn._cpPulseTimer);
    btn._cpPulseTimer = setTimeout(() => {
        btn.classList.remove('is-busy');
        btn._cpPulseTimer = null;
    }, 800);
}

document.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-cp-action]');
    if (!btn) return;
    _runControlPanelAction(btn.dataset.cpAction);
    _cpPulse(btn);
});


// --- Ready to Post queue -------------------------------------------------

// Approved posts come down with content so the Copy button can hand the
// body to the clipboard without an extra fetch per row.
let _readyPosts = [];

function renderReady(posts) {
    const el = document.getElementById('ready-list');
    if (!posts || posts.length === 0) {
        el.innerHTML = '<div class="muted">No approved posts ready yet.</div>';
        return;
    }
    el.innerHTML = posts.map(p => {
        const topic = p.topic ? _escape(p.topic) : '(no topic)';
        const content = p.content ? _escape(p.content) : '(empty)';
        const editedBadge = p.edited_at
            ? ` <span class="edited-badge" title="Last edited ${_escape(_fmtEdited(p.edited_at))}">edited</span>`
            : '';
        const createdShort = _escape((p.created_at || '').slice(0, 16));
        const editedLine = p.edited_at
            ? ` · Edited: ${_escape(_fmtEdited(p.edited_at))}`
            : '';
        // Real-publish buttons are conditional per platform AND grayed
        // out via _publishButtonHTML when the platform isn't in the
        // connections cache as "connected".
        let publishBtn = '';
        if (p.platform === 'LinkedIn') {
            publishBtn = _publishButtonHTML(p.id, 'LinkedIn', 'post-linkedin', 'Post to LinkedIn');
        } else if (p.platform === 'Facebook') {
            publishBtn = _publishButtonHTML(p.id, 'Facebook', 'post-facebook', 'Post to Facebook');
        }
        return (
            `<div class="ready-card" data-id="${p.id}">` +
              `<div class="ready-card-meta">` +
                `#${p.id} ${_escape(p.platform)} — ${topic} ` +
                `<span class="status-badge status-approved">approved</span>` +
                editedBadge +
                `<div class="ready-card-meta-secondary">` +
                  `Created: ${createdShort}${editedLine}` +
                `</div>` +
              `</div>` +
              `<div class="ready-card-content">${content}</div>` +
              `<div class="ready-card-actions">` +
                `<button class="row-action" data-action="copy" ` +
                  `data-id="${p.id}">Copy Post Text</button>` +
                `<button class="row-action" data-action="preview" ` +
                  `data-id="${p.id}">Preview Full Post</button>` +
                publishBtn +
                `<button class="row-action" data-action="mark-posted" ` +
                  `data-id="${p.id}">Mark Posted</button>` +
              `</div>` +
            `</div>`
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

    if (btn.dataset.action === 'preview') {
        openPreview(id);
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
    // Pull the exact text we're about to publish from the ready cache and
    // refuse to even ask for confirmation if the body is empty.
    const post = _readyPosts.find(p => String(p.id) === String(postId));
    const content = (post && post.content) ? post.content : '';
    if (!content.trim()) {
        document.getElementById('cmd-status').textContent =
            `Cannot publish #${postId}: content is empty. Refresh and try again.`;
        document.getElementById('cmd-output').textContent = '';
        return;
    }

    // Surface the EXACT text in the Command Output panel BEFORE the
    // confirm fires, so Topher can read the whole thing without
    // squinting at a tiny modal. The confirm itself shows a truncated
    // preview as a final guardrail.
    document.getElementById('cmd-status').textContent =
        `Preview before posting #${postId} to ${platformLabel}:`;
    document.getElementById('cmd-output').textContent =
        `You are about to publicly post this:\n\n${content}`;

    const truncated = content.length > 280 ? content.slice(0, 280) + '…' : content;
    const proceed = confirm(
        `Post this to ${platformLabel} now? This will publish publicly.\n\n` +
        `Preview:\n${truncated}`
    );
    if (!proceed) {
        document.getElementById('cmd-status').textContent =
            `Cancelled. Nothing was posted to ${platformLabel}.`;
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
        // Prerequisites that must complete BEFORE loadReady / loadStatus
        // run, because they populate DOM nodes / module caches those
        // later renderers depend on:
        //   - loadPartners: creates Parker's #parker-pending / #parker-next
        //   - loadConnections: fills _connectionsByPlatform so renderReady
        //                       knows which publish buttons to gray out.
        await Promise.all([loadPartners(), loadConnections()]);
        await Promise.all([
            loadStatus(), loadSummary(), loadLogs(),
            loadHistory(), loadReady(),
            loadActivity(), loadReports(), loadInbox(),
            loadMetaReadiness(),
        ]);
        // Mission Control reads cached payloads from the loaders above,
        // so it runs last to ensure every cache is populated.
        renderMissionControl();
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

// v5.36: named action functions. Previously these lived as inline
// handlers on the now-removed top-row buttons (#btn-refresh, #btn-run,
// #btn-skip). Extracted so the Control Panel and Mission Control can
// call them directly instead of synthesizing button clicks on elements
// that no longer exist.
async function runDailyOps() {
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
}

async function refreshSummaryOnly() {
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
}

// Initial load on page open.
refreshAll();
