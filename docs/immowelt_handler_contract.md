# Immowelt external challenge-handler contract

**Contract version:** 1  
**Ownership:** operator-owned external component; WohnWerk must not modify its implementation.

WohnWerk owns challenge detection, persistence, invocation, retry/resume semantics and telemetry.
The external handler owns only whatever operator-controlled action is required to turn one persisted
challenge handoff into a disposition.

## Invocation

WohnWerk invokes the configured command directly, without a shell.

Configuration:

- CLI: `--challenge-handler "<command ...>"`
- environment: `WOHNWERK_IMMOWELT_CHALLENGE_HANDLER`
- timeout: `--challenge-handler-timeout` (default 900 seconds)

The command receives exactly one JSON object on stdin and must write one JSON object to stdout.

## Request schema

Current v1 fields:

```json
{
  "source": "immowelt-de",
  "run_id": 990,
  "shard_id": 128,
  "shard_key": "example-shard",
  "shard_params": {},
  "mode": "incremental",
  "reason": "Immowelt access challenge detected",
  "challenge": {},
  "resume_cursor": {},
  "handoff_state": {
    "state_dir": "/var/lib/wohnwerk/challenge-state/immowelt-de/run-990/shard-128/handoff-1",
    "storage_state_path": "/var/lib/wohnwerk/challenge-state/immowelt-de/run-990/shard-128/handoff-1/storage-state.json",
    "screenshot_path": "/var/lib/wohnwerk/challenge-state/immowelt-de/run-990/shard-128/handoff-1/challenge.png"
  },
  "contract_version": 1,
  "handoff_id": ""
}
```

`handoff_id` is reserved as the stable idempotency identity for one persisted handoff. Older
persisted runs may expose an empty value until the runner-side stable-ID migration is completed;
handlers must therefore not require a non-empty value yet.

Paths supplied in `handoff_state` refer to private local operational state. They are not catalog
data and must not be published.

## Response schema

Valid success-path response:

```json
{"action":"resolved","retry_after_seconds":0}
```

Valid actions:

- `resolved`: WohnWerk may restore the persisted browser state and retry the saved navigation point;
- `defer`: keep the run paused and resumable;
- `abort`: fail the active shard/source attempt without fabricating failures for untouched shards.

Optional fields:

- `message`: operator-facing diagnostic text;
- `retry_after_seconds`: non-negative delay before WohnWerk attempts restore/resume.

Invalid JSON, unsupported action, handler start failure, non-zero exit, or timeout is treated as
`defer` by WohnWerk.

## Persistence and ordering guarantees

Before the handler is invoked, WohnWerk commits:

- the active run/shard identity;
- cumulative page/item metrics;
- the resume cursor;
- fair shard order;
- the active challenge payload;
- browser storage state when available;
- a diagnostic screenshot when available.

Therefore handler failure must not be able to erase already-ingested work or force a restart from
page 1.

On `resolved`, WohnWerk retries the saved point inside the same `CrawlRun`. Reconciliation
authority remains withheld unless the resumed run satisfies all normal complete-coverage and
identity-history conditions.

## Security boundary

The handler is not part of the WohnWerk codebase. WohnWerk must not:

- edit/refactor the handler implementation;
- add challenge-solving logic to WohnWerk itself;
- copy private login material into the catalog;
- weaken lifecycle/coverage authority because the handler reported success.

The v0.4.1 development runner gives the handler a minimal allowlisted subprocess environment rather
than inheriting the full WohnWerk runtime environment. The child keeps ordinary execution context
such as PATH/HOME/locale/DISPLAY where present and receives
`WOHNWERK_CHALLENGE_CONTRACT_VERSION=1`; unrelated parent variables such as `DATABASE_URL` are not
forwarded. This becomes production behavior only after the exact v0.4.1 release is deployed.

## Acceptance checks when the operator says the handler is ready

Before touching the saved production run:

1. validate one synthetic request/response against this contract;
2. validate timeout, invalid-output and non-zero-exit paths remain fail-closed;
3. verify persisted `storage_state_path` is readable/writable by the handler execution identity;
4. verify `resolved` does not create a new run or restart the shard at page 1;
5. resume the existing production paused run (currently Run #990 if still current);
6. verify prior metrics remain cumulative and source coverage remains non-authoritative until complete.
