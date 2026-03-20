"""
Catalyst Training Co — Xero OAuth2 Authentication
Run this once to authorize and save tokens. Tokens auto-refresh after that.
"""

import os
import json
import base64
from urllib.parse import urlencode
from flask import Flask, redirect, request
from dotenv import load_dotenv
import requests as http_requests

load_dotenv()

app = Flask(__name__)
TOKEN_FILE = os.path.join(os.path.dirname(__file__), ".xero_tokens.json")

CLIENT_ID = os.getenv("XERO_CLIENT_ID")
CLIENT_SECRET = os.getenv("XERO_CLIENT_SECRET")
REDIRECT_URI = os.getenv("XERO_REDIRECT_URI", "http://localhost:8080/callback")

SCOPES = [
    "offline_access",
    "openid",
    "profile",
    "email",
    "accounting.reports.profitandloss.read",
    "accounting.invoices.read",
    "accounting.banktransactions.read",
    "accounting.contacts.read",
    "accounting.settings.read",
]


@app.route("/")
def login():
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
    }
    auth_url = f"https://login.xero.com/identity/connect/authorize?{urlencode(params)}"
    return redirect(auth_url)


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Error: No authorization code received", 400

    try:
        # Exchange code for tokens via direct POST
        credentials = base64.b64encode(
            f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
        ).decode()

        token_response = http_requests.post(
            "https://identity.xero.com/connect/token",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
        )
        token_response.raise_for_status()
        token = token_response.json()

        # Get tenant ID via connections endpoint
        connections_response = http_requests.get(
            "https://api.xero.com/connections",
            headers={
                "Authorization": f"Bearer {token['access_token']}",
                "Content-Type": "application/json",
            },
        )
        connections_response.raise_for_status()
        connections = connections_response.json()
        tenant_id = connections[0]["tenantId"] if connections else "UNKNOWN"

        token_data = {
            "access_token": token.get("access_token"),
            "refresh_token": token.get("refresh_token"),
            "token_type": token.get("token_type"),
            "expires_in": token.get("expires_in"),
            "tenant_id": str(tenant_id),
        }

        with open(TOKEN_FILE, "w") as f:
            json.dump(token_data, f, indent=2)

        return f"""
        <h1>Xero Connected!</h1>
        <p>Tenant ID: <strong>{tenant_id}</strong></p>
        <p>Tokens saved. Add this tenant ID to your .env as XERO_TENANT_ID</p>
        <p>You can close this window.</p>
        """
    except Exception as e:
        return f"<h1>Error</h1><pre>{e}</pre>", 500


if __name__ == "__main__":
    print("Visit http://localhost:8080 to authorize Xero")
    app.run(host="127.0.0.1", port=8080)
