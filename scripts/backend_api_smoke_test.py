#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from typing import Any


def request_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    expected_status: int = 200,
) -> Any:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body else {},
    )
    try:
        with opener.open(request, timeout=10) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as error:
        status = error.code
        raw = error.read()

    if status != expected_status:
        detail = raw.decode("utf-8", errors="replace")[:500]
        raise AssertionError(
            f"{method} {url} returned {status}, expected {expected_status}: {detail}"
        )
    return json.loads(raw) if raw else None


def session_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def user_overview(base_url: str, user_id: str) -> dict[str, Any]:
    opener = session_opener()
    user = request_json(
        opener,
        f"{base_url}/api/v1/demo/session",
        method="POST",
        payload={"user_id": user_id},
    )
    assert user["user_id"] == user_id

    current_user = request_json(opener, f"{base_url}/api/v1/demo/session")
    assert current_user == user

    overview = request_json(opener, f"{base_url}/api/v1/analytics/overview?months=3")
    assert overview["user"] == user
    assert overview["period_months"] == 3
    assert len(overview["assumptions"]) == 3
    return overview


def run(base_url: str) -> None:
    anonymous = session_opener()
    assert request_json(anonymous, f"{base_url}/health") == {"status": "ok"}
    assert request_json(anonymous, f"{base_url}/ready") == {"status": "ready"}

    users = request_json(anonymous, f"{base_url}/api/v1/demo/users")
    assert {"U001", "U003", "U009"}.issubset({user["user_id"] for user in users})

    request_json(
        anonymous,
        f"{base_url}/api/v1/analytics/overview",
        expected_status=401,
    )
    request_json(
        anonymous,
        f"{base_url}/api/v1/demo/session",
        method="POST",
        payload={"user_id": "UNKNOWN"},
        expected_status=404,
    )
    request_json(
        anonymous,
        f"{base_url}/api/v1/demo/session",
        method="POST",
        payload={"user_id": "U009", "role": "exec"},
        expected_status=422,
    )

    ram = user_overview(base_url, "U009")
    director = user_overview(base_url, "U003")
    executive = user_overview(base_url, "U001")

    assert ram["user"]["role"] == "ram"
    assert ram["user"]["territory_name"] == "New York Metro"
    assert ram["revenue_visible"] is False
    assert ram["revenue"] is None

    assert director["user"]["role"] == "director"
    assert director["user"]["region_name"] == "Northeast"
    assert director["user"]["territory_name"] is None
    assert director["revenue_visible"] is False
    assert director["revenue"] is None

    assert executive["user"]["role"] == "exec"
    assert executive["revenue_visible"] is True
    assert executive["revenue"] is not None

    assert 0 <= ram["organization_count"] <= director["organization_count"]
    assert director["organization_count"] <= executive["organization_count"]
    assert 0 <= ram["transaction_count"] <= director["transaction_count"]
    assert director["transaction_count"] <= executive["transaction_count"]

    print(
        "Backend API smoke test passed: "
        f"RAM={ram['organization_count']} orgs, "
        f"director={director['organization_count']} orgs, "
        f"exec={executive['organization_count']} orgs; "
        "limited-role revenue hidden and executive revenue visible."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify sessions, API-visible RLS scope, and WAC response behavior"
    )
    parser.add_argument("base_url", nargs="?", default="http://localhost:8000")
    args = parser.parse_args()
    try:
        run(args.base_url.rstrip("/"))
    except (AssertionError, OSError, ValueError) as error:
        print(f"Backend API smoke test failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
