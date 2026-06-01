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
let _lastHistory = [];  // v7.21: feeds the "Ship stale" mood check

function _computeMood(status, readyCount, lastHistory) {
    // Priority matches the spec — first matching rule wins.
    if (status && status.health && status.health.status !== 'PASS') {
        return { label: 'Needs attention', cls: 'mood-red' };
    }
    if (status && status.review && status.review.pending_drafts > 0) {
        return { label: 'Needs review', cls: 'mood-yellow' };
    }
    // v7.21: "Ship stale" — readyCount > 0 AND nothing published in
    // the last 24h. Catches the case the audit found: a pile of
    // approved-but-unshipped posts under a misleading-green mood.
    if (readyCount > 0 && _hoursSinceLastPublish(lastHistory) > 24) {
        return { label: 'Ship stale', cls: 'mood-yellow' };
    }
    if (readyCount > 0) {
        return { label: 'Ready to publish', cls: 'mood-green' };
    }
    return { label: 'Ready', cls: 'mood-green' };
}

// v7.21: hours since the most-recent /api/history posted_date. Returns
// Infinity when history is empty (treated as 'never posted' → stale if
// anything is ready). Defensive against malformed dates.
function _hoursSinceLastPublish(history) {
    if (!Array.isArray(history) || history.length === 0) return Infinity;
    let mostRecent = 0;
    for (const it of history) {
        const t = Date.parse(it.posted_date);
        if (!isNaN(t) && t > mostRecent) mostRecent = t;
    }
    if (mostRecent === 0) return Infinity;
    return (Date.now() - mostRecent) / (1000 * 60 * 60);
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
    const mood         = _computeMood(_lastStatus, readyCount, _lastHistory);

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
            // v7.15: align with the other filter-empty strings
            // ('No leads match the filter.', 'No reports match the current filter.')
            '<li class="muted">No Parker work matches the filter.</li>';
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
        _lastHistory = d.items || [];  // v7.21: cache for mood + later
        renderApprovedHistory(_lastHistory);
    } catch (err) {
        _lastHistory = [];
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
        // v7.13: was a bare "—" that read like "loading" or "broken".
        // This branch is the *error* state (fetch failed) — not the
        // empty-window state, which renders "No data in this window."
        // via _renderReportList([]). Copy here matches the error tone.
        const unavail = '<li class="muted">Data unavailable.</li>';
        topicsEl.innerHTML    = unavail;
        platformsEl.innerHTML = unavail;
        combosEl.innerHTML    = unavail;
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
// v6.8: also handles the "Save notes" button per card.
// Scoped to #meta-readiness so it doesn't compete with other delegators.
document.getElementById('meta-readiness').addEventListener('click', async (e) => {
    const verifyBtn = e.target.closest('button[data-action="verify-connection"]');
    if (verifyBtn) {
        await verifyConnection(verifyBtn.dataset.platformKey);
        return;
    }
    const saveBtn = e.target.closest('button.meta-notes-save');
    if (saveBtn) {
        const platform = saveBtn.dataset.platform;
        const textarea = document.querySelector(
            `.meta-notes-input[data-platform="${platform}"]`
        );
        const statusEl = document.querySelector(
            `.meta-notes-status[data-platform="${platform}"]`
        );
        if (!textarea) return;
        const notes = textarea.value || '';
        if (statusEl) statusEl.textContent = 'Saving…';
        try {
            const r = await fetch('/api/meta/notes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ platform, notes }),
            });
            const d = await r.json();
            if (r.ok && d.ok) {
                if (statusEl) statusEl.textContent =
                    `Updated: ${d.updated_at}`;
            } else {
                if (statusEl) statusEl.textContent =
                    `Save failed: ${d.detail || d.message || 'unknown'}`;
            }
        } catch (err) {
            if (statusEl) statusEl.textContent = 'Save failed: ' + err;
        }
        return;
    }
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
        const docLink = p.doc_url
            ? `<a href="${_escape(p.doc_url)}" target="_blank" rel="noopener noreferrer">Docs ↗</a>`
            : '';
        // v6.8: user-authored app-approval notes. Textarea is always
        // visible — the Save button is the explicit commit. Escaped on
        // initial render so prior content can't break the markup.
        const notesText = p.notes || '';
        const notesUpdated = p.notes_updated_at
            ? `Updated: ${_escape(p.notes_updated_at)}`
            : 'Never saved.';
        const notesBlock =
            `<h4>App approval notes</h4>` +
            `<textarea class="meta-notes-input" rows="3" ` +
              `data-platform="${_escape(slug)}" ` +
              `placeholder="Track app review status, granted permissions, reviewer feedback…">` +
              `${_escape(notesText)}` +
            `</textarea>` +
            `<div class="meta-notes-footer">` +
              `<button type="button" class="row-action meta-notes-save" ` +
                `data-platform="${_escape(slug)}">Save notes</button>` +
              `<span class="meta-notes-status" data-platform="${_escape(slug)}">` +
                `${_escape(notesUpdated)}</span>` +
            `</div>`;
        return (
            `<div class="meta-card" data-platform="${_escape(slug)}">` +
              `<h3>${_escape(p.name)}` +
                `<span class="meta-card-status ${statusCls}">${_escape(statusTxt)}</span>` +
              `</h3>` +
              `<h4>Required env keys</h4>` +
              `<ul class="meta-keys">${keysHtml}</ul>` +
              `<h4>Setup steps</h4>` +
              `<ol class="meta-steps">${stepsHtml}</ol>` +
              notesBlock +
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


// --- v6.9: LinkedIn Leads (outbound CRM-lite) ---------------------------
//
// Pure client-side cache + filter. Writes (add/update/delete) go
// through 3 small API endpoints; the response replaces the local cache
// and re-renders. No optimistic UI — keeps the data flow simple.

let _leads = [];
let _leadsFilter = '';
let _editingLeadId = null;  // id of the lead currently in edit mode

// v7.1: urgency-aware sort. Mode is 'updated' (default — newest first) or
// 'follow-up' (overdue → due today → future → no-date). Persisted in
// localStorage so a user who lives in the queue view doesn't have to
// re-pick it on every page load.
const _LEADS_SORT_KEY = 'partnerdesk.leadsSort';
let _leadsSort = (() => {
    try {
        const v = localStorage.getItem(_LEADS_SORT_KEY);
        return v === 'follow-up' ? 'follow-up' : 'updated';
    } catch (e) { return 'updated'; }
})();

function _todayStr() {
    // Local-date YYYY-MM-DD; matches the format follow_up_date is stored in.
    const d = new Date();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${d.getFullYear()}-${mm}-${dd}`;
}

// 0 = overdue, 1 = due today, 2 = future, 3 = no follow-up date set.
function _followUpBucket(l, today) {
    const fu = l.follow_up_date;
    if (!fu) return 3;
    if (fu < today) return 0;
    if (fu === today) return 1;
    return 2;
}

// v7.2: "due this week" = follow_up_date ∈ [today, today+6]. Overdue is
// intentionally excluded: it already has its own red visual on the card
// and the "Follow-up due first" sort surfaces it at the top. The chip
// covers the *planning* window — what does the next 7 days look like.
function _addDays(yyyymmdd, days) {
    const [y, m, d] = yyyymmdd.split('-').map(Number);
    const dt = new Date(y, m - 1, d);
    dt.setDate(dt.getDate() + days);
    const mm = String(dt.getMonth() + 1).padStart(2, '0');
    const dd = String(dt.getDate()).padStart(2, '0');
    return `${dt.getFullYear()}-${mm}-${dd}`;
}
function _isDueThisWeek(l, today, horizon) {
    const fu = l.follow_up_date;
    return !!(fu && fu >= today && fu <= horizon);
}
let _leadsDueFilter = false;  // not persisted — action-driven, not preference

function _filteredLeads() {
    const q = _leadsFilter.trim().toLowerCase();
    let matched = !q ? _leads.slice() : _leads.filter(l => {
        const blob = [l.name, l.company, l.handle, l.source, l.status, l.notes]
            .map(s => (s || '').toLowerCase())
            .join(' ');
        return blob.includes(q);
    });
    if (_leadsDueFilter) {
        const today = _todayStr();
        const horizon = _addDays(today, 6);
        matched = matched.filter(l => _isDueThisWeek(l, today, horizon));
    }
    // v7.25: stack the dashboard filter on top of text + due-this-week.
    matched = matched.filter(_dashboardPredicate);
    if (_leadsSort === 'follow-up') {
        const today = _todayStr();
        // Bucket first; within a dated bucket sort ascending by date
        // (oldest overdue = most urgent, nearest future = next up).
        // The no-date bucket falls back to updated_at desc.
        matched.sort((a, b) => {
            const ba = _followUpBucket(a, today);
            const bb = _followUpBucket(b, today);
            if (ba !== bb) return ba - bb;
            if (ba === 3) {
                return (b.updated_at || '').localeCompare(a.updated_at || '');
            }
            return (a.follow_up_date || '').localeCompare(b.follow_up_date || '');
        });
    } else {
        matched.sort((a, b) =>
            (b.updated_at || '').localeCompare(a.updated_at || '')
        );
    }
    return matched;
}

// v7.16: outreach template registry, fetched once at init from
// /api/leads/templates. Empty until loadMessageTemplates() resolves —
// the per-card <select> just shows "Auto" only in that window.
let _messageTemplates = [];

async function loadMessageTemplates() {
    try {
        const r = await fetch('/api/leads/templates');
        if (!r.ok) throw new Error('http ' + r.status);
        const d = await r.json();
        _messageTemplates = d.templates || [];
    } catch (e) {
        _messageTemplates = [];
    }
}

function _templateLabel(key) {
    const t = _messageTemplates.find(x => x.key === key);
    return t ? t.label : key;
}

// v7.17: substitute {name} and {company} into a template body, mirroring
// the server's draft_message logic. Pure local — no fetch per hover.
function _renderTemplatePreview(body, lead) {
    if (!body || !lead) return '';
    const name    = ((lead.name    || '').trim()) || 'there';
    const company = ((lead.company || '').trim()) || 'your business';
    return body.replace(/\{name\}/g, name).replace(/\{company\}/g, company);
}

function _renderTemplateSelect(leadId) {
    const lead = _leads.find(l => l.id === leadId);
    // v7.18: default to the lead's last_template_key if it points at
    // a still-registered template. If the key has drifted (template
    // renamed/removed), fall through to '' which renders Auto.
    const lastKey = lead && lead.last_template_key;
    const defaultKey = (lastKey && _messageTemplates.some(t => t.key === lastKey))
        ? lastKey : '';
    const sel = (v) => v === defaultKey ? ' selected' : '';
    const opts = _messageTemplates.map(t => {
        // Native title= tooltip on each <option>. Browser support is
        // patchy for in-dropdown tooltips (Firefox: yes, Chromium:
        // mostly, Safari: hover delay) but it's the lightest path
        // and degrades gracefully — worst case the user sees no
        // tooltip, which matches v7.16 behavior.
        const preview = _renderTemplatePreview(t.body, lead);
        return `<option value="${_escape(t.key)}" ` +
            `title="${_escape(preview)}"${sel(t.key)}>${_escape(t.label)}</option>`;
    }).join('');
    // v7.18: also seed the select's own title= so hover-on-closed
    // matches the default selection without waiting for a `change`.
    const initialTitle = defaultKey
        ? _renderTemplatePreview(
            (_messageTemplates.find(t => t.key === defaultKey) || {}).body,
            lead,
        )
        : 'Auto: server picks template based on lead status';
    return (
        `<select class="lead-template-select" ` +
            `data-lead-id="${_escape(leadId)}" aria-label="Message template" ` +
            `title="${_escape(initialTitle)}">` +
            `<option value=""${sel('')}>Auto</option>${opts}` +
        `</select>`
    );
}

// v7.5: short-lived in-card toast. Used by Mark Contacted to surface
// the v7.3 server-side auto-snooze ("Follow-up cleared (was X)") so
// the behavior is discoverable. Generic enough to reuse for other
// per-lead status messages without renaming.
//
// v7.11 extensions:
//   - leadId may be null/missing → toast attaches to #leads-list (the
//     section-level fallback for Add Lead errors where no card exists).
//   - type === 'error' → red palette + longer fade (5.0s / 5.8s) so the
//     user has time to read what failed. Replaces 8 blocking alert()s.
function _flashLeadToast(leadId, message, type) {
    let parent = leadId
        ? document.querySelector(`.lead-card[data-lead-id="${leadId}"]`)
        : null;
    if (!parent) parent = document.getElementById('leads-list');
    if (!parent) return;
    // Drop any prior toast in this scope so back-to-back actions don't
    // stack messages. Per-card and section-level toasts are scoped
    // separately because they have different parents.
    parent.querySelectorAll(':scope > .lead-toast').forEach(t => t.remove());
    const toast = document.createElement('div');
    toast.className = type === 'error'
        ? 'lead-toast lead-toast-error'
        : 'lead-toast';
    toast.textContent = message;
    parent.prepend(toast);
    const fadeAt   = type === 'error' ? 5000 : 2500;
    const removeAt = type === 'error' ? 5800 : 3200;
    setTimeout(() => { toast.classList.add('fade-out'); }, fadeAt);
    setTimeout(() => { toast.remove(); }, removeAt);
}

// v7.4: outreach-cadence presets for the follow-up form. One click
// sets the date and saves immediately — the date input + Save is left
// in place for custom dates.
const _FOLLOWUP_PRESETS = [
    { label: 'Tomorrow', days: 1 },
    { label: '+1 week',  days: 7 },
    { label: '+2 weeks', days: 14 },
    { label: '+1 month', days: 30 },
];
function _renderFollowUpPresets(leadId) {
    // v7.6: title also shows the number hotkey (1-4 → preset index).
    return _FOLLOWUP_PRESETS.map((p, i) =>
        `<button type="button" class="lead-followup-preset" ` +
            `data-action="lead-followup-preset" ` +
            `data-lead-id="${_escape(leadId)}" ` +
            `data-days="${p.days}" ` +
            `title="Set follow-up to ${_addDays(_todayStr(), p.days)} (press ${i + 1})">${p.label}</button>`
    ).join('');
}

function _renderLeadView(l) {
    const status = (l.status || 'cold').toLowerCase();
    const handleHtml = l.handle
        ? `<div class="lead-handle"><a href="${_escape(l.handle)}" ` +
          `target="_blank" rel="noopener noreferrer">${_escape(l.handle)}</a></div>`
        : '';
    const sourceHtml = l.source
        ? `<div class="lead-source">Source: ${_escape(l.source)}</div>` : '';
    const notesHtml = l.notes
        ? `<div class="lead-notes">${_escape(l.notes)}</div>` : '';
    const companyHtml = l.company
        ? `<div class="lead-company">${_escape(l.company)}</div>` : '';
    // v7.0: follow-up queue metadata. Only render lines that have data.
    const contactedHtml = l.contacted_at
        ? `<div class="lead-followup-line">Contacted: ${_escape(l.contacted_at)}</div>` : '';
    let followUpHtml = '';
    if (l.follow_up_date) {
        const today = _todayStr();
        const overdue = l.follow_up_date < today;
        const isToday = l.follow_up_date === today;
        const suffix = overdue ? ' (overdue)' : (isToday ? ' (today)' : '');
        const cls = overdue
            ? 'lead-followup-line lead-followup-overdue'
            : 'lead-followup-line lead-followup-due';
        followUpHtml = `<div class="${cls}">Follow up: ` +
            `${_escape(l.follow_up_date)}${suffix}</div>`;
    }
    const lastMessageHtml = l.last_message
        ? `<details class="lead-last-message"><summary>Last message draft</summary>` +
          `<pre>${_escape(l.last_message)}</pre></details>` : '';
    return (
        `<div class="lead-card" data-lead-id="${_escape(l.id)}">` +
          `<h3>${_escape(l.name)}` +
            `<span class="lead-status-badge lead-status-${_escape(status)}">${_escape(status)}</span>` +
          `</h3>` +
          companyHtml + handleHtml + sourceHtml + notesHtml +
          contactedHtml + followUpHtml + lastMessageHtml +
          `<div class="lead-meta">Updated ${_escape(l.updated_at || '')}</div>` +
          `<div class="lead-actions">` +
            // v7.16: template select sits LEFT of Write Message so the
            // reading order matches "pick template → generate".
            _renderTemplateSelect(l.id) +
            `<button type="button" class="row-action primary" data-action="lead-message" ` +
              `data-lead-id="${_escape(l.id)}">Write Message</button>` +
            `<button type="button" class="row-action" data-action="lead-contacted" ` +
              `data-lead-id="${_escape(l.id)}">Mark Contacted</button>` +
            `<button type="button" class="row-action" data-action="lead-followup-toggle" ` +
              `data-lead-id="${_escape(l.id)}">Follow Up</button>` +
            `<button type="button" class="row-action" data-action="lead-edit" ` +
              `data-lead-id="${_escape(l.id)}">Edit</button>` +
            `<button type="button" class="row-action danger" data-action="lead-delete" ` +
              `data-lead-id="${_escape(l.id)}">Delete</button>` +
          `</div>` +
          // Hidden inline date-picker that "Follow Up" toggles.
          // v7.4: preset buttons (one click → set date + save) for the
          // common outreach cadences. The date input + Save still works
          // for custom dates.
          `<form class="lead-followup-form" hidden data-lead-id="${_escape(l.id)}">` +
            `<input type="date" name="follow_up_date" ` +
              `value="${_escape(l.follow_up_date || '')}" aria-label="Follow-up date">` +
            `<button type="submit" class="primary">Save date</button>` +
            _renderFollowUpPresets(l.id) +
            `<button type="button" data-action="lead-followup-clear">Clear</button>` +
          `</form>` +
        `</div>`
    );
}

function _renderLeadEditForm(l) {
    // Mirror the add-form shape; pre-populated with this lead's values.
    const statusOpts = ['cold', 'warm', 'hot', 'closed', 'dropped'].map(s =>
        `<option value="${s}"${l.status === s ? ' selected' : ''}>${s}</option>`
    ).join('');
    return (
        `<form class="leads-form" data-lead-id="${_escape(l.id)}" data-action="lead-save-form">` +
          `<input class="leads-input" name="name"    value="${_escape(l.name || '')}" required>` +
          `<input class="leads-input" name="company" value="${_escape(l.company || '')}" placeholder="Company">` +
          `<input class="leads-input" name="handle"  value="${_escape(l.handle  || '')}" placeholder="LinkedIn URL or handle">` +
          `<input class="leads-input" name="source"  value="${_escape(l.source  || '')}" placeholder="Source">` +
          `<select class="leads-input" name="status">${statusOpts}</select>` +
          `<textarea class="leads-input" name="notes" rows="2"`+
            ` placeholder="Notes">${_escape(l.notes || '')}</textarea>` +
          `<div class="leads-form-actions">` +
            `<button type="submit" class="primary">Save changes</button>` +
            `<button type="button" data-action="lead-edit-cancel">Cancel</button>` +
          `</div>` +
        `</form>`
    );
}

// v7.2: update the "due this week" chip. Count is computed against the
// full _leads pool (not the filtered list) so the chip is a stable
// signal even when the user is mid-search.
function _updateLeadsDueChip() {
    const chip = document.getElementById('leads-due-chip');
    if (!chip) return;
    const today = _todayStr();
    const horizon = _addDays(today, 6);
    const n = _leads.filter(l => _isDueThisWeek(l, today, horizon)).length;
    if (n === 0) {
        chip.hidden = true;
        // If the filter was on but nothing qualifies any more, clear it
        // so the user doesn't end up looking at an empty list with no
        // visible reason why.
        if (_leadsDueFilter) {
            _leadsDueFilter = false;
            chip.setAttribute('aria-pressed', 'false');
        }
        return;
    }
    chip.hidden = false;
    chip.textContent = `${n} due this week`;
    chip.setAttribute('aria-pressed', _leadsDueFilter ? 'true' : 'false');
}

function renderLeads() {
    const el = document.getElementById('leads-list');
    const counter = document.getElementById('leads-count');
    if (!el) return;
    _updateLeadsDueChip();
    _updateClearFiltersBtn();  // v7.26
    const filtered = _filteredLeads();
    if (counter) {
        const total = _leads.length;
        counter.textContent = filtered.length === total
            ? `${total} lead${total === 1 ? '' : 's'}`
            : `Showing ${filtered.length} of ${total}`;
    }
    if (_leads.length === 0) {
        el.innerHTML = '<div class="muted">No leads yet. Click "+ Add Lead" to add one.</div>';
        return;
    }
    if (filtered.length === 0) {
        // v7.10: when the due-this-week chip is the active filter,
        // an empty list is good news, not a "nothing matches" failure.
        const msg = _leadsDueFilter
            ? 'Nothing due this week — nice.'
            : 'No leads match the filter.';
        el.innerHTML = `<div class="muted">${msg}</div>`;
        return;
    }
    el.innerHTML = filtered.map(l =>
        l.id === _editingLeadId ? _renderLeadEditForm(l) : _renderLeadView(l)
    ).join('');
}

// v7.26: "Clear filters" escape hatch — visible iff any of the three
// stackable filters is active (text input, v7.2 due chip, v7.25
// dashboard filter). Click resets all three, updates the DOM controls
// that hold their state, and re-renders dashboard + board + list.
function _anyLeadsFilterActive() {
    return !!(
        (_leadsFilter && _leadsFilter.trim()) ||
        _leadsDueFilter ||
        _dashboardFilter
    );
}
function _updateClearFiltersBtn() {
    const btn = document.getElementById('leads-clear-filters');
    if (!btn) return;
    btn.hidden = !_anyLeadsFilterActive();
}
function _clearAllLeadsFilters() {
    _leadsFilter = '';
    _leadsDueFilter = false;
    _dashboardFilter = null;
    // Sync DOM controls so the user sees the reset reflected, not just
    // the list re-rendering with hidden filter state.
    const f = document.getElementById('leads-filter');
    if (f) f.value = '';
    const chip = document.getElementById('leads-due-chip');
    if (chip) chip.setAttribute('aria-pressed', 'false');
    renderLeadsDashboard();
    renderLeadsBoard();
    renderLeads();
}

// v7.25: dashboard click-to-filter. _dashboardFilter holds the key of
// the currently active card (or null). Predicate is applied to both
// the board (pre-grouping) and the list (joins _filteredLeads). Not
// persisted across reloads — it's an action filter, not a preference.
let _dashboardFilter = null;

function _dashboardPredicate(lead) {
    if (!_dashboardFilter) return true;
    const today = _todayStr();
    const month = today.slice(0, 7);
    const status = (lead.status || '').toLowerCase();
    const fu = lead.follow_up_date || '';
    switch (_dashboardFilter) {
        case 'cold':         return status === 'cold';
        case 'warm':         return status === 'warm';
        case 'hot':          return status === 'hot';
        case 'due':          return fu === today;
        case 'overdue':      return fu !== '' && fu < today;
        case 'closed-month': return status === 'closed' &&
                                    (lead.updated_at || '').slice(0, 7) === month;
        default:             return true;
    }
}

// v7.24: lead dashboard. Six-card summary strip computed purely from
// _leads — no new fetch, no schema change. Card order is fixed so the
// strip stays scannable. "Closed this month" uses updated_at as a
// proxy for "when the close happened" — it's the only timestamp on
// the row that re-stamps on a status flip, so a flip from cold→closed
// today updates it. Older closes whose updated_at predates this month
// won't double-count.
// v7.25: cards are now <button> elements with data-filter-key=... and
// aria-pressed mirroring _dashboardFilter. Click toggles the filter
// and triggers a full re-render of dashboard + board + list.
function _computeLeadsDashboard(leads, today) {
    const month = (today || '').slice(0, 7);  // 'YYYY-MM'
    const out = { cold: 0, warm: 0, hot: 0, due: 0, overdue: 0, closedMonth: 0 };
    for (const l of leads) {
        const status = (l.status || '').toLowerCase();
        if (status === 'cold') out.cold += 1;
        else if (status === 'warm') out.warm += 1;
        else if (status === 'hot')  out.hot  += 1;
        const fu = l.follow_up_date || '';
        if (fu === today) out.due += 1;
        else if (fu && fu < today) out.overdue += 1;
        if (status === 'closed') {
            const u = l.updated_at || '';
            // updated_at format is 'YYYY-MM-DD HH:MM:SS' — slice the YYYY-MM
            if (u.slice(0, 7) === month) out.closedMonth += 1;
        }
    }
    return out;
}

function renderLeadsDashboard() {
    const el = document.getElementById('leads-dashboard');
    if (!el) return;
    const today = _todayStr();
    const m = _computeLeadsDashboard(_leads, today);
    const cards = [
        { key: 'cold',         label: 'Cold',              value: m.cold,        tone: 'cold'    },
        { key: 'warm',         label: 'Warm',              value: m.warm,        tone: 'warm'    },
        { key: 'hot',          label: 'Hot',               value: m.hot,         tone: 'hot'     },
        { key: 'due',          label: 'Due Today',         value: m.due,         tone: 'due'     },
        { key: 'overdue',      label: 'Overdue',           value: m.overdue,     tone: 'overdue' },
        { key: 'closed-month', label: 'Closed This Month', value: m.closedMonth, tone: 'closed'  },
    ];
    el.innerHTML = cards.map(c => {
        const active = (_dashboardFilter === c.key);
        const titleSuffix = active ? ' — click to clear filter' : ' — click to filter';
        return (
            `<button type="button" class="leads-dashboard-card tone-${c.tone}" ` +
                `data-filter-key="${_escape(c.key)}" aria-pressed="${active}" ` +
                `title="${_escape(c.label)}: ${c.value}${titleSuffix}">` +
              `<div class="leads-dashboard-label">${_escape(c.label)}</div>` +
              `<div class="leads-dashboard-value">${c.value}</div>` +
            `</button>`
        );
    }).join('');
}

// v7.23: pipeline board. Renders the same _leads cache, grouped by
// status into 5 columns. Quick-move buttons on each card PUT a partial
// {status: x} body to the existing /api/leads/{id} endpoint — no new
// API surface, no schema change. The button matching the lead's
// CURRENT status is omitted so we don't surface no-op clicks.
const _LEADS_BOARD_COLUMNS = [
    { key: 'cold',    label: 'Cold'    },
    { key: 'warm',    label: 'Warm'    },
    { key: 'hot',     label: 'Hot'     },
    { key: 'closed',  label: 'Closed'  },
    { key: 'dropped', label: 'Dropped' },
];

function _renderBoardCard(lead) {
    const id = _escape(lead.id);
    const name = _escape(lead.name || '(unnamed)');
    const company = lead.company
        ? `<div class="leads-board-card-meta">${_escape(lead.company)}</div>` : '';
    // Follow-up date with overdue cue (mirrors v7.1 styling).
    let followUp = '';
    if (lead.follow_up_date) {
        const today = _todayStr();
        const overdue = lead.follow_up_date < today;
        const isToday = lead.follow_up_date === today;
        const suffix = overdue ? ' (overdue)' : (isToday ? ' (today)' : '');
        const cls = overdue ? 'leads-board-card-meta leads-board-card-fu-overdue'
                            : 'leads-board-card-meta';
        followUp = `<div class="${cls}">Follow up: ${_escape(lead.follow_up_date)}${suffix}</div>`;
    }
    // Last template used (v7.18).
    const lastTmpl = lead.last_template_key
        ? `<div class="leads-board-card-meta">Last template: ${_escape(_templateLabel(lead.last_template_key))}</div>`
        : '';
    // Quick-move buttons. Spec lists Move to Warm / Hot / Closed / Drop;
    // skip the button matching the lead's current status.
    const moveTargets = [
        { status: 'warm',    label: 'Move to Warm',   danger: false },
        { status: 'hot',     label: 'Move to Hot',    danger: false },
        { status: 'closed',  label: 'Move to Closed', danger: false },
        { status: 'dropped', label: 'Drop',           danger: true  },
    ];
    const buttons = moveTargets
        .filter(t => t.status !== (lead.status || '').toLowerCase())
        .map(t =>
            `<button type="button" class="leads-board-move-btn${t.danger ? ' danger' : ''}" ` +
                `data-action="board-move" ` +
                `data-lead-id="${id}" data-target-status="${_escape(t.status)}">` +
                `${_escape(t.label)}` +
            `</button>`
        ).join('');
    return (
        // v7.27: draggable=true enables HTML5 DnD. Buttons stay as
        // the keyboard/touch fallback so non-mouse users aren't locked
        // out (DnD is mouse-only by spec without polyfills).
        `<div class="leads-board-card" data-lead-id="${id}" draggable="true">` +
          `<div class="leads-board-card-name">${name}</div>` +
          company + followUp + lastTmpl +
          `<div class="leads-board-card-actions">${buttons}</div>` +
        `</div>`
    );
}

function renderLeadsBoard() {
    const el = document.getElementById('leads-board');
    if (!el) return;
    // v7.25: filter leads via the dashboard predicate BEFORE grouping
    // so a dashboard click that says "overdue" only shows overdue
    // leads inside their natural status columns.
    const visible = _leads.filter(_dashboardPredicate);
    // Group leads by status. Unknown statuses (defensive — shouldn't
    // happen since the server validates against ALLOWED_STATUSES) get
    // bucketed into Cold so they're still visible.
    const groups = Object.fromEntries(_LEADS_BOARD_COLUMNS.map(c => [c.key, []]));
    for (const lead of visible) {
        const s = (lead.status || 'cold').toLowerCase();
        if (groups[s]) groups[s].push(lead);
        else groups.cold.push(lead);
    }
    el.innerHTML = _LEADS_BOARD_COLUMNS.map(col => {
        const items = groups[col.key];
        const cardsHtml = items.length
            ? items.map(_renderBoardCard).join('')
            : `<div class="leads-board-cards-empty">No leads</div>`;
        // v7.27: data-status lets the drop handler read the target.
        return (
            `<div class="leads-board-column status-${col.key}" ` +
                `data-status="${_escape(col.key)}">` +
              `<div class="leads-board-column-header">` +
                `<span>${_escape(col.label)}</span>` +
                `<span class="leads-board-count">${items.length}</span>` +
              `</div>` +
              `<div class="leads-board-cards">${cardsHtml}</div>` +
            `</div>`
        );
    }).join('');
}

async function loadLeads() {
    try {
        const r = await fetch('/api/leads');
        if (!r.ok) throw new Error('http ' + r.status);
        const d = await r.json();
        _leads = d.items || [];
        renderLeads();
        renderLeadsBoard();      // v7.23
        renderLeadsDashboard();  // v7.24
    } catch (err) {
        _leads = [];
        const el = document.getElementById('leads-list');
        if (el) el.innerHTML = '<div class="muted">Could not load leads.</div>';
        renderLeadsBoard();      // v7.23: render empty board on fetch failure too
        renderLeadsDashboard();  // v7.24: empty dashboard on failure too
    }
}

// --- v7.28: Lead Scout Queue --------------------------------------------
// Manual capture surface for businesses Topher spots in the wild. No
// scraping, no auto-outreach, no OpenAI. Convert promotes a scout row
// into the existing Logan registry via POST /api/scout-leads/{id}/convert.

let _scoutLeads = [];

function _renderScoutCard(s) {
    const id = _escape(s.id);
    const name = _escape(s.business_name || '(unnamed)');
    const status = (s.status || 'new').toLowerCase();
    const prio = (s.priority || 'medium').toLowerCase();
    const meta = [];
    if (s.category)       meta.push(_escape(s.category));
    if (s.city_state)     meta.push(_escape(s.city_state));
    const metaLine = meta.length
        ? `<div class="scout-card-meta">${meta.join(' · ')}</div>` : '';
    const emailLine = s.contact_email
        ? `<div class="scout-card-meta">${_escape(s.contact_email)}</div>` : '';
    const sourceLine = s.contact_source
        ? `<div class="scout-card-meta">Source: ${_escape(s.contact_source)}</div>` : '';
    const websiteLine = s.website_status
        ? `<div class="scout-card-meta">Website: ${_escape(s.website_status)}</div>` : '';
    const evidenceLine = s.evidence
        ? `<div class="scout-card-evidence">Evidence: ${_escape(s.evidence)}</div>` : '';
    const offerLine = s.offer_angle
        ? `<div class="scout-card-offer">Offer: ${_escape(s.offer_angle)}</div>` : '';
    const notesLine = s.notes
        ? `<div class="scout-card-meta">Notes: ${_escape(s.notes)}</div>` : '';
    const convertedLine = s.converted_lead_id
        ? `<div class="scout-card-meta">→ Converted to Logan lead ` +
          `${_escape(s.converted_lead_id)}</div>` : '';
    // Buttons depend on status. Converted rows show no Qualify/Convert
    // (no-op), but Delete stays available.
    const buttons = [];
    if (status !== 'qualified' && status !== 'converted') {
        buttons.push(`<button type="button" class="row-action" ` +
            `data-action="scout-qualify" data-scout-id="${id}">Qualify</button>`);
    }
    if (status !== 'converted') {
        buttons.push(`<button type="button" class="row-action primary" ` +
            `data-action="scout-convert" data-scout-id="${id}">Convert to Lead</button>`);
    }
    if (status !== 'rejected' && status !== 'converted') {
        buttons.push(`<button type="button" class="row-action" ` +
            `data-action="scout-reject" data-scout-id="${id}">Reject</button>`);
    }
    buttons.push(`<button type="button" class="row-action danger" ` +
        `data-action="scout-delete" data-scout-id="${id}">Delete</button>`);

    return (
        `<div class="scout-card" data-scout-id="${id}">` +
          `<div class="scout-card-name">${name} ` +
            `<span class="scout-status-badge scout-status-${_escape(status)}">${_escape(status)}</span> ` +
            `<span class="scout-priority-badge scout-priority-${_escape(prio)}">${_escape(prio)}</span>` +
          `</div>` +
          metaLine + emailLine + sourceLine + websiteLine +
          evidenceLine + offerLine + notesLine + convertedLine +
          `<div class="scout-card-actions">${buttons.join('')}</div>` +
        `</div>`
    );
}

function renderScoutQueue() {
    const el = document.getElementById('scout-list');
    const counter = document.getElementById('scout-count');
    if (!el) return;
    if (counter) {
        counter.textContent = _scoutLeads.length
            ? `${_scoutLeads.length} scout lead${_scoutLeads.length === 1 ? '' : 's'}`
            : '';
    }
    if (_scoutLeads.length === 0) {
        el.innerHTML = '<div class="muted">No scout leads yet. ' +
            'Click "+ Add Scout Lead" to capture one.</div>';
        return;
    }
    // Sort: newest updated first, but converted/rejected sink to the
    // bottom so the active scouting queue stays at the top.
    const sortRank = s => {
        const st = (s.status || '').toLowerCase();
        if (st === 'converted' || st === 'rejected') return 1;
        return 0;
    };
    const sorted = _scoutLeads.slice().sort((a, b) => {
        const r = sortRank(a) - sortRank(b);
        if (r !== 0) return r;
        return (b.updated_at || '').localeCompare(a.updated_at || '');
    });
    el.innerHTML = sorted.map(_renderScoutCard).join('');
}

async function loadScoutLeads() {
    try {
        const r = await fetch('/api/scout-leads');
        if (!r.ok) throw new Error('http ' + r.status);
        const d = await r.json();
        _scoutLeads = d.items || [];
        renderScoutQueue();
    } catch (err) {
        _scoutLeads = [];
        const el = document.getElementById('scout-list');
        if (el) el.innerHTML = '<div class="muted">Could not load scout queue.</div>';
    }
}

// Toggle the add-scout form.
const _scoutAddToggle = document.getElementById('scout-add-toggle');
const _scoutAddForm   = document.getElementById('scout-add-form');
if (_scoutAddToggle && _scoutAddForm) {
    _scoutAddToggle.addEventListener('click', () => {
        const hidden = _scoutAddForm.hidden;
        _scoutAddForm.hidden = !hidden;
        if (hidden) {
            const first = _scoutAddForm.querySelector('input[name="business_name"]');
            if (first) first.focus();
        }
    });
}

// Add-scout-lead form submit.
if (_scoutAddForm) {
    _scoutAddForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(_scoutAddForm).entries());
        try {
            const r = await fetch('/api/scout-leads', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || 'http ' + r.status);
            _scoutAddForm.reset();
            _scoutAddForm.hidden = true;
            await loadScoutLeads();
        } catch (err) {
            // Surface scout errors on the scout list (no per-card scope
            // yet — failures during add land at the section level).
            const el = document.getElementById('scout-list');
            if (el) {
                const div = document.createElement('div');
                div.className = 'muted';
                div.style.color = '#8a1c1c';
                div.textContent = 'Add failed: ' + err.message;
                el.prepend(div);
                setTimeout(() => div.remove(), 5000);
            }
        }
    });
    _scoutAddForm.addEventListener('click', (e) => {
        if (e.target.dataset.action === 'cancel-scout-add') {
            _scoutAddForm.hidden = true;
        }
    });
}

// Per-card action delegator: Qualify / Convert / Reject / Delete.
const _scoutListEl = document.getElementById('scout-list');
if (_scoutListEl) {
    _scoutListEl.addEventListener('click', async (e) => {
        const btn = e.target.closest('button[data-action]');
        if (!btn) return;
        const action = btn.dataset.action;
        const scoutId = btn.dataset.scoutId;
        if (!scoutId) return;

        try {
            if (action === 'scout-qualify') {
                const r = await fetch(
                    `/api/scout-leads/${encodeURIComponent(scoutId)}`,
                    {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ status: 'qualified' }),
                    },
                );
                const d = await r.json();
                if (!r.ok) throw new Error(d.detail || 'http ' + r.status);
                await loadScoutLeads();
                return;
            }
            if (action === 'scout-reject') {
                if (!confirm('Reject this scout lead?')) return;
                const r = await fetch(
                    `/api/scout-leads/${encodeURIComponent(scoutId)}`,
                    {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ status: 'rejected' }),
                    },
                );
                const d = await r.json();
                if (!r.ok) throw new Error(d.detail || 'http ' + r.status);
                await loadScoutLeads();
                return;
            }
            if (action === 'scout-delete') {
                const scout = _scoutLeads.find(s => s.id === scoutId);
                const label = scout ? scout.business_name : scoutId;
                if (!confirm(`Delete scout lead "${label}"? This cannot be undone.`)) return;
                const r = await fetch(
                    `/api/scout-leads/${encodeURIComponent(scoutId)}`,
                    { method: 'DELETE' },
                );
                if (!r.ok) {
                    const d = await r.json().catch(() => ({}));
                    throw new Error(d.detail || 'http ' + r.status);
                }
                await loadScoutLeads();
                return;
            }
            if (action === 'scout-convert') {
                const scout = _scoutLeads.find(s => s.id === scoutId);
                const label = scout ? scout.business_name : scoutId;
                if (!confirm(
                    `Convert "${label}" into a Logan/LinkedIn Lead?\n\n` +
                    `This copies the scout row into the Logan registry as a ` +
                    `cold lead. No outreach is sent — you still have to ` +
                    `message manually.`
                )) return;
                const r = await fetch(
                    `/api/scout-leads/${encodeURIComponent(scoutId)}/convert`,
                    { method: 'POST' },
                );
                const d = await r.json();
                if (!r.ok) throw new Error(d.detail || 'http ' + r.status);
                await loadScoutLeads();
                await loadLeads();  // refresh Logan side
                document.getElementById('cmd-status').textContent =
                    `Converted "${label}" → new Logan lead id ${d.lead.id}.`;
                return;
            }
        } catch (err) {
            document.getElementById('cmd-status').textContent =
                'Scout action failed: ' + (err.message || err);
        }
    });
}

// Filter input → re-render (no fetch).
const _leadsFilterEl = document.getElementById('leads-filter');
if (_leadsFilterEl) {
    _leadsFilterEl.addEventListener('input', () => {
        _leadsFilter = _leadsFilterEl.value || '';
        renderLeads();
    });
}

// v7.1: sort selector. Initial value reflects the persisted choice so
// the <select> matches what the list is actually doing on first paint.
const _leadsSortEl = document.getElementById('leads-sort');
if (_leadsSortEl) {
    _leadsSortEl.value = _leadsSort;
    _leadsSortEl.addEventListener('change', () => {
        _leadsSort = _leadsSortEl.value === 'follow-up' ? 'follow-up' : 'updated';
        try { localStorage.setItem(_LEADS_SORT_KEY, _leadsSort); } catch (e) {}
        renderLeads();
    });
}

// v7.2: due-this-week chip toggles a filter restricting the list to
// leads with follow_up_date in the next 7 days. Not persisted across
// reloads — it's an action filter, not a preference.
const _leadsDueChipEl = document.getElementById('leads-due-chip');
if (_leadsDueChipEl) {
    _leadsDueChipEl.addEventListener('click', () => {
        _leadsDueFilter = !_leadsDueFilter;
        renderLeads();
    });
}

// v7.6: number-key hotkeys for the follow-up form. Pressing 1-4 fires
// the corresponding preset (Tomorrow / +1 week / +2 weeks / +1 month)
// when focus is inside a visible follow-up form. The date input,
// textareas, and other inputs are explicitly excluded so manual typing
// (e.g., a custom date) still works normally. Document-level listener
// because the form DOM gets re-rendered on every loadLeads() and we
// don't want to re-bind on every render.
function _onFollowUpHotkey(e) {
    if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    const idx = { '1': 0, '2': 1, '3': 2, '4': 3 }[e.key];
    if (idx === undefined) return;
    const active = document.activeElement;
    if (!active) return;
    const form = active.closest && active.closest('.lead-followup-form');
    if (!form || form.hidden) return;
    // Don't hijack typing into any input/textarea/select inside the form.
    if (active.matches('input, textarea, select')) return;
    const btn = form.querySelectorAll(
        '[data-action="lead-followup-preset"]'
    )[idx];
    if (btn) {
        e.preventDefault();
        btn.click();
    }
}
document.addEventListener('keydown', _onFollowUpHotkey);

// "+ Add Lead" toggles the add form.
const _leadsAddToggle = document.getElementById('leads-add-toggle');
const _leadsAddForm = document.getElementById('leads-add-form');
if (_leadsAddToggle && _leadsAddForm) {
    _leadsAddToggle.addEventListener('click', () => {
        const hidden = _leadsAddForm.hidden;
        _leadsAddForm.hidden = !hidden;
        if (hidden) {
            _leadsAddForm.querySelector('input[name="name"]').focus();
        }
    });
}

// v7.20: bulk paste-import form.
const _leadsBulkToggle = document.getElementById('leads-bulk-toggle');
const _leadsBulkForm   = document.getElementById('leads-bulk-form');
if (_leadsBulkToggle && _leadsBulkForm) {
    _leadsBulkToggle.addEventListener('click', () => {
        const hidden = _leadsBulkForm.hidden;
        _leadsBulkForm.hidden = !hidden;
        if (hidden) {
            const ta = _leadsBulkForm.querySelector('textarea');
            if (ta) ta.focus();
        }
    });
}
if (_leadsBulkForm) {
    _leadsBulkForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const text = _leadsBulkForm.querySelector('textarea').value;
        try {
            const r = await fetch('/api/leads/batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text }),
            });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || 'http ' + r.status);
            const addedN = (d.added || []).length;
            const dupN   = (d.skipped_duplicates || []).length;
            const invN   = (d.skipped_invalid    || []).length;
            // Build a terse summary: 'Added N' plus only non-zero qualifiers.
            const parts = [`Added ${addedN}`];
            if (dupN) parts.push(`${dupN} duplicate${dupN === 1 ? '' : 's'}`);
            if (invN) parts.push(`${invN} unrecognized`);
            const summary = parts.join(', ') + '.';
            _leadsBulkForm.reset();
            _leadsBulkForm.hidden = true;
            await loadLeads();
            // Section-level toast (no leadId — addedN may be >1, no single card to attach to).
            _flashLeadToast(null, summary);
        } catch (err) {
            _flashLeadToast(null, 'Bulk import failed: ' + err.message, 'error');
        }
    });
    _leadsBulkForm.addEventListener('click', (e) => {
        if (e.target.dataset.action === 'cancel-bulk') {
            _leadsBulkForm.hidden = true;
        }
    });
}

// Add form submit.
if (_leadsAddForm) {
    _leadsAddForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(_leadsAddForm).entries());
        try {
            const r = await fetch('/api/leads', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || 'http ' + r.status);
            _leadsAddForm.reset();
            _leadsAddForm.hidden = true;
            await loadLeads();
        } catch (err) {
            _flashLeadToast(null, 'Add failed: ' + err.message, 'error');
        }
    });
    _leadsAddForm.addEventListener('click', (e) => {
        if (e.target.dataset.action === 'cancel-add') {
            _leadsAddForm.hidden = true;
        }
    });
}

// Edit/Delete/Save delegators on the lead list.
// v7.23: board click delegator. PUT /api/leads/{id} accepts a partial
// body (LeadIn fields all optional), so we send just {status: x}.
// Server's _clean_lead validates against ALLOWED_STATUSES; an unknown
// status returns 400 and surfaces in a red error toast.
// v7.26: clear-filters button click — reset all three filters at once.
const _leadsClearFiltersEl = document.getElementById('leads-clear-filters');
if (_leadsClearFiltersEl) {
    _leadsClearFiltersEl.addEventListener('click', _clearAllLeadsFilters);
}

// v7.25: dashboard click delegator. Toggles _dashboardFilter on the
// matching card, then re-renders dashboard + board + list so all three
// surfaces stay consistent without another fetch.
const _leadsDashboardEl = document.getElementById('leads-dashboard');
if (_leadsDashboardEl) {
    _leadsDashboardEl.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-filter-key]');
        if (!btn) return;
        const key = btn.dataset.filterKey;
        _dashboardFilter = (_dashboardFilter === key) ? null : key;
        renderLeadsDashboard();
        renderLeadsBoard();
        renderLeads();
    });
}

// v7.27: shared move helper used by both the v7.23 button click and
// the DnD drop handler below. Single PUT path means safety gates,
// error handling, and toast text stay consistent across both UIs.
const _LEADS_STATUS_LABEL = {
    cold: 'Cold', warm: 'Warm', hot: 'Hot',
    closed: 'Closed', dropped: 'Dropped',
};
async function _moveLeadToStatus(leadId, targetStatus) {
    if (!leadId || !targetStatus) return;
    try {
        const r = await fetch(
            `/api/leads/${encodeURIComponent(leadId)}`,
            {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status: targetStatus }),
            },
        );
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || 'http ' + r.status);
        await loadLeads();
        const tgtLabel = _LEADS_STATUS_LABEL[targetStatus] || targetStatus;
        _flashLeadToast(leadId, `Moved to ${tgtLabel}`);
    } catch (err) {
        _flashLeadToast(leadId, 'Move failed: ' + err.message, 'error');
    }
}

const _leadsBoardEl = document.getElementById('leads-board');
if (_leadsBoardEl) {
    // v7.23 buttons — keyboard/touch path.
    _leadsBoardEl.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-action="board-move"]');
        if (!btn) return;
        _moveLeadToStatus(btn.dataset.leadId, btn.dataset.targetStatus);
    });

    // v7.27: HTML5 drag-and-drop, delegated so listeners survive every
    // renderLeadsBoard() that rewrites the DOM. Source id is tracked
    // in a closure var (faster than reading dataTransfer on every
    // dragover, which fires constantly).
    let _dndSourceLeadId = null;
    _leadsBoardEl.addEventListener('dragstart', (e) => {
        const card = e.target.closest('.leads-board-card[data-lead-id]');
        if (!card) return;
        _dndSourceLeadId = card.dataset.leadId;
        if (e.dataTransfer) {
            e.dataTransfer.effectAllowed = 'move';
            // Firefox refuses to drag unless dataTransfer has data set.
            try { e.dataTransfer.setData('text/plain', _dndSourceLeadId); }
            catch (_) {}
        }
        card.classList.add('is-dragging');
    });
    _leadsBoardEl.addEventListener('dragend', (e) => {
        const card = e.target.closest('.leads-board-card');
        if (card) card.classList.remove('is-dragging');
        // Belt + suspenders: wipe any lingering drop-target outlines.
        _leadsBoardEl.querySelectorAll('.leads-board-column.is-drop-target')
            .forEach(c => c.classList.remove('is-drop-target'));
        _dndSourceLeadId = null;
    });
    _leadsBoardEl.addEventListener('dragenter', (e) => {
        const col = e.target.closest('.leads-board-column');
        if (col) col.classList.add('is-drop-target');
    });
    _leadsBoardEl.addEventListener('dragleave', (e) => {
        const col = e.target.closest('.leads-board-column');
        // dragleave fires when crossing into children too — only
        // remove the class when truly leaving the column subtree.
        if (col && (!e.relatedTarget || !col.contains(e.relatedTarget))) {
            col.classList.remove('is-drop-target');
        }
    });
    _leadsBoardEl.addEventListener('dragover', (e) => {
        // preventDefault is REQUIRED for the drop event to fire.
        if (e.target.closest('.leads-board-column')) e.preventDefault();
    });
    _leadsBoardEl.addEventListener('drop', (e) => {
        const col = e.target.closest('.leads-board-column');
        if (!col || !_dndSourceLeadId) return;
        e.preventDefault();
        const target = col.dataset.status;
        // Skip same-column drops to avoid a no-op PUT that would still
        // re-stamp updated_at (and inflate the v7.24 "closed this
        // month" count for closed leads).
        const lead = _leads.find(l => l.id === _dndSourceLeadId);
        if (lead && (lead.status || '').toLowerCase() === target) {
            col.classList.remove('is-drop-target');
            return;
        }
        _moveLeadToStatus(_dndSourceLeadId, target);
        col.classList.remove('is-drop-target');
    });
}

const _leadsListEl = document.getElementById('leads-list');
// v7.17 (relocated from above the declaration to fix TDZ crash that
// hung the whole Hub on "Loading…"): when the user changes a template
// select, copy the chosen option's title= up to the select itself so
// hovering the closed control shows the right preview (Chromium
// ignores per-option titles on the closed select).
if (_leadsListEl) {
    _leadsListEl.addEventListener('change', (e) => {
        const sel = e.target.closest('.lead-template-select');
        if (!sel) return;
        const opt = sel.options[sel.selectedIndex];
        sel.title = opt ? (opt.title || opt.text) : '';
    });
}
if (_leadsListEl) {
    _leadsListEl.addEventListener('click', async (e) => {
        const btn = e.target.closest('button[data-action]');
        if (!btn) return;
        const action = btn.dataset.action;
        const leadId = btn.dataset.leadId;

        if (action === 'lead-edit') {
            _editingLeadId = leadId;
            renderLeads();
            return;
        }
        if (action === 'lead-edit-cancel') {
            _editingLeadId = null;
            renderLeads();
            return;
        }
        if (action === 'lead-delete') {
            const lead = _leads.find(l => l.id === leadId);
            const label = lead ? lead.name : leadId;
            if (!confirm(`Delete lead "${label}"? This cannot be undone.`)) return;
            try {
                const r = await fetch(`/api/leads/${encodeURIComponent(leadId)}`,
                                      { method: 'DELETE' });
                if (!r.ok) {
                    const d = await r.json().catch(() => ({}));
                    throw new Error(d.detail || 'http ' + r.status);
                }
                await loadLeads();
            } catch (err) {
                _flashLeadToast(leadId, 'Delete failed: ' + err.message, 'error');
            }
            return;
        }
        // v7.0 follow-up queue actions
        if (action === 'lead-message') {
            // v7.16: read the per-card template select. Empty value =>
            // server picks based on lead status; explicit key overrides.
            const sel = document.querySelector(
                `.lead-template-select[data-lead-id="${leadId}"]`
            );
            const template = sel ? sel.value : '';
            try {
                const r = await fetch(
                    `/api/leads/${encodeURIComponent(leadId)}/message-draft`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(template ? { template } : {}),
                    },
                );
                const d = await r.json();
                if (!r.ok) throw new Error(d.detail || 'http ' + r.status);
                _showLeadMessageInOutput(d.message);
                await loadLeads();  // last_message is now populated
                // v7.9/v7.16: toast names the template that ran so the
                // user can confirm Auto picked what they expected.
                const usedLabel = _templateLabel(d.template || '');
                _flashLeadToast(leadId, `Draft ready: ${usedLabel}`);
            } catch (err) {
                _flashLeadToast(leadId, 'Message draft failed: ' + err.message, 'error');
            }
            return;
        }
        if (action === 'lead-contacted') {
            if (!confirm('Mark this lead as contacted?')) return;
            // v7.5: capture the prior follow_up_date so we can detect
            // the v7.3 server-side auto-snooze and surface it as a toast.
            const prevLead = _leads.find(l => l.id === leadId);
            const prevFollowUp = prevLead ? prevLead.follow_up_date : null;
            try {
                const r = await fetch(
                    `/api/leads/${encodeURIComponent(leadId)}/contacted`,
                    { method: 'POST' },
                );
                const d = await r.json();
                if (!r.ok) throw new Error(d.detail || 'http ' + r.status);
                await loadLeads();
                if (prevFollowUp) {
                    const updated = _leads.find(l => l.id === leadId);
                    if (updated && !updated.follow_up_date) {
                        _flashLeadToast(leadId,
                            `Follow-up cleared (was ${prevFollowUp})`);
                    }
                }
            } catch (err) {
                _flashLeadToast(leadId, 'Mark contacted failed: ' + err.message, 'error');
            }
            return;
        }
        if (action === 'lead-followup-toggle') {
            // Show the inline date input on the same card.
            const form = document.querySelector(
                `.lead-followup-form[data-lead-id="${leadId}"]`
            );
            if (form) {
                form.hidden = !form.hidden;
                if (!form.hidden) {
                    // v7.6: focus the first preset button (not the date
                    // input) so the 1-4 number hotkeys are immediately
                    // usable. Users who want a custom date can
                    // Shift+Tab to the date input or click it directly.
                    const firstPreset = form.querySelector(
                        '[data-action="lead-followup-preset"]'
                    );
                    if (firstPreset) {
                        firstPreset.focus();
                    } else {
                        const input = form.querySelector('input[name="follow_up_date"]');
                        if (input) input.focus();
                    }
                }
            }
            return;
        }
        if (action === 'lead-followup-preset') {
            // One-click set: compute date locally, POST to /follow-up,
            // then re-render. Server validates the YYYY-MM-DD format.
            const days = parseInt(btn.dataset.days, 10);
            if (!Number.isFinite(days)) return;
            const date = _addDays(_todayStr(), days);
            try {
                const r = await fetch(
                    `/api/leads/${encodeURIComponent(leadId)}/follow-up`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ follow_up_date: date }),
                    },
                );
                const d = await r.json();
                if (!r.ok) throw new Error(d.detail || 'http ' + r.status);
                await loadLeads();
                // v7.7: same helper used by the v7.5 snooze indicator —
                // consistent feedback for any per-card status change.
                _flashLeadToast(leadId, `Follow-up set to ${date}`);
            } catch (err) {
                _flashLeadToast(leadId, 'Set follow-up failed: ' + err.message, 'error');
            }
            return;
        }
        if (action === 'lead-followup-clear') {
            // Send empty date string to clear the field.
            try {
                const r = await fetch(
                    `/api/leads/${encodeURIComponent(leadId)}/follow-up`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ follow_up_date: '' }),
                    },
                );
                const d = await r.json();
                if (!r.ok) throw new Error(d.detail || 'http ' + r.status);
                await loadLeads();
                _flashLeadToast(leadId, 'Follow-up cleared');
            } catch (err) {
                _flashLeadToast(leadId, 'Clear follow-up failed: ' + err.message, 'error');
            }
            return;
        }
    });
    // PUT (edit save) — caught via the form's submit event, not click.
    _leadsListEl.addEventListener('submit', async (e) => {
        // v7.0: follow-up date form submit
        const fuForm = e.target.closest('form.lead-followup-form');
        if (fuForm) {
            e.preventDefault();
            const leadId = fuForm.dataset.leadId;
            const date = fuForm.querySelector('input[name="follow_up_date"]').value;
            try {
                const r = await fetch(
                    `/api/leads/${encodeURIComponent(leadId)}/follow-up`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ follow_up_date: date }),
                    },
                );
                const d = await r.json();
                if (!r.ok) throw new Error(d.detail || 'http ' + r.status);
                await loadLeads();
                // v7.8: surface what actually happened. An empty Save
                // is rare (Clear is the canonical clear path) but
                // truthful feedback beats a misleading "set to ''".
                _flashLeadToast(leadId,
                    date ? `Follow-up set to ${date}` : 'Follow-up cleared');
            } catch (err) {
                _flashLeadToast(leadId, 'Save follow-up failed: ' + err.message, 'error');
            }
            return;
        }
        const form = e.target.closest('form[data-action="lead-save-form"]');
        if (!form) return;
        e.preventDefault();
        const leadId = form.dataset.leadId;
        const data = Object.fromEntries(new FormData(form).entries());
        try {
            const r = await fetch(`/api/leads/${encodeURIComponent(leadId)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || 'http ' + r.status);
            _editingLeadId = null;
            await loadLeads();
        } catch (err) {
            _flashLeadToast(leadId, 'Save failed: ' + err.message, 'error');
        }
    });
}

// v7.0: surface the lead's draft message in #cmd-output with a Copy
// button. The user copy-pastes into LinkedIn manually — we never send
// any message anywhere automatically.
function _showLeadMessageInOutput(message) {
    const cmdStatus = document.getElementById('cmd-status');
    const out = document.getElementById('cmd-output');
    if (!out) return;
    out.textContent = '';
    // Build a small toolbar + the message preformatted.
    const wrap = document.createElement('div');
    wrap.className = 'lead-message-wrap';
    const toolbar = document.createElement('div');
    toolbar.className = 'lead-message-toolbar';
    const copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'primary';
    copyBtn.textContent = 'Copy message';
    copyBtn.addEventListener('click', async () => {
        try {
            await navigator.clipboard.writeText(message);
            copyBtn.textContent = 'Copied ✓';
            setTimeout(() => { copyBtn.textContent = 'Copy message'; }, 2000);
        } catch (err) {
            copyBtn.textContent = 'Copy failed — select + ⌘C';
        }
    });
    const note = document.createElement('span');
    note.className = 'muted';
    note.style.marginLeft = '0.6rem';
    note.textContent = 'Paste into LinkedIn manually — Hub never sends messages automatically.';
    toolbar.appendChild(copyBtn);
    toolbar.appendChild(note);
    const pre = document.createElement('pre');
    pre.className = 'lead-message-pre';
    pre.textContent = message;
    wrap.appendChild(toolbar);
    wrap.appendChild(pre);
    out.appendChild(wrap);
    if (cmdStatus) cmdStatus.textContent = 'Message draft ready (see Command Output).';
    _cpScrollToH2('Command Output');
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
        case 'leads':
            // v6.9: scroll to the LinkedIn Leads section.
            if (!_cpScrollToH2('LinkedIn Leads')) {
                _cpStatus('LinkedIn Leads section not found.');
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

// v7.21: which platforms can the bulk-publish driver actually post to?
// Two requirements: (1) connection is verified, (2) we have a publish
// path wired (LinkedIn + Facebook today; Instagram/GBP still manual).
const _BULK_PUBLISH_PLATFORMS = [
    { label: 'LinkedIn', key: 'linkedin' },
    { label: 'Facebook', key: 'facebook' },
];

function _bulkPublishablePosts() {
    return _readyPosts.filter(p =>
        _BULK_PUBLISH_PLATFORMS.some(bp =>
            bp.label === p.platform && isPlatformConnected(bp.label)
        )
    );
}

function _updateBulkPublishButton() {
    const btn = document.getElementById('bulk-publish-btn');
    if (!btn) return;
    const eligible = _bulkPublishablePosts();
    if (eligible.length === 0) {
        btn.hidden = true;
        return;
    }
    btn.hidden = false;
    btn.textContent = `Publish ${eligible.length} verified`;
    // Per-platform breakdown in the tooltip for transparency.
    const counts = {};
    for (const p of eligible) counts[p.platform] = (counts[p.platform] || 0) + 1;
    btn.title = Object.entries(counts)
        .map(([k, v]) => `${v} ${k}`).join(' + ');
}

function renderReady(posts) {
    const el = document.getElementById('ready-list');
    _updateBulkPublishButton();
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

// v7.21: bulk publish — sequentially POST /publish for every ready
// post on a verified platform with a wired publisher (LinkedIn or
// Facebook today). ONE up-front confirm with counts; individual
// per-post confirms would be N modal prompts. Progress streams to
// cmd-output so failures are visible per-post.
async function _bulkPublishAllVerified() {
    const eligible = _bulkPublishablePosts();
    if (eligible.length === 0) {
        document.getElementById('cmd-status').textContent =
            'Nothing to publish — no ready posts on verified platforms.';
        return;
    }
    const counts = {};
    for (const p of eligible) counts[p.platform] = (counts[p.platform] || 0) + 1;
    const breakdown = Object.entries(counts)
        .map(([k, v]) => `${v} ${k}`).join(' + ');
    const proceed = confirm(
        `Publish ${eligible.length} verified post${eligible.length === 1 ? '' : 's'} now? ` +
        `This will go publicly live.\n\n` +
        `Breakdown: ${breakdown}\n\n` +
        `Posts will be published one at a time. Open Command Output to watch progress.`
    );
    if (!proceed) {
        document.getElementById('cmd-status').textContent =
            'Cancelled. Nothing was published.';
        return;
    }
    setBusy(true);
    const out = document.getElementById('cmd-output');
    const stat = document.getElementById('cmd-status');
    const progress = [];
    let ok = 0, fail = 0;
    stat.textContent = `Bulk publishing ${eligible.length} post(s)…`;
    out.textContent = '';
    // Map platform label → API platform key. Mirrors the per-row dispatch.
    const PLATFORM_KEY = { LinkedIn: 'linkedin', Facebook: 'facebook' };
    for (const p of eligible) {
        const platformKey = PLATFORM_KEY[p.platform];
        if (!platformKey) {
            progress.push(`SKIP #${p.id} (${p.platform}): no publish path`);
            out.textContent = progress.join('\n');
            continue;
        }
        try {
            const r = await fetch(
                `/api/posts/${encodeURIComponent(p.id)}/publish`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ platform: platformKey }),
                },
            );
            const d = await r.json();
            if (r.ok && d.ok) {
                ok += 1;
                progress.push(`OK   #${p.id} (${p.platform})`);
            } else {
                fail += 1;
                const err = d.message || d.detail || `HTTP ${r.status}`;
                progress.push(`FAIL #${p.id} (${p.platform}): ${err}`);
            }
        } catch (err) {
            fail += 1;
            progress.push(`FAIL #${p.id} (${p.platform}): ${err.message || err}`);
        }
        // Stream after each post so the user sees progress live.
        out.textContent = progress.join('\n');
        stat.textContent =
            `Bulk publishing… ${ok + fail}/${eligible.length} done (${fail} failed)`;
    }
    stat.textContent = `Bulk publish done — ${ok} ok, ${fail} failed.`;
    await refreshAll();
    setBusy(false);
}

// v7.21: bulk publish button — bound once at module load.
(function () {
    const btn = document.getElementById('bulk-publish-btn');
    if (btn) btn.addEventListener('click', _bulkPublishAllVerified);
})();

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

// v7.22: per-loader isolation so a single loader failure can't strand
// the rest of the Hub on "Loading…". Each loader name is logged so a
// failure surfaces visibly in Command Output instead of swallowing the
// whole refresh into one opaque toast.
async function _runLoaderSafely(name, fn) {
    try {
        await fn();
        return { name, ok: true };
    } catch (err) {
        return { name, ok: false, error: String(err && err.message || err) };
    }
}

async function refreshAll() {
    document.getElementById('cmd-status').textContent = 'Reloading…';
    // Two batches. The first is a prerequisite set (loadPartners /
    // loadConnections / loadMessageTemplates populate caches the second
    // batch reads), but a failure inside either batch must NOT block
    // sibling loaders any more.
    const batch1 = [
        ['loadPartners',         loadPartners],
        ['loadConnections',      loadConnections],
        ['loadMessageTemplates', loadMessageTemplates],
    ];
    const batch2 = [
        ['loadStatus',        loadStatus],
        ['loadSummary',       loadSummary],
        ['loadLogs',          loadLogs],
        ['loadHistory',       loadHistory],
        ['loadReady',         loadReady],
        ['loadActivity',      loadActivity],
        ['loadReports',       loadReports],
        ['loadInbox',         loadInbox],
        ['loadMetaReadiness', loadMetaReadiness],
        ['loadLeads',         loadLeads],
        ['loadScoutLeads',    loadScoutLeads],  // v7.28
    ];
    const results1 = await Promise.all(batch1.map(([n, f]) => _runLoaderSafely(n, f)));
    const results2 = await Promise.all(batch2.map(([n, f]) => _runLoaderSafely(n, f)));
    // Mission Control reads caches from the loaders above. Guard so a
    // bug here can't drag the whole refresh down.
    let mcError = null;
    try { renderMissionControl(); }
    catch (e) { mcError = String(e && e.message || e); }
    const failures = [...results1, ...results2].filter(r => !r.ok);
    if (mcError) failures.push({ name: 'renderMissionControl', error: mcError });
    const status = document.getElementById('cmd-status');
    const out    = document.getElementById('cmd-output');
    if (failures.length === 0) {
        status.textContent = 'Hub refreshed.';
    } else {
        status.textContent =
            `Hub refreshed with ${failures.length} section error${failures.length === 1 ? '' : 's'}.`;
        if (out) {
            out.textContent = failures
                .map(f => `FAIL ${f.name}: ${f.error}`)
                .join('\n');
        }
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
