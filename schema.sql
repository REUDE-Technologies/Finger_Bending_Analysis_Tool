-- Finger Analysis Tool — Supabase Schema
-- Run in Supabase SQL Editor to create tables

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

-- Row Level Security: allow anon key (used by Railway app) to read/write
ALTER TABLE finger_types ENABLE ROW LEVEL SECURITY;
ALTER TABLE materials ENABLE ROW LEVEL SECURITY;
ALTER TABLE saved_configs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow anon all on finger_types" ON finger_types FOR ALL TO anon USING (true) WITH CHECK (true);
CREATE POLICY "Allow anon all on materials" ON materials FOR ALL TO anon USING (true) WITH CHECK (true);
CREATE POLICY "Allow anon all on saved_configs" ON saved_configs FOR ALL TO anon USING (true) WITH CHECK (true);

-- Seed some defaults
INSERT INTO finger_types (name) VALUES ('Finger 1'), ('Finger 2') ON CONFLICT DO NOTHING;
INSERT INTO materials (name, type) VALUES ('Silicone', 'body'), ('Silicone', 'skin') ON CONFLICT DO NOTHING;
