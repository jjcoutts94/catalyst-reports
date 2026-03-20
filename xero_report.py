"""
Catalyst Training Co — Xero Weekly Revenue Report
Pulls revenue, expenses, and net position for the past 7 days.
"""

import os
import json
import base64
from datetime import datetime, timedelta
from dotenv import load_dotenv
import requests

load_dotenv()

TOKEN_FILE = os.path.join(os.path.dirname(__file__), ".xero_tokens.json")


def _load_tokens():
    """Load OAuth2 tokens from file or XERO_TOKENS env var."""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return json.load(f)
    # Fall back to env var (for Railway/cloud deployment)
    env_tokens = os.getenv("XERO_TOKENS")
    if env_tokens:
        return json.loads(env_tokens)
    raise FileNotFoundError(
        f"No token file at {TOKEN_FILE} and no XERO_TOKENS env var. Run xero_auth.py first."
    )


def _save_tokens(tokens):
    """Save refreshed tokens back to file and update env var."""
    try:
        with open(TOKEN_FILE, "w") as f:
            json.dump(tokens, f, indent=2)
    except OSError:
        pass  # Read-only filesystem in cloud — tokens still in memory
    os.environ["XERO_TOKENS"] = json.dumps(tokens)


def _refresh_token(token_data):
    """Refresh the access token using the refresh token."""
    client_id = os.getenv("XERO_CLIENT_ID")
    client_secret = os.getenv("XERO_CLIENT_SECRET")
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    response = requests.post(
        "https://identity.xero.com/connect/token",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": token_data["refresh_token"],
        },
    )
    response.raise_for_status()
    new_tokens = response.json()

    token_data["access_token"] = new_tokens["access_token"]
    token_data["refresh_token"] = new_tokens.get(
        "refresh_token", token_data["refresh_token"]
    )
    _save_tokens(token_data)
    return token_data


def _api_get(endpoint, token_data, params=None):
    """Make authenticated GET request to Xero API, refreshing token if needed."""
    tenant_id = os.getenv("XERO_TENANT_ID") or token_data.get("tenant_id")
    headers = {
        "Authorization": f"Bearer {token_data['access_token']}",
        "Xero-Tenant-Id": tenant_id,
        "Accept": "application/json",
    }

    response = requests.get(
        f"https://api.xero.com/api.xro/2.0/{endpoint}",
        headers=headers,
        params=params or {},
        timeout=30,
    )

    # If unauthorized, refresh and retry
    if response.status_code == 401:
        token_data = _refresh_token(token_data)
        headers["Authorization"] = f"Bearer {token_data['access_token']}"
        response = requests.get(
            f"https://api.xero.com/api.xro/2.0/{endpoint}",
            headers=headers,
            params=params or {},
            timeout=30,
        )

    response.raise_for_status()
    return response.json()


def get_weekly_report(from_date=None, to_date=None):
    """Pull Profit & Loss for a date range from Xero."""
    token_data = _load_tokens()

    if not from_date or not to_date:
        today = datetime.now()
        week_ago = today - timedelta(days=7)
        from_date = week_ago.strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")

    pl = _api_get(
        "Reports/ProfitAndLoss",
        token_data,
        params={"fromDate": from_date, "toDate": to_date},
    )

    report_data = {
        "period": f"{from_date} to {to_date}",
        "revenue": 0.0,
        "expenses": 0.0,
        "net_position": 0.0,
        "revenue_breakdown": [],
        "expense_breakdown": [],
    }

    if pl and "Reports" in pl and pl["Reports"]:
        report = pl["Reports"][0]
        for section in report.get("Rows", []):
            section_title = section.get("Title", "")
            rows = section.get("Rows", [])

            if "Income" in section_title or "Revenue" in section_title:
                for row in rows:
                    cells = row.get("Cells", [])
                    if len(cells) >= 2:
                        name = cells[0].get("Value", "")
                        amount = _parse_amount(cells[1].get("Value"))
                        if name and amount != 0:
                            report_data["revenue_breakdown"].append(
                                {"name": name, "amount": amount}
                            )
                            report_data["revenue"] += amount

            elif "Expense" in section_title or "Operating" in section_title:
                for row in rows:
                    cells = row.get("Cells", [])
                    if len(cells) >= 2:
                        name = cells[0].get("Value", "")
                        amount = _parse_amount(cells[1].get("Value"))
                        if name and amount != 0:
                            report_data["expense_breakdown"].append(
                                {"name": name, "amount": amount}
                            )
                            report_data["expenses"] += amount

    report_data["net_position"] = report_data["revenue"] - report_data["expenses"]
    return report_data


def _parse_amount(value):
    """Parse a string amount to float, handling currency symbols."""
    if not value:
        return 0.0
    cleaned = str(value).replace(",", "").replace("$", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


if __name__ == "__main__":
    data = get_weekly_report()
    print(f"\n--- Xero Weekly Report ({data['period']}) ---")
    print(f"Revenue:      ${data['revenue']:,.2f}")
    print(f"Expenses:     ${data['expenses']:,.2f}")
    print(f"Net Position: ${data['net_position']:,.2f}")

    if data["revenue_breakdown"]:
        print("\nRevenue Breakdown:")
        for item in data["revenue_breakdown"]:
            print(f"  {item['name']}: ${item['amount']:,.2f}")

    if data["expense_breakdown"]:
        print("\nExpense Breakdown:")
        for item in data["expense_breakdown"]:
            print(f"  {item['name']}: ${item['amount']:,.2f}")
