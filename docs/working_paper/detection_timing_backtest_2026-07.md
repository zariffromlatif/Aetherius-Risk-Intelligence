# Detection-Timing Backtest of a Deterministic Downside-Risk Screen Across Three Modern Financial Crises

**A working paper. Revision 2.1, October 2026 (first version July 2026).**

**Author:** Zarif Latif, independent researcher · zarif@aetheriusresearch.tech

**Keywords:** risk screening, event study, entity resolution, textual analysis, GDELT, SEC EDGAR, bank failures, backtesting

**JEL codes:** G14, G17, G21

> **What changed in Revision 2.** Revision 1 reported that the pipeline flagged all nine affected names "before the realized event date," with a median lead of about 2.5 days. That is true, but the realized event date was the *formal resolution* (receivership, insolvency filing, Chapter 11), not the market's reaction. Revision 2 adds a test of timing against the first headline reporting each stock already falling (Section 4.5). Measured that way, **no first flag came before the market reaction.** Revision 2 also adds confidence intervals, states the hindsight selection of events and watchlists, documents two known false-positive classes, removes commercial framing, and describes a pre-registered live forward test (Section 8). Every number in this revision is reproduced by pinned tests.
>
> **What changed in Revision 2.1.** A pre-publication check found that **no control name appears in any of the three corpora**, so the "0 false positives on controls" result was never actually tested. Text in Revisions 1 and 2 describing control headlines was wrong and has been removed. Section 4.6 explains what happened. Revision 2.1 also adds related work and references, and discloses that the Section 4.5 price-reaction pattern was written after the headlines had been read.

---

## Abstract

We replay a deterministic entity-mapping and severity-scoring pipeline against real news headlines from three well-studied financial crises: the March 2023 U.S. regional-bank contagion, the June 2020 Wirecard AG accounting fraud and the November 2022 FTX collapse. For each affected name we report detection timing and how it compares with the market's own reaction.

On 161 archived observations from GDELT DOC 2.0, the pipeline flagged **all 9 affected names** at "elevated" or "high" severity before each name's formal resolution date, with a median lead of 2.48 days. With only nine names, the 95% confidence interval for recall is 66–100%. The study's three control names never appear in the corpus, so it provides **no evidence about false positives**.

The more important finding is about timing. In all 9 detections, the first flag arrived **at the same time as, not before,** the first headline reporting that the stock was already falling. In 8 of 9 it *was* that headline. The pipeline is therefore evidence of fast, auditable **triage** of a market reaction already underway. It is not evidence of anticipating the market. We describe the pipeline, the corpus and the ground truth, discuss the limitations, and describe a pre-registered live forward test started on 2026-10-16. All code and data are Apache-2.0 licensed and reproducible.

**This is detection-timing evidence on frozen historical windows. It is not a return forecast, a trading signal, or a causal claim.**

---

## 1. Motivation

Concentrated public-equity books, such as those of search funds, small family offices, litigation-finance analysts and small credit shops, carry large single-name risk. Professional surveillance products are priced and configured for large institutional teams.

"Just read the news" fails because news is abundant, not scarce. A book of 5–10 names produces hundreds of candidate headlines a week, and human triage of that volume is uneven. A systematic screen helps in three narrow ways:

1. **Conservative entity resolution.** Each headline gets a word-boundary-safe answer to "does this really mention one of our names?"
2. **Deterministic severity scoring.** Each observation is scored against a fixed adverse-language list, so the same input always gets the same answer and every score can be audited.
3. **False-positive discipline.** Adverse content on names outside the book, and benign content on names inside it, should stay quiet.

The question here is narrow: **on the headlines that actually existed at the time, when would this pipeline have flagged the affected names, both relative to their formal resolution and relative to the market's own reaction?** False-positive behavior is the subject of the live forward test (Section 8), because this corpus cannot measure it (Section 4.6).

### 1.1 Related work

Media text carries information about stock returns and firm fundamentals: pessimistic language in a daily newspaper column predicts downward pressure on market prices (Tetlock, 2007), and the share of negative words in firm-specific news predicts earnings and returns (Tetlock, Saar-Tsechansky and Macskassy, 2008). Word lists matter in finance: Loughran and McDonald (2011) show that general-purpose negative-word dictionaries misclassify many common financial terms, and build finance-specific lists from 10-K filings. This paper's adverse-term list is smaller and hand-written. Replacing it with the Loughran–McDonald negative list is a natural robustness test (Section 8). Event timing here follows the event-study idea of measuring information arrival around a dated event (Fama, Fisher, Jensen and Roll, 1969), but uses headline timestamps, not returns. The news archive is the GDELT project (Leetaru and Schrodt, 2013).

---

## 2. Pipeline overview

The pipeline is the production Aetherius code, unchanged for this exercise. Paths are relative to the repository root.

### 2.1 Ingestion

- **`aetherius/app/services/ingestion/edgar_adapter.py`** maps a ticker to its SEC CIK, pulls submissions from `data.sec.gov`, keeps downside-relevant forms (`8-K`, `10-Q`, `10-K`, `NT 10-Q`, `NT 10-K` and amendments), and writes one observation per filing. The observation text contains the form type, date and accession number, *not* the filing body.
- **`aetherius/app/services/ingestion/gdelt_adapter.py`** queries GDELT DOC 2.0 for the company name and aliases, keeps a whitelist of financial-news domains, and writes one observation per article (headline plus provenance line), deduplicated by URL.

For the backtest, all news observations come from GDELT.

### 2.2 Entity mapping

`aetherius/app/services/entity_mapping/service.py` matches each observation's upper-cased text against each watchlist name:

- Word-boundary regex `(?<![A-Z0-9]){name}(?![A-Z0-9])`, so ticker `AI` cannot match inside `CHAIN` or `SAID`.
- An acronym stoplist (`CEO`, `GDP`, `FED`, `USD`, `AI`, …) for ticker-shaped token extraction.
- Matches on ticker, company name, aliases, sector, and declared relationships, returning a relationship type and a relevance score. The precedence is direct, then sector, then relationship.

Because matching is case-insensitive, a ticker that is also an English word matches ordinary text (Section 5.5).

### 2.3 Severity scoring

`aetherius/app/services/scoring/service.py` computes:

- a **risk score**: a fixed weighted sum of source confidence, freshness, directness, cross-confirmation, watchlist priority, event severity and relationship strength;
- an **urgency score** and a **brief-priority score** derived from it.

`severity_label()` bins risk into `low`, `moderate`, `elevated` or `high`. Every weight is a constant, and there are no learned parameters.

### 2.4 Adverse-language gate

`adverse_severity(raw_text)` (same module) counts matches against a fixed list of about 40 downside terms (`loss`, `plunge`, `withdrawals`, `deposit run`, `receivership`, `collapse`, `funding pressure`, `distress`, `insolven…`, …) and maps the count to an event-severity score. An observation is a **shippable flag** only when its severity label is `elevated` or `high` **and** at least one adverse term is present. Unit tests show the gate holding a benign direct mention below shippable severity (for example, "Microsoft expands Copilot across product suite"). The backtest corpora contain no such case for the controls (Section 4.6). Since Revision 2, the live API, the backtest and the forward test all import this single implementation.

### 2.5 Backtest harness

`simulations/backtest/run_backtest.py` replays each event's `observations.jsonl` in chronological order against its `watchlist.json` and `ground_truth.json`, records the first shippable flag per name, and computes:

- **Detection recall:** affected names with a shippable flag before the realized event date.
- **Lead time:** hours from first flag to the *realized event date* in `ground_truth.json`, which is the formal resolution date (Appendix B).
- **Mapping precision:** raw matches attributable to affected names or their declared relationships.
- **False positives:** control names that produced any shippable flag.

Reruns of the same fixture at the same commit produce bit-identical metrics.

---

## 3. Corpus construction

Every news observation came from GDELT DOC 2.0. There are no hand-written summaries, and every observation keeps its real `source_url`. `simulations/backtest/build_fixture.py`:

1. reads the event's watchlist and ground truth;
2. queries GDELT per watchlist name over the event window;
3. keeps only the domain whitelist (Reuters, Bloomberg, WSJ, FT, MarketWatch, CNBC, Yahoo Finance, Motley Fool, Investor's Business Daily, American Banker, regulators, and others);
4. deduplicates by URL;
5. prepends regulatory anchors (SEC filings, FDIC releases, insolvency filings) from `ground_truth.primary_sources`;
6. writes the merged, chronological `observations.jsonl`.

An earlier SVB fixture of hand-written summaries was removed from the repository. All results use the GDELT corpus.

---

## 4. Results

### 4.1 Aggregate

| Metric | Value |
|---|---|
| Events | 3 |
| Observations replayed | 161 |
| Watchlist names (union) | 12 (9 affected + 3 controls, the controls never appear in the corpus) |
| Affected names flagged before resolution date | **9 / 9** (95% CI 66–100%) |
| Median lead to resolution date | 2.48 days (mean 3.58) |
| Mapping precision | 100% (uninformative: no control was ever matched) |
| False positives on controls | not tested (Section 4.6) |
| First flags that came **before** the first price-reaction headline | **0 / 9** (Section 4.5) |

Confidence intervals are exact (Clopper–Pearson, 1934) binomial intervals. The nine names span three failure modes: bank runs (SVB, Signature, First Republic, Western Alliance, PacWest), accounting fraud (Wirecard) and crypto counterparty contagion (Silvergate, Coinbase, Signature).

### 4.2 SVB-2023

**Event.** On 2023-03-08 SVB Financial Group (SIVB) disclosed a loss on a $21B securities sale and a planned $2.25B capital raise. Deposit outflows followed, and the FDIC took SVB into receivership on 2023-03-10. Signature Bank was closed on 2023-03-12.

**Watchlist.** SIVB, SBNY, FRC, WAL and PACW, with MSFT as a non-bank control. **Corpus:** 98 observations, 2023-03-06 to 2023-03-12.

| Ticker | First flag | Resolution date | Lead (d) | Peak severity | First-flag evidence |
|---|---|---|---|---|---|
| SIVB | 2023-03-09 13:00Z | 2023-03-10 | 0.46 | high | marketwatch.com: *SVB Financial stock plummets toward biggest one-day selloff in 23 years* |
| SBNY | 2023-03-09 12:30Z | 2023-03-12 | 2.48 | high | marketwatch.com: *Signature Bank stock drops sharply after Silvergate announces winddown* |
| FRC | 2023-03-09 17:45Z | 2023-03-13 | 3.26 | high | fool.com: *Why Shares of First Republic Bank Are Falling Today* |
| WAL | 2023-03-10 15:45Z | 2023-03-13 | 2.34 | elevated | investors.com: *SVB Trading Halted, Company Seeks Buyer, Financial Stocks Shudder* |
| PACW | 2023-03-10 15:45Z | 2023-03-13 | 2.34 | high | investors.com: *SVB Trading Halted, Company Seeks Buyer, Financial Stocks Shudder* |

### 4.3 Wirecard-2020

**Event.** On 2020-06-18 Wirecard AG (WDI) disclosed that €1.9B of reported cash likely did not exist. It filed for insolvency on 2020-06-25.

**Watchlist.** WDI, with Deutsche Telekom (DTE) as a control. Payments peers were left out to avoid scoring `peer_readthrough` flags. **Corpus:** 14 observations, 2020-06-15 to 2020-06-30. The corpus is thin because European coverage falls mostly outside the whitelist, which was not widened after the fact.

| Ticker | First flag | Resolution date | Lead (d) | Peak severity | First-flag evidence |
|---|---|---|---|---|---|
| WDI | 2020-06-18 09:30Z | 2020-06-25 | 6.60 | high | marketwatch.com: *Wirecard shares plunge as Ernst & Young says no evidence for 1.9 billion euros of cash on balance sheet* |

### 4.4 FTX-2022

**Event.** On 2022-11-02 CoinDesk reported that Alameda Research's assets were largely FTX-issued FTT tokens. FTX halted withdrawals on 2022-11-08 and filed Chapter 11 on 2022-11-11. The test is contagion into listed crypto-exposed equities.

**Watchlist.** SI, COIN and SBNY, with MSFT as a control. **Corpus:** 49 observations, 2022-11-02 to 2022-11-14.

| Ticker | First flag | Resolution date | Lead (d) | Peak severity | First-flag evidence |
|---|---|---|---|---|---|
| SI | 2022-11-03 21:00Z | 2022-11-11 | 7.12 | high | fool.com: *Why Coinbase, Silvergate Capital, and Marathon Digital Holdings Are Falling This Week* |
| COIN | 2022-11-03 21:00Z | 2022-11-11 | 7.12 | high | fool.com: *(same article)* |
| SBNY | 2022-11-10 11:00Z | 2022-11-11 | 0.54 | elevated | marketwatch.com: *Robinhood, Coinbase Distance Themselves from FTX After Crypto Plunge* |

Both 7.12-day leads come from a single article. Without it, both would shrink substantially.

### 4.5 Timing relative to the market reaction

The lead times above are measured to the formal resolution date. An investor cares about a different clock: when the *price* moved. The evidence titles in Sections 4.2–4.4 already hint at the answer, since almost every one reports a stock that is falling.

`simulations/backtest/market_reaction_check.py` makes this precise. For each detected name, it finds the earliest observation in the corpus that maps to that name and reports a price decline already underway, using a pattern that pairs a price noun ("shares", "stock") with a falling verb ("plunge", "drops", "falling", …). It then compares that headline's time with the first flag. The pattern was written after the headlines had been read, so this is not a blind test. Every classification is listed below with its headline, and each can be checked by eye.

| Event | Ticker | First flag | First price-reaction headline | Flag lead over reaction | Flag headline itself reports a fall |
|---|---|---|---|---|---|
| SVB-2023 | FRC | 2023-03-09 17:45Z | 2023-03-09 17:45Z | 0.0 h | yes |
| SVB-2023 | PACW | 2023-03-10 15:45Z | 2023-03-10 15:45Z | 0.0 h | yes |
| SVB-2023 | SBNY | 2023-03-09 12:30Z | 2023-03-09 12:30Z | 0.0 h | yes |
| SVB-2023 | SIVB | 2023-03-09 13:00Z | 2023-03-09 13:00Z | 0.0 h | yes |
| SVB-2023 | WAL | 2023-03-10 15:45Z | 2023-03-10 15:45Z | 0.0 h | yes |
| Wirecard-2020 | WDI | 2020-06-18 09:30Z | 2020-06-18 09:30Z | 0.0 h | yes |
| FTX-2022 | COIN | 2022-11-03 21:00Z | 2022-11-03 21:00Z | 0.0 h | yes |
| FTX-2022 | SI | 2022-11-03 21:00Z | 2022-11-03 21:00Z | 0.0 h | yes |
| FTX-2022 | SBNY | 2022-11-10 11:00Z | none in corpus | n/a | no (headline reports a *crypto* price fall) |

**No first flag came before the market reaction.** The pipeline flagged each name at the moment the press reported its shares falling. This is expected given how it works: adverse-language scoring of headlines fires most strongly on headlines *about* a sell-off.

That is still useful for a small team. Out of hundreds of headlines, the names that need attention today were surfaced within the same news cycle, with an auditable reason. But it is **triage, not anticipation**, and Revision 1's framing of "lead time" overstated what the evidence supports.

### 4.6 The control test was not exercised

Each fixture includes one control name (MSFT twice, DTE once) that the pipeline should not flag. None did, but none could have: **no observation in any corpus maps to a control name.** The fixture builder did query GDELT for each control ("Microsoft Corporation", "Deutsche Telekom"), and GDELT returned articles. GDELT matches article bodies, but the pipeline stores and scores headlines only, and none of those headlines names the control. `market_reaction_check.py` prints this coverage, and a test (`test_controls_never_appear_in_the_frozen_corpora`) pins it so the paper must be updated if a fixture is ever rebuilt.

Revisions 1 and 2 reported "0 false positives on 3 controls" as evidence of specificity, and described control headlines that do not exist in the data. Both were errors. This study therefore says nothing about how often the screen fires on companies that turned out fine. The same fact makes the 100% mapping precision uninformative. Measuring false positives is the purpose of the forward test (Section 8).

---

## 5. Limitations

### 5.1 What this measures and what it does not

**It measures** whether, on a whitelisted, archived corpus, the pipeline flags known-affected names at elevated or high severity before the formal resolution date, and how that timing compares with the press reporting the price reaction.

**It does not measure:**

- **Returns.** There is no PnL, position sizing or execution.
- **Anticipation of price moves.** See Section 4.5.
- **Causality.** No causal model is used.
- **Unfiltered feeds.** False-positive rates on the full GDELT firehose would be higher.
- **Non-Anglophone events.** The Wirecard corpus has only 14 observations.
- **Adversarial input.** Misleading press releases are not defended against.

### 5.2 Sample size

Three events and nine affected names make a very small sample. 9/9 recall is consistent with a true recall as low as 66% (exact binomial 95% interval). There is no false-positive sample at all (Section 4.6). One added event that failed would deserve equal reporting.

### 5.3 Hindsight selection

The three events, the affected names, and the decision to include each name were all chosen **after the outcomes were known**, from among the best-known failures of recent years. The adverse-term list was also written by people who knew how these crises unfolded, and its vocabulary ("deposit run", "receivership", "unrealized loss", "capital raise") is close to bank-run reporting. A screen tested only on famous failures cannot tell us how often it fires on companies that turned out fine. The forward test in Section 8 is designed to address this.

### 5.4 Lookahead

The harness sorts observations by GDELT `seendate` and only counts flags strictly before the resolution date (pinned by `test_time_safety_lead_time_never_negative`). Regulatory anchors are inserted at a small offset from the resolution date. Removing them, and keeping news headlines only, leaves recall and median lead unchanged for all three events (5/5 and 2.34 days, 1/1 and 6.60 days, 3/3 and 7.12 days).

### 5.5 Known false-positive classes

- **Ticker words.** Matching is case-insensitive, so a ticker that is an English word matches ordinary text. For example, "Bitcoin *coin* prices fall" matches Coinbase (`COIN`) directly. The live forward test keeps `COIN` and `META` on its watchlist to measure this.
- **Substring adverse terms.** Terms match as substrings, so "fall" also fires inside "shortfall" or "fallout", and "slide" fires on a presentation slide.
- **EDGAR metadata.** Filing observations hold the form type and date, not the filing text, so they never contain adverse terms and cannot ship on their own. EDGAR currently adds provenance, not signal.

### 5.6 Domain whitelist

The whitelist was fixed before the fixtures were built and was not tuned on results. It is still a selection: adding aggregators would raise both coverage and noise.

---

## 6. Reproduction

Repository: `https://github.com/zariffromlatif/Aetherius-Risk-Intelligence` (Apache-2.0).

```bash
pip install -r requirements.txt

# Full test suite, including the pinned backtest and market-timing results.
pytest aetherius/tests -v

# Per-event backtest metrics.
python simulations/backtest/run_backtest.py --event svb-2023
python simulations/backtest/run_backtest.py --event wirecard-2020
python simulations/backtest/run_backtest.py --event ftx-2022

# Section 4.5 table.
PYTHONPATH=aetherius python simulations/backtest/market_reaction_check.py --markdown

# (Optional, needs internet) Rebuild a corpus from GDELT DOC 2.0.
python simulations/backtest/build_fixture.py --event svb-2023
```

---

## 7. What this paper is not

- **A trading strategy.** Section 4.5 shows the flags coincide with the market reaction.
- **A causal claim.** Deposit-run headlines two days before a receivership are downstream of balance-sheet stress, not upstream of it.
- **A guarantee.** The pipeline could miss a future event that unfolds in a way not seen here.

What it does show is narrower: a small, deterministic, auditable pipeline running on real headlines would have put nine affected names in front of a reviewer within the same news cycle as their market reaction, ahead of formal resolution. It does not show how often the screen raises false alarms.

---

## 8. Future work

1. **Pre-registered live forward test (running since 2026-10-16).** `simulations/forward_test/` fixes a 20-name, all-`normal`-priority watchlist chosen for coverage rather than expected distress, and commits its hash. A daily GitHub Action scores live GDELT news and SEC filings with the *frozen* backtest scorer and appends timestamped rows to the `forward-test-log` branch. The planned report covers alerts per name per week, human-labeled precision, and the stock's 5-session return before and after each flag.
2. **Rule-based event selection.** Choose events by a rule fixed in advance (for example, every listed U.S. bank failure on the FDIC list in a period, or every S&P 500 constituent with a ≥50% drawdown in a year) instead of by fame.
3. **Real controls.** Rebuild each fixture with control headlines that actually name the control company, ideally many controls per event chosen by a rule (for example, every same-sector name that did not fail), and report false positives with confidence intervals.
4. **Finance-specific word lists.** Re-run with the Loughran and McDonald (2011) negative list in place of the hand-written adverse terms.
5. **Price-anchored evaluation.** Measure timing against the first ≥10% close-to-close decline, using price data, not headlines.
6. **Matcher fixes.** Use case-sensitive ticker matching or require a cashtag for ticker-word symbols, and add whole-word adverse terms. These would be evaluated as a *new* model version, with the frozen version kept for comparison.
7. **Filing text.** Score 8-K item text (for example, Item 2.06 impairments or Item 4.02 non-reliance) instead of metadata.

---

## References

Clopper, C. J., and Pearson, E. S. (1934). The use of confidence or fiducial limits illustrated in the case of the binomial. *Biometrika*, 26(4), 404–413.

Fama, E. F., Fisher, L., Jensen, M. C., and Roll, R. (1969). The adjustment of stock prices to new information. *International Economic Review*, 10(1), 1–21.

Leetaru, K., and Schrodt, P. A. (2013). GDELT: Global data on events, location, and tone, 1979–2012. Paper presented at the International Studies Association Annual Convention.

Loughran, T., and McDonald, B. (2011). When is a liability not a liability? Textual analysis, dictionaries, and 10-Ks. *Journal of Finance*, 66(1), 35–65.

Tetlock, P. C. (2007). Giving content to investor sentiment: The role of media in the stock market. *Journal of Finance*, 62(3), 1139–1168.

Tetlock, P. C., Saar-Tsechansky, M., and Macskassy, S. (2008). More than words: Quantifying language to measure firms' fundamentals. *Journal of Finance*, 63(3), 1437–1467.

---

## Appendix A — Watchlists

Full JSON lives at `simulations/backtest/events/<event-id>/watchlist.json`.

Controls are listed for completeness; none appears in its corpus (Section 4.6).

- **SVB-2023:** SIVB (critical), SBNY (high), FRC (high), WAL (normal), PACW (normal), MSFT (control)
- **Wirecard-2020:** WDI (critical), DTE (control)
- **FTX-2022:** SI (critical), COIN (high), SBNY (normal), MSFT (control)

## Appendix B — Ground truth

Each "realized event date" is the formal resolution date, not the first price reaction.

| Event | Ticker | Realized event date | Expected min severity |
|---|---|---|---|
| SVB-2023 | SIVB | 2023-03-10 (FDIC receivership) | high |
| SVB-2023 | SBNY | 2023-03-12 (NY DFS closure) | elevated |
| SVB-2023 | FRC | 2023-03-13 (deposit flight) | elevated |
| SVB-2023 | WAL | 2023-03-13 (drawdown) | elevated |
| SVB-2023 | PACW | 2023-03-13 (drawdown) | elevated |
| Wirecard-2020 | WDI | 2020-06-25 (insolvency filing) | high |
| FTX-2022 | SI | 2022-11-11 (FTX Chapter 11) | high |
| FTX-2022 | COIN | 2022-11-11 | elevated |
| FTX-2022 | SBNY | 2022-11-11 | elevated |

## Appendix C — Primary sources

**SVB-2023.** SEC EDGAR, SVB Financial Group (CIK 0000719739), Form 8-K filed 2023-03-08. FDIC press release pr23016 (2023-03-10). Federal Reserve joint statement (2023-03-12).

**Wirecard-2020.** Wirecard AG ad-hoc release (2020-06-18). BaFin statements (2020-06-18 to 2020-06-25). Insolvency filing, Munich District Court (2020-06-25).

**FTX-2022.** CoinDesk Alameda balance-sheet report (2022-11-02). Binance FTT announcement (2022-11-06). FTX Chapter 11 filing, D. Del. (2022-11-11). Silvergate Capital 8-K filings (November 2022).

Every news observation also carries its own `source_url`.

## Appendix D — Reproducibility

- **License:** Apache-2.0.
- **Tests:** the full suite (122 tests at Revision 2.1) pins the backtest metrics, the Section 4.5 timing result, the Section 4.6 control coverage, and the parity between live and backtest scoring.
- **Determinism:** scoring weights are constants with no learned parameters, and reruns are bit-identical.
- **Rebuild:** corpora can be regenerated from GDELT DOC 2.0 with `simulations/backtest/build_fixture.py`.

---

*Research software. Not investment advice, and not a recommendation to buy, sell or hold any security.*
