"""
Catalyst Training Co — Meta Ads Weekly Report
Pulls ad spend, cost per lead, and leads by campaign for the past 7 days.
"""

import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import requests

load_dotenv()

API_VERSION = "v19.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"


def _api_get(endpoint, params=None):
    """Make authenticated GET to Meta Graph API."""
    token = os.getenv("META_ACCESS_TOKEN")
    all_params = {"access_token": token}
    if params:
        all_params.update(params)
    r = requests.get(f"{BASE_URL}/{endpoint}", params=all_params, timeout=30)
    r.raise_for_status()
    return r.json()


def get_weekly_report(from_date=None, to_date=None):
    """Pull ad performance for a date range from Meta."""
    account_id = os.getenv("META_AD_ACCOUNT_ID")

    if not from_date or not to_date:
        today = datetime.now()
        week_ago = today - timedelta(days=7)
        from_date = week_ago.strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")

    time_range = f'{{"since":"{from_date}","until":"{to_date}"}}'

    report_data = {
        "period": f"{from_date} to {to_date}",
        "total_spend": 0.0,
        "total_leads": 0,
        "overall_cpl": 0.0,
        "total_impressions": 0,
        "total_clicks": 0,
        "total_reach": 0,
        "campaigns": [],
    }

    # Account-level insights
    try:
        account_data = _api_get(
            f"{account_id}/insights",
            {
                "time_range": time_range,
                "fields": "spend,impressions,clicks,reach,actions,cost_per_action_type",
            },
        )

        if account_data.get("data"):
            insight = account_data["data"][0]
            report_data["total_spend"] = float(insight.get("spend", 0))
            report_data["total_impressions"] = int(insight.get("impressions", 0))
            report_data["total_clicks"] = int(insight.get("clicks", 0))
            report_data["total_reach"] = int(insight.get("reach", 0))

            # Extract leads from actions
            for action in insight.get("actions", []):
                if action["action_type"] in (
                    "lead",
                    "offsite_conversion.fb_pixel_lead",
                    "onsite_conversion.lead_grouped",
                ):
                    report_data["total_leads"] += int(action["value"])

            if report_data["total_leads"] > 0:
                report_data["overall_cpl"] = (
                    report_data["total_spend"] / report_data["total_leads"]
                )
    except Exception as e:
        print(f"Warning: Account insights: {e}")

    # Campaign-level breakdown
    try:
        campaigns = _api_get(
            f"{account_id}/campaigns",
            {
                "fields": "name,status,objective",
                "effective_status": '["ACTIVE","PAUSED"]',
                "limit": 100,
            },
        )

        for campaign in campaigns.get("data", []):
            try:
                ci_data = _api_get(
                    f"{campaign['id']}/insights",
                    {
                        "time_range": time_range,
                        "fields": "spend,impressions,clicks,reach,actions,cost_per_action_type",
                    },
                )

                if not ci_data.get("data"):
                    continue

                ci = ci_data["data"][0]
                spend = float(ci.get("spend", 0))
                leads = 0

                for action in ci.get("actions", []):
                    if action["action_type"] in (
                        "lead",
                        "offsite_conversion.fb_pixel_lead",
                        "onsite_conversion.lead_grouped",
                    ):
                        leads += int(action["value"])

                cpl = spend / leads if leads > 0 else 0.0

                report_data["campaigns"].append(
                    {
                        "name": campaign["name"],
                        "status": campaign.get("status", ""),
                        "objective": campaign.get("objective", ""),
                        "spend": spend,
                        "leads": leads,
                        "cpl": cpl,
                        "impressions": int(ci.get("impressions", 0)),
                        "clicks": int(ci.get("clicks", 0)),
                        "reach": int(ci.get("reach", 0)),
                    }
                )
            except Exception:
                continue

    except Exception as e:
        print(f"Warning: Campaign insights: {e}")

    # Sort by spend descending
    report_data["campaigns"].sort(key=lambda c: c["spend"], reverse=True)
    return report_data


if __name__ == "__main__":
    data = get_weekly_report()
    print(f"\n--- Meta Ads Weekly Report ({data['period']}) ---")
    print(f"Total Spend:  ${data['total_spend']:,.2f}")
    print(f"Total Leads:  {data['total_leads']}")
    print(f"Overall CPL:  ${data['overall_cpl']:,.2f}")
    print(f"Impressions:  {data['total_impressions']:,}")
    print(f"Clicks:       {data['total_clicks']:,}")
    print(f"Reach:        {data['total_reach']:,}")

    if data["campaigns"]:
        print("\nBy Campaign:")
        for c in data["campaigns"]:
            print(
                f"  {c['name']}: ${c['spend']:,.2f} spend | "
                f"{c['leads']} leads | ${c['cpl']:,.2f} CPL | "
                f"{c['clicks']} clicks"
            )
