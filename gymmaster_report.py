"""
Catalyst Training Co — GymMaster Weekly Report
Pulls prospects, memberships, trials, classes, PT sessions,
churn, revenue, failed payments, and casual sales.
"""

import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import requests

load_dotenv()


def _api_post(endpoint, payload):
    """Make authenticated POST to GymMaster Reporting API."""
    base_url = os.getenv("GYMMASTER_API_URL", "").rstrip("/")
    headers = {
        "X-GM-API-KEY": os.getenv("GYMMASTER_API_KEY"),
        "Content-Type": "application/json",
    }
    r = requests.post(
        f"{base_url}/{endpoint.lstrip('/')}",
        headers=headers,
        json=payload,
        timeout=60,
    )
    r.raise_for_status()
    return r.json().get("result", [])


def _run_report(report_id, start_date, end_date):
    """Run a GymMaster standard report."""
    return _api_post(
        "api/v2/report/standard_report",
        {
            "start_date": start_date,
            "end_date": end_date,
            "report_id": report_id,
            "company_id": None,
        },
    )


def _parse_dollar(value):
    """Parse '$1,234.56' to float."""
    if not value:
        return 0.0
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def get_weekly_report(from_date=None, to_date=None):
    """Pull all metrics from GymMaster for a date range."""
    if not from_date or not to_date:
        today = datetime.now()
        week_ago = today - timedelta(days=7)
        from_date = week_ago.strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")
    start = from_date
    end = to_date

    report = {
        "period": f"{start} to {end}",
        "prospects_total": 0,
        "prospects_excl_fp": 0,
        "prospects_fp": 0,
        "prospect_names": [],
        "new_memberships": 0,
        "new_membership_list": [],
        "new_trials": 0,
        "trial_list": [],
        "class_count": 0,
        "class_avg_attendance": 0.0,
        "class_total_checkins": 0,
        "pt_sessions_total": 0,
        "pt_breakdown": [],
        "churned": 0,
        "churn_reasons": [],
        "active_members": 0,
        "churn_rate": 0.0,
        "revenue_total": 0.0,
        "revenue_by_type": {},
        "failed_payments_count": 0,
        "failed_payments_amount": 0.0,
        "casual_sales": 0.0,
        "other_sales": 0.0,
    }

    # --- 1. Prospects (report 30) — exclude Fitness Passport ---
    try:
        prospects = _run_report(30, start, end)
        report["prospects_total"] = len(prospects)
        non_fp = [
            p for p in prospects
            if (p.get("Member Source Promotion") or "") != "Fitness Passport Member"
        ]
        report["prospects_excl_fp"] = len(non_fp)
        report["prospects_fp"] = report["prospects_total"] - report["prospects_excl_fp"]
        report["prospect_names"] = [
            {
                "name": p.get("Member Name", ""),
                "source": p.get("Member Source Promotion") or "Direct",
            }
            for p in non_fp
        ]
    except Exception as e:
        print(f"Warning: Prospects: {e}")

    # --- 2. New Memberships (report 315) ---
    try:
        memberships = _run_report(315, start, end)
        report["new_memberships"] = len(memberships)
        report["new_membership_list"] = [
            {
                "name": m.get("Member Name", ""),
                "type": m.get("Membership Type Name", ""),
                "fee": m.get("Membership Fee", ""),
                "rejoin": m.get("Rejoin") == "Rejoin",
            }
            for m in memberships
        ]
        # Trials from new memberships
        trial_keywords = ["catalyst signature experience", "drop in"]
        trials = [
            m for m in memberships
            if any(kw in (m.get("Membership Type Name") or "").lower() for kw in trial_keywords)
        ]
        report["new_trials"] = len(trials)
        report["trial_list"] = [
            {"name": t.get("Member Name", ""), "type": t.get("Membership Type Name", "")}
            for t in trials
        ]
    except Exception as e:
        print(f"Warning: New Memberships: {e}")

    # --- 3. Class Summary (report 341) ---
    try:
        classes = _run_report(341, start, end)
        report["class_count"] = len(classes)
        total_checkins = sum(c.get("Number Checked In", 0) for c in classes)
        report["class_total_checkins"] = total_checkins
        if classes:
            report["class_avg_attendance"] = round(total_checkins / len(classes), 1)
    except Exception as e:
        print(f"Warning: Classes: {e}")

    # --- 4. PT / 1-on-1 Sessions (report 3) ---
    try:
        pt = _run_report(3, start, end)
        total_sessions = sum(row.get("Session Count", 0) for row in pt)
        report["pt_sessions_total"] = total_sessions
        # Aggregate by trainer
        trainer_totals = {}
        for row in pt:
            name = row.get("Trainer Name", "")
            if name not in trainer_totals:
                trainer_totals[name] = {"sessions": 0, "no_shows": 0}
            trainer_totals[name]["sessions"] += row.get("Session Count", 0)
            trainer_totals[name]["no_shows"] += row.get("No Shows", 0)
        report["pt_breakdown"] = [
            {"trainer": name, "sessions": vals["sessions"], "no_shows": vals["no_shows"]}
            for name, vals in trainer_totals.items()
        ]
    except Exception as e:
        print(f"Warning: PT Sessions: {e}")

    # --- 4b. Trial bookings from Trainer Bookings (report 310) ---
    try:
        trainer_bookings = _run_report(310, start, end)
        trial_keywords = ["catalyst signature experience", "drop in"]
        trial_bookings = [
            b for b in trainer_bookings
            if any(kw in (b.get("Membership Type") or "").lower() for kw in trial_keywords)
        ]
        # Get unique trial members (not already counted)
        existing_trial_names = {t["name"] for t in report["trial_list"]}
        seen = set()
        for tb in trial_bookings:
            name = tb.get("Member Name", "")
            if name not in existing_trial_names and name not in seen:
                seen.add(name)
                report["trial_list"].append(
                    {"name": name, "type": tb.get("Membership Type", "")}
                )
        report["new_trials"] = len(report["trial_list"])
    except Exception as e:
        print(f"Warning: Trial Bookings: {e}")

    # --- 5. Cancellations / Churn (report 327) ---
    try:
        cancellations = _run_report(327, start, end)
        # Exclude cancellations due to membership change (upgrades/downgrades)
        real_cancellations = [
            c for c in cancellations
            if not c.get("Canceled due to membership change")
        ]
        report["churned"] = len(real_cancellations)
        report["churn_reasons"] = [
            {
                "name": c.get("Member Name", ""),
                "type": c.get("Membership Type Name", ""),
                "reason": c.get("Cancel Reason") or c.get("Membership Feedback") or "Not specified",
            }
            for c in real_cancellations
        ]
    except Exception as e:
        print(f"Warning: Cancellations: {e}")

    # --- 6. Active Members (KPI) ---
    try:
        kpi = _api_post(
            "api/v2/report/kpi/fields",
            {
                "date": {"start": start, "end": end},
                "selected_fields": ["current_members", "member_churn_percentage"],
                "company_id": None,
            },
        )
        if isinstance(kpi, dict):
            cm = kpi.get("current_members", {})
            report["active_members"] = cm.get("value", 0) if isinstance(cm, dict) else 0
            churn = kpi.get("member_churn_percentage", {})
            report["churn_rate"] = churn.get("value", 0) if isinstance(churn, dict) else 0
    except Exception as e:
        print(f"Warning: KPI: {e}")

    # --- 7. Revenue / All Sales (report 14) ---
    try:
        sales = _run_report(14, start, end)
        for s in sales:
            amount = s.get("sorted_Sale Amount (Incl Tax)", 0) or 0
            sale_type = (s.get("Sale Type") or "").lower()
            description = (s.get("Sale Description") or "").lower()

            report["revenue_total"] += amount

            # Categorise
            type_key = s.get("Sale Type") or "Other"
            report["revenue_by_type"][type_key] = (
                report["revenue_by_type"].get(type_key, 0) + amount
            )

            # Casual visits
            if "casual" in description or "casual" in sale_type:
                report["casual_sales"] += amount

        # Other sales = non-billing, non-casual
        report["other_sales"] = sum(
            v for k, v in report["revenue_by_type"].items()
            if k.lower() not in ("billing",)
        )
    except Exception as e:
        print(f"Warning: Sales: {e}")

    # --- 8. Failed Payments (report 311) ---
    try:
        failed = _run_report(311, start, end)
        report["failed_payments_count"] = len(failed)
        report["failed_payments_amount"] = sum(
            f.get("sorted_Amount", 0) or 0 for f in failed
        )
    except Exception as e:
        print(f"Warning: Failed Payments: {e}")

    return report


if __name__ == "__main__":
    data = get_weekly_report()
    print(f"\n{'='*55}")
    print(f" GYMMASTER WEEKLY REPORT ({data['period']})")
    print(f"{'='*55}")

    print(f"\n--- Prospects ---")
    print(f"  Total (excl Fitness Passport): {data['prospects_excl_fp']}")
    print(f"  Fitness Passport:              {data['prospects_fp']}")
    for p in data["prospect_names"]:
        print(f"    - {p['name']} ({p['source']})")

    print(f"\n--- Memberships ---")
    print(f"  New Memberships: {data['new_memberships']}")
    for m in data["new_membership_list"]:
        rejoin = " (Rejoin)" if m["rejoin"] else ""
        print(f"    - {m['name']}: {m['type']} @ {m['fee']}{rejoin}")

    print(f"\n--- Trials ---")
    print(f"  New Trials: {data['new_trials']}")
    for t in data["trial_list"]:
        print(f"    - {t['name']}: {t['type']}")

    print(f"\n--- Classes ---")
    print(f"  Classes Run:        {data['class_count']}")
    print(f"  Total Check-ins:    {data['class_total_checkins']}")
    print(f"  Avg Attendance:     {data['class_avg_attendance']}")

    print(f"\n--- 1-on-1 Training ---")
    print(f"  Total Sessions: {data['pt_sessions_total']}")
    for pt in data["pt_breakdown"]:
        print(f"    - {pt['trainer']}: {pt['sessions']} sessions ({pt['no_shows']} no-shows)")

    print(f"\n--- Churn ---")
    print(f"  Active Members: {data['active_members']}")
    print(f"  Churned:        {data['churned']}")
    print(f"  Churn Rate:     {data['churn_rate']}%")
    for c in data["churn_reasons"]:
        print(f"    - {c['name']} ({c['type']}): {c['reason']}")

    print(f"\n--- Revenue ---")
    print(f"  Total Revenue:  ${data['revenue_total']:,.2f}")
    for rtype, amount in data["revenue_by_type"].items():
        print(f"    - {rtype}: ${amount:,.2f}")

    print(f"\n--- Failed Payments ---")
    print(f"  Count:  {data['failed_payments_count']}")
    print(f"  Amount: ${data['failed_payments_amount']:,.2f}")

    print(f"\n--- Other Sales ---")
    print(f"  Casual Sales: ${data['casual_sales']:,.2f}")
    print(f"  Other Sales:  ${data['other_sales']:,.2f}")
