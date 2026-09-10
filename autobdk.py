#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Agent-first attendance repair CLI. All commands emit JSON and never prompt."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from http.client import HTTPException
from datetime import date, datetime, time as daytime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, HTTPRedirectHandler, build_opener
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Asia/Shanghai")
DEFAULT_HOST = "https://e.xinrenxinshi.com"
CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "autobdk/config.json"


class ToolError(Exception):
    def __init__(self, code, message, *, uncertain=False):
        super().__init__(message)
        self.code, self.uncertain = code, uncertain


def require(condition, code, message):
    if not condition:
        raise ToolError(code, message)


def read_json(path):
    try:
        return json.load(sys.stdin) if path == "-" else json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ToolError("INVALID_INPUT", "Cannot read valid JSON input.") from exc


def load_config():
    cfg = read_json(str(CONFIG_PATH)) if CONFIG_PATH.exists() else {}
    require(isinstance(cfg, dict), "INVALID_CONFIG", "Configuration must be an object.")
    return cfg


def configure(path):
    values = read_json(path)
    allowed = {"token", "host", "app_secret", "department_id", "start", "end"}
    require(isinstance(values, dict) and not values.keys() - allowed, "INVALID_CONFIG", "Unknown configuration fields.")
    require(all(isinstance(v, str) for v in values.values()), "INVALID_CONFIG", "Configuration values must be strings.")
    cfg = load_config()
    cfg.update(values)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement also avoids exposing a partial configuration to another run.
    temporary = CONFIG_PATH.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(cfg, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    temporary.chmod(0o600)
    temporary.replace(CONFIG_PATH)
    return {"configured": sorted(values), "path": str(CONFIG_PATH)}


def now():
    return datetime.now(ZONE)


def month_start(value):
    require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}", value), "INVALID_MONTH", "Use YYYY-MM for the cycle month.")
    try:
        return date.fromisoformat(value + "-01")
    except ValueError as exc:
        raise ToolError("INVALID_MONTH", "Invalid cycle month.") from exc


def shift_month(day, offset):
    index = day.year * 12 + day.month - 1 + offset
    try:
        return date(index // 12, index % 12 + 1, 1)
    except ValueError as exc:
        raise ToolError("INVALID_MONTH", "Cycle is outside the supported date range.") from exc


def cycle(month, instant=None):
    instant = (instant or now()).astimezone(ZONE)
    first = month_start(month)
    begin, end = shift_month(first, -1).replace(day=26), first.replace(day=26)
    opens = datetime.combine(end, daytime(), ZONE)
    freezes = datetime.combine(shift_month(first, 1), daytime(), ZONE)
    state = "not_open" if instant < opens else "frozen" if instant >= freezes else "open"
    return {"month": month, "start": begin.isoformat(), "end": end.isoformat(),
            "opens_at": opens.isoformat(), "freezes_at": freezes.isoformat(), "state": state}


def assert_open(month):
    info = cycle(month)
    if info["state"] != "open":
        code = "WINDOW_NOT_OPEN" if info["state"] == "not_open" else "WINDOW_CLOSED"
        raise ToolError(code, f"Cycle {month}: opens {info['opens_at']}, freezes {info['freezes_at']}.")


def timestamp(day):
    return int(datetime.combine(date.fromisoformat(day), daytime(), ZONE).timestamp())


def clock(value):
    require(isinstance(value, str) and re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value), "INVALID_TIME", "Time must be HH:MM (00:00 through 23:59).")
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


urlopen = build_opener(NoRedirect).open


class Client:
    def __init__(self, cfg, token=None, host=None):
        self.host = (host or os.environ.get("AUTOBDK_HOST") or cfg.get("host") or DEFAULT_HOST).rstrip("/")
        require(urlparse(self.host).scheme == "https" and bool(urlparse(self.host).netloc), "INVALID_CONFIG", "Host must be an HTTPS URL.")
        # The public token is the opaque QJYDSID session value.
        token = token if token is not None else os.environ.get("AUTOBDK_TOKEN") or cfg.get("token")
        require(isinstance(token, str) and bool(token.strip()), "AUTH_REQUIRED", "Provide --token SESSION_VALUE, AUTOBDK_TOKEN, or configure token.")
        require(not any(c in token for c in "\r\n;") and not token.startswith("QJYDSID="), "INVALID_INPUT", "Supply only the session value, without a Cookie name or header.")
        self.headers = {"Cookie": f"QJYDSID={token}", "Accept": "application/json"}
        self.secret = os.environ.get("AUTOBDK_APP_SECRET") or cfg.get("app_secret")
        require(isinstance(self.secret, str) and bool(self.secret), "CONFIG_REQUIRED", "Configure app_secret for the provider's common-endpoint signing protocol.")
        self.account = None

    def request(self, path, form=None, *, write=False):
        encoded = urlencode(form).encode() if form is not None else None
        req = Request(self.host + path, data=encoded, headers=self.headers)
        try:
            with urlopen(req, timeout=30) as response:
                # A login redirect may return HTML with HTTP 200.
                if urlparse(response.url).netloc != urlparse(self.host).netloc:
                    raise ToolError("AUTH_EXPIRED", "Session redirected to another host; refresh the session token.", uncertain=write)
                raw = response.read()
        except HTTPError as exc:
            if exc.code in (401, 403) or 300 <= exc.code < 400:
                raise ToolError("AUTH_EXPIRED", "Session token expired or access was denied.") from exc
            raise ToolError("HTTP_ERROR", f"Provider returned HTTP {exc.code}.", uncertain=write) from exc
        except (URLError, TimeoutError, OSError, HTTPException) as exc:
            raise ToolError("NETWORK_ERROR", "Request failed or timed out; check connectivity.", uncertain=write) from exc
        try:
            envelope = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise ToolError("INVALID_RESPONSE", "Expected JSON; session may have expired.", uncertain=write) from exc
        if not isinstance(envelope, dict):
            raise ToolError("INVALID_RESPONSE", "Expected an API response object.", uncertain=write)
        if envelope.get("status") is False:
            message = str(envelope.get("message") or "Provider rejected the request.")
            secrets = [self.headers.get("Cookie"), self.headers.get("X-CSRF-TOKEN")]
            secrets.extend(part.partition("=")[2].strip() for part in self.headers.get("Cookie", "").split(";") if "=" in part)
            for secret in secrets:
                if secret:
                    message = message.replace(secret, "[redacted]")
            code = "DUPLICATE_SUBMISSION" if "重复提交" in message else "API_ERROR"
            if any(term in message.lower() for term in ("登录", "login", "jwt", "csrf", "token")):
                code = "AUTH_EXPIRED"
            raise ToolError(code, message)
        # Success codes have not been established independently of status.
        if envelope.get("status") is not True:
            raise ToolError("INVALID_RESPONSE", "Missing boolean success status.", uncertain=write)
        return envelope.get("data")

    def login(self):
        stamp = int(time.time() * 1000)
        sign = hashlib.md5(f"sign_methodmd5timestamp{stamp}version1.0.0app_keyemployee{self.secret}".encode()).hexdigest()
        query = urlencode({"timestamp": stamp, "app_key": "employee", "sign_method": "md5", "version": "1.0.0", "sign": sign})
        data = self.request("/env/ajax-common?" + query)
        require(isinstance(data, dict) and data.get("csrf") and data.get("employeeName"), "AUTH_EXPIRED", "Session has no account or CSRF token; refresh the session token.")
        self.headers["X-CSRF-TOKEN"] = str(data["csrf"])
        self.account = str(data["employeeName"])

    def month(self, month):
        data = self.request("/attendance/ajax-get-attendance-record-list", {"yearmo": month.replace("-", "")})
        require(isinstance(data, dict) and isinstance(data.get("records"), list), "INVALID_RESPONSE", "Expected monthly records.")
        return data["records"]

    def detail(self, day):
        data = self.request("/attendance/ajax-get-attendance-record-by-date", {"date": day.replace("-", "")})
        require(isinstance(data, dict) and isinstance(data.get("signTimeList"), list), "INVALID_RESPONSE", "Expected daily attendance slots.")
        return data

    def approvals(self, day):
        data = self.request("/attendance/ajax-get-approve-bdk-flow", {"date": str(timestamp(day))})
        require(isinstance(data, list) and all(isinstance(x, dict) for x in data), "INVALID_RESPONSE", "Expected daily approvals.")
        return data

    def settings(self):
        data = self.request("/attendance/ajax-new-sign-again", {})
        require(isinstance(data, dict) and isinstance(data.get("departmentList"), list), "INVALID_RESPONSE", "Expected approval form settings.")
        return data

    def submit(self, item, settings, department):
        payload = {"flow_type": settings["flow_type"], "flowSettingId": settings["flowSettingId"],
                   "departmentId": department, "isClocking": 0, "date": str(timestamp(item["date"])),
                   "start_date": item["date"] + " " + item["time"], "reason": item.get("reason", ""),
                   "image_path": "", "timeRangeId": item["range_id"], "bdkDate": item["date"],
                   "clockType": item["clock_type"], "rangeModels": [], "custom_field": "[]"}
        return self.request("/attendance/ajax-start-attendance-approval", {"data": json.dumps(payload)}, write=True)


def approval_state(flows, item):
    """Known endpoint fields cannot reliably distinguish pending/rejected/cancelled."""
    uncertain = False
    for flow in flows:
        try:
            dt = datetime.fromtimestamp(float(flow["startDate"]), ZONE)
        except (KeyError, ValueError, TypeError, OverflowError, OSError):
            uncertain = True
            continue
        same_time = dt.strftime("%Y-%m-%d %H:%M") == item["date"] + " " + item["time"]
        kind, slot = flow.get("clockType"), flow.get("timeRangeId")
        if same_time and (kind is None or str(kind) == str(item["clock_type"])) and (slot is None or str(slot) == item["range_id"]):
            return "existing"
        if kind is None or slot is None:
            uncertain = True
        elif str(kind) == str(item["clock_type"]) and str(slot) == item["range_id"]:
            uncertain = True
    return "review" if uncertain else "clear"


def inspect(client, months, start="10:00", end="19:00"):
    clock(start), clock(end)
    require(start < end, "INVALID_TIME", "Default start must precede default end.")
    today = now().date().isoformat()
    periods = [cycle(m) for m in months]
    by_day, details = {}, {}
    calendar_months = sorted({month for p in periods for month in (p["start"][:7], p["end"][:7])})
    for month in calendar_months:
        for row in client.month(month):
            try:
                day = datetime.fromtimestamp(float(row["time"]), ZONE).date().isoformat()
            except (KeyError, ValueError, TypeError, OverflowError, OSError) as exc:
                raise ToolError("INVALID_RESPONSE", "Monthly record has an invalid timestamp.") from exc
            # Calendar endpoints may include padding days: take the owning month.
            if day[:7] == month:
                by_day[day] = row
    for p in periods:
        records = []
        for day, row in sorted(by_day.items()):
            if not p["start"] <= day <= min(p["end"], today) or row.get("situation") != -1:
                continue
            if day not in details:
                details[day] = client.detail(day), client.approvals(day)
            detail, flows = details[day]
            slots, issues = detail["signTimeList"], []
            for slot in slots:
                require(isinstance(slot, dict), "INVALID_RESPONSE", "Attendance slot must be an object.")
                actual, description = slot.get("clockTime"), slot.get("statusDesc")
                if actual and not description:
                    continue
                kind = slot.get("clockAttribution")
                item = {"date": day, "clock_type": kind, "range_id": str(slot.get("rangeId") or ""),
                        "time": start if kind == 1 else end, "reason": ""}
                state = approval_state(flows, item)
                eligible = kind in (1, 2) and bool(item["range_id"]) and row.get("isWorkday") != 0 and not detail.get("bdkErrorMessage")
                eligible = eligible and datetime.fromisoformat(day + "T" + item["time"]).replace(tzinfo=ZONE) <= now()
                if not eligible:
                    state = "review"
                issues.append({**item, "actual_time": actual, "description": description,
                               "kind": "anomaly" if actual else "missing", "approval_state": state,
                               "candidate": eligible and state == "clear"})
            record = {"date": day, "issues": issues,
                      "approvals": [{k: f.get(k) for k in ("flowSid", "startDate", "isFinish", "clockType", "timeRangeId") if k in f} for f in flows],
                      "provider_message": detail.get("bdkErrorMessage"), "incomplete_slots": not {1, 2}.issubset({s.get("clockAttribution") for s in slots})}
            if not issues:
                record["needs_review"] = True
            records.append(record)
        p["records"] = records
        p["summary"] = {"abnormal_days": len(records), "missing": sum(i["kind"] == "missing" for r in records for i in r["issues"]),
                        "existing_approvals": sum(len(r["approvals"]) for r in records),
                        "candidates": sum(i["candidate"] and i["kind"] == "missing" for r in records for i in r["issues"])}
    settings = client.settings()
    departments = [{"id": str(d["departmentId"]), "name": d.get("departmentName", "")} for d in settings["departmentList"] if isinstance(d, dict) and d.get("departmentId")]
    return {"host": client.host, "account": client.account, "timezone": str(ZONE), "departments": departments, "cycles": periods}


def make_plan(report, include_anomalies=False):
    require(len(report["cycles"]) == 1, "INVALID_INPUT", "Choose exactly one cycle to plan.")
    p = report["cycles"][0]
    entries, review = [], []
    for record in p["records"]:
        if record.get("needs_review"):
            review.append(record)
        for item in record["issues"]:
            if item["candidate"] and (item["kind"] == "missing" or include_anomalies):
                entries.append({k: item[k] for k in ("date", "clock_type", "range_id", "time", "reason")})
            else:
                review.append(item)
    return {"schema_version": 1, "kind": "attendance_plan", "host": report["host"], "account": report["account"],
            "month": p["month"], "cycle": {k: v for k, v in p.items() if k not in ("records", "summary")},
            "entries": entries, "review": review}


def validate_plan(plan):
    require(isinstance(plan, dict) and plan.get("schema_version") == 1 and plan.get("kind") == "attendance_plan", "INVALID_PLAN", "Expected an attendance_plan with schema_version 1.")
    p = cycle(plan.get("month"))
    require(isinstance(plan.get("entries"), list), "INVALID_PLAN", "Plan entries must be an array.")
    seen = set()
    for item in plan["entries"]:
        require(isinstance(item, dict), "INVALID_PLAN", "Each entry must be an object.")
        try:
            day = date.fromisoformat(item["date"]).isoformat()
        except (KeyError, ValueError, TypeError) as exc:
            raise ToolError("INVALID_PLAN", "Each entry needs an ISO date.") from exc
        require(day == item["date"] and p["start"] <= day <= p["end"], "INVALID_PLAN", "Entry is outside the selected cycle.")
        clock(item.get("time"))
        require(type(item.get("clock_type")) is int and item["clock_type"] in (1, 2), "INVALID_PLAN", "clock_type must be 1 or 2.")
        require(isinstance(item.get("range_id"), str) and bool(item["range_id"]), "INVALID_PLAN", "range_id is required.")
        require(isinstance(item.get("reason", ""), str), "INVALID_PLAN", "reason must be a string.")
        key = (day, item["range_id"], item["clock_type"])
        require(key not in seen, "INVALID_PLAN", "Plan contains duplicate slots.")
        seen.add(key)
    return plan


def check_entry(client, item, entries, confirmed=()):
    require(datetime.fromisoformat(item["date"] + "T" + item["time"]).replace(tzinfo=ZONE) <= now(), "FUTURE_TIME", "Cannot submit a future clock time.")
    detail, flows = client.detail(item["date"]), client.approvals(item["date"])
    # A confirmed request in this plan supplies attribution that the legacy
    # daily endpoint omits. Do not mistake our own earlier write for ambiguity.
    flows = [flow for flow in flows if not any(
        (known["date"], known["range_id"], known["clock_type"]) != (item["date"], item["range_id"], item["clock_type"])
        and approval_state([flow], known) == "existing" for known in confirmed)]
    state = approval_state(flows, item)
    if state == "existing":
        return "existing"
    require(state == "clear", "APPROVAL_REVIEW_REQUIRED", "An existing approval cannot be mapped safely; inspect its status before submitting.")
    require(not detail.get("bdkErrorMessage"), "PROVIDER_BLOCKED", str(detail.get("bdkErrorMessage")))
    slots = detail["signTimeList"]
    matching = [s for s in slots if str(s.get("rangeId")) == item["range_id"] and s.get("clockAttribution") == item["clock_type"]]
    require(len(matching) == 1, "SLOT_CHANGED", "The selected attendance slot is missing or ambiguous.")
    slot = matching[0]
    if slot.get("clockTime") and not slot.get("statusDesc"):
        return "resolved"
    other_kind = 2 if item["clock_type"] == 1 else 1
    planned = [e["time"] for e in entries if e["date"] == item["date"] and e["range_id"] == item["range_id"] and e["clock_type"] == other_kind]
    actual = [s.get("clockTime") for s in slots if str(s.get("rangeId")) == item["range_id"] and s.get("clockAttribution") == other_kind and s.get("clockTime")]
    normal = [s.get("clockTime") for s in slots if str(s.get("rangeId")) == item["range_id"] and s.get("clockAttribution") == other_kind and s.get("clockTime") and not s.get("statusDesc")]
    counterpart = normal or planned or actual
    if counterpart:
        other = clock(counterpart[0])
        require(item["time"] < other if item["clock_type"] == 1 else item["time"] > other, "TIME_ORDER", "Start must precede end; adjust the plan's times.")
    return "ready"


def apply_plan(client, plan, department=None, interval=10):
    validate_plan(plan)
    require(plan.get("host") == client.host and plan.get("account") == client.account, "PLAN_ACCOUNT_MISMATCH", "Plan belongs to another host or account; regenerate it.")
    assert_open(plan["month"])
    require(interval >= 0 and interval <= 300, "INVALID_INPUT", "Interval must be between 0 and 300 seconds.")
    entries = sorted(plan["entries"], key=lambda e: (e["date"], e["range_id"], e["clock_type"]))
    if not entries:
        return {"results": [], "submitted": 0, "skipped": 0, "failed": 0, "unknown": 0}
    # Check the entire plan before the first write.
    confirmed = []
    for item in entries:
        if check_entry(client, item, entries, confirmed) == "existing":
            confirmed.append(item)
    settings = client.settings()
    require("flow_type" in settings and "flowSettingId" in settings, "INVALID_RESPONSE", "Approval flow settings are incomplete.")
    departments = [str(d["departmentId"]) for d in settings["departmentList"] if isinstance(d, dict) and d.get("departmentId")]
    if department is None:
        require(len(departments) == 1, "DEPARTMENT_REQUIRED", "Select department_id in configuration or --department-id.")
        department = departments[0]
    require(str(department) in departments, "INVALID_DEPARTMENT", "Selected department is unavailable.")
    results, stopped, wrote = [], False, False
    for item in entries:
        result = {"date": item["date"], "clock_type": item["clock_type"], "range_id": item["range_id"]}
        if stopped:
            results.append({**result, "status": "not_attempted"})
            continue
        try:
            if wrote:
                time.sleep(interval)
            assert_open(plan["month"])
            status = check_entry(client, item, entries, confirmed)
            if status != "ready":
                results.append({**result, "status": "skipped", "reason": status})
                continue
            wrote = True
            data = client.submit(item, settings, str(department))
            # Only expose known identifiers; do not dump arbitrary provider payloads.
            ids = {k: data[k] for k in ("flowSid", "id") if isinstance(data, dict) and k in data}
            confirmed.append(item)
            results.append({**result, "status": "submitted", **ids})
        except ToolError as exc:
            if exc.code == "DUPLICATE_SUBMISSION":
                try:
                    if approval_state(client.approvals(item["date"]), item) == "existing":
                        confirmed.append(item)
                        results.append({**result, "status": "skipped", "reason": "existing"})
                        continue
                except ToolError:
                    pass
                exc.uncertain = True
            status = "unknown" if exc.uncertain else "failed"
            results.append({**result, "status": status, "error": {"code": exc.code, "message": str(exc)}})
            stopped = exc.uncertain or exc.code in {"AUTH_EXPIRED", "WINDOW_CLOSED", "WINDOW_NOT_OPEN"}
    counts = {key: sum(r["status"] == key for r in results) for key in ("submitted", "skipped", "failed", "unknown", "not_attempted")}
    return {"results": results, **counts}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ToolError("INVALID_ARGUMENT", message)


def main(argv=None):
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("configure", help="Merge runtime settings from a JSON file (or stdin: -). Never echoes values.")
    setup.add_argument("--file", required=True)
    for name in ("inspect", "plan", "apply"):
        sub = commands.add_parser(name)
        sub.add_argument("--token", help="Session value only; sent as the QJYDSID Cookie. CLI > AUTOBDK_TOKEN > config token.")
        sub.add_argument("--host")
        sub.add_argument("--json", action="store_true", help="JSON is always enabled; accepted for consistency.")
        if name == "inspect":
            sub.add_argument("--months", type=int, default=3, help="Current cycle plus preceding cycles (default: 3).")
            sub.add_argument("--month", help="Inspect one cycle, YYYY-MM.")
        elif name == "plan":
            sub.add_argument("--month", required=True, help="Selected cycle, YYYY-MM; dates run from previous month 26 to this month 26 inclusive.")
            sub.add_argument("--include-anomalies", action="store_true", help="Also propose corrections for recorded but abnormal clock times.")
        else:
            sub.add_argument("--file", required=True, help="Plan or plan-command JSON envelope; - reads stdin.")
            sub.add_argument("--department-id")
            sub.add_argument("--interval", type=float, default=10)
        if name != "apply":
            sub.add_argument("--start", help="Suggested start time (config or 10:00).")
            sub.add_argument("--end", help="Suggested end time (config or 19:00).")
    args = parser.parse_args(argv)
    if args.command == "configure":
        return configure(args.file)
    cfg = load_config()
    if args.command == "apply":
        plan = read_json(args.file)
        if isinstance(plan, dict) and plan.get("ok") is True:
            plan = plan.get("data")
        validate_plan(plan)
        assert_open(plan["month"])
    else:
        if args.command == "inspect" and not args.month:
            require(1 <= args.months <= 24, "INVALID_ARGUMENT", "--months must be between 1 and 24.")
            months = [shift_month(now().date(), -i).strftime("%Y-%m") for i in range(args.months)]
        else:
            month_start(args.month)
            months = [args.month]
    client = Client(cfg, token=args.token, host=args.host)
    client.login()
    if args.command == "apply":
        return apply_plan(client, plan, args.department_id or cfg.get("department_id"), args.interval)
    report = inspect(client, months, args.start or cfg.get("start", "10:00"), args.end or cfg.get("end", "19:00"))
    return make_plan(report, args.include_anomalies) if args.command == "plan" else report


def cli():
    try:
        data = main()
        failed = any(data.get(k, 0) for k in ("failed", "unknown", "not_attempted"))
        result = {"schema_version": 1, "ok": not failed, "data": data}
        if failed:
            result["error"] = {"code": "PARTIAL_FAILURE", "message": "Some entries were not confirmed submitted; inspect individual results before retrying."}
        code = 1 if failed else 0
    except ToolError as exc:
        result = {"schema_version": 1, "ok": False, "error": {"code": exc.code, "message": str(exc)}}
        code = 2 if exc.code.startswith("INVALID") or exc.code.endswith("REQUIRED") else 1
    except KeyboardInterrupt:
        result = {"schema_version": 1, "ok": False, "error": {"code": "INTERRUPTED", "message": "Interrupted; if submission was in progress, query existing approvals before retrying."}}
        code = 130
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result = {"schema_version": 1, "ok": False, "error": {"code": "UNEXPECTED_RESPONSE", "message": "Unexpected response or local I/O error; no automatic retry. Inspect records before resuming."}}
        code = 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(cli())
