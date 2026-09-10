# Maintaining autobdk

## Purpose and architecture

`autobdk.py` is an executable uv single-file script using Python 3.11+ and only the standard library. Keep the runtime self-contained and independent of the current working directory. Do not restore Node.js, a compilation step, or a required virtual-environment setup.

The CLI is agent-first: `inspect`, `plan`, `apply`, and `configure` never prompt. Normal command output is one JSON envelope with `schema_version`, `ok`, and `data` or `error`; `--help` is human-readable. Exit 0 means successful completion (which may include skips), 1 means service/operation failure, 2 means invalid input or missing setup, and 130 means interruption. Diagnostics belong on stderr. `apply` accepts either a plan object or the complete successful `plan` output envelope, including via stdin.

Keep API transport, cycle arithmetic, inspection/planning, validation, execution, and CLI parsing as clear sections/functions within the script. The maintained operating skill is `skills/autobdk/SKILL.md`; keep it aligned with commands and schemas. Personal skill installations may link to this directory.

README.md is for human users: setup, commands, and the attendance workflow. Provider protocol and implementation rationale belong in AGENTS.md; assistant operating instructions belong in SKILL.md.

## Attendance decisions

- Interpret dates in `Asia/Shanghai`, independently of the machine timezone.
- A cycle named YYYY-MM covers the previous month's 26th through this month's 26th, both inclusive. Submission opens this month's 26th at 00:00 and freezes next month's 1st at 00:00. The shared 26th boundary is deliberate; do not silently change either endpoint to the 25th or 27th.
- Inspect the current cycle and two preceding cycles by default. Query all underlying calendar months and deduplicate their padding days. Show actual records and window status so the agent can ask which cycle to handle, unless the user has already chosen one. Frozen cycles remain visible.
- Inspection and planning are allowed outside the submission window. Recompute eligibility during apply and immediately before every write; never trust a saved plan's window state.
- Missing clock records are the default planning candidates. Existing but abnormal clock times require explicit `--include-anomalies` or explicit plan edits. Suggested 10:00/19:00 times are configurable, not evidence of actual attendance. Keep times editable and validate their order.
- Do not drop an entire day merely because one slot is missing. Preserve incomplete information and expose it for review. Never invent a range ID.
- The historical approval response establishes `flowSid`, `startDate`, and `isFinish`. It does NOT establish how to distinguish approved, rejected, withdrawn, or pending states. Do not invent enum semantics or infer clock attribution from an hour cutoff. Exact existing requests can be skipped; unmatched approvals need review. Optional typed slot metadata may be used when present.
- Preserve account/host binding, validate the complete plan before writes, and fetch current slots/approvals before each submission. Do not submit future times or automatically choose the first of multiple departments.
- Submission is not safely retryable on timeout. Report `unknown`, stop remaining writes, and require reconciliation with current records. A duplicate response triggers a readback, never a tight retry loop. Report per-entry outcomes and nonzero status for incomplete batches.
- The provider has no established idempotency key or atomic check-and-submit endpoint. Rechecking reduces duplicates but cannot guarantee safety between concurrent processes. Do not run concurrent apply commands for the same account.

## Provider and credentials

The provider endpoint paths, form encoding, CSRF bootstrap, and common-endpoint MD5 signature are implemented in `Client`. The bootstrap signing value belongs in local configuration (`app_secret`) or `AUTOBDK_APP_SECRET`, never in source. This is protocol compatibility, not a replacement for HTTPS.

The credential is a session value supplied through `--token SESSION_VALUE`. `Client` sends it in the `QJYDSID` Cookie for both the CSRF bootstrap and subsequent requests, adding `X-CSRF-TOKEN` after bootstrap.

Credential precedence is `--token`, `AUTOBDK_TOKEN`, then config `token`. Other environment settings are `AUTOBDK_HOST` and `AUTOBDK_APP_SECRET`.

Configuration is `$XDG_CONFIG_HOME/autobdk/config.json` (default `~/.config/autobdk/config.json`). `configure --file -` merges supplied fields without echoing values. A user may give the agent the session token directly; using it for the requested operation is expected. Reuse a supplied/local credential until the service rejects it, then ask for a replacement. Do not impose unnecessary credential rotation or external secret-management requirements.

Never commit actual credentials, employer names/domains, personal paths, captured production responses, or conversation transcripts. Keep organization-specific values in local configuration. Record enduring decisions and their rationale, not conversational history.

## Verification and commits

Run `python3 -m unittest discover -s tests -v`. Tests use mocked transport and synthetic records; routine verification must not create real attendance requests. Exercise month/year boundaries, timezone independence, incomplete slots, ambiguous approvals, edited plans, account mismatch, duplicate/unknown results, and invocation from another directory when changing those behaviors.

Automatically commit completed changes at a reasonable functional granularity after relevant checks pass. Do not wait for a separate request to commit. Include only task-owned changes; do not amend unrelated work or push unless requested.

Each commit must have a short English imperative subject describing what changed, then a concise body explaining its purpose. End the body with a Git co-author trailer naming the coding agent's actual model name and version, using the exact runtime model identifier when available:

`Co-authored-by: ACTUAL_MODEL_ID <noreply@openai.com>`

Determine the identity from the active runtime/session, never from an old commit or an example. Do not substitute a generic product name or invent a model revision; if identity is unavailable, resolve it before committing.
