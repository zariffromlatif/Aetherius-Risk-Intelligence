# Working Paper

**Detection-Timing Backtest of a Deterministic Downside-Risk Screen Across Three Modern Financial Crises**
Md. Zarif Latif (BRAC University). Revision 2.1, October 2026 (first version July 2026).

Revision 2's headline finding: the pipeline flagged all 9 affected names before their formal resolution dates, but **no first flag came before the first headline reporting the stock already falling** (Section 4.5). The paper presents the system as fast, auditable triage, not anticipation.

## Files

- `detection_timing_backtest_2026-07.md` — the paper. Renders on GitHub, Substack, arXiv-style preprint sites. **This is the primary artifact.**
- `detection_timing_backtest_2026-07.html` — self-contained HTML. Open in any browser. Save-as-PDF via browser print dialog for a shareable attachment.

## Rebuild the HTML

```bash
python scripts/render_working_paper.py
```

The HTML has all CSS inlined and no external assets, so a single file emailed / posted anywhere renders correctly on any modern browser.

## Reproduce the results

The paper's numbers come from three pinned fixtures at `simulations/backtest/events/`:

```bash
# Reproduce all three events (offline, uses the committed observations.jsonl).
pytest aetherius/tests/test_backtest_harness.py -v

# Or per-event:
python simulations/backtest/run_backtest.py --event svb-2023
python simulations/backtest/run_backtest.py --event wirecard-2020
python simulations/backtest/run_backtest.py --event ftx-2022
```

To rebuild an event's observations corpus from live GDELT DOC 2.0:

```bash
python simulations/backtest/build_fixture.py --event svb-2023
```

Per-target GDELT responses are cached under `simulations/backtest/events/<event-id>/_gdelt_cache/` (git-ignored) so partial failures resume without re-fetching.

## Reproduce the market-timing result (Section 4.5)

```bash
PYTHONPATH=aetherius python simulations/backtest/market_reaction_check.py --markdown
pytest aetherius/tests/test_market_reaction_check.py -v
```

## Posting as a preprint

- **SSRN** (ssrn.com, free): good fit under Financial Economics → Risk Management. Upload a PDF made from the HTML (browser print → Save as PDF). No affiliation is required.
- **arXiv q-fin.RM / q-fin.CP**: a first-time submitter usually needs an endorsement from an existing arXiv author in that category. Ask a professor or a researcher whose work you cite.
- In the abstract, keep the Revision 2 framing: triage at the market reaction, not anticipation.
