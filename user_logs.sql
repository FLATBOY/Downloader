CREATE TABLE user_logs (
    id SERIAL PRIMARY KEY,
    ip TEXT,
    country TEXT,
    city TEXT,
    format TEXT,
    filename TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    duration_seconds INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);