-- Migration: create_session_costs
-- Run this in your Supabase SQL editor (https://supabase.com/dashboard/project/jppgtjiochtlxauwvbnu/sql)
-- to enable cost tracking sync to Supabase.

CREATE TABLE IF NOT EXISTS session_costs (
  session_id TEXT PRIMARY KEY,
  messages INT,
  input_tokens INT,
  output_tokens INT,
  cache_read INT,
  cache_write INT,
  total_tokens INT,
  cost_usd FLOAT,
  categories JSONB,
  model TEXT,
  first_timestamp TEXT,
  last_timestamp TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
