-- Hard-purge every company except one.
--
-- A development/staging data-reset tool. It genuinely deletes financial
-- records, which the schema is built to prevent — see the trigger section
-- below — so it is deliberately a separate, named script rather than
-- anything reachable from the product.
--
-- Usage:
--     psql -v keep_company_id="'<uuid>'" -f scripts/purge_companies.sql
--
-- The whole thing runs in ONE transaction: either every company but the
-- kept one is gone with referential integrity intact, or nothing changed.
-- A half-purged database is far worse than an un-purged one, because the
-- orphans it leaves are exactly the rows nobody thinks to look for.

\set ON_ERROR_STOP on

BEGIN;

-- The id lives in a temp table rather than being interpolated into the
-- checks below: psql does not substitute its variables inside
-- dollar-quoted blocks, so a `:keep_company_id` in a DO block is a syntax
-- error — and a guard that fails to parse is a guard that does not run.
CREATE TEMP TABLE keep AS SELECT :keep_company_id::uuid AS id;

-- Refuse to run if the company to keep does not exist. Without this a
-- typo'd id purges *everything* and succeeds, which is the one outcome
-- there is no recovering from.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM companies WHERE id = (SELECT id FROM keep)
  ) THEN
    RAISE EXCEPTION
      'The company to keep (%) does not exist. Refusing to purge, because '
      'a mistyped id would delete every company and report success.',
      (SELECT id FROM keep);
  END IF;
END $$;

CREATE TEMP TABLE doomed AS
SELECT id FROM companies WHERE id <> (SELECT id FROM keep);

\echo 'Companies to purge:'
SELECT count(*) AS doomed_companies FROM doomed;

-- --- Immutability triggers ------------------------------------------
--
-- Eight tables refuse UPDATE and/or DELETE outright: the financial audit
-- trail, the ledger, invoices, invoice and credit-note lines, the usage
-- snapshot, and the pricing audit log. That is the point of them, and in
-- production they should never be bypassed — a mistake there is corrected
-- by posting an opposite entry, never by deletion.
--
-- Disabled here explicitly, in the open, and re-enabled before COMMIT.
-- Doing it once in a named script beats a trigger written to tolerate
-- "some" deletes, because a rule with an exception is a rule somebody
-- finds a way through.
-- Keep this list in step with the triggers that actually fire on DELETE:
--
--   SELECT c.relname, t.tgname FROM pg_trigger t
--     JOIN pg_class c ON c.oid = t.tgrelid
--     JOIN pg_namespace n ON n.oid = c.relnamespace
--    WHERE NOT t.tgisinternal AND n.nspname = 'public' AND (t.tgtype & 8) <> 0;
--
-- A trigger missing from here does not corrupt anything — the whole run is
-- one transaction and aborts — but it costs a full attempt to find, one
-- table at a time.
ALTER TABLE financial_audit_events DISABLE TRIGGER trg_financial_audit_immutable;
ALTER TABLE ledger_entries DISABLE TRIGGER trg_ledger_entries_immutable;
ALTER TABLE pricing_audit_log DISABLE TRIGGER trg_pricing_audit_log_immutable;
ALTER TABLE invoices DISABLE TRIGGER trg_invoices_no_delete;
ALTER TABLE invoices DISABLE TRIGGER trg_invoices_frozen_after_issue;
ALTER TABLE invoice_lines DISABLE TRIGGER trg_invoice_lines_immutable;
ALTER TABLE credit_note_lines DISABLE TRIGGER trg_credit_note_lines_immutable;
ALTER TABLE usage_period_lines DISABLE TRIGGER trg_usage_period_lines_immutable;
-- Metering and context. These CASCADE from the company rather than being
-- deleted by name, but a cascade still fires row triggers, so they are
-- just as blocking as the financial tables above.
ALTER TABLE billable_events DISABLE TRIGGER trg_billable_events_immutable;
ALTER TABLE billing_daily_summary DISABLE TRIGGER trg_billing_daily_summary_no_delete;
ALTER TABLE usage_records DISABLE TRIGGER trg_usage_records_immutable;
ALTER TABLE conversation_context_bindings DISABLE TRIGGER trg_conversation_context_bindings_immutable;
ALTER TABLE customer_context_versions DISABLE TRIGGER trg_customer_context_versions_immutable;
ALTER TABLE service_versions DISABLE TRIGGER trg_service_versions_immutable;
ALTER TABLE routing_decisions DISABLE TRIGGER trg_routing_decisions_immutable;

-- --- Financial records, in dependency order -------------------------
--
-- Everything below is a table whose foreign key to companies is RESTRICT
-- (it would block the delete) or SET NULL (it would survive as an orphan
-- with no company). Both need handling explicitly; the other 43 tables
-- CASCADE and follow the company row automatically.

-- Allocations reference both payments and invoices with RESTRICT, so they
-- go before either.
DELETE FROM payment_allocations pa
USING invoices i WHERE pa.invoice_id = i.id AND i.company_id IN (SELECT id FROM doomed);
DELETE FROM payment_allocations pa
USING payments p WHERE pa.payment_id = p.id AND p.company_id IN (SELECT id FROM doomed);

DELETE FROM payment_refunds WHERE company_id IN (SELECT id FROM doomed);
DELETE FROM payment_intents WHERE company_id IN (SELECT id FROM doomed);

-- Dunning chases an unpaid invoice and holds it with RESTRICT, so it goes
-- before the invoice does.
DELETE FROM dunning_notices WHERE company_id IN (SELECT id FROM doomed);

DELETE FROM credit_note_lines cnl
USING credit_notes cn WHERE cnl.credit_note_id = cn.id AND cn.company_id IN (SELECT id FROM doomed);
DELETE FROM credit_notes WHERE company_id IN (SELECT id FROM doomed);

DELETE FROM invoice_lines il
USING invoices i WHERE il.invoice_id = i.id AND i.company_id IN (SELECT id FROM doomed);
DELETE FROM invoices WHERE company_id IN (SELECT id FROM doomed);

DELETE FROM payments WHERE company_id IN (SELECT id FROM doomed);

-- The usage snapshot cascades from billing_periods, which cascades from
-- companies — but the immutability trigger blocks it, so it is explicit.
DELETE FROM usage_period_lines upl
USING billing_periods bp WHERE upl.billing_period_id = bp.id
  AND bp.company_id IN (SELECT id FROM doomed);

-- Billing periods CASCADE from the company, but four tables hold them
-- with RESTRICT, so the cascade never gets the chance. Usage and billable
-- events are the meter readings a period is computed from; the daily
-- summary is the rollup of them.
DELETE FROM billable_events WHERE company_id IN (SELECT id FROM doomed);
DELETE FROM billing_daily_summary WHERE company_id IN (SELECT id FROM doomed);
DELETE FROM usage_records WHERE company_id IN (SELECT id FROM doomed);

-- Context bindings hold a customer-context version AND a service version
-- with RESTRICT, and both of those CASCADE from the company. Whichever
-- Postgres reaches first would be blocked, so the binding goes first.
DELETE FROM conversation_context_bindings WHERE company_id IN (SELECT id FROM doomed);

-- SET NULL columns: these would survive with company_id = NULL, which is
-- correct for a real deletion (an audit row must outlive its subject) but
-- not for a data reset, where they would be unattributable noise.
DELETE FROM ledger_entries WHERE company_id IN (SELECT id FROM doomed);
DELETE FROM financial_audit_events WHERE company_id IN (SELECT id FROM doomed);
DELETE FROM pricing_audit_log WHERE company_id IN (SELECT id FROM doomed);

-- Company-scoped price overrides. Global and profile rates have a NULL
-- company_id and are deliberately untouched.
DELETE FROM pricing_rates WHERE company_id IN (SELECT id FROM doomed);

-- --- The companies themselves ---------------------------------------
--
-- 43 tables CASCADE from here: users, agents, conversations, messages,
-- customers, channels, queues, roles, teams, departments, notifications,
-- usage records, billing periods, dunning notices and the rest.
DELETE FROM companies WHERE id IN (SELECT id FROM doomed);

-- --- Restore the triggers -------------------------------------------
ALTER TABLE financial_audit_events ENABLE TRIGGER trg_financial_audit_immutable;
ALTER TABLE ledger_entries ENABLE TRIGGER trg_ledger_entries_immutable;
ALTER TABLE pricing_audit_log ENABLE TRIGGER trg_pricing_audit_log_immutable;
ALTER TABLE invoices ENABLE TRIGGER trg_invoices_no_delete;
ALTER TABLE invoices ENABLE TRIGGER trg_invoices_frozen_after_issue;
ALTER TABLE invoice_lines ENABLE TRIGGER trg_invoice_lines_immutable;
ALTER TABLE credit_note_lines ENABLE TRIGGER trg_credit_note_lines_immutable;
ALTER TABLE usage_period_lines ENABLE TRIGGER trg_usage_period_lines_immutable;
ALTER TABLE billable_events ENABLE TRIGGER trg_billable_events_immutable;
ALTER TABLE billing_daily_summary ENABLE TRIGGER trg_billing_daily_summary_no_delete;
ALTER TABLE usage_records ENABLE TRIGGER trg_usage_records_immutable;
ALTER TABLE conversation_context_bindings ENABLE TRIGGER trg_conversation_context_bindings_immutable;
ALTER TABLE customer_context_versions ENABLE TRIGGER trg_customer_context_versions_immutable;
ALTER TABLE service_versions ENABLE TRIGGER trg_service_versions_immutable;
ALTER TABLE routing_decisions ENABLE TRIGGER trg_routing_decisions_immutable;

-- --- Prove it before committing -------------------------------------
--
-- Checked inside the transaction, so a failure here rolls the purge back
-- rather than leaving a database somebody has to reason about.
DO $$
DECLARE
  remaining integer;
  orphans integer;
BEGIN
  SELECT count(*) INTO remaining FROM companies;
  IF remaining <> 1 THEN
    RAISE EXCEPTION 'Expected exactly 1 company to remain, found %', remaining;
  END IF;

  SELECT (SELECT count(*) FROM invoices
            WHERE company_id <> (SELECT id FROM keep))
       + (SELECT count(*) FROM payments
            WHERE company_id <> (SELECT id FROM keep))
       + (SELECT count(*) FROM ledger_entries
            WHERE company_id IS NOT NULL AND company_id <> (SELECT id FROM keep))
       + (SELECT count(*) FROM conversations
            WHERE company_id <> (SELECT id FROM keep))
    INTO orphans;
  IF orphans <> 0 THEN
    RAISE EXCEPTION '% row(s) still reference a purged company', orphans;
  END IF;
END $$;

COMMIT;

\echo ''
\echo 'Remaining:'
SELECT c.name, c.slug,
       (SELECT count(*) FROM users u WHERE u.company_id = c.id) AS users,
       (SELECT count(*) FROM conversations v WHERE v.company_id = c.id) AS conversations,
       (SELECT count(*) FROM channel_configs h WHERE h.company_id = c.id) AS channels,
       (SELECT count(*) FROM invoices i WHERE i.company_id = c.id) AS invoices,
       (SELECT count(*) FROM ledger_entries l WHERE l.company_id = c.id) AS ledger_entries
FROM companies c;
