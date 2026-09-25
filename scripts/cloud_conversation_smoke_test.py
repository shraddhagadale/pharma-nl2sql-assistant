#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
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
                "the deployed model is temporarily unavailable; verify provider health "
                "and runtime configuration, then retry"
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
    *,
    include_sql: bool = False,
) -> dict[str, Any]:
    try:
        return request_json(
            opener,
            f"{base_url}/api/v1/chat",
            payload={
                "question": question,
                "conversation": conversation or [],
                "include_sql": include_sql,
            },
        )
    except RuntimeError as error:
        raise RuntimeError(f"{question!r}: {error}") from error


def run(base_url: str) -> None:
    ram = login(base_url, "U009")
    denied = ask(ram, base_url, "Show gross revenue last month.")
    assert denied["status"] == "denied", denied

    paid_demand = ask(ram, base_url, "Show paid demand for the last 3 months.")
    assert paid_demand["status"] == "answered", paid_demand
    assert paid_demand["rows"], paid_demand

    incomplete_market_share = ask(
        ram, base_url, "Show market share by territory for the last 3 months."
    )
    assert incomplete_market_share["status"] == "clarification", incomplete_market_share
    assert not incomplete_market_share["rows"], incomplete_market_share
    assert incomplete_market_share["sql"] is None, incomplete_market_share

    director = login(base_url, "U003")
    accounts = ask(
        director, base_url, "Rank the top 10 accounts by pack units last quarter."
    )
    assert accounts["status"] == "answered", accounts
    assert accounts["rows"], accounts

    prior = ask(director, base_url, "Show paid demand for the last 3 months.")
    follow_up = ask(
        director,
        base_url,
        "Give me from last month instead.",
        conversation=[
            {"role": "user", "content": "Show paid demand for the last 3 months."},
            {"role": "assistant", "content": prior["answer"]},
        ],
        include_sql=True,
    )
    assert follow_up["status"] == "answered", follow_up
    assert follow_up["sql"], follow_up
    normalized_answer = follow_up["answer"].casefold()
    assert any(
        phrase in normalized_answer
        for phrase in ("last month", "most recently completed full month")
    ), follow_up
    assert follow_up["rows"] != prior["rows"], follow_up
    assert re.search(r"(?:\b\w+\.)?mo_offset\s*=", follow_up["sql"].casefold()), (
        follow_up
    )

    executive = login(base_url, "U001")
    revenue = ask(executive, base_url, "Show gross revenue last month.")
    assert revenue["status"] == "answered", revenue
    assert revenue["rows"], revenue

    market_share = ask(
        executive, base_url, "Show Zenovax market share for the last 3 months."
    )
    assert market_share["status"] == "answered", market_share

    print(
        "Cloud conversation gate passed: RAM denial, paid demand, and market-share "
        "clarification; director top accounts and marker-free follow-up; executive "
        "revenue and product-specific market share."
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
