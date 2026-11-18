# Memo: an AI assistant for portfolio questions and monthly variance reporting

**To:** Head of Asset Management  **Status:** working prototype on made-up data; pilot proposed

## The problem
Answering "which assets have leases rolling soon, and what do the renewal terms say?" means pulling
numbers from reports and re-reading lease and loan documents. Monthly budget-vs-actual commentary is
written by hand. Both are slow, and a mismatch between a document and the system of record is easy to
miss. This prototype tests whether an AI assistant can do the first pass, with every answer traceable.

## What exists today
- **Ask a question in plain English.** The answer comes with its sources: the exact data query, or the
  document and page. Where nothing supports an answer, it says it cannot tell.
- **Flags disagreements.** If a lease document and the database state different rents or dates, it
  reports both instead of picking one.
- **Monthly variance report.** For one property or the whole portfolio, it compares actuals with
  budget. All arithmetic is done by ordinary software, not the AI. The AI only drafts a short summary,
  and any number in it that is not in the tables is rejected automatically. Items off budget by at
  least 10% and $25,000 are listed for a person to review. Reviewers can rate each result and type a correction.

## What we measured
On a test set of 146 questions written for this prototype (made-up portfolio of 60 properties):
- **146 of 146 answered correctly**, with sources, no unsupported numbers, and no question wrongly refused.
- **8 of 8 deliberately planted document-vs-database mismatches were flagged**, and 6 clean documents
  were not falsely flagged.
- **10 of 10 attempts to change data or reach restricted information were declined**; no data changed.
- Variance totals match an independent calculation exactly for all 24 months.

**These results are encouraging, not proof.** The questions were written by the builder, the data is
made up and tidy, and the test is now too easy to tell good changes from bad ones. Accuracy on real,
messy documents is unknown.

## Risks
| Risk | Control today | Still open |
|---|---|---|
| A confident wrong answer | Sources on every answer; unsupported numbers flagged on screen | Wrong reasoning with correct numbers is not caught automatically |
| Misuse of the data | Read-only access to approved tables; every action logged | No user accounts or permissions yet |
| Data leaves our systems | Prototype uses made-up data only | Questions and results go to the AI provider; needs an approval before real data |
| Overreliance | Variance items over the threshold are routed to a person | Needs a clear policy on who signs off |

## Not yet known
Time saved, accuracy on real leases and loan documents (scans, varied formats), and whether analysts
will trust and use it. No benefit is claimed until a pilot measures it.

## Proposed rollout
1. **Weeks 1-2: approvals.** Decide whether the AI provider terms allow real portfolio data; choose a
   small set of assets and documents.
2. **Weeks 3-6: shadow pilot** with 2-3 analysts. They keep working as usual; the assistant answers the
   same questions in parallel. We record time spent and every disagreement with the analyst.
3. **Week 7: decision.** Proposed bar: analysts agree with the sourced answers on at least 95% of a
   sampled set, no number is wrong without being flagged, and reviewers report a net time saving.
   Adjust these numbers with the team before starting.
4. **If it passes:** add user accounts, widen to more assets, and keep a standing review of corrections.

**Decision requested:** approve steps 1-2 (approvals and a six-week shadow pilot).
