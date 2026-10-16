from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "aetherius"
if str(APP_ROOT) not in sys.path:
    sys.path.append(str(APP_ROOT))

from app.services.entity_mapping.service import extract_entities, match_item  # noqa: E402
from app.services.scoring.service import (  # noqa: E402
    ADVERSE_TERMS,
    PRIORITY_SCORE,
    SEVERITY_RANK,
    SHIP_SEVERITIES,
    ScoreInput,
    adverse_severity,
    compute_brief_priority_score,
    compute_risk_score,
    compute_urgency_score,
    confidence_label,
    severity_label,
)

EVENTS_DIR = Path(__file__).resolve().parent / "events"
VALIDATION_DIR = REPO_ROOT / "simulations" / "validation"

_SEVERITY_RANK = SEVERITY_RANK
_SHIP_SEVERITIES = SHIP_SEVERITIES
_ADVERSE_TERMS = ADVERSE_TERMS
_adverse_severity = adverse_severity


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _load_event(event_id: str):
    base = EVENTS_DIR / event_id
    watchlist = json.loads((base / "watchlist.json").read_text(encoding="utf-8"))
    ground_truth = json.loads((base / "ground_truth.json").read_text(encoding="utf-8"))
    observations = []
    for line in (base / "observations.jsonl").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            observations.append(json.loads(line))
    observations.sort(key=lambda o: _parse_dt(o["observed_at"]))
    return watchlist, observations, ground_truth


def _score_observation(obs, item, relationship_type, relevance):
    event_severity = _adverse_severity(obs.get("raw_text", ""))
    inpt = ScoreInput(
        source_confidence=float(obs.get("source_confidence", 0.7)),
        freshness_score=0.9,
        directness_score=relevance,
        cross_confirmation_score=0.5,
        watchlist_priority_score=PRIORITY_SCORE.get(item.get("priority_level"), 0.5),
        event_severity_score=event_severity,
        relationship_strength_score=relevance,
        time_sensitivity=0.6,
        event_window_proximity=0.6,
    )
    risk = compute_risk_score(inpt)
    urgency = compute_urgency_score(inpt, risk)
    priority = compute_brief_priority_score(inpt, risk, urgency)
    return {
        "risk_score": risk,
        "urgency_score": urgency,
        "brief_priority_score": priority,
        "severity": severity_label(risk),
        "confidence": confidence_label(risk),
        "relationship_type": relationship_type,
        "event_severity_score": event_severity,
    }


def run_backtest(event_id: str, commit: str | None = None) -> dict:
    watchlist, observations, ground_truth = _load_event(event_id)
    items = watchlist["items"]

    affected = {a["ticker"]: a for a in ground_truth.get("affected", [])}
    controls = {c["ticker"] for c in ground_truth.get("controls_should_not_flag", [])}

    first_flag = {}
    max_severity_rank = {}
    all_flags = []
    mapping_hits = 0
    mapping_total = 0

    for obs in observations:
        text_upper = obs["raw_text"].upper()
        extracted = {e["ticker"] for e in extract_entities(obs["raw_text"])}
        obs_dt = _parse_dt(obs["observed_at"])

        for item in items:
            match = match_item(
                text_upper,
                ticker=item["ticker"],
                company_name=item.get("company_name"),
                sector=item.get("sector"),
                aliases=item.get("aliases"),
                relationships=item.get("relationships"),
            )
            if not match:
                continue
            relationship_type, relevance = match
            mapping_total += 1
            if item["ticker"] in affected or relationship_type.endswith("_readthrough"):
                mapping_hits += 1

            scored = _score_observation(obs, item, relationship_type, relevance)
            flag = {
                "ticker": item["ticker"],
                "observed_at": obs["observed_at"],
                "title": obs.get("title"),
                "source_name": obs.get("source_name"),
                "source_url": obs.get("source_url"),
                "extracted_tickers": sorted(extracted),
                **scored,
            }
            # A name match on benign content (no adverse/risk language at all) is
            # not a shippable risk flag, however direct the match. This is what
            # keeps a control like MSFT ("expands Copilot") from false-positiving
            # purely on the strength of its name appearing in the text.
            is_shippable = scored["severity"] in _SHIP_SEVERITIES and scored["event_severity_score"] > 0.0
            if is_shippable:
                all_flags.append(flag)
                ticker = item["ticker"]
                rank = _SEVERITY_RANK[scored["severity"]]
                if rank > max_severity_rank.get(ticker, -1):
                    max_severity_rank[ticker] = rank
                if ticker not in first_flag:
                    flag["_dt"] = obs_dt
                    first_flag[ticker] = flag

    detections = []
    misses = []
    for ticker, gt in affected.items():
        realized = _parse_dt(gt["realized_event_date"])
        if ticker in first_flag:
            flag = first_flag[ticker]
            lead_hours = (realized - flag["_dt"]).total_seconds() / 3600.0
            # Lead time is measured from the FIRST shippable flag (earliest
            # detection), but expected-severity is judged against the PEAK
            # severity the name reached across the window: a name can be flagged
            # early at "elevated" and escalate to "high" before the event.
            peak_rank = max_severity_rank.get(ticker, _SEVERITY_RANK[flag["severity"]])
            reached = peak_rank >= _SEVERITY_RANK[gt.get("expected_min_severity", "elevated")]
            peak_severity = next(s for s, r in _SEVERITY_RANK.items() if r == peak_rank)
            detections.append({
                "ticker": ticker,
                "first_flag_at": flag["observed_at"],
                "realized_event_date": gt["realized_event_date"],
                "lead_time_hours": round(lead_hours, 1),
                "lead_time_days": round(lead_hours / 24.0, 2),
                "first_flag_severity": flag["severity"],
                "peak_severity": peak_severity,
                "reached_expected_severity": reached,
                "evidence_title": flag["title"],
                "evidence_source": flag["source_name"],
            })
        else:
            misses.append({"ticker": ticker, "realized_event_date": gt["realized_event_date"]})

    false_positives = sorted({f["ticker"] for f in all_flags if f["ticker"] in controls})
    lead_times = [d["lead_time_hours"] for d in detections if d["lead_time_hours"] > 0]
    median_lead = sorted(lead_times)[len(lead_times) // 2] if lead_times else 0.0

    return {
        "event_id": event_id,
        "event_name": ground_truth.get("event_name"),
        "commit": commit or "unspecified",
        "dataset_window": {"start": ground_truth.get("window_start"), "end": ground_truth.get("window_end")},
        "observation_count": len(observations),
        "watchlist_size": len(items),
        "affected_count": len(affected),
        "control_count": len(controls),
        "detection_recall": round(len(detections) / len(affected), 3) if affected else 0.0,
        "detections_reaching_expected_severity": sum(1 for d in detections if d["reached_expected_severity"]),
        "mapping_precision": round(mapping_hits / mapping_total, 3) if mapping_total else 0.0,
        "false_positive_tickers": false_positives,
        "false_positive_count": len(false_positives),
        "median_lead_time_hours": round(median_lead, 1),
        "median_lead_time_days": round(median_lead / 24.0, 2),
        "detections": sorted(detections, key=lambda d: d["ticker"]),
        "misses": misses,
        "shippable_flag_count": len(all_flags),
        "anti_hype_note": (
            "Measures detection timing and ranking on a frozen historical window. "
            "This is early-detection and prioritization evidence, NOT a return forecast "
            "or guarantee. Causal-mechanism confidence is not claimed here."
        ),
    }


def _render_summary(m: dict) -> str:
    L = []
    L.append("# Aetherius Backtest Summary - " + str(m["event_name"]))
    L.append("")
    L.append("- Event ID: `" + m["event_id"] + "`")
    L.append("- Commit: `" + m["commit"] + "`")
    L.append("- Dataset window: " + str(m["dataset_window"]["start"]) + " -> " + str(m["dataset_window"]["end"]))
    L.append("- Observations replayed: " + str(m["observation_count"]) + " | Watchlist size: " + str(m["watchlist_size"]))
    L.append("")
    L.append("## Headline metrics")
    L.append("")
    L.append("| Metric | Value |")
    L.append("| --- | --- |")
    L.append("| Detection recall | " + format(m["detection_recall"], ".0%") + " (" + str(len(m["detections"])) + "/" + str(m["affected_count"]) + ") |")
    L.append("| Median lead time | " + str(m["median_lead_time_days"]) + " days (" + str(m["median_lead_time_hours"]) + " h) |")
    L.append("| Mapping precision | " + format(m["mapping_precision"], ".0%") + " |")
    L.append("| False positives | " + str(m["false_positive_count"]) + " " + str(m["false_positive_tickers"] or "") + " |")
    L.append("")
    L.append("## Detections (first evidence-backed elevated/high flag per name)")
    L.append("")
    L.append("| Ticker | First flag | Realized event | Lead (days) | Severity | Evidence |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    for d in m["detections"]:
        L.append("| " + d["ticker"] + " | " + d["first_flag_at"] + " | " + d["realized_event_date"] + " | " + str(d["lead_time_days"]) + " | " + d["first_flag_severity"] + " | " + str(d["evidence_source"]) + ": " + str(d["evidence_title"]) + " |")
    if m["misses"]:
        L.append("")
        L.append("## Misses")
        for x in m["misses"]:
            L.append("- " + x["ticker"] + " (realized " + x["realized_event_date"] + ")")
    L.append("")
    L.append("## Honest reading")
    L.append("")
    L.append(m["anti_hype_note"])
    L.append("")
    return "\n".join(L)


def _control_observation_count(event_id: str) -> int:
    """Observations that map to any control name; 0 means the control test is vacuous."""
    watchlist, observations, ground_truth = _load_event(event_id)
    controls = {c["ticker"] for c in ground_truth.get("controls_should_not_flag", [])}
    items = [i for i in watchlist["items"] if i["ticker"] in controls]
    return sum(
        1
        for obs in observations
        for item in items
        if match_item(
            obs["raw_text"].upper(),
            ticker=item["ticker"],
            company_name=item.get("company_name"),
            sector=item.get("sector"),
            aliases=item.get("aliases"),
            relationships=item.get("relationships"),
        )
    )


def _git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        )
        return out.stdout.strip() or "unspecified"
    except (OSError, subprocess.CalledProcessError):
        return "unspecified"


def _resolve_commit(metrics: dict, metrics_path: Path, explicit: str | None) -> str:
    """Pick the commit label to record for this run.

    An explicit ``--commit`` always wins. Otherwise, if the committed metrics are
    identical apart from the label, keep the existing label so a plain
    reproduction run leaves the tree clean. If the numbers moved, record the
    current git HEAD so the new results are attributable.
    """
    if explicit:
        return explicit
    if metrics_path.exists():
        try:
            previous = json.loads(metrics_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None
        if previous and {k: v for k, v in previous.items() if k != "commit"} == {
            k: v for k, v in metrics.items() if k != "commit"
        }:
            return previous.get("commit") or _git_head()
    return _git_head()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an Aetherius historical detection-timing backtest.")
    parser.add_argument("--event", default="svb-2023")
    parser.add_argument("--commit", default=None)
    args = parser.parse_args()

    metrics = run_backtest(args.event, commit=args.commit)
    out_dir = VALIDATION_DIR / args.event
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics["commit"] = _resolve_commit(metrics, out_dir / "metrics.json", args.commit)
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (out_dir / "summary.md").write_text(_render_summary(metrics), encoding="utf-8")

    print("Backtest complete for event=" + args.event)
    print("  detection recall : " + format(metrics["detection_recall"], ".0%") + " (" + str(len(metrics["detections"])) + "/" + str(metrics["affected_count"]) + ")")
    print("  median lead time : " + str(metrics["median_lead_time_days"]) + " days")
    print(
        "  false positives  : " + str(metrics["false_positive_count"])
        + " (controls matched in corpus: " + str(_control_observation_count(args.event)) + ")"
    )
    print("  metrics -> " + str(out_dir / "metrics.json"))
    print("  summary -> " + str(out_dir / "summary.md"))


if __name__ == "__main__":
    main()