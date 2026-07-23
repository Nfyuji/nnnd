-- PostgreSQL schema for Saudi Leads Scraper

CREATE TABLE IF NOT EXISTS companies (
    id BIGSERIAL PRIMARY KEY,
    company_name VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    industry VARCHAR(100),

    website VARCHAR(500),
    email VARCHAR(255),
    phone VARCHAR(50),
    whatsapp VARCHAR(50),

    city VARCHAR(100),
    country VARCHAR(100) DEFAULT 'Saudi Arabia',
    address VARCHAR(500),

    linkedin_url VARCHAR(500),
    instagram_url VARCHAR(500),
    tiktok_url VARCHAR(500),
    twitter_url VARCHAR(500),
    facebook_url VARCHAR(500),

    employees VARCHAR(50),
    source VARCHAR(100),
    maps_url VARCHAR(500),
    rating VARCHAR(20),
    reviews_count INTEGER,

    score INTEGER DEFAULT 0,
    enriched BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contacts (
    id BIGSERIAL PRIMARY KEY,
    company_id BIGINT REFERENCES companies(id) ON DELETE CASCADE,
    full_name VARCHAR(255),
    job_title VARCHAR(150),
    email VARCHAR(255),
    phone VARCHAR(50),
    linkedin_url VARCHAR(500),
    verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS leads (
    id BIGSERIAL PRIMARY KEY,
    company_id BIGINT REFERENCES companies(id) ON DELETE CASCADE,
    status VARCHAR(50) DEFAULT 'new',
    score INT DEFAULT 0,
    notes TEXT,
    last_contact DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scrape_jobs (
    id BIGSERIAL PRIMARY KEY,
    query VARCHAR(255) NOT NULL,
    city VARCHAR(100) NOT NULL,
    category VARCHAR(100),
    status VARCHAR(50) DEFAULT 'pending',
    results_count INTEGER DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scrape_state (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_companies_email ON companies(email);
CREATE INDEX IF NOT EXISTS idx_companies_phone ON companies(phone);
CREATE INDEX IF NOT EXISTS idx_companies_city ON companies(city);
CREATE INDEX IF NOT EXISTS idx_companies_score ON companies(score);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
