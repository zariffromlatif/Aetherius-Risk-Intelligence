from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_operator
from app.models.entities import (
    BriefingRuns,
    Clients,
    Deliveries,
    RiskSignals,
    SourceObservations,
    WatchlistItems,
    Watchlists,
)

template_dir = Path(__file__).resolve().parents[2] / "templates" / "console"
templates = Jinja2Templates(directory=str(template_dir))

router = APIRouter(prefix="/console", tags=["console"], dependencies=[Depends(require_operator)])


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    ctx = {
        "request": request,
        "pending_review": db.query(BriefingRuns).filter(BriefingRuns.status == "pending_review").count(),
        "failed_deliveries": db.query(Deliveries).filter(Deliveries.delivery_status == "failed").count(),
        "open_signals": db.query(RiskSignals).filter(RiskSignals.status == "open").count(),
        "recent_observations": db.query(SourceObservations).order_by(SourceObservations.ingested_at.desc()).limit(10).all(),
    }
    return templates.TemplateResponse("dashboard.html", ctx)


@router.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request, db: Session = Depends(get_db)):
    rows = db.query(Clients).order_by(Clients.created_at.desc()).all()
    return templates.TemplateResponse("clients.html", {"request": request, "clients": rows})


@router.get("/clients/{client_id}", response_class=HTMLResponse)
def client_detail(request: Request, client_id: str, db: Session = Depends(get_db)):
    client = db.query(Clients).filter(Clients.id == client_id).one()
    watchlists = db.query(Watchlists).filter(Watchlists.client_id == client_id).all()
    return templates.TemplateResponse("client_detail.html", {"request": request, "client": client, "watchlists": watchlists})


@router.get("/watchlists/{watchlist_id}", response_class=HTMLResponse)
def watchlist_detail(request: Request, watchlist_id: str, db: Session = Depends(get_db)):
    items = db.query(WatchlistItems).filter(WatchlistItems.watchlist_id == watchlist_id).all()
    return templates.TemplateResponse("watchlist_detail.html", {"request": request, "items": items})


@router.get("/evidence", response_class=HTMLResponse)
def evidence_inbox(request: Request, db: Session = Depends(get_db)):
    observations = db.query(SourceObservations).order_by(SourceObservations.ingested_at.desc()).limit(50).all()
    return templates.TemplateResponse("evidence_inbox.html", {"request": request, "observations": observations})


@router.get("/signals/review", response_class=HTMLResponse)
def signal_review_page(request: Request, db: Session = Depends(get_db)):
    runs = (
        db.query(BriefingRuns)
        .filter(BriefingRuns.status.in_(["pending_review", "draft"]))
        .order_by(BriefingRuns.created_at.desc())
        .limit(100)
        .all()
    )
    return templates.TemplateResponse("signal_review.html", {"request": request, "runs": runs})
