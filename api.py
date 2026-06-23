"""
LocalPulse — FastAPI Backend
------------------------------
Handles subscriber sign-ups, digest retrieval, and email delivery.

Run with:
    uvicorn api:app --reload

Endpoints:
    POST /subscribe          — Add a new subscriber
    DELETE /unsubscribe      — Remove a subscriber by email
    GET  /digest/{zip_code}  — Get this week's digest for a ZIP
    POST /send/{zip_code}    — Trigger digest email send for a ZIP (admin)
    GET  /health             — Health check
"""

import os
import resend
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from loguru import logger

# ── Load environment variables ────────────────────────────
load_dotenv()

DATABASE_URL   = os.getenv("DATABASE_URL")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
ADMIN_SECRET   = os.getenv("ADMIN_SECRET", "localpulse-admin")
FROM_EMAIL     = os.getenv("FROM_EMAIL", "digest@localpulse.app")

resend.api_key = RESEND_API_KEY
engine = create_engine(DATABASE_URL) if DATABASE_URL else None

# ── App setup ─────────────────────────────────────────────
app = FastAPI(
    title="LocalPulse API",
    description="Backend for LocalPulse — AI neighborhood digest by ZIP code",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Restrict to your domain in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response Models ─────────────────────────────
class SubscribeRequest(BaseModel):
    email: EmailStr
    zip_code: str

class UnsubscribeRequest(BaseModel):
    email: EmailStr


# ── Helpers ───────────────────────────────────────────────
def get_db():
    if not engine:
        raise HTTPException(status_code=503, detail="Database not configured.")
    return engine.connect()

def require_admin(x_admin_secret: str = Header(None)):
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Unauthorized.")


# ── Routes ────────────────────────────────────────────────

@app.get("/health")
def health_check():
    """Simple health check — use this to verify the API is running."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/subscribe")
def subscribe(body: SubscribeRequest):
    """
    Add a new subscriber for a given ZIP code.
    Called by the subscription form on the frontend.
    """
    zip_code = body.zip_code.strip()
    email    = body.email.strip().lower()

    # Basic ZIP validation
    if not zip_code.isdigit() or len(zip_code) != 5:
        raise HTTPException(status_code=400, detail="Invalid ZIP code. Must be 5 digits.")

    with get_db() as conn:
        # Check for duplicate
        existing = conn.execute(text(
            "SELECT id FROM subscribers WHERE email = :email AND zip_code = :zip"
        ), {"email": email, "zip": zip_code}).fetchone()

        if existing:
            raise HTTPException(status_code=409, detail="You're already subscribed for this ZIP code.")

        conn.execute(text("""
            INSERT INTO subscribers (email, zip_code, subscribed_at, is_active)
            VALUES (:email, :zip, NOW(), TRUE)
        """), {"email": email, "zip": zip_code})
        conn.commit()

    logger.success(f"New subscriber: {email} → ZIP {zip_code}")

    # Send a welcome email
    try:
        resend.Emails.send({
            "from":    FROM_EMAIL,
            "to":      email,
            "subject": f"Welcome to LocalPulse — ZIP {zip_code}",
            "html":    build_welcome_email(zip_code),
        })
    except Exception as e:
        logger.warning(f"Welcome email failed for {email}: {e}")

    return {"message": f"Subscribed! Your first digest for ZIP {zip_code} arrives this Monday."}


@app.delete("/unsubscribe")
def unsubscribe(body: UnsubscribeRequest):
    """Remove a subscriber by email (unsubscribes from all ZIP codes)."""
    email = body.email.strip().lower()
    with get_db() as conn:
        conn.execute(text(
            "UPDATE subscribers SET is_active = FALSE WHERE email = :email"
        ), {"email": email})
        conn.commit()
    logger.info(f"Unsubscribed: {email}")
    return {"message": "You've been unsubscribed from all LocalPulse digests."}


@app.get("/digest/{zip_code}")
def get_digest(zip_code: str):
    """
    Return this week's digest items for a given ZIP code.
    Used by the frontend to render live digest previews.
    """
    one_week_ago = datetime.utcnow() - timedelta(days=7)
    with get_db() as conn:
        rows = conn.execute(text("""
            SELECT title, category, summary, source_url, source_date
            FROM digest_items
            WHERE zip_code = :zip
              AND created_at >= :since
            ORDER BY source_date DESC
        """), {"zip": zip_code, "since": one_week_ago}).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No digest found for ZIP {zip_code} this week.")

    return {
        "zip_code": zip_code,
        "week_of":  one_week_ago.strftime("%B %d, %Y"),
        "items":    [dict(r._mapping) for r in rows],
    }


@app.post("/send/{zip_code}")
def send_digest(zip_code: str, x_admin_secret: str = Header(None)):
    """
    Admin endpoint — trigger the weekly digest email send for a ZIP code.
    Protected by ADMIN_SECRET header.
    Typically called by a GitHub Actions cron job every Monday.
    """
    require_admin(x_admin_secret)

    # Fetch this week's digest
    one_week_ago = datetime.utcnow() - timedelta(days=7)
    with get_db() as conn:
        items = conn.execute(text("""
            SELECT title, category, summary, source_url
            FROM digest_items
            WHERE zip_code = :zip AND created_at >= :since
            ORDER BY source_date DESC
        """), {"zip": zip_code, "since": one_week_ago}).fetchall()

        subscribers = conn.execute(text("""
            SELECT email FROM subscribers
            WHERE zip_code = :zip AND is_active = TRUE
        """), {"zip": zip_code}).fetchall()

    if not items:
        raise HTTPException(status_code=404, detail="No digest items found for this ZIP this week.")

    if not subscribers:
        return {"message": "No active subscribers for this ZIP code."}

    # Build email HTML
    email_html = build_digest_email(zip_code, [dict(r._mapping) for r in items])

    # Send to all subscribers
    sent = 0
    for sub in subscribers:
        try:
            resend.Emails.send({
                "from":    FROM_EMAIL,
                "to":      sub.email,
                "subject": f"LocalPulse Weekly · ZIP {zip_code} · {datetime.now().strftime('%b %d')}",
                "html":    email_html,
            })
            sent += 1
        except Exception as e:
            logger.error(f"Failed to send to {sub.email}: {e}")

    logger.success(f"Sent digest for ZIP {zip_code} to {sent}/{len(subscribers)} subscribers.")
    return {"message": f"Digest sent to {sent} subscribers.", "zip_code": zip_code}


# ── Email Templates ───────────────────────────────────────

def build_welcome_email(zip_code: str) -> str:
    return f"""
    <div style="font-family:sans-serif;max-width:560px;margin:0 auto;color:#0E0F0D;">
      <div style="background:#1A5C3A;padding:24px 28px;border-radius:8px 8px 0 0;">
        <h1 style="color:white;font-size:22px;margin:0;">Welcome to LocalPulse 🟢</h1>
        <p style="color:rgba(255,255,255,0.7);margin:6px 0 0;font-size:14px;">ZIP {zip_code}</p>
      </div>
      <div style="background:white;padding:28px;border:1px solid #e5e5e5;border-top:none;border-radius:0 0 8px 8px;">
        <p style="font-size:16px;">You're subscribed. Your first digest arrives this <strong>Monday morning</strong>.</p>
        <p style="color:#555;font-size:14px;line-height:1.6;">
          Every week, LocalPulse scans public government records for your neighborhood —
          zoning changes, building permits, council votes, and crime reports —
          and sends you a plain-English summary that takes 3 minutes to read.
        </p>
        <p style="color:#555;font-size:14px;">See you Monday.</p>
        <p style="color:#555;font-size:14px;margin-top:32px;">— The LocalPulse team</p>
        <hr style="border:none;border-top:1px solid #eee;margin:24px 0;" />
        <p style="font-size:12px;color:#aaa;">
          You subscribed with this email for ZIP {zip_code}.
          <a href="https://localpulse.app/unsubscribe" style="color:#1A5C3A;">Unsubscribe</a>
        </p>
      </div>
    </div>
    """


def build_digest_email(zip_code: str, items: list[dict]) -> str:
    category_icons = {
        "Zoning":      "🏗",
        "Permits":     "📋",
        "City Council":"🏛",
        "Safety":      "🚔",
    }

    items_html = ""
    for item in items:
        icon = category_icons.get(item["category"], "📌")
        items_html += f"""
        <div style="border-left:3px solid #1A5C3A;padding:8px 0 8px 16px;margin-bottom:16px;">
          <p style="font-size:11px;color:#888;text-transform:uppercase;
                    letter-spacing:0.06em;margin:0 0 4px;">{icon} {item['category']}</p>
          <p style="font-size:15px;font-weight:600;color:#0E0F0D;margin:0 0 6px;">{item['title']}</p>
          <p style="font-size:14px;color:#3A3B38;line-height:1.6;margin:0 0 8px;">{item['summary']}</p>
          <a href="{item['source_url']}" style="font-size:12px;color:#1A5C3A;">
            View original document →
          </a>
        </div>
        """

    week_str = datetime.now().strftime("%B %d, %Y")

    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;color:#0E0F0D;">
      <div style="background:#0E0F0D;padding:24px 28px;border-radius:8px 8px 0 0;
                  display:flex;justify-content:space-between;align-items:center;">
        <div>
          <h1 style="color:white;font-size:20px;margin:0;">LocalPulse Weekly</h1>
          <p style="color:rgba(255,255,255,0.5);margin:4px 0 0;font-size:13px;">
            ZIP {zip_code} · {week_str}
          </p>
        </div>
      </div>
      <div style="background:white;padding:28px;border:1px solid #e5e5e5;
                  border-top:none;border-radius:0 0 8px 8px;">
        <p style="font-size:14px;color:#555;margin:0 0 24px;">
          Here's what happened in your neighborhood this week.
          All items link to the original public document.
        </p>
        {items_html}
        <hr style="border:none;border-top:1px solid #eee;margin:24px 0;" />
        <p style="font-size:12px;color:#aaa;">
          You're receiving this because you subscribed to LocalPulse for ZIP {zip_code}.
          <a href="https://localpulse.app/unsubscribe" style="color:#1A5C3A;">Unsubscribe</a>
        </p>
      </div>
    </div>
    """
