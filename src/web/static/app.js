const VIEWS = [
  { id: "inbox", label: "Inbox" },
  { id: "pipeline", label: "Pipeline" },
  { id: "browse", label: "Browse" },
  { id: "profile", label: "Profile" },
  { id: "settings", label: "Settings" }
];

const state = {
  activeView: getInitialView(),
  health: null,
  profile: null,
  preferences: null,
  sources: [],
  suggestions: [],
  jobs: [],
  matches: [],
  alerts: [],
  actions: [],
  loading: {},
  errors: {},
  sourceTest: null,
  toast: null,
  jobFilters: { q: "", remote_policy: "", source_id: "", sort: "newest" },
  inboxFilters: { tier: "all", since: "all" }
};

const app = document.querySelector("#app");
const toastRoot = document.querySelector("#toast-root");

document.addEventListener("DOMContentLoaded", init);
document.addEventListener("click", handleDocumentClick);
document.addEventListener("submit", handleDocumentSubmit);
document.addEventListener("input", handleFilterInput);
document.addEventListener("change", handleFilterChange);
window.addEventListener("hashchange", () => {
  state.activeView = getInitialView();
  render();
});

function init() {
  render();
  loadAll();
}

function getInitialView() {
  const id = window.location.hash.replace("#", "");
  return VIEWS.some((view) => view.id === id) ? id : "inbox";
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    },
    ...options
  });

  if (response.status === 404 && options.allow404) {
    return null;
  }

  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `Request failed: ${response.status}`);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

function api(path, options = {}) {
  return request(`/api${path}`, options);
}

async function loadAll() {
  state.loading.app = true;
  state.errors.app = "";
  render();

  const loaders = [
    loadHealth(),
    loadProfile(),
    loadPreferences(),
    loadSources(),
    loadSuggestions(),
    loadJobs(),
    loadMatches(),
    loadAlerts(),
    loadActions()
  ];

  const results = await Promise.allSettled(loaders);
  const failed = results.filter((result) => result.status === "rejected");
  if (failed.length) {
    state.errors.app = failed[0].reason.message;
  }

  state.loading.app = false;
  render();
}

async function loadHealth() {
  state.health = await request("/health");
}

async function loadProfile() {
  state.profile = await api("/profile", { allow404: true });
}

async function loadPreferences() {
  state.preferences = await api("/preferences");
}

async function loadSources() {
  state.sources = await api("/sources");
}

async function loadSuggestions() {
  state.suggestions = await api("/discovery/suggestions");
}

function buildQuery(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) {
      search.set(key, value);
    }
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function loadJobs() {
  const { q, remote_policy, source_id, sort } = state.jobFilters;
  state.jobs = await api(`/jobs${buildQuery({ q, remote_policy, source_id, sort, limit: 100 })}`);
}

async function loadMatches() {
  state.matches = await api(`/matches${buildQuery({ sort: "score", exclude_rejected: "true", limit: 200 })}`);
}

async function loadAlerts() {
  state.alerts = await api("/alerts");
}

async function loadActions() {
  state.actions = await api("/jobs/actions");
}

/* ---------- derived data ---------- */

function actionByJobId() {
  const map = new Map();
  state.actions.forEach((action) => map.set(action.job_posting_id, action));
  return map;
}

function jobById(jobId) {
  return state.jobs.find((job) => job.id === jobId) || null;
}

function inboxEntries() {
  const actions = actionByJobId();
  const seen = new Set();
  const entries = [];
  const { tier, since } = state.inboxFilters;

  const cutoff = since === "all" ? null : (() => {
    const d = new Date();
    d.setDate(d.getDate() - Number(since));
    return d;
  })();

  for (const match of state.matches) {
    if (seen.has(match.job_posting_id)) continue;
    seen.add(match.job_posting_id);
    if (match.decision === "rejected") continue;
    const action = actions.get(match.job_posting_id);
    if (action && ["applied", "dismissed", "not_relevant"].includes(action.action)) continue;

    const score = Number(match.score ?? 0);
    if (tier === "strong" && score < 85) continue;
    if (tier === "good" && (score < 65 || score >= 85)) continue;
    if (tier === "weak" && score >= 65) continue;

    if (cutoff) {
      const dateStr = match.posted_at || match.first_seen_at;
      const postDate = dateStr ? new Date(dateStr) : null;
      if (!postDate || Number.isNaN(postDate.getTime()) || postDate < cutoff) continue;
    }

    entries.push({ match, action });
  }

  entries.sort((a, b) => (b.match.score ?? 0) - (a.match.score ?? 0));
  return entries;
}

function pipelineGroups() {
  const groups = { saved: [], applied: [], dismissed: [] };
  for (const action of state.actions) {
    if (action.action === "saved") groups.saved.push(action);
    else if (action.action === "applied") groups.applied.push(action);
    else groups.dismissed.push(action);
  }
  return groups;
}

/* ---------- render ---------- */

function render() {
  const focusSnapshot = captureFocus();
  app.className = "";
  app.innerHTML = `
    ${renderMasthead()}
    <main class="page">
      ${state.errors.app ? renderBanner(state.errors.app, "error") : ""}
      ${renderActiveView()}
    </main>
  `;
  restoreFocus(focusSnapshot);
  renderToast();
}

function renderMasthead() {
  const inboxCount = state.loading.app ? 0 : inboxEntries().length;
  const groups = pipelineGroups();
  const pipelineCount = groups.saved.length + groups.applied.length;
  const counts = { inbox: inboxCount, pipeline: pipelineCount };

  const nav = VIEWS.map((view) => `
    <a class="nav-link ${state.activeView === view.id ? "active" : ""}"
       href="#${escAttr(view.id)}"
       aria-current="${state.activeView === view.id ? "page" : "false"}">
      ${esc(view.label)}${counts[view.id] ? `<sup>${counts[view.id]}</sup>` : ""}
    </a>
  `).join("");

  const healthKind = !state.health ? "warn" : state.health.status === "ok" ? "ok" : "error";
  const healthTitle = state.health
    ? `System ${state.health.status} · LLM ${state.health.llm_configured ? "on" : "off"} · Email ${state.health.smtp_configured ? "on" : "off"}`
    : "Checking system";

  return `
    <header class="masthead">
      <div class="masthead-inner">
        <a class="wordmark" href="#inbox">Instaply</a>
        <nav class="nav" aria-label="Primary navigation">${nav}</nav>
        <div class="masthead-meta">
          <span class="sys-dot ${healthKind}" title="${escAttr(healthTitle)}"></span>
          <button class="btn ghost small" type="button" data-action="refreshAll" ${state.loading.app ? "disabled" : ""}>
            ${state.loading.app ? "Refreshing" : "Refresh"}
          </button>
        </div>
      </div>
    </header>
  `;
}

function renderActiveView() {
  if (state.loading.app) {
    return `<div class="loading-row"><span class="spinner" aria-hidden="true"></span><span>Loading your desk</span></div>`;
  }

  switch (state.activeView) {
    case "pipeline":
      return renderPipelineView();
    case "browse":
      return renderBrowseView();
    case "profile":
      return renderProfileView();
    case "settings":
      return renderSettingsView();
    default:
      return renderInboxView();
  }
}

/* ---------- inbox ---------- */

function renderInboxView() {
  const { tier, since } = state.inboxFilters;
  const hasFilters = tier !== "all" || since !== "all";
  const entries = inboxEntries();
  const strong = entries.filter((entry) => (entry.match.score ?? 0) >= 85);
  const worth = entries.filter((entry) => (entry.match.score ?? 0) < 85);
  const today = new Date().toLocaleDateString("en-US", { timeZone: "America/New_York", weekday: "long", month: "long", day: "numeric" });

  let headline;
  if (!state.profile) {
    headline = `Set up your <em>profile</em> to start matching.`;
  } else if (!entries.length && hasFilters) {
    headline = `No matches for those filters.`;
  } else if (!entries.length) {
    headline = `Nothing on your desk. <em>Sources</em> are being watched.`;
  } else if (strong.length) {
    headline = `${strong.length === 1 ? "One role" : `${strong.length} roles`} worth <em>applying to</em> today.`;
  } else {
    headline = `${entries.length === 1 ? "One match" : `${entries.length} matches`} worth <em>a look</em>.`;
  }

  return `
    <div class="view-head reveal">
      <p class="kicker">${esc(today)}</p>
      <h1>${headline}</h1>
      <p class="lede">New postings from ${state.sources.length} monitored ${state.sources.length === 1 ? "source" : "sources"}, scored against your profile. Strongest first — apply, save for later, or clear them out.</p>
    </div>

    ${!state.profile ? emptyState("No profile yet", "Paste your resume in Profile so new postings can be scored against it.", "#profile", "Set up profile") : ""}

    <div class="filter-bar">
      <select data-filter-scope="inbox" data-filter-key="tier" aria-label="Score tier">
        <option value="all" ${tier === "all" ? "selected" : ""}>All scores</option>
        <option value="strong" ${tier === "strong" ? "selected" : ""}>Strong (85+)</option>
        <option value="good" ${tier === "good" ? "selected" : ""}>Good (65–84)</option>
        <option value="weak" ${tier === "weak" ? "selected" : ""}>Weak (&lt;65)</option>
      </select>
      <select data-filter-scope="inbox" data-filter-key="since" aria-label="Posted since">
        <option value="all" ${since === "all" ? "selected" : ""}>Any time</option>
        <option value="7" ${since === "7" ? "selected" : ""}>Last 7 days</option>
        <option value="14" ${since === "14" ? "selected" : ""}>Last 14 days</option>
        <option value="30" ${since === "30" ? "selected" : ""}>Last 30 days</option>
      </select>
      ${hasFilters ? `<button class="btn ghost small" type="button" data-action="clearInboxFilters">Clear</button>` : ""}
    </div>

    ${strong.length ? `
      <div class="rule-head"><h2>Apply today</h2><span class="rule-note">score 85+</span></div>
      <div class="entry-list">${strong.map((entry, index) => renderEntry(entry, index)).join("")}</div>
    ` : ""}

    ${worth.length ? `
      <div class="rule-head"><h2>Worth a look</h2><span class="rule-note">below the alert bar</span></div>
      <div class="entry-list">${worth.map((entry, index) => renderEntry(entry, index + strong.length)).join("")}</div>
    ` : ""}

    ${state.profile && !entries.length ? emptyState("Inbox zero", "When a monitored source posts something that fits, it lands here. Add more sources to widen the net.", "#settings", "Manage sources") : ""}
  `;
}

function renderEntry(entry, index) {
  const { match, action } = entry;
  const job = jobById(match.job_posting_id);
  const score = Number(match.score ?? 0);
  const tier = score >= 85 ? "strong" : score >= 65 ? "mid" : "low";
  const tierLabel = score >= 85 ? "strong" : score >= 65 ? "good" : "weak";
  const url = match.job_url || job?.canonical_url;

  const jobForDates = job ?? {
    posted_at: match.posted_at,
    provider_updated_at: match.provider_updated_at,
    first_seen_at: match.first_seen_at,
  };
  const metaParts = [
    match.company_name || "Company",
    job?.locations?.length ? job.locations.join(", ") : null,
    formatSalary(job),
    ...postingDates(jobForDates)
  ].filter(Boolean);

  return `
    <article class="entry reveal" style="--i:${Math.min(index, 8)}">
      <div class="entry-score">
        <span class="score ${tier}">${Number.isFinite(score) ? score : 0}</span>
        <span class="score-label">${tierLabel}</span>
      </div>
      <div class="entry-body">
        <h3 class="entry-title">${url ? `<a href="${escAttr(url)}" target="_blank" rel="noreferrer">${esc(match.job_title || "Job")}</a>` : esc(match.job_title || "Job")}</h3>
        <p class="entry-meta">${metaParts.map(esc).join('<span class="sep">·</span>')}${action?.action === "saved" ? '<span class="sep">·</span><span class="tag saved">Saved</span>' : ""}</p>
        ${match.summary ? `<p class="entry-summary">${esc(match.summary)}</p>` : ""}
        ${renderWhy(match)}
        ${renderCoverLetter(match)}
      </div>
      <div class="entry-actions">
        ${url ? `<a class="btn apply" href="${escAttr(url)}" target="_blank" rel="noreferrer">Apply&nbsp;↗</a>` : ""}
        <button class="btn quiet small" type="button" data-action="jobAction" data-id="${escAttr(match.job_posting_id)}" data-job-action="applied">Mark applied</button>
        ${action?.action === "saved" ? "" : `<button class="btn ghost small" type="button" data-action="jobAction" data-id="${escAttr(match.job_posting_id)}" data-job-action="saved">Save for later</button>`}
        <button class="btn ghost small" type="button" data-action="jobAction" data-id="${escAttr(match.job_posting_id)}" data-job-action="dismissed">Dismiss</button>
      </div>
    </article>
  `;
}

function renderWhy(match) {
  const hasContent = (match.matching_reasons || []).length
    || (match.missing_requirements || []).length
    || (match.uncertainties || []).length
    || Object.keys(match.score_breakdown || {}).length;
  if (!hasContent) return "";

  return `
    <details class="entry-why">
      <summary>Why this score</summary>
      <div class="why-grid">
        ${whyColumn("In your favor", match.matching_reasons)}
        ${whyColumn("Gaps", match.missing_requirements)}
        ${whyColumn("Unclear", match.uncertainties)}
        ${renderBreakdown(match.score_breakdown)}
      </div>
    </details>
  `;
}

function renderCoverLetter(match) {
  if (!match.cover_letter) return "";
  return `
    <details class="entry-why">
      <summary>Cover letter draft</summary>
      <div class="cover-letter">
        <p style="white-space: pre-wrap; margin: 10px 0;">${esc(match.cover_letter)}</p>
        <button class="btn quiet small" type="button" data-action="copyLetter" data-id="${escAttr(match.id)}">Copy letter</button>
      </div>
    </details>
  `;
}

function whyColumn(title, items) {
  const values = (items || []).filter(Boolean);
  return `
    <div class="why-col">
      <h4>${esc(title)}</h4>
      ${values.length ? `<ul>${values.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : `<p class="muted">None noted</p>`}
    </div>
  `;
}

// Labels and maxima per dimension — maxima must stay in sync with WEIGHTS
// in src/matching/scorer.py.
const SCORE_DIMENSIONS = {
  semantic_fit: { label: "Semantic match", max: 30 },
  role_title_fit: { label: "Role & title", max: 15 },
  required_skills_fit: { label: "Required skills", max: 15 },
  experience_fit: { label: "Experience", max: 10 },
  preferences_fit: { label: "Your preferences", max: 15 },
  domain_company_fit: { label: "Domain & company", max: 5 },
  preferred_skills_bonus: { label: "Preferred skills", max: 10 },
};

function renderBreakdown(breakdown) {
  const { confidence, required_skills_gate: gate, ...dims } = breakdown || {};
  const entries = Object.entries(dims);
  if (!entries.length && confidence == null) return "";

  const items = entries.map(([key, value]) => {
    const dim = SCORE_DIMENSIONS[key];
    if (!dim) {
      return `<div class="breakdown-item"><span class="breakdown-label">${esc(labelize(key))}</span><span></span><strong>${esc(String(value))}</strong></div>`;
    }
    const pct = Math.max(0, Math.min(100, (value / dim.max) * 100));
    return `
      <div class="breakdown-item">
        <span class="breakdown-label">${esc(dim.label)}</span>
        <span class="breakdown-meter"><i style="width:${pct.toFixed(0)}%"></i></span>
        <strong>${esc(String(value))}<em>/${dim.max}</em></strong>
      </div>
    `;
  }).join("");

  return `
    <div class="breakdown-row">
      ${items}
      ${gate ? `<p class="breakdown-note gate">Score capped at 49 — fewer than a third of the required skills matched.</p>` : ""}
      ${confidence != null ? `<p class="breakdown-note">Confidence ${esc(String(confidence))}% — share of scoring signals with real data behind them.</p>` : ""}
    </div>
  `;
}

/* ---------- pipeline ---------- */

function renderPipelineView() {
  const groups = pipelineGroups();
  const total = groups.saved.length + groups.applied.length;

  return `
    <div class="view-head reveal">
      <p class="kicker">Pipeline</p>
      <h1>${total ? `Tracking <em>${total}</em> ${total === 1 ? "role" : "roles"}.` : "Your application <em>pipeline</em>."}</h1>
      <p class="lede">Everything you've saved or applied to, so nothing slips. Dismissed roles stay out of your inbox.</p>
    </div>

    <div class="rule-head"><h2>Saved</h2><span class="rule-note">${groups.saved.length} waiting on you</span></div>
    ${groups.saved.length ? `<div class="row-list">${groups.saved.map(renderPipelineRow).join("")}</div>` : emptyState("Nothing saved", "Save roles from your inbox to line them up here.", "#inbox", "Go to inbox")}

    <div class="rule-head"><h2>Applied</h2><span class="rule-note">${groups.applied.length} in flight</span></div>
    ${groups.applied.length ? `<div class="row-list">${groups.applied.map(renderPipelineRow).join("")}</div>` : `<p class="muted" style="padding: 14px 0;">No applications recorded yet. Marking a role applied moves it here.</p>`}

    ${groups.dismissed.length ? `
      <div class="rule-head"><h2>Dismissed</h2><span class="rule-note">${groups.dismissed.length}</span></div>
      <div class="row-list">${groups.dismissed.map(renderPipelineRow).join("")}</div>
    ` : ""}
  `;
}

function renderPipelineRow(action) {
  const metaParts = [
    action.company_name,
    action.locations?.length ? action.locations.join(", ") : null,
    formatSalary(action)
  ].filter(Boolean);

  const isSaved = action.action === "saved";
  const isDismissed = !isSaved && action.action !== "applied";

  return `
    <div class="row reveal">
      <div class="row-main">
        <div class="row-title">${action.canonical_url ? `<a href="${escAttr(action.canonical_url)}" target="_blank" rel="noreferrer">${esc(action.job_title)}</a>` : esc(action.job_title)}</div>
        <div class="row-meta">${metaParts.map(esc).join(" · ")}</div>
      </div>
      <div class="row-side">
        <span class="tag ${escAttr(actionTagKind(action.action))}">${esc(titleCase(action.action))}</span>
        <span class="row-date">${esc(formatDate(action.created_at))}</span>
        ${isSaved && action.canonical_url ? `<a class="btn apply small" href="${escAttr(action.canonical_url)}" target="_blank" rel="noreferrer">Apply&nbsp;↗</a>` : ""}
        ${isSaved ? `<button class="btn quiet small" type="button" data-action="jobAction" data-id="${escAttr(action.job_posting_id)}" data-job-action="applied">Mark applied</button>` : ""}
        ${isSaved ? `<button class="btn ghost small" type="button" data-action="jobAction" data-id="${escAttr(action.job_posting_id)}" data-job-action="dismissed">Dismiss</button>` : ""}
        ${isDismissed ? `<button class="btn ghost small" type="button" data-action="jobAction" data-id="${escAttr(action.job_posting_id)}" data-job-action="saved">Restore</button>` : ""}
      </div>
    </div>
  `;
}

function actionTagKind(action) {
  if (action === "applied") return "applied";
  if (action === "saved") return "saved";
  return "dismissed";
}

/* ---------- browse ---------- */

function renderBrowseView() {
  const filters = state.jobFilters;
  const hasFilters = Boolean(filters.q || filters.remote_policy || filters.source_id);
  const actions = actionByJobId();
  const sourceOptions = [...state.sources]
    .sort((a, b) => a.company_name.localeCompare(b.company_name))
    .map((source) => `
      <option value="${escAttr(source.id)}" ${filters.source_id === source.id ? "selected" : ""}>
        ${esc(source.company_name)}
      </option>
    `).join("");

  return `
    <div class="view-head reveal">
      <p class="kicker">Browse</p>
      <h1>Every posting, <em>as it lands</em>.</h1>
      <p class="lede">The raw feed from your monitored sources. Score anything that catches your eye.</p>
    </div>

    <div class="rule-head">
      <h2>Postings</h2>
      <span class="filter-count">${state.jobs.length}${state.jobs.length === 100 ? "+" : ""} shown</span>
    </div>
    <div class="filter-bar">
      <input type="search" data-filter-scope="jobs" data-filter-key="q"
             value="${escAttr(filters.q)}" placeholder="Search title or company" aria-label="Search jobs">
      <select data-filter-scope="jobs" data-filter-key="remote_policy" aria-label="Remote policy">
        <option value="">Any workplace</option>
        ${["remote", "hybrid", "onsite", "unknown"].map((policy) => `
          <option value="${escAttr(policy)}" ${filters.remote_policy === policy ? "selected" : ""}>${esc(titleCase(policy))}</option>
        `).join("")}
      </select>
      <select data-filter-scope="jobs" data-filter-key="source_id" aria-label="Source">
        <option value="">All companies</option>
        ${sourceOptions}
      </select>
      <select data-filter-scope="jobs" data-filter-key="sort" aria-label="Sort order">
        ${[
          ["newest", "Newest first"],
          ["oldest", "Oldest first"],
          ["posted", "Recently posted"],
          ["title", "Title A–Z"],
          ["company", "Company A–Z"]
        ].map(([value, label]) => `
          <option value="${escAttr(value)}" ${filters.sort === value ? "selected" : ""}>${esc(label)}</option>
        `).join("")}
      </select>
      ${hasFilters ? `<button class="btn ghost small" type="button" data-action="clearJobFilters">Clear</button>` : ""}
    </div>
    ${state.loading.jobs
      ? `<div class="loading-row"><span class="spinner" aria-hidden="true"></span><span>Loading postings</span></div>`
      : state.jobs.length
        ? `<div class="row-list">${state.jobs.map((job) => renderJobRow(job, actions.get(job.id))).join("")}</div>`
        : hasFilters
          ? emptyState("No matching postings", "Try a different search or clear the filters.", null, null)
          : emptyState("No postings yet", "Add and poll a source to start collecting jobs.", "#settings", "Manage sources")}
  `;
}

function renderJobRow(job, action) {
  const metaParts = [
    job.company_name,
    job.locations?.length ? job.locations.join(", ") : null,
    formatSalary(job),
    ...postingDates(job)
  ].filter(Boolean);

  return `
    <div class="row">
      <div class="row-main">
        <div class="row-title">${job.canonical_url ? `<a href="${escAttr(job.canonical_url)}" target="_blank" rel="noreferrer">${esc(job.title)}</a>` : esc(job.title)}</div>
        <div class="row-meta">${metaParts.map(esc).join(" · ")}</div>
      </div>
      <div class="row-side">
        ${job.match_score != null ? `<span class="tag" title="Match score (${escAttr(job.match_decision || "")})">${esc(String(job.match_score))} · ${esc(job.match_decision || "")}</span>` : ""}
        ${job.remote_policy && job.remote_policy !== "unknown" ? `<span class="tag">${esc(job.remote_policy)}</span>` : ""}
        ${action ? `<span class="tag ${escAttr(actionTagKind(action.action))}">${esc(titleCase(action.action))}</span>` : ""}
        <button class="btn quiet small" type="button" data-action="scoreJob" data-id="${escAttr(job.id)}" ${state.loading[`score-${job.id}`] ? "disabled" : ""}>
          ${state.loading[`score-${job.id}`] ? "Scoring" : "Score"}
        </button>
        ${action?.action === "saved" ? "" : `<button class="btn ghost small" type="button" data-action="jobAction" data-id="${escAttr(job.id)}" data-job-action="saved">Save</button>`}
        ${action?.action === "dismissed" ? "" : `<button class="btn ghost small" type="button" data-action="jobAction" data-id="${escAttr(job.id)}" data-job-action="dismissed">Dismiss</button>`}
      </div>
    </div>
  `;
}

/* ---------- profile ---------- */

function renderProfileView() {
  const profile = state.profile;
  const structured = profile?.structured_profile;
  const skills = structured?.skills || [];
  const roles = structured?.roles || [];
  const domains = structured?.domains || [];
  const prefs = state.preferences || {};
  const seniority = new Set(prefs.seniority_levels || []);
  const remotePolicy = prefs.remote_policy || "any";

  return `
    <div class="view-head reveal">
      <p class="kicker">Profile</p>
      <h1>Who you are, <em>what you want</em>.</h1>
      <p class="lede">Matching quality depends on this page. Keep the resume current and the criteria honest.</p>
    </div>

    <div class="rule-head"><h2>Resume</h2>${profile ? `<span class="rule-note">v${esc(String(profile.version))} · ${esc(formatDate(profile.created_at))}</span>` : `<span class="rule-note">not set</span>`}</div>
    <div class="split" style="padding-top: 18px;">
      <form id="profileForm" class="sheet">
        <label class="field">
          <span>Resume text</span>
          <textarea name="resume_text" rows="16" placeholder="Paste resume text here"></textarea>
        </label>
        <div class="form-actions">
          <button class="btn" type="submit" ${state.loading.profile ? "disabled" : ""}>
            ${state.loading.profile ? "Parsing" : profile ? "Update profile" : "Save profile"}
          </button>
        </div>
      </form>
      <div>
        ${profile ? `
          <div class="fact-block">
            <h3>Read from your resume</h3>
            <div class="fact-line"><span>Seniority</span><strong>${esc(titleCase(structured?.seniority_level || "Unknown"))}</strong></div>
            <div class="fact-line"><span>Experience</span><strong>${esc(String(structured?.years_of_experience ?? "Unknown"))} ${structured?.years_of_experience != null ? "years" : ""}</strong></div>
          </div>
          ${chipSection("Skills", skills.map((skill) => skill.name || skill))}
          ${listSection("Roles", roles.map((role) => [role.title, role.company].filter(Boolean).join(" at ")))}
          ${chipSection("Domains", domains)}
          ${structured?.summary ? `<div class="fact-block"><h3>Summary</h3><p class="summary-text">${esc(structured.summary)}</p></div>` : ""}
        ` : `
          <div class="fact-block">
            <h3>How this works</h3>
            <p class="summary-text muted">Paste your resume and it gets parsed into skills, roles, and seniority. Every new posting is scored against that picture — the better the input, the sharper the matches.</p>
          </div>
        `}
      </div>
    </div>

    <div class="rule-head"><h2>What you're looking for</h2>${prefs.id ? `<span class="rule-note">saved</span>` : `<span class="rule-note">defaults</span>`}</div>
    <form id="preferencesForm" class="sheet" style="margin-top: 18px;">
      <div class="form-grid">
        ${textField("target_roles", "Target roles", toCsv(prefs.target_roles), "Software Engineer, Product Engineer")}
        ${textField("locations", "Locations", toCsv(prefs.locations), "Remote, Toronto")}
        ${textField("must_have_skills", "Must-have skills", toCsv(prefs.must_have_skills), "TypeScript, React")}
        ${textField("nice_to_have_skills", "Nice-to-have skills", toCsv(prefs.nice_to_have_skills), "FastAPI, PostgreSQL")}
        ${textField("excluded_keywords", "Excluded keywords", toCsv(prefs.excluded_keywords), "Intern, unpaid")}
        ${numberField("min_salary", "Minimum salary", prefs.min_salary, "150000")}
        ${textField("salary_currency", "Currency", prefs.salary_currency || "", "USD")}
        ${numberField("alert_threshold", "Alert threshold", prefs.alert_threshold ?? 85, "85", 0, 100)}
      </div>

      <div class="form-grid" style="margin-top: 18px;">
        <fieldset class="fieldset">
          <legend>Seniority</legend>
          <div class="checkbox-row">
            ${["intern", "junior", "mid", "senior", "staff", "principal", "lead", "manager"].map((level) => `
              <label class="check-pill">
                <input type="checkbox" name="seniority_levels" value="${escAttr(level)}" ${seniority.has(level) ? "checked" : ""}>
                <span>${esc(titleCase(level))}</span>
              </label>
            `).join("")}
          </div>
        </fieldset>

        <fieldset class="fieldset">
          <legend>Workplace</legend>
          <div class="segmented">
            ${["any", "remote", "hybrid", "onsite"].map((policy) => `
              <label>
                <input type="radio" name="remote_policy" value="${escAttr(policy)}" ${remotePolicy === policy ? "checked" : ""}>
                <span>${esc(titleCase(policy))}</span>
              </label>
            `).join("")}
          </div>
          <label class="toggle-row" style="margin-top: 10px;">
            <input type="checkbox" name="needs_visa_sponsorship" ${prefs.needs_visa_sponsorship ? "checked" : ""}>
            <span>Needs visa sponsorship</span>
          </label>
        </fieldset>
      </div>

      <div class="form-actions">
        <button class="btn" type="submit" ${state.loading.preferences ? "disabled" : ""}>
          ${state.loading.preferences ? "Saving" : "Save criteria"}
        </button>
      </div>
    </form>
  `;
}

/* ---------- settings ---------- */

function renderSettingsView() {
  const health = state.health;

  return `
    <div class="view-head reveal">
      <p class="kicker">Settings</p>
      <h1>Sources &amp; <em>system</em>.</h1>
      <p class="lede">The machinery behind the inbox: which career pages get watched, and how alerts go out.</p>
    </div>

    <div class="rule-head"><h2>System</h2></div>
    <div class="status-grid">
      <span class="status-item"><span class="sys-dot ${health?.status === "ok" ? "ok" : "error"}"></span><strong>${esc(titleCase(health?.status || "unknown"))}</strong></span>
      <span class="status-item">LLM <strong>${health?.llm_configured ? "configured" : "off — heuristic fallback"}</strong></span>
      <span class="status-item">Email <strong>${health?.smtp_configured ? "configured" : "off — in-app alerts only"}</strong></span>
      <span class="status-item">
        <button class="btn quiet small" type="button" data-action="sendDigest" ${state.loading.digest ? "disabled" : ""}>
          ${state.loading.digest ? "Sending" : "Send digest now"}
        </button>
      </span>
    </div>

    <div class="rule-head"><h2>Add a source</h2></div>
    <form id="sourceForm" class="sheet" style="margin-top: 18px;">
      <div class="form-grid">
        ${textField("source_url", "Source URL", "", "https://boards.greenhouse.io/company")}
        ${textField("company_name", "Company name", "", "Optional")}
        <label class="field">
          <span>Priority</span>
          <select name="priority">
            <option value="normal">Normal</option>
            <option value="high">High</option>
            <option value="low">Low</option>
          </select>
        </label>
      </div>
      ${state.sourceTest ? `<div class="inline-result ${state.sourceTest.success ? "success" : "error"}">${esc(state.sourceTest.message)}</div>` : ""}
      <div class="form-actions">
        <button class="btn quiet" type="button" data-action="testSource" ${state.loading.testSource ? "disabled" : ""}>
          ${state.loading.testSource ? "Testing" : "Test"}
        </button>
        <button class="btn" type="submit" ${state.loading.source ? "disabled" : ""}>
          ${state.loading.source ? "Adding" : "Add source"}
        </button>
      </div>
    </form>

    <div class="rule-head">
      <h2>Suggested sources</h2>
      ${state.suggestions.length ? `<span class="rule-note">${state.suggestions.length}</span>` : ""}
      <span class="rule-note">
        <button class="btn quiet small" type="button" data-action="runDiscovery" ${state.loading.discovery ? "disabled" : ""}>
          ${state.loading.discovery ? "Discovering…" : "Discover now"}
        </button>
      </span>
    </div>
    ${state.suggestions.length
      ? `<div class="row-list">${state.suggestions.map(renderSuggestionRow).join("")}</div>`
      : `<p class="muted" style="padding: 14px 0;">Companies hiring for your target roles appear here after a discovery run — accept one to start watching it.</p>`}

    <div class="rule-head"><h2>Monitored sources</h2><span class="rule-note">${state.sources.length}</span></div>
    ${state.sources.length
      ? `<div class="row-list">${state.sources.map(renderSourceRow).join("")}</div>`
      : emptyState("No sources yet", "Add a Greenhouse, Lever, or Ashby careers URL above to start watching.", null, null)}

    <div class="rule-head"><h2>Alert log</h2><span class="rule-note">${state.alerts.length}</span></div>
    ${state.alerts.length
      ? `<div class="row-list">${state.alerts.slice(0, 20).map(renderAlertRow).join("")}</div>`
      : `<p class="muted" style="padding: 14px 0;">Strong matches trigger alerts; they're logged here.</p>`}
  `;
}

function renderSourceRow(source) {
  return `
    <div class="row">
      <div class="row-main">
        <div class="row-title">${esc(source.company_name)}</div>
        <div class="row-meta">${esc(source.provider)} · ${esc(source.priority)} priority · ${esc(source.source_url)}</div>
      </div>
      <div class="row-side">
        <span class="tag ${escAttr(statusKind(source.status))}">${esc(titleCase(source.status))}</span>
        <span class="row-date" title="Last success">${esc(formatDate(source.last_success_at))}</span>
        <button class="btn quiet small" type="button" data-action="pollSource" data-id="${escAttr(source.id)}" ${state.loading[`poll-${source.id}`] ? "disabled" : ""}>
          ${state.loading[`poll-${source.id}`] ? "Polling" : "Poll now"}
        </button>
        <button class="btn ghost small" type="button" data-action="toggleSource" data-id="${escAttr(source.id)}" data-status="${escAttr(source.status)}">
          ${source.status === "paused" ? "Resume" : "Pause"}
        </button>
        <button class="btn danger small" type="button" data-action="deleteSource" data-id="${escAttr(source.id)}">Delete</button>
      </div>
    </div>
  `;
}

function renderSuggestionRow(suggestion) {
  const titles = (suggestion.matching_titles || []).filter(Boolean);
  return `
    <div class="row">
      <div class="row-main">
        <div class="row-title">
          ${suggestion.board_url
            ? `<a href="${escAttr(suggestion.board_url)}" target="_blank" rel="noreferrer">${esc(suggestion.company_name)}</a>`
            : esc(suggestion.company_name)}
        </div>
        <div class="row-meta">
          ${esc(suggestion.provider || "unknown")} · ${suggestion.job_count} open role${suggestion.job_count === 1 ? "" : "s"}${suggestion.reason ? ` · ${esc(suggestion.reason)}` : ""}
        </div>
        ${titles.length ? `<div class="row-meta">Hiring: ${esc(titles.join(" · "))}</div>` : ""}
      </div>
      <div class="row-side">
        <button class="btn small" type="button" data-action="acceptSuggestion" data-id="${escAttr(suggestion.id)}" ${state.loading[`suggest-${suggestion.id}`] ? "disabled" : ""}>
          ${state.loading[`suggest-${suggestion.id}`] ? "Adding" : "Accept"}
        </button>
        <button class="btn ghost small" type="button" data-action="rejectSuggestion" data-id="${escAttr(suggestion.id)}" ${state.loading[`suggest-${suggestion.id}`] ? "disabled" : ""}>Dismiss</button>
      </div>
    </div>
  `;
}

function renderAlertRow(alert) {
  const score = Number(alert.score ?? 0);
  const tier = score >= 85 ? "strong" : score >= 65 ? "mid" : "low";
  return `
    <div class="row">
      <div class="row-main">
        <div class="row-title">${alert.job_url ? `<a href="${escAttr(alert.job_url)}" target="_blank" rel="noreferrer">${esc(alert.job_title || "Job alert")}</a>` : esc(alert.job_title || "Job alert")}</div>
        <div class="row-meta">${esc(alert.company_name || "Company")}${alert.match_summary ? ` · ${esc(alert.match_summary)}` : ""}</div>
      </div>
      <div class="row-side">
        <span class="score ${tier}" style="font-size: 18px;">${Number.isFinite(score) ? score : 0}</span>
        <span class="tag ${escAttr(statusKind(alert.status))}">${esc(titleCase(alert.status))}</span>
        <span class="row-date">${esc(formatDate(alert.sent_at || alert.created_at))}</span>
      </div>
    </div>
  `;
}

/* ---------- shared fragments ---------- */

function emptyState(title, body, href, actionLabel) {
  return `
    <div class="empty-state">
      <h3>${esc(title)}</h3>
      <p>${esc(body)}</p>
      ${href && actionLabel ? `<a class="btn quiet" href="${escAttr(href)}">${esc(actionLabel)}</a>` : ""}
    </div>
  `;
}

function renderBanner(message, kind) {
  return `
    <div class="banner ${escAttr(kind)}">
      <span>${esc(message)}</span>
      <button type="button" data-action="dismissAppError" aria-label="Dismiss">✕</button>
    </div>
  `;
}

function textField(name, label, value, placeholder) {
  return `
    <label class="field">
      <span>${esc(label)}</span>
      <input type="text" name="${escAttr(name)}" value="${escAttr(value || "")}" placeholder="${escAttr(placeholder || "")}">
    </label>
  `;
}

function numberField(name, label, value, placeholder, min, max) {
  return `
    <label class="field">
      <span>${esc(label)}</span>
      <input type="number" name="${escAttr(name)}" value="${escAttr(value ?? "")}" placeholder="${escAttr(placeholder || "")}" ${min !== undefined ? `min="${escAttr(min)}"` : ""} ${max !== undefined ? `max="${escAttr(max)}"` : ""}>
    </label>
  `;
}

function chipSection(title, values) {
  const items = (values || []).filter(Boolean);
  if (!items.length) return "";
  return `
    <div class="fact-block">
      <h3>${esc(title)}</h3>
      <div class="chip-row">${items.map((item) => `<span class="chip">${esc(item)}</span>`).join("")}</div>
    </div>
  `;
}

function listSection(title, values) {
  const items = (values || []).filter(Boolean);
  if (!items.length) return "";
  return `
    <div class="fact-block">
      <h3>${esc(title)}</h3>
      <ul class="plain-list">${items.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>
    </div>
  `;
}

function statusKind(status) {
  const value = String(status || "unknown").toLowerCase();
  if (["ok", "active", "sent", "remote", "yes"].includes(value)) return "ok";
  if (["degraded", "pending", "hybrid", "unknown", "paused"].includes(value)) return "warn";
  if (["failed", "disabled", "error", "no"].includes(value)) return "error";
  return "warn";
}

/* ---------- filters ---------- */

function handleFilterInput(event) {
  const input = event.target.closest("input[data-filter-scope]");
  if (!input) return;
  applyFilterValue(input.dataset.filterKey, input.value, 300);
}

function handleFilterChange(event) {
  const select = event.target.closest("select[data-filter-scope]");
  if (!select) return;
  const { filterScope, filterKey } = select.dataset;
  if (filterScope === "inbox") {
    state.inboxFilters[filterKey] = select.value;
    render();
    return;
  }
  applyFilterValue(filterKey, select.value, 0);
}

function applyFilterValue(key, value, delay) {
  if (state.jobFilters[key] === value) return;
  state.jobFilters[key] = value;

  window.clearTimeout(applyFilterValue.timer);
  applyFilterValue.timer = window.setTimeout(() => {
    runAction("jobs", async () => {
      await loadJobs();
      render();
    });
  }, delay);
}

function captureFocus() {
  const active = document.activeElement;
  if (!active || !active.dataset || !active.dataset.filterKey) return null;
  return {
    key: active.dataset.filterKey,
    selectionStart: active.selectionStart,
    selectionEnd: active.selectionEnd
  };
}

function restoreFocus(snapshot) {
  if (!snapshot) return;
  const element = document.querySelector(`[data-filter-key="${snapshot.key}"]`);
  if (!element) return;
  element.focus();
  if (snapshot.selectionStart !== null && snapshot.selectionStart !== undefined && element.setSelectionRange) {
    try {
      element.setSelectionRange(snapshot.selectionStart, snapshot.selectionEnd);
    } catch {
      // Selection is not supported on every input type; focus is enough.
    }
  }
}

/* ---------- event handling ---------- */

async function handleDocumentClick(event) {
  const trigger = event.target.closest("[data-action]");
  if (!trigger) return;

  const action = trigger.dataset.action;

  if (action === "refreshAll") {
    await runAction("app", loadAll);
  } else if (action === "dismissAppError") {
    state.errors.app = "";
    render();
  } else if (action === "testSource") {
    await handleTestSource();
  } else if (action === "pollSource") {
    await handlePollSource(trigger.dataset.id);
  } else if (action === "toggleSource") {
    await handleToggleSource(trigger.dataset.id, trigger.dataset.status);
  } else if (action === "deleteSource") {
    await handleDeleteSource(trigger.dataset.id);
  } else if (action === "clearInboxFilters") {
    state.inboxFilters = { tier: "all", since: "all" };
    render();
  } else if (action === "clearJobFilters") {
    state.jobFilters = { q: "", remote_policy: "", source_id: "", sort: state.jobFilters.sort };
    await runAction("jobs", async () => {
      await loadJobs();
      render();
    });
  } else if (action === "sendDigest") {
    await handleSendDigest();
  } else if (action === "runDiscovery") {
    await handleRunDiscovery();
  } else if (action === "acceptSuggestion") {
    await handleSuggestionDecision(trigger.dataset.id, "accept");
  } else if (action === "rejectSuggestion") {
    await handleSuggestionDecision(trigger.dataset.id, "reject");
  } else if (action === "scoreJob") {
    await handleScoreJob(trigger.dataset.id);
  } else if (action === "jobAction") {
    await handleJobAction(trigger.dataset.id, trigger.dataset.jobAction);
  } else if (action === "copyLetter") {
    const match = state.matches.find((m) => m.id === trigger.dataset.id);
    if (match?.cover_letter) {
      try {
        await navigator.clipboard.writeText(match.cover_letter);
        showToast("Cover letter copied", "success");
      } catch {
        showToast("Could not copy — select the text manually", "error");
      }
    }
  }
}

async function handleDocumentSubmit(event) {
  if (event.target.id === "profileForm") {
    event.preventDefault();
    await handleSaveProfile(event.target);
  } else if (event.target.id === "preferencesForm") {
    event.preventDefault();
    await handleSavePreferences(event.target);
  } else if (event.target.id === "sourceForm") {
    event.preventDefault();
    await handleAddSource(event.target);
  }
}

async function handleSaveProfile(form) {
  const resumeText = form.querySelector("[name='resume_text']").value.trim();
  if (!resumeText) {
    showToast("Paste resume text first", "error");
    return;
  }

  await runAction("profile", async () => {
    state.profile = await api("/profile/resume", {
      method: "POST",
      body: JSON.stringify({ resume_text: resumeText })
    });
    showToast("Profile saved", "success");
    render();
  });
}

async function handleSavePreferences(form) {
  const formData = new FormData(form);
  const payload = {
    target_roles: csvToArray(formData.get("target_roles")),
    seniority_levels: formData.getAll("seniority_levels"),
    locations: csvToArray(formData.get("locations")),
    remote_policy: formData.get("remote_policy") || "any",
    min_salary: nullableInt(formData.get("min_salary")),
    salary_currency: nullableString(formData.get("salary_currency")),
    needs_visa_sponsorship: Boolean(formData.get("needs_visa_sponsorship")),
    must_have_skills: csvToArray(formData.get("must_have_skills")),
    nice_to_have_skills: csvToArray(formData.get("nice_to_have_skills")),
    excluded_keywords: csvToArray(formData.get("excluded_keywords")),
    alert_threshold: nullableInt(formData.get("alert_threshold")) ?? 85
  };

  await runAction("preferences", async () => {
    state.preferences = await api("/preferences", {
      method: "PUT",
      body: JSON.stringify(payload)
    });
    showToast("Criteria saved", "success");
    render();
  });
}

async function handleTestSource() {
  const form = document.querySelector("#sourceForm");
  if (!form) return;
  const payload = sourcePayloadFromForm(form);
  if (!payload.url) {
    showToast("Enter a source URL", "error");
    return;
  }

  await runAction("testSource", async () => {
    state.sourceTest = await api("/sources/test", {
      method: "POST",
      body: JSON.stringify(payload)
    });
    showToast(state.sourceTest.message, state.sourceTest.success ? "success" : "error");
    render();
  });
}

async function handleAddSource(form) {
  const payload = sourcePayloadFromForm(form);
  if (!payload.url) {
    showToast("Enter a source URL", "error");
    return;
  }

  await runAction("source", async () => {
    await api("/sources", {
      method: "POST",
      body: JSON.stringify(payload)
    });
    form.reset();
    state.sourceTest = null;
    await loadSources();
    showToast("Source added", "success");
    render();
  });
}

async function handlePollSource(sourceId) {
  await runAction(`poll-${sourceId}`, async () => {
    const result = await api(`/sources/${sourceId}/poll?score_matches=true`, {
      method: "POST"
    });
    await Promise.all([loadSources(), loadJobs(), loadMatches(), loadAlerts()]);
    const baselineText = result.baseline_count
      ? `, ${result.baseline_count} baselined`
      : "";
    showToast(`Poll complete: ${result.new_count} new${baselineText}, ${result.matched_count} matched`, result.error ? "error" : "success");
    render();
  });
}

async function handleToggleSource(sourceId, status) {
  const nextStatus = status === "paused" ? "active" : "paused";
  await runAction(`toggle-${sourceId}`, async () => {
    await api(`/sources/${sourceId}`, {
      method: "PATCH",
      body: JSON.stringify({ status: nextStatus })
    });
    await loadSources();
    showToast(nextStatus === "active" ? "Source resumed" : "Source paused", "success");
    render();
  });
}

async function handleDeleteSource(sourceId) {
  if (!window.confirm("Delete this source and its jobs?")) {
    return;
  }

  await runAction(`delete-${sourceId}`, async () => {
    await api(`/sources/${sourceId}`, { method: "DELETE" });
    await Promise.all([loadSources(), loadJobs(), loadMatches(), loadAlerts(), loadActions()]);
    showToast("Source deleted", "success");
    render();
  });
}

async function handleSendDigest() {
  await runAction("digest", async () => {
    const result = await api("/alerts/digest", { method: "POST" });
    await loadAlerts();
    if (result.error) {
      showToast(`Digest failed: ${result.error}`, "error");
    } else if (!result.sent) {
      showToast("No new matches to digest", "success");
    } else {
      showToast(`Digest sent: ${result.sent} matches via ${result.channel.replace("_", "-")}`, "success");
    }
    render();
  });
}

async function handleRunDiscovery() {
  await runAction("discovery", async () => {
    const stats = await api("/discovery/run", { method: "POST" });
    await loadSuggestions();
    if (!stats.candidates) {
      showToast("Nothing to discover — set target roles in Preferences, or review pending suggestions", "success");
    } else if (stats.suggested) {
      showToast(`Found ${stats.suggested} new compan${stats.suggested === 1 ? "y" : "ies"} hiring for your roles`, "success");
    } else {
      showToast(`Checked ${stats.candidates} companies — no new boards matched this run`, "success");
    }
    render();
  });
}

async function handleSuggestionDecision(suggestionId, decision) {
  await runAction(`suggest-${suggestionId}`, async () => {
    await api(`/discovery/suggestions/${suggestionId}/${decision}`, { method: "POST" });
    await Promise.all([loadSuggestions(), loadSources()]);
    showToast(
      decision === "accept"
        ? "Now monitoring — first poll baselines existing posts"
        : "Dismissed — it won't be suggested again",
      "success"
    );
    render();
  });
}

async function handleScoreJob(jobId) {
  await runAction(`score-${jobId}`, async () => {
    const match = await api(`/matches/jobs/${jobId}?send_alerts=true`, {
      method: "POST"
    });
    await Promise.all([loadMatches(), loadAlerts()]);
    showToast(`Scored ${match.score}/100 — see Inbox`, "success");
    render();
  });
}

const ACTION_TOASTS = {
  applied: "Marked applied — tracked in Pipeline",
  saved: "Saved to Pipeline",
  dismissed: "Dismissed"
};

async function handleJobAction(jobId, action) {
  await runAction(`job-action-${jobId}`, async () => {
    await api(`/jobs/${jobId}/actions`, {
      method: "POST",
      body: JSON.stringify({ action })
    });
    await loadActions();
    showToast(ACTION_TOASTS[action] || `Marked ${action.replace("_", " ")}`, "success");
    render();
  });
}

async function runAction(key, fn) {
  state.loading[key] = true;
  state.errors[key] = "";
  render();
  try {
    await fn();
  } catch (error) {
    state.errors[key] = error.message;
    showToast(error.message, "error");
    render();
  } finally {
    state.loading[key] = false;
    render();
  }
}

/* ---------- utilities ---------- */

function sourcePayloadFromForm(form) {
  const formData = new FormData(form);
  return {
    url: String(formData.get("source_url") || "").trim(),
    company_name: nullableString(formData.get("company_name")),
    priority: formData.get("priority") || "normal"
  };
}

function csvToArray(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function toCsv(value) {
  return (value || []).join(", ");
}

function nullableInt(value) {
  const text = String(value || "").trim();
  if (!text) return null;
  const parsed = Number.parseInt(text, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function nullableString(value) {
  const text = String(value || "").trim();
  return text || null;
}

function titleCase(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function labelize(value) {
  return titleCase(String(value).replace(/_/g, " "));
}

function formatSalary(record) {
  if (!record) return null;
  const { salary_min: min, salary_max: max, salary_currency: currency } = record;
  if (!min && !max) return null;
  const fmt = (amount) => amount >= 1000 ? `${Math.round(amount / 1000)}k` : String(amount);
  const range = min && max && min !== max ? `${fmt(min)}–${fmt(max)}` : fmt(min || max);
  return `${range}${currency ? ` ${currency}` : ""}`;
}

function formatDay(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const opts = { timeZone: "America/New_York", month: "short", day: "numeric" };
  if (date.getFullYear() !== new Date().getFullYear()) opts.year = "numeric";
  return date.toLocaleDateString("en-US", opts);
}

function postingDates(job) {
  if (!job) return [];
  if (!job.posted_at) {
    return job.first_seen_at ? [`seen ${formatDate(job.first_seen_at)}`] : [];
  }
  const parts = [`posted ${formatDay(job.posted_at)}`];
  // An old req that's still being touched is alive, just not new — show both.
  const posted = new Date(job.posted_at);
  const updated = new Date(job.provider_updated_at || "");
  if (!Number.isNaN(updated.getTime()) && updated - posted > 86400000) {
    parts.push(`updated ${formatDay(job.provider_updated_at)}`);
  }
  return parts;
}

function formatDate(value) {
  if (!value) return "Never";
  // SQLite CURRENT_TIMESTAMP is UTC but carries no zone marker; tag it so it
  // is not misread as local wall-clock time.
  const normalized = typeof value === "string" && /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value)
    ? `${value.replace(" ", "T")}Z`
    : value;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-US", {
    timeZone: "America/New_York",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function showToast(message, kind) {
  state.toast = { message, kind };
  renderToast();
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    state.toast = null;
    renderToast();
  }, 3600);
}

function renderToast() {
  if (!toastRoot) return;
  toastRoot.innerHTML = state.toast
    ? `<div class="toast ${escAttr(state.toast.kind)}">${esc(state.toast.message)}</div>`
    : "";
}

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function escAttr(value) {
  return esc(value).replace(/`/g, "&#096;");
}
