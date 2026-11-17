"""
Standalone login health check — used by .github/workflows/check-login.yml.

Does NOT reuse any cached token: it performs a fresh login every run, so it
catches cases where the site changed its login endpoint/payload/headers
(which has happened before and silently broke the main scraper).

Writes status.json in the shields.io "endpoint badge" schema:
https://shields.io/badges/endpoint-badge
"""
import json
import os
import sys

from curl_cffi import requests as cffi_requests

STATUS_FILE = "status.json"

COLORS = {
    "ok": "brightgreen",
    "captcha": "yellow",
    "failing": "red",
}

MESSAGES = {
    "ok": "passing",
    "captcha": "captcha required",
    "failing": "failing",
}


def write_status(state):
    payload = {
        "schemaVersion": 1,
        "label": "login",
        "message": MESSAGES[state],
        "color": COLORS[state],
    }
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"status -> {state} ({MESSAGES[state]})")


def response_needs_captcha(response):
    try:
        data = response.json()
    except Exception:
        return False
    blob = json.dumps(data).lower()
    return "captcha" in blob or "turnstile" in blob


def apply_tokens(session, token_v2):
    if "__cf_bm" not in session.cookies.get_dict():
        session.get("https://privacy.com.br/", impersonate="chrome142")
    response = session.get(
        "https://privacy.com.br/strangler/Authorize",
        params={"TokenV2": token_v2, "ReturnUrl": "/"},
        headers={
            "Host": "privacy.com.br",
            "Referer": "https://privacy.com.br/auth?route=sign-in",
            "Accept": "application/json, text/plain, */*",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        },
        impersonate="chrome142"
    )
    return response.status_code == 200


def try_login(email, password):
    session = cffi_requests.Session()

    if "__cf_bm" not in session.cookies.get_dict():
        session.get("https://privacy.com.br/", impersonate="chrome142")

    payload = {
        "Email": email,
        "Document": None,
        "Password": password,
        "Locale": "pt-BR",
        "CanReceiveEmail": True,
        "ProfileName": "",
        "ClientSignals": {
            "Screen": "1920x1080@1",
            "WebglVendor": "Google Inc. (Google)",
            "WebglRenderer": "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)"
        }
    }

    response = session.post(
        "https://service.privacy.com.br/auth/identity/login",
        data=json.dumps(payload),
        headers={
            "Host": "service.privacy.com.br",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pt-BR",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Priority": "u=1, i",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
            "Sec-CH-UA": '"Not-A.Brand";v="99", "Chromium";v="142", "Google Chrome";v="142"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
            "Sec-Fetch-Site": "same-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Sec-GPC": "1",
            "Origin": "https://privacy.com.br",
            "Referer": "https://privacy.com.br/",
        },
        impersonate="chrome142"
    )

    if response.status_code == 200:
        token = response.json().get("token")
        if token and apply_tokens(session, token):
            return "ok"
        return "failing"

    if response_needs_captcha(response):
        return "captcha"

    print(f"login failed: status={response.status_code} body={response.text[:300]!r}")
    return "failing"


def main():
    email = os.getenv("PRIVACY_EMAIL")
    password = os.getenv("PRIVACY_PASSWORD")
    if not email or not password:
        print("PRIVACY_EMAIL/PRIVACY_PASSWORD not set")
        write_status("failing")
        sys.exit(1)

    try:
        state = try_login(email, password)
    except Exception as e:
        print(f"unexpected error: {e!r}")
        state = "failing"

    write_status(state)
    sys.exit(0 if state == "ok" else 1)


if __name__ == "__main__":
    main()
