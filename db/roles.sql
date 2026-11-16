-- Read-only role for the agent's SQL tool. Cannot see audit_log or feedback.
CREATE ROLE agent_ro LOGIN PASSWORD 'agent_ro';
GRANT CONNECT ON DATABASE asset_copilot TO agent_ro;
GRANT USAGE ON SCHEMA public TO agent_ro;
GRANT SELECT ON properties, tenants, leases, operating_statements, budgets, debt,
                documents, document_chunks TO agent_ro;
ALTER ROLE agent_ro SET statement_timeout = '5s';
ALTER ROLE agent_ro SET default_transaction_read_only = on;
