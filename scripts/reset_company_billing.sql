-- Erase one company's billing data, keeping the company itself.
--
-- A development/staging data-reset tool, and a narrower one than
-- scripts/purge_companies.sql: that removes whole companies, while this one
-- keeps the company, its people, its channels and its conversations and
-- removes only the financial records — invoices, credit notes, payments,
-- allocations, the ledger, the financial audit trail, the usage snapshot and
-- the billing periods they belong to.
--
-- Like the purge, it genuinely deletes financial records, which the schema is
-- built to prevent — see the trigger section below — so it is deliberately a
-- separate, named script rather than anything reachable from the product, and
-- not anything a migration runs on deploy. In production a mistake in the
-- books is corrected by posting an opposite entry, never by deletion.
--
-- Why it exists: a company's billing currency is **fixed once it has been
-- billed**, because re-denominating issued documents is never safe — an
-- invoice states an amount in a currency, and a document that silently
-- changes currency is a different document with the same number. A
-- development tenant billed in the wrong currency therefore cannot simply be
-- corrected in place: the documents in the old currency have to go first, and
-- once they are gone nothing is being re-denominated, because nothing is left
-- to re-denominate. See docs/architecture/billing.md.
--
-- Usage:
--     psql -v company_id="'<uuid>'" -f scripts/reset_company_billing.sql
--
-- The whole thing runs in ONE transaction: either every financial record of
-- that company is gone with referential integrity intact, or nothing changed.
-- A half-erased company is far worse than an un-erased one, because the
-- orphans it leaves are exactly the rows nobody thinks to look for.

\set ON_ERROR_STOP on

BEGIN;

-- The id lives in a temp table rather than being interpolated into the checks
-- below: psql does not substitute its variables inside dollar-quoted blocks,
-- so a `:company_id` in a DO block is a syntax error — and a guard that fails
-- to parse is a guard that does not run.
CREATE TEMP TABLE target AS SELECT :company_id::uuid AS id;

-- Refuse to run if the company does not exist. A mistyped id would otherwise
-- delete nothing and report success, and "it did not work" is a much cheaper
-- answer than a reset somebody believes happened.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM companies WHERE id = (SELECT id FROM target)) THEN
    RAISE EXCEPTION
      'Company % does not exist. Refusing to run, because a mistyped id would '
      'erase nothing and report success.',
      (SELECT id FROM target);
  END IF;
END $$;

\echo 'Company:'
SELECT c.name, c.slug, c.country_code, c.billing_currency
FROM companies c WHERE c.id = (SELECT id FROM target);

\echo 'Financial records to erase:'
SELECT
  (SELECT count(*) FROM invoices WHERE company_id = (SELECT id FROM target)) AS invoices,
  (SELECT count(*) FROM credit_notes WHERE company_id = (SELECT id FROM target)) AS credit_notes,
  (SELECT count(*) FROM payments WHERE company_id = (SELECT id FROM target)) AS payments,
  (SELECT count(*) FROM ledger_entries WHERE company_id = (SELECT id FROM target)) AS ledger_entries,
  (SELECT count(*) FROM financial_audit_events WHERE company_id = (SELECT id FROM target)) AS audit_events,
  (SELECT count(*) FROM billing_periods WHERE company_id = (SELECT id FROM target)) AS billing_periods,
  (SELECT count(*) FROM usage_records WHERE company_id = (SELECT id FROM target)) AS usage_records;

-- Every other company's rows, counted before the deletes and compared after.
-- The failure this catches is a scoping mistake — a join that reaches past the
-- target company — which is silent, unrecoverable, and the only way this
-- script can do real harm.
CREATE TEMP TABLE untouched_before AS
SELECT
  (SELECT count(*) FROM invoices WHERE company_id <> (SELECT id FROM target)) AS invoices,
  (SELECT count(*) FROM invoice_lines il JOIN invoices i ON i.id = il.invoice_id
     WHERE i.company_id <> (SELECT id FROM target)) AS invoice_lines,
  (SELECT count(*) FROM credit_notes WHERE company_id <> (SELECT id FROM target)) AS credit_notes,
  (SELECT count(*) FROM payments WHERE company_id <> (SELECT id FROM target)) AS payments,
  (SELECT count(*) FROM payment_allocations) AS payment_allocations_total,
  (SELECT count(*) FROM ledger_entries
     WHERE company_id IS NULL OR company_id <> (SELECT id FROM target)) AS ledger_entries,
  (SELECT count(*) FROM financial_audit_events
     WHERE company_id IS NULL OR company_id <> (SELECT id FROM target)) AS audit_events,
  (SELECT count(*) FROM billing_periods WHERE company_id <> (SELECT id FROM target)) AS billing_periods,
  (SELECT count(*) FROM usage_records WHERE company_id <> (SELECT id FROM target)) AS usage_records,
  (SELECT count(*) FROM pricing_rates) AS pricing_rates_total,
  (SELECT count(*) FROM companies) AS companies_total;

-- The allocation count is a total rather than a per-company one because
-- payment_allocations carries no company_id: it is reached only through the
-- payment and the invoice it links, and the figure below is derived the same
-- way the deletes are.
CREATE TEMP TABLE allocations_before AS
SELECT count(*) AS mine FROM payment_allocations pa
WHERE pa.payment_id IN (SELECT id FROM payments WHERE company_id = (SELECT id FROM target))
   OR pa.invoice_id IN (SELECT id FROM invoices WHERE company_id = (SELECT id FROM target));

-- --- Immutability triggers ------------------------------------------
--
-- Seven triggers refuse DELETE outright: the financial audit trail, the
-- ledger, invoices, invoice and credit-note lines, the usage snapshot and the
-- finalized daily aggregates. That is the point of them, and in production
-- they should never be bypassed. Disabled here explicitly, in the open, and
-- re-enabled before COMMIT — the same choice scripts/purge_companies.sql
-- makes, and for the same reason: doing it once in a named script beats a
-- trigger written to tolerate "some" deletes, because a rule with an
-- exception is a rule somebody finds a way through.
--
-- trg_invoices_frozen_after_issue and trg_pricing_audit_log_immutable are
-- deliberately left enabled: this script never updates an invoice and never
-- touches pricing history.
ALTER TABLE financial_audit_events DISABLE TRIGGER trg_financial_audit_immutable;
ALTER TABLE ledger_entries DISABLE TRIGGER trg_ledger_entries_immutable;
ALTER TABLE invoices DISABLE TRIGGER trg_invoices_no_delete;
ALTER TABLE invoice_lines DISABLE TRIGGER trg_invoice_lines_immutable;
ALTER TABLE credit_note_lines DISABLE TRIGGER trg_credit_note_lines_immutable;
ALTER TABLE usage_period_lines DISABLE TRIGGER trg_usage_period_lines_immutable;
ALTER TABLE billing_daily_summary DISABLE TRIGGER trg_billing_daily_summary_no_delete;

-- --- The records, in dependency order -------------------------------
--
-- The company row itself survives, so nothing can be left to CASCADE from it:
-- every table below is deleted explicitly, including the ones whose foreign
-- key to companies would have carried them away in a full purge.

-- Allocations reference both payments and invoices with RESTRICT, so they go
-- before either. Two statements, one per parent, because an allocation can be
-- reached through either side.
DELETE FROM payment_allocations pa
USING invoices i
WHERE pa.invoice_id = i.id AND i.company_id = (SELECT id FROM target);
DELETE FROM payment_allocations pa
USING payments p
WHERE pa.payment_id = p.id AND p.company_id = (SELECT id FROM target);

DELETE FROM payment_refunds WHERE company_id = (SELECT id FROM target);
DELETE FROM payment_intents WHERE company_id = (SELECT id FROM target);

-- Dunning notices reference the invoice with RESTRICT and would block it.
DELETE FROM dunning_notices WHERE company_id = (SELECT id FROM target);

DELETE FROM credit_note_lines cnl
USING credit_notes cn
WHERE cnl.credit_note_id = cn.id AND cn.company_id = (SELECT id FROM target);
DELETE FROM credit_notes WHERE company_id = (SELECT id FROM target);

DELETE FROM invoice_lines il
USING invoices i
WHERE il.invoice_id = i.id AND i.company_id = (SELECT id FROM target);
DELETE FROM invoices WHERE company_id = (SELECT id FROM target);

DELETE FROM payments WHERE company_id = (SELECT id FROM target);

-- The daily aggregates and the frozen usage snapshot both hang off billing
-- periods with RESTRICT or a blocked CASCADE, so they precede the periods.
DELETE FROM billing_daily_summary WHERE company_id = (SELECT id FROM target);
DELETE FROM usage_period_lines upl
USING billing_periods bp
WHERE upl.billing_period_id = bp.id AND bp.company_id = (SELECT id FROM target);
DELETE FROM usage_records WHERE company_id = (SELECT id FROM target);
DELETE FROM billing_periods WHERE company_id = (SELECT id FROM target);

-- SET NULL columns: these would survive with company_id = NULL, which is
-- correct when a company is genuinely deleted (an audit row must outlive its
-- subject) but not here, where the company stays and they would be figures
-- and evidence attached to documents that no longer exist.
DELETE FROM ledger_entries WHERE company_id = (SELECT id FROM target);
DELETE FROM financial_audit_events WHERE company_id = (SELECT id FROM target);

-- Company-scoped price overrides are deliberately untouched: a price is
-- configuration, not a billing record, and re-pricing a tenant is a separate
-- decision from clearing what it has been billed.

-- --- Restore the triggers -------------------------------------------
ALTER TABLE financial_audit_events ENABLE TRIGGER trg_financial_audit_immutable;
ALTER TABLE ledger_entries ENABLE TRIGGER trg_ledger_entries_immutable;
ALTER TABLE invoices ENABLE TRIGGER trg_invoices_no_delete;
ALTER TABLE invoice_lines ENABLE TRIGGER trg_invoice_lines_immutable;
ALTER TABLE credit_note_lines ENABLE TRIGGER trg_credit_note_lines_immutable;
ALTER TABLE usage_period_lines ENABLE TRIGGER trg_usage_period_lines_immutable;
ALTER TABLE billing_daily_summary ENABLE TRIGGER trg_billing_daily_summary_no_delete;

-- --- Prove it before committing -------------------------------------
--
-- Checked inside the transaction, so a failure here rolls the whole reset back
-- rather than leaving a database somebody has to reason about.
DO $$
DECLARE
  mine integer;
  drifted text;
BEGIN
  SELECT (SELECT count(*) FROM invoices WHERE company_id = (SELECT id FROM target))
       + (SELECT count(*) FROM credit_notes WHERE company_id = (SELECT id FROM target))
       + (SELECT count(*) FROM payments WHERE company_id = (SELECT id FROM target))
       + (SELECT count(*) FROM payment_intents WHERE company_id = (SELECT id FROM target))
       + (SELECT count(*) FROM payment_refunds WHERE company_id = (SELECT id FROM target))
       + (SELECT count(*) FROM dunning_notices WHERE company_id = (SELECT id FROM target))
       + (SELECT count(*) FROM ledger_entries WHERE company_id = (SELECT id FROM target))
       + (SELECT count(*) FROM financial_audit_events WHERE company_id = (SELECT id FROM target))
       + (SELECT count(*) FROM billing_periods WHERE company_id = (SELECT id FROM target))
       + (SELECT count(*) FROM billing_daily_summary WHERE company_id = (SELECT id FROM target))
       + (SELECT count(*) FROM usage_records WHERE company_id = (SELECT id FROM target))
    INTO mine;
  IF mine <> 0 THEN
    RAISE EXCEPTION '% financial row(s) still belong to company %',
      mine, (SELECT id FROM target);
  END IF;

  -- Nothing may have been reached past the target company.
  SELECT string_agg(problem, '; ') INTO drifted FROM (
    SELECT 'invoices' AS problem FROM untouched_before b
      WHERE b.invoices <> (SELECT count(*) FROM invoices)
    UNION ALL
    SELECT 'invoice_lines' FROM untouched_before b
      WHERE b.invoice_lines <> (SELECT count(*) FROM invoice_lines)
    UNION ALL
    SELECT 'credit_notes' FROM untouched_before b
      WHERE b.credit_notes <> (SELECT count(*) FROM credit_notes)
    UNION ALL
    SELECT 'payments' FROM untouched_before b
      WHERE b.payments <> (SELECT count(*) FROM payments)
    UNION ALL
    SELECT 'payment_allocations' FROM untouched_before b, allocations_before a
      WHERE b.payment_allocations_total - a.mine <> (SELECT count(*) FROM payment_allocations)
    UNION ALL
    SELECT 'ledger_entries' FROM untouched_before b
      WHERE b.ledger_entries <> (SELECT count(*) FROM ledger_entries)
    UNION ALL
    SELECT 'financial_audit_events' FROM untouched_before b
      WHERE b.audit_events <> (SELECT count(*) FROM financial_audit_events)
    UNION ALL
    SELECT 'billing_periods' FROM untouched_before b
      WHERE b.billing_periods <> (SELECT count(*) FROM billing_periods)
    UNION ALL
    SELECT 'usage_records' FROM untouched_before b
      WHERE b.usage_records <> (SELECT count(*) FROM usage_records)
    UNION ALL
    SELECT 'pricing_rates' FROM untouched_before b
      WHERE b.pricing_rates_total <> (SELECT count(*) FROM pricing_rates)
    UNION ALL
    SELECT 'companies' FROM untouched_before b
      WHERE b.companies_total <> (SELECT count(*) FROM companies)
  ) AS drift;
  IF drifted IS NOT NULL THEN
    RAISE EXCEPTION
      'Rows outside company % changed (%). Rolling back — a reset that reaches '
      'past its target is the one outcome there is no recovering from.',
      (SELECT id FROM target), drifted;
  END IF;
END $$;

COMMIT;

\echo ''
\echo 'Remaining for this company (all zero) and its currency:'
SELECT c.name, c.slug, c.country_code, c.billing_currency,
       (SELECT count(*) FROM invoices i WHERE i.company_id = c.id) AS invoices,
       (SELECT count(*) FROM credit_notes n WHERE n.company_id = c.id) AS credit_notes,
       (SELECT count(*) FROM payments p WHERE p.company_id = c.id) AS payments,
       (SELECT count(*) FROM ledger_entries l WHERE l.company_id = c.id) AS ledger_entries,
       (SELECT count(*) FROM financial_audit_events e WHERE e.company_id = c.id) AS audit_events,
       (SELECT count(*) FROM billing_periods b WHERE b.company_id = c.id) AS billing_periods
FROM companies c WHERE c.id = (SELECT id FROM target);
