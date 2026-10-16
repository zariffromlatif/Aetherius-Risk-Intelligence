import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import BriefingEvidenceRefs, BriefingItems, BriefingRuns, Deliveries
from app.utils.time import utcnow


def _env() -> Environment:
    template_dir = Path(__file__).resolve().parents[2] / "templates"
    return Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html"]))


def render_email(briefing_run: BriefingRuns, items: list[BriefingItems]) -> str:
    template = _env().get_template("email/daily_brief.html")
    return template.render(run=briefing_run, items=items)


def render_pdf_html(briefing_run: BriefingRuns, items: list[BriefingItems]) -> str:
    template = _env().get_template("pdf/daily_brief.html")
    return template.render(run=briefing_run, items=items)


def render_pdf_bytes(briefing_run: BriefingRuns, items: list[BriefingItems]) -> bytes:
    from weasyprint import HTML

    html = render_pdf_html(briefing_run, items)
    return HTML(string=html).write_pdf()


# Looser markers used to detect the disclaimer regardless of template whitespace.
# Kept in sync with the disclaimer block in templates/email/daily_brief.html
# and templates/pdf/daily_brief.html.
_DISCLAIMER_TOKENS = ("information and risk-monitoring service", "not investment advice")

# Hype / certainty language that must never reach a client-facing brief.
BANNED_LANGUAGE = (
    "guaranteed",
    "certain",
    "must",
    "obvious crash",
    "sure thing",
    "can't lose",
    "cannot lose",
    "risk-free",
    "riskless",
    "will crash",
    "will collapse",
    "definitely",
)


DUPLICATE_SUPPRESSED = "Duplicate alert suppressed unless materially changed."
RETRY_BASE_DELAY = timedelta(minutes=5)


def _normalize(text: str) -> str:
    return " ".join((text or "").split()).lower()


def _contains_banned(body: str) -> bool:
    """Whole-word/phrase match for banned language.

    Word-boundary matching so legitimate, compliant prose is not rejected:
    "uncertain"/"uncertainty" must not trip on "certain", and "must" must not
    trip inside "mustard"/"customer". Multi-word entries match as phrases.
    """
    normalized = _normalize(body)
    for term in BANNED_LANGUAGE:
        if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", normalized):
            return True
    return False


def disclaimer_present(rendered_html: str) -> bool:
    """True if the rendered brief contains the required disclaimer.

    Whitespace-insensitive so template reflow does not silently disable the gate.
    """
    normalized = _normalize(rendered_html)
    return all(_normalize(token) in normalized for token in _DISCLAIMER_TOKENS)


def quality_gates(items: list[BriefingItems], recipient: str) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if not items:
        issues.append("No briefing items to send.")
    if "@" not in recipient:
        issues.append("Recipient is invalid.")
    for item in items:
        if item.severity_level in {"elevated", "high"} and not item.body:
            issues.append(f"Missing explanation body for elevated/high item: {item.title}")
        body = _normalize(item.body or "")
        if _contains_banned(body):
            issues.append(f"Forbidden language in item: {item.title}")
    return (len(issues) == 0, issues)


def send_email(recipient: str, subject: str, html_body: str) -> str:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username and settings.smtp_password:
            server.login(settings.smtp_username, settings.smtp_password)
        server.sendmail(settings.smtp_from, [recipient], msg.as_string())
    return f"smtp-{datetime.now(timezone.utc).timestamp()}"


def _fail(db: Session, delivery: Deliveries, message: str) -> Deliveries:
    delivery.delivery_status = "failed"
    delivery.error_message = message
    delivery.attempt_count = delivery.attempt_count + 1
    delivery.last_attempt_at = utcnow()
    db.commit()
    db.refresh(delivery)
    return delivery


def _attempt_delivery(db: Session, delivery: Deliveries) -> Deliveries:
    """Run every quality gate and, if all pass, send. Used by first send and retries."""
    run = db.query(BriefingRuns).filter(BriefingRuns.id == delivery.briefing_run_id).one()
    items = (
        db.query(BriefingItems)
        .filter(BriefingItems.briefing_run_id == delivery.briefing_run_id)
        .order_by(BriefingItems.display_order)
        .all()
    )
    ok, issues = quality_gates(items, delivery.recipient)
    if not ok:
        return _fail(db, delivery, "; ".join(issues))
    duplicate_recent = (
        db.query(Deliveries)
        .filter(
            Deliveries.briefing_run_id == delivery.briefing_run_id,
            Deliveries.recipient == delivery.recipient,
            Deliveries.delivery_status == "sent",
            Deliveries.id != delivery.id,
        )
        .first()
    )
    if duplicate_recent:
        return _fail(db, delivery, DUPLICATE_SUPPRESSED)

    high_items = [i for i in items if i.severity_level in {"elevated", "high"}]
    for hi in high_items:
        has_ref = db.query(BriefingEvidenceRefs).filter(BriefingEvidenceRefs.briefing_item_id == hi.id).count() > 0
        if not has_ref:
            return _fail(db, delivery, f"Missing evidence for high severity item: {hi.title}")

    try:
        html = render_email(run, items)
        # Compliance gate: never send a client-facing brief without the disclaimer.
        if not disclaimer_present(html):
            return _fail(db, delivery, "Required disclaimer missing from rendered brief.")
        # Render PDF to enforce render-success quality gate.
        _ = render_pdf_bytes(run, items)
        message_id = send_email(delivery.recipient, f"Aetherius Brief - {run.run_type}", html)
    except Exception as exc:  # noqa: BLE001 - any render/SMTP failure is recorded on the delivery row
        return _fail(db, delivery, str(exc))
    delivery.delivery_status = "sent"
    delivery.provider_message_id = message_id
    delivery.error_message = None
    delivery.attempt_count = delivery.attempt_count + 1
    delivery.last_attempt_at = utcnow()
    run.status = "sent"
    run.sent_at = utcnow()
    db.commit()
    db.refresh(delivery)
    return delivery


def deliver_briefing(db: Session, briefing_run_id: str, recipient: str, channel: str = "email") -> Deliveries:
    db.query(BriefingRuns).filter(BriefingRuns.id == briefing_run_id).one()
    delivery = Deliveries(
        briefing_run_id=briefing_run_id,
        channel=channel,
        recipient=recipient,
        delivery_status="queued",
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    return _attempt_delivery(db, delivery)


def retry_backoff(attempt_count: int) -> timedelta:
    """Exponential backoff before the next retry: 5, 10, 20, ... minutes."""
    return RETRY_BASE_DELAY * (2 ** max(attempt_count - 1, 0))


def retry_failed_delivery(
    db: Session, delivery_id: str, max_attempts: int = 3, respect_backoff: bool = False
) -> Deliveries:
    """Re-attempt a failed delivery, re-running every quality gate.

    No-ops when the delivery is not failed, has exhausted ``max_attempts``, was
    suppressed as a duplicate, or (with ``respect_backoff``) is still inside its
    backoff window.
    """
    delivery = db.query(Deliveries).filter(Deliveries.id == delivery_id).one()
    if delivery.delivery_status != "failed" or delivery.attempt_count >= max_attempts:
        return delivery
    if delivery.error_message == DUPLICATE_SUPPRESSED:
        return delivery
    if respect_backoff and delivery.last_attempt_at is not None:
        if utcnow() < delivery.last_attempt_at + retry_backoff(delivery.attempt_count):
            return delivery
    return _attempt_delivery(db, delivery)


def retry_failed_deliveries(db: Session, max_attempts: int = 3) -> list[Deliveries]:
    """Sweep all retryable failed deliveries whose backoff has elapsed."""
    candidates = (
        db.query(Deliveries)
        .filter(Deliveries.delivery_status == "failed", Deliveries.attempt_count < max_attempts)
        .all()
    )
    return [
        retry_failed_delivery(db, str(d.id), max_attempts=max_attempts, respect_backoff=True) for d in candidates
    ]
