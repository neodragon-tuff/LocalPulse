"""
LocalPulse — Government Portal Scraper
---------------------------------------
Scrapes public government records by ZIP code and summarizes
them using the Claude API. Stores results in PostgreSQL.

Usage:
    python scraper.py --zip 78701
    python scraper.py --zip 94103 --dry-run
"""

import os
import argparse
import requests
import pdfplumber
import pgeocode
from io import BytesIO
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from anthropic import Anthropic
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

# ── Load environment variables ────────────────────────────
load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DATABASE_URL      = os.getenv("DATABASE_URL")

client = Anthropic(api_key=ANTHROPIC_API_KEY)
engine = create_engine(DATABASE_URL) if DATABASE_URL else None

# ── ZIP → City/State lookup ───────────────────────────────
nomi = pgeocode.Nominatim("us")

def zip_to_location(zip_code: str) -> dict:
    """Convert a ZIP code to city and state."""
    result = nomi.query_postal_code(zip_code)
    if result is None or str(result.get("place_name")) == "nan":
        raise ValueError(f"ZIP code {zip_code} not found.")
    return {
        "zip":   zip_code,
        "city":  result["place_name"],
        "state": result["state_name"],
        "state_code": result["state_code"],
        "lat":   result["latitude"],
        "lng":   result["longitude"],
    }


# ── Claude AI Summarizer ──────────────────────────────────
def summarize_document(raw_text: str, category: str, location: dict) -> str:
    """
    Send raw document text to Claude API and return a
    plain-English summary for residents.
    """
    prompt = f"""
You are summarizing a public government document for residents of {location['city']}, {location['state_code']}.

Document category: {category}
Your job: Extract only information that directly affects residents. Write 2-4 sentences in plain English.
- No jargon, no legalese
- State what is happening, where, and when if known
- Note if there is a public comment period or action residents can take
- Do not editorialize or add opinion

Document text:
{raw_text[:8000]}

Summary:
"""
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()


# ── PDF Extractor ─────────────────────────────────────────
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def extract_pdf_text(url: str) -> str:
    """Download a PDF from a URL and extract its text."""
    logger.info(f"Downloading PDF: {url}")
    response = requests.get(url, timeout=30, headers={"User-Agent": "LocalPulse/1.0"})
    response.raise_for_status()
    with pdfplumber.open(BytesIO(response.content)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    return text.strip()


# ── HTML Page Scraper ─────────────────────────────────────
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def scrape_html_page(url: str, content_selector: str = "main") -> str:
    """Scrape text content from an HTML government page."""
    logger.info(f"Scraping HTML: {url}")
    response = requests.get(url, timeout=30, headers={"User-Agent": "LocalPulse/1.0"})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    # Remove nav, footer, scripts, styles
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    main = soup.find(content_selector) or soup.find("body")
    return main.get_text(separator="\n", strip=True) if main else ""


# ── Per-City Scrapers ─────────────────────────────────────
# Each function returns a list of dicts:
# { "title", "category", "url", "raw_text", "date" }
# Add new cities by following the same pattern.

def scrape_austin_tx(zip_code: str) -> list[dict]:
    """Scrape Austin, TX government portals."""
    results = []
    logger.info("Scraping Austin, TX portals...")

    # Austin City Council meeting minutes (example endpoint)
    try:
        url = "https://www.austintexas.gov/department/city-council/meetings"
        text = scrape_html_page(url)
        if text:
            results.append({
                "title":    "Austin City Council — Recent Meeting",
                "category": "City Council",
                "url":      url,
                "raw_text": text,
                "date":     datetime.now().date(),
            })
    except Exception as e:
        logger.warning(f"Austin council scrape failed: {e}")

    # Austin building permits (example endpoint)
    try:
        url = "https://abc.austintexas.gov/web/permit/public-search-other"
        text = scrape_html_page(url)
        if text:
            results.append({
                "title":    "Austin Building Permits — This Week",
                "category": "Permits",
                "url":      url,
                "raw_text": text,
                "date":     datetime.now().date(),
            })
    except Exception as e:
        logger.warning(f"Austin permits scrape failed: {e}")

    return results


def scrape_san_francisco_ca(zip_code: str) -> list[dict]:
    """Scrape San Francisco, CA government portals."""
    results = []
    logger.info("Scraping San Francisco, CA portals...")

    # SF Planning Commission
    try:
        url = "https://sfplanning.org/commission-calendars"
        text = scrape_html_page(url)
        if text:
            results.append({
                "title":    "SF Planning Commission — Recent Calendar",
                "category": "Zoning",
                "url":      url,
                "raw_text": text,
                "date":     datetime.now().date(),
            })
    except Exception as e:
        logger.warning(f"SF planning scrape failed: {e}")

    return results


# ── City Router ───────────────────────────────────────────
CITY_SCRAPERS = {
    ("austin",         "tx"): scrape_austin_tx,
    ("san francisco",  "ca"): scrape_san_francisco_ca,
    # Add more cities here as you expand coverage
}

def get_scraper_for_location(location: dict):
    """Return the correct scraper function for a given city/state."""
    city  = location["city"].lower()
    state = location["state_code"].lower()
    for (c, s), fn in CITY_SCRAPERS.items():
        if c in city and s == state:
            return fn
    return None


# ── Database Storage ──────────────────────────────────────
def save_digest_item(zip_code: str, item: dict, summary: str):
    """Save a summarized digest item to the database."""
    if not engine:
        logger.warning("No DATABASE_URL set — skipping database save.")
        return
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO digest_items
                (zip_code, title, category, source_url, summary, source_date, created_at)
            VALUES
                (:zip_code, :title, :category, :source_url, :summary, :source_date, NOW())
            ON CONFLICT DO NOTHING
        """), {
            "zip_code":    zip_code,
            "title":       item["title"],
            "category":    item["category"],
            "source_url":  item["url"],
            "summary":     summary,
            "source_date": item["date"],
        })
        conn.commit()
    logger.success(f"Saved: {item['title']}")


# ── Main Runner ───────────────────────────────────────────
def run_scraper(zip_code: str, dry_run: bool = False):
    """
    Full pipeline for a given ZIP code:
    1. Look up city/state
    2. Find the right scraper
    3. Scrape documents
    4. Summarize each with Claude
    5. Save to database
    """
    logger.info(f"Starting LocalPulse scraper for ZIP {zip_code}")

    # Step 1: Resolve location
    try:
        location = zip_to_location(zip_code)
        logger.info(f"Location: {location['city']}, {location['state_code']}")
    except ValueError as e:
        logger.error(str(e))
        return

    # Step 2: Find scraper
    scraper_fn = get_scraper_for_location(location)
    if not scraper_fn:
        logger.warning(f"No scraper yet for {location['city']}, {location['state_code']}. "
                       f"Add one to CITY_SCRAPERS in scraper.py.")
        return

    # Step 3: Scrape
    raw_items = scraper_fn(zip_code)
    logger.info(f"Found {len(raw_items)} document(s) to summarize.")

    # Step 4 & 5: Summarize and save
    for item in raw_items:
        logger.info(f"Summarizing: {item['title']}")
        try:
            summary = summarize_document(item["raw_text"], item["category"], location)
            logger.info(f"Summary: {summary[:120]}...")
            if not dry_run:
                save_digest_item(zip_code, item, summary)
            else:
                logger.info("[DRY RUN] Would have saved to database.")
        except Exception as e:
            logger.error(f"Failed to summarize {item['title']}: {e}")

    logger.success(f"Scraper complete for ZIP {zip_code}.")


# ── CLI Entry Point ───────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LocalPulse government portal scraper")
    parser.add_argument("--zip",     required=True, help="ZIP code to scrape (e.g. 78701)")
    parser.add_argument("--dry-run", action="store_true", help="Run without saving to database")
    args = parser.parse_args()
    run_scraper(args.zip, dry_run=args.dry_run)
