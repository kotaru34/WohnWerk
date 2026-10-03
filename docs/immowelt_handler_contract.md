# Immowelt external challenge-handler contract

**Contract version:** 1  
**Ownership:** external command remains operator-owned when configured; v0.4.16 also supports an optional WohnWerk-owned, source-specific DataDome bridge to the local loopback solver.

WohnWerk owns challenge detection, persistence, invocation, retry/resume semantics and telemetry.
The external handler owns only whatever operator-controlled action is required to turn one persisted
challenge handoff into a disposition.

## Invocation

WohnWerk invokes the configured command directly, without a shell.

Configuration:

- CLI: `--challenge-handler "<command ...>"`
- environment: `WOHNWERK_IMMOWELT_CHALLENGE_HANDLER`
- optional local DataDome bridge: `WOHNWERK_IMMOWELT_SOLVER_URL` (for example
  `http://127.0.0.1:8877`)
- timeout: `--challenge-handler-timeout` (default 900 seconds)

An explicit external command always takes precedence over the bundled local-solver bridge.
The external command receives exactly one JSON object on stdin and must write one JSON object
to stdout.

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
    "screenshot_path": "/var/lib/wohnwerk/challenge-state/immowelt-de/run-990/shard-128/handoff-1/challenge.png",
    "browser_patch_path": "/var/lib/wohnwerk/challenge-state/immowelt-de/run-990/shard-128/handoff-1/browser-patch.json"
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

## Security and browser-session boundary

The generic external command remains outside the WohnWerk codebase and keeps the minimal allowlisted
subprocess environment introduced in v0.4.1. The child receives
`WOHNWERK_CHALLENGE_CONTRACT_VERSION=1`; unrelated parent variables such as `DATABASE_URL` are not
forwarded.

The v0.4.16 local-solver integration is deliberately narrower than the generic handler contract:

- it is enabled only by explicit `WOHNWERK_IMMOWELT_SOLVER_URL` configuration;
- it only acts on positively identified Immowelt **DataDome** gates;
- it does not treat a generic HTTP 403 as solvable without DataDome frame/content evidence;
- it calls the loopback solver for a DataDome clearance candidate and requires a cookie scoped to
  Immowelt plus the exact solver browser User-Agent;
- the handler writes only a versioned `browser-patch.json` inside the persisted handoff directory;
  the Immowelt adapter validates that patch, merges the `datadome` cookie into its own persisted
  Playwright storage state, and recreates the crawler context with the solver's exact User-Agent;
- the bridge records only a SHA-256 digest of the last clearance candidate for loop detection; it
  never writes the clearance value into run telemetry or the catalog;
- if the same candidate is produced again, or the bounded candidate count is exhausted, the handler
  returns `defer` rather than reporting another false `resolved`;
- Cloudflare/Turnstile and other challenge families are **not** generically replayed through this
  bridge because their tokens/clearances can require stronger same-browser/fingerprint semantics;
- a handler result never weakens lifecycle/coverage authority. The normal crawler must still load
  the saved page successfully and satisfy all ordinary coverage rules.

This design keeps the solver's separate browser from masquerading as the crawler session: only the
specific DataDome artifacts whose replay contract is IP + exact User-Agent are staged, then the
crawler itself proves whether the gate is actually gone.

## Acceptance checks when the operator says the handler is ready

Before touching the saved production run:

1. validate one synthetic request/response against this contract;
2. validate timeout, invalid-output and non-zero-exit paths remain fail-closed;
3. verify persisted `storage_state_path` is readable/writable by the handler execution identity;
4. verify `resolved` does not create a new run or restart the shard at page 1;
5. resume the existing production paused run (currently Run #990 if still current);
6. verify prior metrics remain cumulative and source coverage remains non-authoritative until complete.


## v0.4.16 local DataDome acceptance rules

Before enabling the local bridge in production:

1. exact-head CI must pass;
2. the loopback solver must be healthy on the configured URL;
3. the sidecar must have no proxy configured when WohnWerk itself is using the host's direct egress;
4. a synthetic handler test must prove a solved response stages a versioned browser patch and that
   repeated identical clearance candidates fail closed to `defer`;
5. a headed-adapter test must prove the patch is validated, the DataDome cookie is merged only for
   Immowelt scope, and the recreated crawler context uses the exact solver User-Agent;
6. no live third-party challenge solve is required merely to deploy the bridge;
7. after deployment, a real challenge may only be considered resolved after the normal crawler
   successfully retries the saved navigation point. A repeated gate remains paused/deferred rather
   than restarting from page 1.
