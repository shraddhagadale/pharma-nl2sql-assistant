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
    payload: dict[str, Any] | None = None,
) -> Any:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method="POST" if body else "GET",
        headers={"Content-Type": "application/json"} if body else {},
    )
    try:
        with opener.open(request, timeout=60) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        if error.code == 503:
            raise RuntimeError(
                "the deployed model is unavailable; configure openai_api_key in the "
                "application runtime secret and redeploy"
            ) from error
        raise AssertionError(
            f"{request.method} {url} returned {error.code}: {detail}"
        ) from error
    return json.loads(raw) if raw else None


def login(base_url: str, user_id: str) -> urllib.request.OpenerDirector:
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar())
    )
    user = request_json(
        opener,
        f"{base_url}/api/v1/demo/session",
        payload={"user_id": user_id},
    )
    assert user["user_id"] == user_id
    return opener


def ask(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    question: str,
    conversation: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return request_json(
        opener,
        f"{base_url}/api/v1/chat",
        payload={
            "question": question,
            "conversation": conversation or [],
            "include_sql": False,
        },
    )


def run(base_url: str) -> None:
    ram = login(base_url, "U009")
    denied = ask(ram, base_url, "Show gross revenue last month.")
    assert denied["status"] == "denied"

    paid_demand = ask(ram, base_url, "Show paid demand for the last 3 months.")
    assert paid_demand["status"] == "answered"
    assert paid_demand["rows"]

    director = login(base_url, "U003")
    accounts = ask(
        director, base_url, "Rank the top accounts by pack units last quarter."
    )
    assert accounts["status"] == "answered"
    assert accounts["rows"]

    follow_up = ask(
        director,
        base_url,
        "What about last month?",
        conversation=[
            {"role": "user", "content": "Show paid demand for the last 3 months."},
            {"role": "assistant", "content": "The validated result was returned."},
        ],
    )
    assert follow_up["status"] == "answered"

    executive = login(base_url, "U001")
    revenue = ask(executive, base_url, "Show gross revenue last month.")
    assert revenue["status"] == "answered"
    assert revenue["rows"]

    market_share = ask(executive, base_url, "Show market share for the last 3 months.")
    assert market_share["status"] == "answered"

    print(
        "Cloud conversation gate passed: RAM denial and paid demand, director top "
        "accounts and follow-up, executive revenue, and market share."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the live model-backed cloud product gate"
    )
    parser.add_argument("base_url", nargs="?", default="http://localhost:3000")
    args = parser.parse_args()
    try:
        run(args.base_url.rstrip("/"))
    except (AssertionError, OSError, RuntimeError, ValueError) as error:
        print(f"Cloud conversation gate failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
