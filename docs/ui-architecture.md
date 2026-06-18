# UI Architecture

## Recommended First UI Approach

For the next implementation slice, build a lightweight frontend served by FastAPI. This keeps deployment and local development simple while making the backend immediately usable.

Recommended path:

- Static HTML/CSS/JavaScript under `src/web/static`.
- FastAPI serves the app shell at `/app`.
- Keep API routes under `/api`.
- Redirect `/` to `/app` once the UI exists.

This can later be replaced with React/Vite if the interface becomes complex.

## Why Not Start With React

React is reasonable, but it adds build tooling before the product loop has been felt by a user. The V1 UI is mostly forms, tables, detail panels, and API calls. Plain TypeScript or modern JavaScript can carry that cleanly for now.

Use React/Vite if:

- The UI grows complex stateful interactions.
- Multiple developers will work on frontend.
- Component reuse starts becoming painful.
- A richer design system is needed.

## Proposed Files

```text
src/web/
  __init__.py
  router.py
  static/
    index.html
    styles.css
    app.js
```

FastAPI wiring:

- Mount static assets at `/static`.
- Serve `index.html` at `/app`.
- Redirect `/` to `/app`.
- Keep `/docs` available for API debugging.

## Frontend State Model

Use a simple client-side state object:

```js
const state = {
  profile: null,
  preferences: null,
  sources: [],
  jobs: [],
  matches: [],
  alerts: [],
  loading: {},
  errors: {},
  activeView: "dashboard"
};
```

Do not introduce global state libraries in the first UI.

## API Client

Create a tiny API wrapper:

```js
async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `Request failed: ${response.status}`);
  }

  return response.json();
}
```

## Rendering Approach

Use view functions that render into a single app root:

```js
function render() {
  document.querySelector("#app").innerHTML = layout({
    nav: renderNav(),
    content: renderActiveView()
  });
}
```

For forms, bind event listeners after render. Keep event handler names explicit, such as `handleSavePreferences` or `handlePollSource`.

## Screen Layout

Use:

- Left sidebar navigation on desktop.
- Top navigation or drawer on mobile.
- Main content area with page title and actions.
- Tables for repeated operational data.
- Detail panels for match and alert explanations.

Avoid:

- Cards inside cards.
- Large empty hero layouts.
- Decorative backgrounds.

## Component Inventory

V1 components:

- `AppShell`
- `SidebarNav`
- `StatusBadge`
- `ScoreBadge`
- `SourceTable`
- `JobTable`
- `MatchList`
- `AlertList`
- `ProfileForm`
- `PreferencesForm`
- `SourceForm`
- `ReasonList`
- `ScoreBreakdown`
- `EmptyState`
- `Toast`

## Loading And Errors

Each view should have:

- Loading state.
- Empty state.
- Error state.
- Success toast for writes.

Avoid blocking the whole app when one panel fails. For example, source loading failure should not prevent alerts from rendering.

## Accessibility

Baseline requirements:

- Use semantic buttons and inputs.
- Every input has a label.
- Tables have headers.
- Keyboard users can reach all actions.
- Do not rely only on color for status.
- Keep focus visible.

## Security

- Escape user-provided text before inserting into HTML.
- Do not render raw job description HTML in V1.
- Do not expose API keys in frontend code.
- Treat resume text as sensitive.

