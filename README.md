# Aetherius Risk Intelligence

**Deterministic, backtest-validated downside-risk screening on primary-source financial news and regulatory filings.**

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org/)
[![Tests: 76 passed](https://img.shields.io/badge/Tests-76%20passed-success.svg)](aetherius/tests/)
[![Backtest Recall: 9/9](https://img.shields.io/badge/Backtest%20Recall-100%25%20(9%2F9)-informational.svg)](docs/working_paper/detection_timing_backtest_2026-07.md)

---

## What is Aetherius?

Aetherius is an open-source risk-screening engine built for concentrated public-equity books, search funds, litigation-finance analysts, and credit desks. 

Instead of relying on black-box LLM prompts that hallucinate or non-deterministic sentiment models, Aetherius uses a **purely deterministic, auditable pipeline**:

1. **Primary-Source Ingestion** — Scrapes real-time SEC EDGAR filings (`8-K`, `10-Q`, `10-K`, `NT 10-K`) and global news wires via GDELT DOC 2.0.
2. **Word-Boundary Entity Resolution** — Strict regex matching with acronym stoplists to prevent false positives (e.g. distinguishing the ticker `AI` from words like `CHAIN` or `SAID`).
3. **Deterministic 7-Factor Severity Scoring** — Computes risk and urgency based on fixed compile-time taxonomies. Every single score is transparent, verifiable, and explainable in court or an investment committee.
4. **Automated Stress-Test Reports** — Assembles 8–15 page per-target diligence decks detailing counterparty exposure, filing timelines, and macro sensitivities.

---

## The Backtest Benchmark

Aetherius was validated by replaying 161 real historical news observations across three major modern crises on frozen windows using the GDELT archive:

| Event | Mechanism | Watchlist | Recall | Median Lead Time | False Positives on Controls |
|---|---|---|---|---|---|
| **SVB-2023** | Regional Bank Contagion (Mar 6–12) | 5 affected + MSFT (control) | **5 / 5 (100%)** | **2.34 days** | **0 / 1** |
| **Wirecard-2020** | Accounting Fraud & Insolvency (Jun 15–30) | 1 affected + DTE (control) | **1 / 1 (100%)** | **6.60 days** | **0 / 1** |
| **FTX-2022** | Counterparty Contagion (Nov 2–14) | 3 affected + MSFT (control) | **3 / 3 (100%)** | **7.12 days** | **0 / 1** |

*All fixtures, watchlists, ground-truth records, and replay harnesses are committed and bit-identical across runs. Read the full working paper: [`docs/working_paper/detection_timing_backtest_2026-07.md`](docs/working_paper/detection_timing_backtest_2026-07.md).*

---

## Architecture

```text
┌──────────────────────────────────────────────────────────┐
│                   Primary Ingestion                      │
│   • EDGAR Adapter (SEC 8-K, 10-Q, 10-K, NT filings)       │
│   • GDELT DOC 2.0 Adapter (Financial Whitelist Filter)   │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│                Entity Mapping & Filtering                │
│   • Word-boundary regex matching                         │
│   • Multi-class acronym stoplist (CEO, AI, FED, etc.)    │
│   • Declared alias & counterparty relationship links     │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│              Deterministic Severity Scoring              │
│   • 7-factor weighted scoring formula (compile-time)     │
│   • Adverse-language taxonomy gate (30+ downside terms)  │
│   • Zero LLM non-determinism in flagging logic          │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│                  Delivery & Reporting                    │
│   • 8-15 Page Target Stress-Test Deck generation (HTML)  │
│   • Delivery quality gates (banned language / disclaimers│
└──────────────────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Install Dependencies

```bash
git clone https://github.com/zariffromlatif/Aetherius.git
cd Aetherius
pip install -r requirements.txt
```

### 2. Run the Test Suite

```bash
pytest aetherius/tests -v
```

### 3. Replay a Historical Crisis Backtest

Replay the SVB regional-banking crisis through the production scoring and mapping engine:

```bash
python simulations/backtest/run_backtest.py --event svb-2023
```

*(You can also run `--event wirecard-2020` or `--event ftx-2022`)*.

### 4. Generate a Stress-Test Diligence Deck (Offline Fixture Mode)

```bash
python scripts/build_deck.py \
  --ticker SIVB \
  --name "SVB Financial Group" \
  --sector "Regional Banks" \
  --aliases "Silicon Valley Bank,SVB" \
  --thesis "Concentrated regional-bank position with rate-sensitive HTM book." \
  --counterparty "FRC:First Republic Bank:peer:0.6:First Republic" \
  --window 2023-03-06:2023-03-12 \
  --fixture-jsonl simulations/backtest/events/svb-2023/observations.jsonl \
  --out sivb-deck.html
```

Open `sivb-deck.html` in your browser and select **Print → Save as PDF** for a publication-ready diligence brief.

---

## Project Structure

```text
aetherius/
  app/
    services/
      ingestion/         # SEC EDGAR and GDELT API adapters
      entity_mapping/    # Regex and acronym disambiguation
      scoring/           # Deterministic risk & urgency formulas
      signals/           # Downside signal taxonomy
      delivery/          # PDF rendering & regulatory quality gates
  tests/                 # 76-test unit & integration test suite
simulations/
  backtest/
    events/              # Frozen crisis fixtures (SVB, Wirecard, FTX)
    run_backtest.py      # Backtest replay harness
    build_fixture.py     # GDELT fixture builder
scripts/
  build_deck.py          # CLI to compile Target Stress-Test Decks
docs/
  working_paper/         # Full academic write-up and methodology
```

---

## Contributing

We welcome contributions! Please check [`CONTRIBUTING.md`](CONTRIBUTING.md) for workflow details. All PRs must:
- Maintain deterministic scoring behavior.
- Include unit/integration tests (`pytest` passing 100%).
- Ensure historical crisis fixtures remain bit-identical.

---

## License

This project is licensed under the **Apache License 2.0** - see the [`LICENSE`](LICENSE) file for details.

---

## Disclaimer

*Aetherius Risk Intelligence is an open-source research and decision-support tool. It does not provide investment advice, fiduciary services, or guaranteed return forecasts. All analyses are strictly for informational and quantitative research purposes.*
