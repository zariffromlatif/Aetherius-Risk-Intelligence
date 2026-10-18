# Live Forward Test

The historical backtest (`simulations/backtest/`) replays three crises chosen
with hindsight. This forward test answers the question a skeptic actually
asks: **what does the same frozen model say on live data, before anyone knows
the outcome, and how many of its alerts are noise?**

## Design

- **Pre-registered watchlist.** `watchlist.json` was committed on 2026-10-16,
  before any data was collected. It holds 20 large, liquid US names across
  sectors, all at `normal` priority, chosen for coverage rather than expected
  distress. SHA-256 at registration: `5bde996cb7b19a6cb1af4cf24ecde6c6fce73a71d7731a8d8cdf337154fca3d0`. Every run records the
  hash, and the report says loudly if it ever changes.
- **Frozen model.** Every observation is scored with the backtest's own
  `run_backtest._score_observation`. No tuning is allowed during the test.
- **Append-only, timestamped logs.** A daily GitHub Action
  (`.github/workflows/forward-test.yml`) pulls the last 26 hours of GDELT news
  plus recent SEC filings and commits the new rows to the `forward-test-log`
  branch. Each row carries `recorded_at`. The branch's commit history is the
  independent proof of *when* each alert was raised.
- **Every match is logged, not just flags**, so false-alarm rates and missed
  events can be measured later.

## Files (on the `forward-test-log` branch)

| File | Contents |
| --- | --- |
| `log/observations-YYYY-MM.jsonl` | Every matched observation with its scores |
| `log/flags-YYYY-MM.jsonl` | Only shippable (elevated/high, adverse) flags |
| `log/runs.jsonl` | One line per run: counts, watchlist hash, fetch errors |
| `log/REPORT.md` | Alert burden, labeled precision, price context |

## Measuring it honestly

1. **Label flags.** Add judgments to `labels.json` on `main`:
   `{"<flag key>": {"material": true, "note": "guidance cut"}}`. Label
   without looking at the price chart first where you can.
2. **Read the price context.** `summarize.py --prices` shows the stock's
   5-session return *before* and *after* each flag. Flags that mostly follow a
   ≥10% fall are reporting the move, not anticipating it.
3. **Report everything**, including weeks with only noise.

## Known limitations, recorded before the test

- **Ticker words.** Matching is case-insensitive, so tickers that are English
  words (`COIN`, `META`) match ordinary text ("coin prices fall"). They are kept in the list on purpose so this false-positive class gets measured.
- **EDGAR metadata only.** Filings are scored on form type and date, with no
  adverse wording, so EDGAR rows alone never become flags.
- **GDELT coverage** limits the news feed to the whitelisted domains in `gdelt_adapter.DOWNSIDE_DOMAINS`.
- **GDELT throttling.** GDELT rate-limits GitHub's shared runners. On the first
  run (2026-10-16), 6 of 20 names got "429 Too Many Requests" after every retry.
  Requests are now spaced 20 seconds apart (the second live run, still at
  6 seconds, again lost 6 of 20 names). Each run retries failed names once after a 2-minute cooldown, stops
  starting requests after a 40-minute budget, and records every name it could
  not fetch. The report's **News fetch failures** column shows these gaps: a
  failed day is missing coverage, not a quiet day.

## Run locally

```bash
python simulations/forward_test/run_forward_test.py --log-dir /tmp/ft-log
python simulations/forward_test/summarize.py --log-dir /tmp/ft-log --prices
```
