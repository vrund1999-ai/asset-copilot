# UI revamp: design brief (M7)

Status: draft for review. Decisions marked **Decided** came from the project owner; everything else
is a proposal to confirm before building.

## Why

The current UI (`app/streamlit_app.py`, `app/pages/1_Variance_Report.py`) proves the backend works:
a chat box and one report page, default styling, citations in a single expander. It does not
orient a new visitor, treats every reader the same, and hides the things this project is about
(sources, governance, measured accuracy) behind clicks.

## Decisions

- **Decided: three audiences, one toggle.** A "View" switch in the sidebar selects how the same
  data is presented. It never changes the answer, only the presentation (see Views).
- **Decided: stay in Streamlit, with a deeper restyle**: custom theme (`.streamlit/config.toml`),
  restructured layout and navigation, and a small amount of custom CSS/HTML where Streamlit's
  components fall short. No new framework and no build step.
- **Decided: landing and navigation come first.** The first slice is a home page and the
  navigation shell; chat, variance and citation work follow in later PRs.

## Views

| | Asset manager (default) | Analyst | Reviewer / demo |
|---|---|---|---|
| Goal | Get the answer, trust it quickly | Verify and dig in | Understand what was built and how it is controlled |
| Answer | Plain-language answer first | Answer plus inline SQL and result table | Answer plus a "how this was checked" strip |
| Sources | Collapsed; document name, page and excerpt shown as readable cards | Expanded; raw SQL, row counts, document ids | Expanded; each source labelled by kind |
| Trust cues | Grounded / not grounded badge | Badge plus which numbers were traced | Badge plus guard, read-only role and audit log explained in one line |
| Variance report | Flagged items first, commentary on top | Full tables, sortable, all lines | Flags plus the commentary check status and fallback used |
| Extras | Sample questions | Session id, model calls, latency | Links to results, limitations and the eval table |

The view is stored in `st.session_state` and in the URL query string so a link keeps it. The default
is Asset manager.

## Primary tasks (must be fast)

1. Ask a question and see the answer and where it came from.
2. Check a source: open the SQL or the cited document page text.
3. Review a variance flag: see what is flagged, why, and drill to the property and month.
4. Leave a rating or correction without losing the answer.

## First slice: landing and navigation

- **Home page** with: one-sentence purpose; a row of sample questions that start a chat when
  clicked; a portfolio snapshot (properties, leases, latest month revenue/opex/NOI vs budget, count
  of items flagged); links to Ask and Variance report; a short "what it will not do" note
  (no data outside the database and documents; cannot change data).
- **Navigation shell**: `st.navigation` with Home, Ask, Variance report; sidebar holds the View
  toggle and API status (reachable / not reachable) so API-down is visible before a question fails.
- **Open decision: snapshot data.** The snapshot needs one cheap read-only endpoint (for example
  `GET /portfolio/summary`) reusing the variance code for the latest month. This is a small backend
  addition and needs tests. Alternative: show only static copy and sample questions in this slice.

## Visual direction (proposal)

Quiet, data-first: neutral background, one accent colour, restrained use of status colours (always
paired with text or icon), tabular numbers, consistent number formats (`$1,234,567`, `+2.51%`), and
generous spacing. Dark and light both supported through the Streamlit theme. No decorative imagery.

## Out of scope

Authentication, multi-user state, a custom JavaScript frontend, real-time streaming of answers, and
any change to agent or governance behaviour.

## Acceptance (maps to the M7 items in `ROADMAP.md`)

- Each slice ships with before/after screenshots for the happy path and at least one empty or error
  state, saved in `docs/screenshots/`.
- Existing behaviour is unchanged: `pytest` and `ruff check .` pass, and the UI still shows
  refused, ungrounded, loading and API-down states distinctly.
- A usability pass with at least 2 people other than the author before the milestone is ticked.

## Slices

1. Landing page, navigation shell, View toggle (this brief's first slice).
2. Ask page: result-first answers and source cards per view, state handling, one-click feedback.
3. Variance report: flagged first, sortable tables, drill-down.
4. Document citations show the supporting page text.
5. Accessibility pass, refreshed screenshots and demo GIF, usability check.
