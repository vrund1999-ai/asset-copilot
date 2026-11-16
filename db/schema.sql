CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE properties (
    property_id   SERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    asset_type    TEXT NOT NULL CHECK (asset_type IN ('logistics','multifamily','office','hospitality')),
    city          TEXT NOT NULL,
    state         CHAR(2) NOT NULL,
    sq_ft         INTEGER NOT NULL,
    year_built    INTEGER,
    acquired_on   DATE NOT NULL,
    purchase_price NUMERIC(14,2) NOT NULL
);

CREATE TABLE tenants (
    tenant_id SERIAL PRIMARY KEY,
    name      TEXT NOT NULL,
    industry  TEXT
);

CREATE TABLE leases (
    lease_id        SERIAL PRIMARY KEY,
    property_id     INTEGER NOT NULL REFERENCES properties,
    tenant_id       INTEGER NOT NULL REFERENCES tenants,
    suite           TEXT,
    leased_sq_ft    INTEGER NOT NULL,
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    base_rent_psf   NUMERIC(8,2) NOT NULL,
    annual_escalation NUMERIC(5,4) NOT NULL DEFAULT 0.03,
    renewal_options INTEGER NOT NULL DEFAULT 0,
    document_id     INTEGER
);

CREATE TABLE operating_statements (
    property_id INTEGER NOT NULL REFERENCES properties,
    month       DATE NOT NULL,
    revenue     NUMERIC(14,2) NOT NULL,
    opex        NUMERIC(14,2) NOT NULL,
    noi         NUMERIC(14,2) GENERATED ALWAYS AS (revenue - opex) STORED,
    PRIMARY KEY (property_id, month)
);

CREATE TABLE budgets (
    property_id INTEGER NOT NULL REFERENCES properties,
    month       DATE NOT NULL,
    revenue     NUMERIC(14,2) NOT NULL,
    opex        NUMERIC(14,2) NOT NULL,
    PRIMARY KEY (property_id, month)
);

CREATE TABLE debt (
    property_id   INTEGER PRIMARY KEY REFERENCES properties,
    lender        TEXT NOT NULL,
    principal     NUMERIC(14,2) NOT NULL,
    rate          NUMERIC(6,4) NOT NULL,
    maturity_date DATE NOT NULL
);

-- Unstructured layer: source documents and their retrievable chunks
CREATE TABLE documents (
    document_id SERIAL PRIMARY KEY,
    property_id INTEGER REFERENCES properties,
    doc_type    TEXT NOT NULL,
    title       TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'synthetic'
);

CREATE TABLE document_chunks (
    chunk_id    SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents,
    page        INTEGER,
    content     TEXT NOT NULL,
    embedding   vector(1024)
);

-- Governance: every agent action is logged
CREATE TABLE audit_log (
    id         BIGSERIAL PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
    session_id TEXT,
    action     TEXT NOT NULL,
    detail     JSONB NOT NULL
);

-- User feedback loop
CREATE TABLE feedback (
    id         BIGSERIAL PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
    session_id TEXT,
    question   TEXT NOT NULL,
    answer     TEXT NOT NULL,
    rating     SMALLINT NOT NULL CHECK (rating IN (-1, 1)),
    correction TEXT
);
