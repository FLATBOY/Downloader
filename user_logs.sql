CREATE TABLE IF NOT EXISTS user_logs (
  id SERIAL PRIMARY KEY,
  ip VARCHAR(45),
  format VARCHAR(10),
  filename TEXT,
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);