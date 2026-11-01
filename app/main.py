import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .database import Base, SessionLocal, add_missing_columns, engine
from .routers import admin, assistant, auth, businesses, feedback, method, payments, statements, uploads

Base.metadata.create_all(bind=engine)  # creates any missing tables in MySQL on startup
add_missing_columns()                  # and any new columns in existing tables


def _ensure_super_admin() -> None:
    from .invites import ensure_super_admin
    with SessionLocal() as db:
        ensure_super_admin(db)  # after an upgrade, the oldest admin becomes super admin
        db.commit()


_ensure_super_admin()

STATIC = Path(__file__).resolve().parent / "static"

@asynccontextmanager
async def lifespan(_app):
    from .notify import reminder_loop
    from .renewals import renew_loop
    task = asyncio.create_task(reminder_loop())  # monthly reminders, 2nd to 10th of each month
    renew = asyncio.create_task(renew_loop())    # Biashara Pro renewal notices and M-Pesa prompts
    yield
    task.cancel()
    renew.cancel()


app = FastAPI(
    lifespan=lifespan,
    title="SME Loss-Risk Early Warning System",
    description="Predicts the probability of a net operating loss in the next 90 days. "
    "Decision support only, not a guarantee of business outcomes.",
    version="0.3.0",
)

app.include_router(auth.router)
app.include_router(businesses.router)
app.include_router(uploads.router)
app.include_router(admin.router)
app.include_router(payments.router)
app.include_router(statements.router)
app.include_router(feedback.router)
app.include_router(method.router)
app.include_router(assistant.router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    """Served from the root so it can look after every page of the app."""
    return FileResponse(STATIC / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sectors", tags=["login"], summary="Types of business, for the sign-up and admin forms")
def sectors():
    from .sectors import SECTORS
    return [{"id": k, "label": v} for k, v in SECTORS.items()]


# Pages. Each page checks /auth/me itself and sends you to /login if needed.
_ASSET = re.compile(r'"/static/([\w./-]+\.(?:css|js))"')


def _page(name: str) -> HTMLResponse:
    """The page with ?v=<file date> on its styles and scripts, so a browser (or the installed app)
    never keeps using an old app.css or app.js after an update."""
    html = (STATIC / name).read_text(encoding="utf-8")

    def stamp(m: re.Match) -> str:
        f = STATIC / m.group(1)
        v = int(f.stat().st_mtime) if f.exists() else 0
        return f'"/static/{m.group(1)}?v={v}"'

    return HTMLResponse(_ASSET.sub(stamp, html), headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def home():
    return _page("index.html")


@app.get("/login", include_in_schema=False)
def login_page():
    return _page("login.html")


@app.get("/account", include_in_schema=False)
def account_page():
    return _page("account.html")


@app.get("/install", include_in_schema=False)
def install_page():
    """Get the app: install on a phone or computer (public, so it can be shared before logging in)."""
    return _page("install.html")


@app.get("/how", include_in_schema=False)
def how_page():
    return _page("how.html")


@app.get("/admin", include_in_schema=False)
def admin_page():
    return _page("admin.html")


@app.get("/health", tags=["system"])
def health():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
