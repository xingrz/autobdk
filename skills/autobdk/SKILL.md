---
name: autobdk
description: Inspect attendance anomalies and existing repair requests, select an attendance cycle, and prepare or submit clock-repair plans with the autobdk CLI. Use for missing clock-ins/outs, 补卡, 补签, and attendance repair; not for filling project timesheets.
---

# Attendance repair

Use the installed `autobdk` command. It is a uv single-file Python script with no third-party Python dependencies. If the command is absent, locate the user's autobdk checkout and invoke its executable `autobdk.py` by absolute path; do not assume a particular checkout location or require changing directories. `autobdk --help` and subcommand `--help` describe supported flags.

## Credentials and setup

Reuse the session token from local configuration or `AUTOBDK_TOKEN`. If unavailable, ask the user for a session token and use it for the requested operation. Tokens may be supplied directly to the agent and saved in local configuration for reuse.

For one invocation, pass `--token SESSION_VALUE` after the subcommand. To reuse it, merge an object such as `{"token":"SESSION_VALUE"}` through `autobdk configure --file -` on stdin, substituting the actual user-supplied value only at runtime. Accepted keys: `token`, `host`, `app_secret`, `department_id`, `start`, `end`. The provider's common-endpoint signing value (`app_secret`) is a separate local setting, not the session token. Configuration lives at `~/.config/autobdk/config.json` or under `XDG_CONFIG_HOME`. Never place credential values in tracked files or repeat them in summaries. If `AUTH_EXPIRED` occurs, stop and ask for a refreshed session token; do not keep retrying the old one.

## Workflow

1. Run `autobdk inspect --months 3`. Present the returned cycle ranges, anomaly counts, existing applications, and window states. Ask which cycle to handle unless the user already specified it. `--month YYYY-MM` inspects one selected cycle.
2. Run `autobdk plan --month YYYY-MM`. This only reads data. Save its complete JSON output to a temporary file outside the repository. Its `data.entries` are proposed requests; `data.review` contains issues excluded from automatic planning. Read and explain review items rather than claiming they are resolved.
3. Adjust the plan according to the user's intended dates and times. Each entry has `date`, `clock_type` (1 start, 2 end), `range_id`, `time` (HH:MM), and `reason`. Preserve host/account binding and returned range IDs. Missing clock records are proposed by default; use `--include-anomalies` only when corrections to recorded-but-abnormal times are intended. Defaults 10:00/19:00 are suggestions, not facts about attendance.
4. Show the concrete selected changes and submit once the user has authorized them. Existing explicit authorization can cover this step; do not request it again unnecessarily. Run `autobdk apply --file /absolute/path/to/plan.json`. The command also accepts a bare plan object or `--file -` for stdin. Do not run concurrent applies for the same account.

All operational commands produce JSON on stdout and never prompt; the agent handles user dialogue. There is no need to simulate terminal keystrokes. Exit 0 can include skips, so inspect each result. Exit 1 indicates an operation/partial failure, 2 invalid input or missing setup, 130 interruption.

## Cycle and recovery rules

- Use the reported cycle boundaries: previous month's 26th through the selected month's 26th inclusive, in Asia/Shanghai. Submission opens on the selected month's 26th and freezes on the following month's 1st at midnight. Both adjacent cycles include their shared 26th; never adjust this boundary yourself.
- `WINDOW_NOT_OPEN` and `WINDOW_CLOSED` prevent writes, but inspection/planning remain available. Do not override the clock or edit saved window fields to bypass the rules.
- Existing approvals cannot always be mapped to a slot or interpreted as approved/rejected/withdrawn. `APPROVAL_REVIEW_REQUIRED` calls for checking actual status, not deleting evidence or inventing status mappings.
- `DEPARTMENT_REQUIRED` means the service offered zero or multiple departments. Use an ID from inspect output `data.departments` that matches the user's selection; do not choose the first automatically.
- Results may be `submitted`, `skipped`, `failed`, `unknown`, or `not_attempted`. `unknown` means the server may have accepted a request. Inspect fresh records before resuming, and never blindly replay the saved batch. `skipped: existing` records an existing request, not a claim of approval.
