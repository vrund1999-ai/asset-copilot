# Roadmap

Target: ~4-5 weeks of evenings. Each milestone lists acceptance criteria ("done when"). Tick the
box when met. Prefer finishing one thing well over breadth.

## M0. Scaffold (done)

- [x] Schema, read-only role, synthetic generator, SQL guard + tests, API/UI skeleton, CI, eval stub

## M1. SQL agent with citations (week 1-2)

Implement `agent.py` (Claude tool use loop) and wire it to `POST /ask`. Delivered in two PRs:
**PR A (foundations)** and **PR B (agent, API, UI, evals)**.

### Gaps in the scaffold that M1 closes

1. Blocked queries are not audited (`db.run_readonly_query` logs only on success).
2. DB errors (e.g. unknown column) are not `UnsafeQueryError`; the loop must catch and feed them back.
3. The row cap is not enforced on fetch, and `document_chunks.embedding` could flood the context.
4. The generator uses `date.today()`, so "next 18 months" and "latest month" drift daily and gold
   answers are not reproducible. Fix with an `--as-of` date, also injected into the agent prompt.
5. Many leases are already expired (multifamily leases are 1 year). "Active" means `end_date >= as_of`;
   the prompt must say so.
6. The latest month in `operating_statements` is the current, unclosed month; document it in the prompt.
7. `evals/questions.jsonl` has 2 rows using the old `type` field; migrate to `category` and grow to ~25.

### Module layout

| File | Purpose |
|---|---|
| `agent.py` | Loop, tool dispatch, citation assembly, grounding check |
| `tools.py` | Tool schemas, `run_sql` and `calculate` handlers |
| `calc.py` | Safe `ast`-based arithmetic evaluator |
| `prompts.py` | System prompt and schema description |
| `config.py` | `max_iterations` (8), `max_tokens`, `max_result_rows_to_model` (50), `as_of_date` |
| `api.py` | Wire `/ask` |
| `db.py` | Audit blocked/failed queries, enforce row cap |

### Tools

- `run_sql(sql, purpose)`: calls `db.run_readonly_query`. Assigns a per-request query id (`Q1`, `Q2`, ...).
  Returns `{query_id, columns, rows (first 50), row_count, truncated}`; the full result is kept server-side.
  Guard or DB errors return `{error, hint}` as an error tool result and count against a retry budget.
  Decimals and dates are serialized as strings.
- `calculate(expression, label)`: `ast` parser allowing only numeric constants, `+ - * / // % **`,
  parentheses, unary minus, and `round`/`abs`/`min`/`max`. No names or attributes, capped expression
  length and exponent, `Decimal` arithmetic, divide-by-zero returned as an error. Results get ids (`C1`, ...).
- `submit_answer(status, answer, query_ids, calc_ids)`: terminates the loop. `status` is
  `answered` or `cannot_determine`.

### Loop behavior

- Execute all `tool_use` blocks in a turn and return every `tool_result` in one user message.
- Stop on `submit_answer`. A plain-text end turn gets one nudge to call it; then counts as failure.
  `max_iterations` exceeded returns "I couldn't complete this within N steps" with the trace in `audit_log`.
  Handle `stop_reason == "max_tokens"` explicitly.
- SDK errors map to 429 / 502 / 503 with clear messages; a missing API key returns 503 before any call.
- No `temperature`/forced `tool_choice` (`claude-sonnet-5-5` rejects both with a 400); `tool_choice` stays `auto`.
  Schema prompt in a `cache_control` block; token usage accumulated per request. The `refusal` stop reason
  is handled explicitly. Server-side refusal fallbacks are not enabled yet (needs a live key to verify).
- Tool results are untrusted data, not instructions (tenant names and later document text may contain injections).

### System prompt

Role and hard rules (never compute, never state a number not from a tool, always cite, refuse when the data
cannot answer); compact schema with semantics (`month` = first of month, `noi` generated, `base_rent_psf`
annual, `annual_escalation` a fraction, `renewal_options` a count, active = `end_date >= as_of`,
occupancy = active leased sq ft / `properties.sq_ft`); the `as_of` date; 2-3 few-shot examples
(aggregate, rollover, refusal); refusal rules (forecasts, out-of-schema, document-dependent until M2,
questions about the agent's own logs).

### Citations and grounding

- Citations are built by code. `submit_answer.query_ids` is resolved against queries that actually ran;
  the response carries the real SQL text. Unknown ids are rejected and the model must retry.
- Number check: every number in the answer must appear in a cited query or calc result (allowing for
  `$1.2M`, `12.5%`, separators, and rounding tolerance; dates and list indexes exempt). On a miss, one
  corrective turn; if it still fails, return with `grounded: false` and log it. Evals count ungrounded as failures.
- Refusal (`cannot_determine`) returns "I can't determine that from the data" plus what is missing and
  may carry no citations. The rule is: `answered` implies at least one citation.

### Response contract and audit

- `AskResponse` (additive): `answer`, `citations` (`{kind, reference, label?}`), `session_id` (generated if
  absent), `status`, `grounded`, `steps`, `usage`.
- `audit_log` rows, one per event, all with the session id: `ask_received`, `model_call`, `tool_call`,
  `sql_blocked`, `grounding_check`, `answer_final`, `agent_error`.
- Streamlit: citations in an expander with SQL in `st.code`; distinct states for refusal, ungrounded
  warning, and API error.

### Evals in M1

Migrate `type` to `category`; add ~25 questions (12 `sql_aggregate`, 6 `sql_filter_rank`, 4 `lease_rollover`,
3 `refusal`, plus 3 adversarial prompts). `run_evals.py` gets basic numeric/set comparison against gold SQL
and a refusal check. Rich scoring stays in M4.

### Build order

PR A: (1) `calc.py` + tests, (2) `db.py` row cap and blocked/failed audit + governance tests,
(3) `--as-of` in the generator.
PR B: (4) `tools.py` + `prompts.py`, (5) `agent.py` loop with a fake client + tests, (6) grounding check,
(7) wire `/ask` + API tests, (8) Streamlit UI, (9) questions + eval scorer, (10) live run, tick README/ROADMAP.

### Tests (mocked client, no network, no DB)

Scripted `FakeAnthropic` with `run_readonly_query` and `audit` monkeypatched. Cover: happy path with citations
resolving to real SQL; unsafe SQL blocked and recovered; DB error retried; iteration cap; hallucinated number
-> correction -> `grounded: false`; fabricated `query_id` rejected; multiple tool calls per turn; refusal;
audit rows in order; `calculate` valid cases, injection attempts, huge exponent, divide by zero; result
truncation and Decimal serialization. One `@pytest.mark.integration` test (real DB and model) skipped in CI.

Done when:
- [x] `/ask` answers the SQL questions in `evals/questions.jsonl` end to end via the Streamlit UI
- [x] Every `answered` response includes at least one citation; uncitable questions return "I can't determine that from the data"
- [x] Unsafe model-generated SQL is blocked and the error is fed back (covered by a test with a mocked model)
- [x] Each tool call and final answer is in `audit_log` with the session id
- [x] Unit tests with a mocked Anthropic client (no network in CI)
- [x] Generated data and gold answers are reproducible via a fixed `--as-of` date (PR A)

## M2. Documents: generation, ingestion, retrieval (week 2-3)

- Generate synthetic lease abstracts / lease text (2-4 pages each) for a subset of leases, consistent with
  the `leases` table values (rent, term, renewal options) plus a few deliberate discrepancies for
  reconciliation tests. Also loan summaries for `debt`. Store as markdown/PDF under `data/generated/` (gitignored); generator must be seeded.
- Ingest: parse, chunk (keep page numbers), embed, load `documents` + `document_chunks`
  (`vector(1024)` in schema; change the dimension in `db/schema.sql` if the chosen embedding model differs).
- `search_documents(query, property_id?)` tool returning passages with `document title` and `page`.
- Extend the agent to combine SQL and document evidence. Citations: `kind: "document"`, `reference: "<title> p.<n>"`.
- Reconciliation: flag when a document's stated value disagrees with the database (e.g. lease end date) instead of silently picking one.

Done when:
- [x] Hybrid questions ("which assets roll over >20% in 18 months and what do their renewal options say?") answered with both citation kinds
- [x] At least 5 seeded discrepancies are detected and reported
- [x] Retrieval hit-rate measured in evals (see `docs/EVALS.md`)

## M3. Variance report workflow (week 3-4)

- Endpoint + UI page: pick a property (or portfolio) and month; compare `operating_statements` vs `budgets`.
- Deterministic calc of revenue/opex/NOI variance ($ and %) in code; LLM only drafts commentary on top of the computed numbers.
- Drivers: identify the largest contributing properties/line items; draft a short commentary; flag items over a threshold for human review.
- Feedback: thumbs up/down and optional correction in the UI -> `POST /feedback` -> `feedback` table.

Done when:
- [x] Report numbers match a gold SQL calculation exactly (tested)
- [x] Commentary contains no number absent from the computed tables (checked automatically)
- [x] Feedback is stored and surfaced in an eval/analysis script

## M4. Evals and hardening (week 4)

See `docs/EVALS.md`. Build the labeled set (target 100+ questions), scoring, per-category accuracy,
and a results history so improvements are visible (before/after table in the README).

Done when:
- [x] `python evals/run_evals.py` produces per-category accuracy and writes `evals/results/<timestamp>.json`
- [x] README includes a results table and at least one documented improvement driven by eval failures
- [x] CI runs unit tests; evals run manually (they need an API key and DB)

## M5. Packaging and communication (week 5)

- [x] README: architecture diagram, results, governance section, limitations, demo GIF/video
- [x] `docs/STAKEHOLDER_MEMO.md`: one page for a head of asset management (problem, outcome metrics, risks, rollout plan), no jargon
- [ ] Optional: deploy a hosted demo (synthetic data only)

## M6. Evals that discriminate (next)

The 146-question set is author-written and at 100% in every category, so it catches regressions but
cannot tell a good change from a bad one. Goal: evidence that comes from outside the author and
shows run-to-run noise.

- [ ] Questions not written by the author: run the app with at least 2 other people, collect thumbs-down
      ratings and corrections, export with `python evals/feedback_report.py --export`, and add each item
      with a verified gold answer (new `source` field on the question so these stay identifiable)
- [ ] Repeated runs: run the full set at least 5 times per configuration and report per-question
      pass rate and per-category spread, so a one-off flip is not mistaken for a real change
- [ ] Add a failure-seeking pass: a second model or a person writes questions meant to break the agent;
      keep only those with a verified gold answer
- [ ] README Results shows spread across runs (not a single score) and the share of questions written by
      someone other than the author
- [ ] A change is only claimed as an improvement if it beats the run-to-run spread (document the rule in
      `docs/EVALS.md`)

## M7. UI revamp (after M6)

The original Streamlit UI (a chat page and one report page) was built to show that
the backend works. Goal: an interface a portfolio manager would choose to use, still in Streamlit
unless a concrete need says otherwise. Scope the design first; do not start by restyling.

- [x] Short design brief: [`docs/UI_BRIEF.md`](UI_BRIEF.md) (audiences, tasks, scope, slices)
- [x] Landing page, navigation shell and a View toggle (Asset manager / Analyst / Reviewer) that changes
      presentation only, never the answer (slice 1; includes a read-only `GET /portfolio/summary`)
- [ ] Answers lead with the result; citations, SQL and document excerpts are one click away but not in the way
- [ ] Clear distinct states for answered, refused, ungrounded, loading and API-down (screenshots of each)
- [ ] Variance report: sortable tables, flagged items first, drill from a flag to the underlying month and property
- [ ] Document citations show the page text that supports the claim, not only a title and page number
- [ ] Feedback flow takes one click for a rating and does not block reading the answer
- [ ] Keyboard and screen-reader basics: labelled controls, sufficient contrast, no information by colour alone
- [ ] Before/after screenshots in `docs/screenshots/`, README and demo GIF refreshed
- [ ] Usability check with at least 2 people other than the author (this also feeds the M6 feedback items)

## Non-goals

- Real or confidential data, authentication/multi-tenancy, a custom JavaScript frontend (the Streamlit UI is revamped in M7), fine-tuning.
