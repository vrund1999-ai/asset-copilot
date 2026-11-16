# Why this project exists

asset-copilot is a portfolio project built to demonstrate the skills of an **Applied AI Engineer**
embedded with a real estate investment business. This is a summary of the requirements it targets;
it is not the posting text.

## What such a role looks like

- Works directly with investment, asset management, and portfolio teams to find high-impact
  AI/automation opportunities, define measurable outcomes, and ship.
- Builds agents, dashboards, data pipelines, and workflows over proprietary real estate data that
  mixes structured data, unstructured documents, external information, and user feedback.
- Hands-on with Python, SQL, APIs, databases, LLMs, agents, and retrieval.
- Works with engineering, data, and security teams so solutions are secure, governed, and tested.
- Communicates progress, risks, and recommendations to technical and non-technical leaders.
- Emphasis on accuracy and reliability with real-world data (spreadsheets, documents, databases).

## How the project maps to it

| Expectation | Where it shows up |
|---|---|
| Structured + unstructured + feedback | Postgres tables, document RAG (M2), feedback loop (M3) |
| Agents with LLMs, SQL, APIs | Tool-use agent (M1), FastAPI service |
| Accuracy and reliability | Deterministic calc, cited answers, discrepancy detection, eval harness (M4) |
| Secure, governed, tested | SQL guard, read-only role, audit log, unit tests, CI |
| Business impact | Variance report workflow with measurable time savings (M3) |
| Communicating to stakeholders | Stakeholder memo, results tables, clear README (M5) |

## Implications for priorities

1. Evals and governance matter more than UI polish.
2. Every claim on the resume must be backed by something measurable in this repo
   (e.g. "X% accuracy on N questions"). Never claim production or business impact that did not happen.
3. Use CRE vocabulary correctly (NOI, rent roll, T-12, lease rollover, WALT, DSCR) so the domain
   interest is credible, but do not pretend to have industry experience.
