-- LocalPulse — PostgreSQL Database Schema
-- Run with: psql $DATABASE_URL -f schema.sql
-- ──────────────────────────────────────────────────────────

-- ── Subscribers ───────────────────────────────────────────
-- Stores everyone who has signed up for a LocalPulse digest.

CREATE TABLE IF NOT EXISTS subscribers (
    id              SERIAL PRIMARY KEY,
    email           TEXT NOT NULL,
    zip_code        CHAR(5) NOT NULL,
    subscribed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,

    -- A subscriber can only sign up once per ZIP code
    CONSTRAINT unique_email_zip UNIQUE (email, zip_code)
);

CREATE INDEX IF NOT EXISTS idx_subscribers_zip
    ON subscribers (zip_code)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_subscribers_email
    ON subscribers (email);


-- ── Digest Items ──────────────────────────────────────────
-- Stores each summarized record from government portals.
-- One row per document per ZIP code per week.

CREATE TABLE IF NOT EXISTS digest_items (
    id              SERIAL PRIMARY KEY,
    zip_code        CHAR(5) NOT NULL,
    title           TEXT NOT NULL,
    category        TEXT NOT NULL,          -- 'Zoning', 'Permits', 'City Council', 'Safety'
    summary         TEXT NOT NULL,          -- AI-generated plain-English summary
    source_url      TEXT NOT NULL,          -- Link back to the original document
    source_date     DATE,                   -- Date the original document was published
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Prevent duplicate entries for the same source document
    CONSTRAINT unique_source_per_zip UNIQUE (zip_code, source_url)
);

CREATE INDEX IF NOT EXISTS idx_digest_items_zip_created
    ON digest_items (zip_code, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_digest_items_category
    ON digest_items (category);


-- ── Keyword Alerts ────────────────────────────────────────
-- Stores keywords a subscriber wants to be alerted about immediately
-- (e.g. their street name, a business they care about).

CREATE TABLE IF NOT EXISTS keyword_alerts (
    id              SERIAL PRIMARY KEY,
    subscriber_id   INTEGER NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
    keyword         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT unique_keyword_per_subscriber UNIQUE (subscriber_id, keyword)
);

CREATE INDEX IF NOT EXISTS idx_keyword_alerts_subscriber
    ON keyword_alerts (subscriber_id);


-- ── Digest Send Log ───────────────────────────────────────
-- Tracks every digest email that was sent, for debugging
-- and to avoid sending duplicates.

CREATE TABLE IF NOT EXISTS send_log (
    id              SERIAL PRIMARY KEY,
    subscriber_id   INTEGER NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
    zip_code        CHAR(5) NOT NULL,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    week_of         DATE NOT NULL,          -- The Monday this digest covers
    status          TEXT NOT NULL           -- 'sent', 'failed', 'skipped'
);

CREATE INDEX IF NOT EXISTS idx_send_log_subscriber
    ON send_log (subscriber_id, week_of);


-- ── Scraped Sources ───────────────────────────────────────
-- Tracks which government portal URLs have been scraped and when,
-- so the scraper avoids re-scraping documents it already processed.

CREATE TABLE IF NOT EXISTS scraped_sources (
    id              SERIAL PRIMARY KEY,
    url             TEXT NOT NULL UNIQUE,
    zip_code        CHAR(5),
    scraped_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    success         BOOLEAN NOT NULL DEFAULT TRUE,
    error_message   TEXT                            -- Populated if success = FALSE
);

CREATE INDEX IF NOT EXISTS idx_scraped_sources_url
    ON scraped_sources (url);

CREATE INDEX IF NOT EXISTS idx_scraped_sources_zip
    ON scraped_sources (zip_code, scraped_at DESC);
