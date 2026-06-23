# LocalPulse 🟢

> **AI that reads city hall so you don't have to.**

LocalPulse scrapes public government records — zoning filings, council minutes, permits, crime reports — and delivers a plain-English neighborhood digest to your inbox every Monday, sorted by ZIP code. Democracy works better when people actually know what's happening on their street.

![LocalPulse Screenshot](screenshot.png)

🌐 **Live site:** [neodragon-tuff.github.io/Local-Pulse-](https://neodragon-tuff.github.io/Local-Pulse-/)

---

## The Problem

City hall decisions that reshape your street are already public record. Rezoning approvals, building permits, council votes, crime clusters — all of it is posted online. But it's buried in PDFs, spread across a dozen different government portals, and written in language nobody reads voluntarily.

By the time most residents find out about a zoning change or a new development, the public comment period is already closed.

**LocalPulse fixes that.**

---

## What It Does

- 🔍 Scrapes official government portals weekly by ZIP code
- 📄 Parses PDFs and extracts what actually matters to residents
- 🤖 Uses the Claude API to summarize bureaucratic language into 3-minute digests
- 📬 Delivers personalized neighborhood newsletters via email every Monday
- 🔔 Lets residents set keyword alerts for instant notifications (coming soon)
- 📁 Archives all past digests in a personal dashboard (coming soon)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | HTML, CSS, JavaScript |
| Backend | Python, FastAPI |
| AI Summarization | Claude API (Anthropic) |
| Scraping | Python, BeautifulSoup, pdfplumber |
| Database | PostgreSQL (Supabase) |
| Email Delivery | Resend |
| Hosting | GitHub Pages (frontend), Render (backend) |
| Scheduler | GitHub Actions (weekly cron) |

---

## Project Structure

```
Local-Pulse/
├── index.html          # Frontend — subscription landing page
├── scraper.py          # Government portal scrapers by ZIP code
├── api.py              # FastAPI backend — subscriptions & digest delivery
├── schema.sql          # PostgreSQL database schema
├── requirements.txt    # Python dependencies
├── .gitignore          # Keeps secrets and junk out of the repo
└── README.md           # You are here
```

---

## Getting Started

### 1. Clone the repo
```bash
git clone https://github.com/neodragon-tuff/Local-Pulse-.git
cd Local-Pulse-
```

### 2. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 3. Set up environment variables
Create a `.env` file in the root directory:
```
ANTHROPIC_API_KEY=your_claude_api_key
RESEND_API_KEY=your_resend_api_key
DATABASE_URL=your_postgresql_connection_string
```

### 4. Set up the database
```bash
psql $DATABASE_URL -f schema.sql
```

### 5. Run the scraper manually
```bash
python scraper.py --zip 78701
```

### 6. Start the backend API
```bash
uvicorn api:app --reload
```

### 7. Open the frontend
Open `index.html` in your browser or visit the live GitHub Pages URL.

---

## How the Scraper Works

1. Given a ZIP code, the scraper identifies the correct city and county government portals
2. It downloads recent documents (PDFs, HTML pages) from each portal
3. Text is extracted using `pdfplumber` (PDFs) or `BeautifulSoup` (HTML)
4. Raw text is sent to the Claude API with a summarization prompt
5. Summaries are stored in the database, tagged by ZIP code and category
6. Every Monday, the digest emailer pulls that week's summaries and sends them to all subscribers in that ZIP

---

## Roadmap

- [x] Frontend landing page with subscription form
- [x] Sample digest UI
- [ ] Python scraper for government portals (in progress)
- [ ] FastAPI backend for subscriptions
- [ ] PostgreSQL subscriber database
- [ ] Weekly email delivery via Resend
- [ ] ZIP-to-city mapping
- [ ] Keyword alert system
- [ ] Subscriber dashboard and digest archive
- [ ] Coverage expansion beyond initial ZIP code

---

## Built By

**LocalPulse** is an open-source student project. Built because civic information should be free, readable, and actually reach the people it affects.

---

## License

MIT License — free to use, fork, and build on.
