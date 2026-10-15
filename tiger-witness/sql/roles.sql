-- Least-privilege runtime role. Run ONCE as the admin (tsdbadmin) after migrations:
--   psql "$ADMIN_URL" -v app_password="'...'" -f sql/roles.sql
-- The app connects as witness_app; migrations run as the admin/owner in CI/CD only.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'witness_app') THEN CREATE ROLE witness_app LOGIN; END IF;
END $$;
ALTER ROLE witness_app PASSWORD :app_password;
GRANT USAGE ON SCHEMA witness TO witness_app;
GRANT SELECT ON ALL TABLES IN SCHEMA witness TO witness_app;
GRANT INSERT ON witness.life_events, witness.inbound, witness.actions, witness.receipts, witness.approvals,
                witness.memories, witness.sessions TO witness_app;
GRANT INSERT, UPDATE ON witness.mandates, witness.accounts, witness.users TO witness_app;
GRANT DELETE ON witness.sessions TO witness_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA witness TO witness_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA witness TO witness_app;
-- receipts: no UPDATE/DELETE grant at all (and a trigger blocks it even for owners).
REVOKE UPDATE, DELETE, TRUNCATE ON witness.receipts FROM witness_app;
-- v2 (07/08): RLS tables need the app to set witness.user_id per transaction; agent_events only via views.
GRANT SELECT, INSERT, UPDATE, DELETE ON witness.agent_tasks, witness.memory_items, witness.grants, witness.pending_approvals,
      witness.pay_mandates, witness.api_tokens, witness.channel_links, witness.link_codes, witness.mcp_servers,
      witness.connectors TO witness_app;
GRANT SELECT, INSERT ON witness.payments, witness.memory_forget_log TO witness_app;
REVOKE SELECT ON witness.agent_events, witness.habits_daily FROM witness_app;
GRANT INSERT ON witness.agent_events TO witness_app;
GRANT SELECT ON witness.my_agent_events, witness.my_habits TO witness_app;
