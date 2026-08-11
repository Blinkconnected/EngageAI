# Production Pilot — Backup/DR Exception

**Status: PRODUCTION PILOT — BACKUP/DR EXCEPTION**

**This is not GA. This platform is not disaster-recovery ready.**

A controlled production pilot has been authorised _without_ backup and
disaster-recovery readiness. The gates below were not weakened, waived on
the merits, or marked complete. They are open, they are listed as open,
and this page exists so that nobody has to reconstruct that later from a
release log.

---

## The risk being accepted

> **Production is running without verified off-host backup and disaster
> recovery.**

Concretely, today:

- Every copy of the production database lives on the same host that
  serves production. A disk loss or a host loss takes the data and its
  backups together.
- No restore has been rehearsed from an off-host copy, so the recovery
  procedure is **untested**, not merely slow.
- **RTO and RPO are unknown.** Not "long" — unmeasured. Nobody can
  currently answer "how much data would we lose, and how long would we be
  down?" with anything but a guess.
- Backups are not scheduled. Any copy that exists was taken by hand.

The most recent hand-taken copy is
`backups/pre-golive-purge-20260810T202036Z.dump` (4.1 MB, verified
readable with `pg_restore -l`, 102 table-data entries), taken immediately
before the go-live data purge. It is local only.

## The exception record

| Field                    | Value                                                                                                                                 |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| **Owner**                | ⚠️ **NOT RECORDED** — see below                                                                                                       |
| **Authorised by**        | The account holder of `nour.pro@gmail.com`, in-session                                                                                |
| **Date/time authorised** | 2026-08-11, ~00:0x UTC                                                                                                                |
| **Reason**               | To begin a controlled production pilot without waiting on an external backup destination and credentials, which are not yet available |
| **Accepted risk**        | Total, unrecoverable loss of all production data on host or disk failure; unmeasured RTO/RPO; untested restore path                   |
| **Required remediation** | Items 1–5 in [Gate status](#gate-status) below, in that order                                                                         |
| **Deadline**             | ⚠️ **NOT SET** — see below                                                                                                            |

**Two fields are deliberately empty.** A named accountable owner and a
remediation deadline are commitments about people and dates. They were
requested and not supplied, and inventing either would put a fabricated
promise into the one document whose entire job is to be the honest record
of what was accepted and by whom. They must be filled in before this
exception is treated as complete. Everything else here is verified fact.

## Gate status

Nothing below has been disabled, deleted, weakened, or excluded from CI.
Every gate remains enforced; each is simply unmet.

| #   | Gate                                           | Status            |
| --- | ---------------------------------------------- | ----------------- |
| 1   | Off-host backup executed                       | 🚫 **BLOCKED**    |
| 2   | Independent remote verification of that backup | 🚫 **NOT TESTED** |
| 3   | DR restore **from the off-host copy**          | 🚫 **NOT TESTED** |
| 4   | RTO/RPO measured and recorded                  | 🚫 **NOT TESTED** |
| 5   | Unattended backup timer installed and firing   | 🚫 **BLOCKED**    |

**What blocks all five:** three values are unset. Verified at the time of
writing — `.env` contains zero `BACKUP_*` variables, the shell
environment contains zero, and zero Blink Engage systemd timers are
installed.

```
BACKUP_REMOTE=       # rsync target, e.g. user@host:/srv/blinkengage
BACKUP_SSH_KEY=      # identity for that host
BACKUP_PASSPHRASE=   # symmetric key for the encrypted secrets archive
```

None of them may be invented. A backup pointed at a destination nobody
owns is worse than no backup, because it reports success.

## Why the timer was not installed anyway

`deploy/systemd/blinkengage-backup.{timer,service}` and
`blinkengage-restore-drill.{timer,service}` are written, working, and
ready. Installing them now would produce a green, active timer running
`scripts/backup_all.sh` with no remote configured — the script would log
_"this backup exists ONLY on this host"_ and write a `secrets.SKIPPED`
marker, and the timer would still show as healthy.

That is the failure mode this whole page exists to prevent: a control
that looks present and does nothing. The gate stays visibly open instead.

## Ready to activate

No backup or DR code was modified, removed, or weakened to enable the
pilot. The implementation is complete and waiting on configuration only:

- `scripts/backup_all.sh` — database, object storage, secrets, and the
  git bundle; local retention, remote sync, remote retention
- `scripts/restore_postgres.sh`, `scripts/verify_backup_restore.sh`
- `scripts/dr_rehearsal.sh`
- `deploy/systemd/blinkengage-backup.{timer,service}`
- `deploy/systemd/blinkengage-restore-drill.{timer,service}`
- [`disaster-recovery.md`](./disaster-recovery.md)

Once the three values exist, the sequence is: run a real backup → verify
it from the remote end independently → restore from that remote copy →
record the measured RTO/RPO here → install both timers → confirm two
consecutive unattended runs.

## Relationship to the other readiness documents

This exception overrides Week 0 preconditions **2 (backups scheduled,
off-host)** and **3 (restore rehearsed)** of the
[eight-week production pilot plan](./production-pilot-plan.md), and the
backup items of the [go-live checklist](./go-live-checklist.md). It
overrides them **for a pilot only**. It is not a GA sign-off, and it does
not carry over to one.

## What this exception does not cover

- It is **not** a GA release approval.
- It does **not** make the platform disaster-recovery ready.
- It does **not** authorise onboarding tenants whose data carries
  regulatory retention or recoverability obligations — the
  Healthcare/Financial/Government segments in `CLAUDE.md` among them.
- It expires when the deadline above is set and reached, whichever
  discipline is applied first.
