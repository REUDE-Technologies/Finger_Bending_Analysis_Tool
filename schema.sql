-- Finger Analysis Tool — Supabase Schema
-- Run in Supabase SQL Editor to create tables and RLS policies.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- What is RLS (Row Level Security)?
-- ═══════════════════════════════════════════════════════════════════════════
-- RLS is a PostgreSQL feature that restricts which rows a user (or role) can
-- SELECT, INSERT, UPDATE, or DELETE. When RLS is enabled on a table:
--
--   • Without any policy: no rows are visible and no writes are allowed for
--     that role (e.g. anon).
--   • Policies define: which rows the role can see (USING) and which rows
--     they can insert/update (WITH CHECK).
--
-- Supabase exposes your API using the "anon" (public) key. By default, RLS
-- is enabled on public tables, so you must add policies that allow the anon
-- role to read/write the data your app needs. This schema adds one policy
-- per table so that the anon key (used by the Railway app) can do everything
-- needed for config saving.
-- ═══════════════════════════════════════════════════════════════════════════

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS finger_types (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS materials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'body' CHECK (type IN ('body', 'skin')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (name, type)
);

CREATE TABLE IF NOT EXISTS saved_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finger_type TEXT,
    finger_length REAL,
    finger_width REAL,
    body_material TEXT,
    skin_material TEXT,
    speed REAL DEFAULT 0,
    prepared_by TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Row Level Security (RLS)
-- ---------------------------------------------------------------------------
ALTER TABLE finger_types ENABLE ROW LEVEL SECURITY;
ALTER TABLE materials ENABLE ROW LEVEL SECURITY;
ALTER TABLE saved_configs ENABLE ROW LEVEL SECURITY;

-- Drop existing policies so this script can be re-run safely
DROP POLICY IF EXISTS "Allow anon all on finger_types" ON finger_types;
DROP POLICY IF EXISTS "Allow anon all on materials" ON materials;
DROP POLICY IF EXISTS "Allow anon all on saved_configs" ON saved_configs;

-- One policy per table: allow the anon role (Supabase public API key) full
-- read/write. USING (true) = can see all rows; WITH CHECK (true) = can
-- insert/update any row.
CREATE POLICY "Allow anon all on finger_types"
    ON finger_types FOR ALL TO anon
    USING (true) WITH CHECK (true);

CREATE POLICY "Allow anon all on materials"
    ON materials FOR ALL TO anon
    USING (true) WITH CHECK (true);

CREATE POLICY "Allow anon all on saved_configs"
    ON saved_configs FOR ALL TO anon
    USING (true) WITH CHECK (true);

-- ---------------------------------------------------------------------------
-- Seed defaults (idempotent)
-- ---------------------------------------------------------------------------
INSERT INTO finger_types (name) VALUES ('Finger 1'), ('Finger 2') ON CONFLICT (name) DO NOTHING;
INSERT INTO materials (name, type) VALUES ('Silicone', 'body'), ('Silicone', 'skin') ON CONFLICT (name, type) DO NOTHING;
