#!/usr/bin/env python3
"""
send_test_emails.py — Operational utility to send test/seed emails into a
                       user's M365 mailbox via Microsoft Graph API.

Used to test the email-to-jira cron bot (or any email triage agent) by
injecting realistic bug reports, feature requests, and improvement emails.

Usage:
    # On the prod server (where AG_FIELD_ENCRYPTION_KEY and DB are available):
    set -a; source /etc/storeglance/prod/agent/.env; set +a
    PYTHONPATH=/var/www/ai.storeglance.com/api:/var/www/ai.storeglance.com/api/core \
        python3 ops/send_test_emails.py [OPTIONS]

Options:
    --sender   EMAIL    Sender address (default: support@storeglance.com)
    --to       EMAIL    Recipient address (default: support@storeglance.com)
    --tenant-db NAME    Tenant database name (default: prod_agent_tenant_2a5fe12b)
    --conn-id  INT      ag_cred.connections.connection_id for M365 (default: 1)
    --dry-run           Print emails without sending
    --count    INT      Number of emails to send from the pool (default: all)
    --category CAT      Filter: bug, feature, improvement, all (default: all)

Requires: cryptography, requests, psycopg2 (all part of the agent runtime)
"""

import argparse
import json
import subprocess
import sys
import os
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

# ---------------------------------------------------------------------------
# Email Pool — realistic fleet management emails
# ---------------------------------------------------------------------------

EMAIL_POOL = [
    # ── BUGS ──────────────────────────────────────────────────────────────
    {
        "category": "bug",
        "subject": "Driver app crashes on poor network when uploading shift photos",
        "body": (
            "<p>Hi Team,</p>"
            "<p>Multiple drivers reporting the mobile app crashes when they try to upload shift photos "
            "on 2G/3G networks. The upload has no retry logic and no timeout handling. When the "
            "connection drops mid-upload the app throws an unhandled exception and force-closes. "
            "Drivers lose their photo evidence and have to restart the shift documentation process. "
            "This happens 10-15 times/day across our fleet of 300 drivers.</p>"
            "<p>Need retry with exponential backoff, background upload queue, and graceful timeout handling.</p>"
            "<p>Regards,<br>Fleet Operations</p>"
        ),
    },
    {
        "category": "bug",
        "subject": "GET /vehicle/maintenance returns 504 timeout for fleets over 200 vehicles",
        "body": (
            "<p>Hi Team,</p>"
            "<p>The maintenance history endpoint does a full table scan with no indexing on "
            "vehicle_id + date range. For our 450-vehicle fleet, GET /vehicle/maintenance?fleetId=12 "
            "takes 38 seconds and usually times out at the 30s gateway limit. The query joins "
            "maintenance_records, parts_inventory, and service_providers with no pagination. "
            "Smaller fleets under 50 vehicles work fine. This is a P1 for enterprise clients.</p>"
            "<p>Regards,<br>Fleet Support</p>"
        ),
    },
    {
        "category": "bug",
        "subject": "Attendance reports double-count drivers who work split shifts",
        "body": (
            "<p>Hi Team,</p>"
            "<p>The attendance calculation logic counts each clock-in as a separate attendance day. "
            "Drivers who work split shifts (morning 6am-12pm, evening 4pm-10pm) show up as 2 "
            "attendance days instead of 1. This affects 85 of our 300 drivers. Payroll is "
            "overpaying overtime because the system thinks these drivers worked 60 days in a "
            "30-day month. We have manually corrected payroll for the last 3 months.</p>"
            "<p>Regards,<br>Fleet Payroll</p>"
        ),
    },
    {
        "category": "bug",
        "subject": "Penalty system allows negative balance with no driver notification",
        "body": (
            "<p>Hi Team,</p>"
            "<p>The driver penalty system (POST /driverpenalty) deducts from driver earnings but has "
            "no floor check. A driver can accumulate penalties exceeding their total earnings, "
            "resulting in a negative settlement. The driver is never notified when a penalty is "
            "applied - they only discover it on payday. Three drivers quit last month after "
            "unexpected negative settlements.</p>"
            "<p>Need: penalty cap, push notification on penalty, driver acknowledgment before "
            "deduction, and a penalty dispute flow.</p>"
            "<p>Regards,<br>Fleet HR</p>"
        ),
    },
    {
        "category": "bug",
        "subject": "Scheduled reports via email not working - cron endpoint returns 500 since last deploy",
        "body": (
            "<p>Hi Team,</p>"
            "<p>The POST /report/schedule endpoint has been returning 500 Internal Server Error "
            "since the July 1st deployment. The error log shows NullReferenceException in "
            "ReportSchedulerService.cs at line 142 when trying to serialize the cron expression. "
            "All 12 of our scheduled daily/weekly reports have stopped generating. Fleet managers "
            "are manually exporting reports every morning which takes 45 minutes. This is a "
            "regression from the deploy.</p>"
            "<p>Regards,<br>Fleet Support</p>"
        ),
    },
    {
        "category": "bug",
        "subject": "Shift lifecycle has no overlap or conflict detection",
        "body": (
            "<p>Hi Team,</p>"
            "<p>POST /shift/Start has no conflict handling: drivers create duplicate active shifts, "
            "orphaned shifts from app crashes never auto-close, two drivers can start shifts on "
            "same vehicle simultaneously. Creates corrupt payroll data.</p>"
            "<p>Need 409 Conflict for double-start, auto-close for shifts &gt;16h, vehicle exclusivity.</p>"
            "<p>Regards,<br>Fleet Engineering</p>"
        ),
    },
    {
        "category": "bug",
        "subject": "17 Fleet DTOs accept all-null payloads - missing field validation",
        "body": (
            "<p>Hi Team,</p>"
            "<p>17 request schemas define properties but ZERO required fields. ClockIn/ClockOut DTOs "
            "accept empty payloads. ReportFilterDTO with no filters triggers full table scans. "
            "ShiftPhotoBundle accepts uploads with no photo ref. Need required field arrays on "
            "all write-path DTOs.</p>"
            "<p>Regards,<br>Fleet Backend</p>"
        ),
    },

    # ── FEATURES ──────────────────────────────────────────────────────────
    {
        "category": "feature",
        "subject": "Real-time vehicle GPS tracking needed for live fleet map",
        "body": (
            "<p>Hi Team,</p>"
            "<p>204 endpoints but zero location tracking. Need GET /vehicle/{id}/location, "
            "GET /vehicle/locations, POST for GPS pings from driver app, WebSocket for live "
            "streaming. Table stakes for any fleet product. Enables dispatch optimization, "
            "geofence alerts, customer ETAs.</p>"
            "<p>Regards,<br>Fleet Product</p>"
        ),
    },
    {
        "category": "feature",
        "subject": "Fuel tracking module has no anomaly detection for theft prevention",
        "body": (
            "<p>Hi Team,</p>"
            "<p>The fuel management endpoints only do basic CRUD. Zero anomaly detection. "
            "If a driver reports 80L fill-up on a 50L tank vehicle, the system accepts it. "
            "No way to detect fuel siphoning patterns, no alerts for consumption rates outside "
            "normal range, no cross-referencing with GPS mileage data. Fleet managers estimate "
            "8-12% fuel theft goes undetected.</p>"
            "<p>Need anomaly scoring on fuel entries, automated alerts, and fuel efficiency dashboard.</p>"
            "<p>Regards,<br>Fleet Operations</p>"
        ),
    },
    {
        "category": "feature",
        "subject": "Driver onboarding workflow is completely manual with no document verification",
        "body": (
            "<p>Hi Team,</p>"
            "<p>Adding a new driver requires 7 separate API calls with no workflow orchestration. "
            "If any step fails midway the driver record is in a broken state. No document expiry "
            "tracking - 23 drivers found operating with expired licenses last month.</p>"
            "<p>Need a POST /driver/onboard atomic workflow, document OCR extraction, expiry alerts, "
            "and automatic deactivation when documents expire.</p>"
            "<p>Regards,<br>Fleet HR</p>"
        ),
    },
    {
        "category": "feature",
        "subject": "Settlement cycle needs preview and driver dispute workflow",
        "body": (
            "<p>Hi Team,</p>"
            "<p>Settlement cycle has basic CRUD only. Managers cannot preview before finalizing. "
            "Drivers cannot see pending earnings/deductions. No dispute mechanism. No approval "
            "flow before finance.</p>"
            "<p>Need GET /settlementcycle/{id}/preview, POST /dispute, POST /approve endpoints.</p>"
            "<p>Regards,<br>Fleet Product</p>"
        ),
    },
    {
        "category": "feature",
        "subject": "Route planning API needed for optimizing daily delivery sequences",
        "body": (
            "<p>Hi Team,</p>"
            "<p>120 delivery vehicles do 15 stops/day. Drivers plan routes manually using Google Maps, "
            "wasting 20-30 minutes/day/driver. Need POST /route/optimize that accepts stop coordinates "
            "and returns optimal sequence considering traffic, time windows, vehicle capacity. "
            "Also need GET /route/{id}/progress for live tracking and automatic re-routing. "
            "Would save ~2400 driver-hours per month.</p>"
            "<p>Regards,<br>Fleet Logistics</p>"
        ),
    },
    {
        "category": "feature",
        "subject": "Emergency SOS feature needed in driver app with live location sharing",
        "body": (
            "<p>Hi Team,</p>"
            "<p>Two roadside incidents last quarter with no way to alert fleet managers in real-time. "
            "Need a panic button in driver app triggering POST /driver/{id}/sos with GPS, automatic "
            "notification to manager + emergency contacts, live location stream until cancelled, "
            "and nearest service center lookup. Some state transport authorities making this mandatory.</p>"
            "<p>Regards,<br>Fleet Safety</p>"
        ),
    },

    # ── IMPROVEMENTS ──────────────────────────────────────────────────────
    {
        "category": "improvement",
        "subject": "20 Fleet list endpoints return unbounded datasets - needs pagination",
        "body": (
            "<p>Hi Team,</p>"
            "<p>Several Fleet API list endpoints return ALL records without any pagination "
            "(GET /driverpenalty, GET /staffclock/History, GET /shift/List, "
            "GET /driverattendance/History and 16 others). A fleet with 500 drivers at "
            "2 shifts/day generates 365K records/year. Single GET call returns multi-MB JSON "
            "causing timeouts and frontend freezes. Need standard pagination (pageNumber, pageSize) "
            "on all 20 list endpoints. Blocking scale-up.</p>"
            "<p>Regards,<br>Fleet Engineering</p>"
        ),
    },
    {
        "category": "improvement",
        "subject": "No audit trail for vehicle status changes - compliance risk",
        "body": (
            "<p>Hi Team,</p>"
            "<p>When a vehicle status is changed via PUT /vehicle/{id}/status, there is no audit log. "
            "Cannot answer basic compliance questions: Who decommissioned vehicle #4521? When was it "
            "taken offline? Was it approved? The RTO audit flagged this as a major compliance gap.</p>"
            "<p>Need immutable audit_log table, GET /vehicle/{id}/audit-trail endpoint, and mandatory "
            "reason field on status change requests.</p>"
            "<p>Regards,<br>Fleet Compliance</p>"
        ),
    },
    {
        "category": "improvement",
        "subject": "Fleet API response times need SLA monitoring and alerting",
        "body": (
            "<p>Hi Team,</p>"
            "<p>We have no visibility into API response times. The maintenance endpoint took 38s "
            "to respond for weeks before anyone noticed. Need: a /health/metrics endpoint exposing "
            "p50/p95/p99 latencies per endpoint, Prometheus-compatible format, alert rules when "
            "p95 exceeds 2s, and a Grafana dashboard showing trends. Currently flying blind on "
            "API performance.</p>"
            "<p>Regards,<br>Fleet Platform</p>"
        ),
    },
    {
        "category": "improvement",
        "subject": "Driver and vehicle APIs should support bulk operations",
        "body": (
            "<p>Hi Team,</p>"
            "<p>Fleet onboarding and seasonal scaling requires creating/updating many drivers and "
            "vehicles at once. Currently requires individual API calls per record. Creating 50 drivers "
            "means 50 separate POST /driver calls. Need POST /driver/bulk-create, PUT /vehicle/bulk-update, "
            "and DELETE /driver/bulk-deactivate with batch progress tracking. Would reduce onboarding "
            "time from 2 hours to 5 minutes for a 50-driver fleet expansion.</p>"
            "<p>Regards,<br>Fleet Engineering</p>"
        ),
    },
]


def get_m365_token(tenant_db_name: str, connection_id: int) -> tuple:
    """Resolve M365 credentials from the tenant DB and obtain a Graph API token."""
    result = subprocess.run(
        ["sudo", "-u", "postgres", "psql", "-t", "-A", "-F", "|",
         "-d", tenant_db_name, "-c",
         f"SELECT config::text, secret_enc FROM ag_cred.connections "
         f"WHERE connection_id = {connection_id}"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"✗ psql error: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    line = result.stdout.strip()
    if not line or "|" not in line:
        print(f"✗ No M365 connection found with connection_id={connection_id}", file=sys.stderr)
        sys.exit(1)

    config_str, secret_enc = line.split("|", 1)
    config = json.loads(config_str)

    from core.security import decrypt_secret
    client_secret = decrypt_secret(secret_enc)

    import requests
    tid = config["tenant_id"]
    resp = requests.post(
        f"https://login.microsoftonline.com/{tid}/oauth2/v2.0/token",
        data={
            "client_id": config["client_id"],
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"], config.get("user_email", "")


def send_email(token: str, sender: str, recipient: str, subject: str, body: str) -> bool:
    """Send a single email via Microsoft Graph API. Returns True on success."""
    import requests
    url = f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body},
            "toRecipients": [{"emailAddress": {"address": recipient}}],
        }
    }
    r = requests.post(url, headers=headers, json=payload, timeout=15)
    return r.status_code == 202


def main():
    parser = argparse.ArgumentParser(
        description="Send test/seed emails into an M365 mailbox for bot testing"
    )
    parser.add_argument("--sender", default="support@storeglance.com",
                        help="Sender email address (must be in the M365 tenant)")
    parser.add_argument("--to", default="support@storeglance.com",
                        help="Recipient email address")
    parser.add_argument("--tenant-db", default="prod_agent_tenant_2a5fe12b",
                        help="Tenant database name")
    parser.add_argument("--conn-id", type=int, default=1,
                        help="ag_cred.connections.connection_id for M365")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print emails without sending")
    parser.add_argument("--count", type=int, default=0,
                        help="Number of emails to send (0 = all)")
    parser.add_argument("--category", choices=["bug", "feature", "improvement", "all"],
                        default="all", help="Filter by email category")
    parser.add_argument("--shuffle", action="store_true",
                        help="Randomize email order")
    args = parser.parse_args()

    # Filter by category
    pool = EMAIL_POOL if args.category == "all" else [
        e for e in EMAIL_POOL if e["category"] == args.category
    ]

    if args.shuffle:
        random.shuffle(pool)

    # Limit count
    if args.count > 0:
        pool = pool[:args.count]

    if not pool:
        print("No emails match the filter criteria.")
        sys.exit(0)

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Sending {len(pool)} email(s)")
    print(f"  From: {args.sender}")
    print(f"  To:   {args.to}")
    print()

    if not args.dry_run:
        token, _ = get_m365_token(args.tenant_db, args.conn_id)
        print("✓ Graph API token obtained\n")

    ok = 0
    fail = 0
    for i, email in enumerate(pool, 1):
        tag = email["category"].upper()[:3]
        subj = email["subject"]

        if args.dry_run:
            print(f"  {i:2d}. [{tag}] {subj[:70]}")
        else:
            success = send_email(token, args.sender, args.to, subj, email["body"])
            status = "✓" if success else "✗"
            print(f"  {i:2d}. {status} [{tag}] {subj[:65]}")
            if success:
                ok += 1
            else:
                fail += 1

    print()
    if args.dry_run:
        print(f"Dry run complete. {len(pool)} email(s) would be sent.")
    else:
        print(f"Done! {ok} sent, {fail} failed.")


if __name__ == "__main__":
    main()
