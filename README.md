# autobdk

Review attendance anomalies and submit clock-repair requests from the command line or through an AI assistant.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run `autobdk.py` by its full path. You can also link it into a directory on your PATH as `autobdk`. No build step is required.

To use the tool through an AI assistant, install the [autobdk skill](skills/autobdk/SKILL.md).

## Usage

Check recent attendance records with your session token:

```sh
autobdk inspect --token SESSION_VALUE
```

This shows the current attendance cycle and the two preceding cycles. Choose a cycle, prepare its repair plan, review the proposed dates and times, and submit:

```sh
autobdk plan --month 2026-09 --token SESSION_VALUE > /tmp/attendance-plan.json
autobdk apply --file /tmp/attendance-plan.json --token SESSION_VALUE
```

An attendance cycle covers the previous month's 26th through the selected month's 26th. Requests can be submitted from the selected month's 26th until the next month begins. Older records remain available for inspection.

Commands return JSON. An assistant can help explain the results and edit the plan. If a token is already saved locally or set in `AUTOBDK_TOKEN`, omit `--token`.

For development and maintenance, see [AGENTS.md](AGENTS.md).
