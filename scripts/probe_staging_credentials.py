#!/usr/bin/env python3
"""Destination-pinned, value-free provider capability diagnostics before arming.

Uses the existing Railway staging project token with its documented project
header. Never prints response bodies, header values, error messages or metadata.
"""

import json
import os
import subprocess
from pathlib import Path
import urllib.error
import urllib.request

PROJECT = "c613898d-bf03-43a6-8813-761f72e1c00a"
ENVIRONMENT = "05d1eac2-510d-4bd3-999e-fea9ead766b7"


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(text)
    temp.replace(path)


ENDPOINT = "https://backboard.railway.com/graphql/v2"
PROBES = {
    "project_token_identity": "query { projectToken { projectId environmentId } }"
}
CODES = {
    "UNAUTHENTICATED",
    "UNAUTHORIZED",
    "FORBIDDEN",
    "GRAPHQL_VALIDATION_FAILED",
    "INTERNAL_SERVER_ERROR",
    "BAD_USER_INPUT",
    "NOT_FOUND",
}
FIELDS = {"projectToken", "projectId", "environmentId"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Provider redirect refused")


def probe(token, opener=None):
    results = []
    opener = opener or urllib.request.build_opener(NoRedirect)
    for name, query in PROBES.items():
        result = {
            "probe": name,
            "http_status": None,
            "error_codes": [],
            "error_paths": [],
            "result": "BLOCKED",
        }
        try:
            request = urllib.request.Request(
                ENDPOINT,
                data=json.dumps({"query": query}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Project-Access-Token": token,
                },
                method="POST",
            )
            with opener.open(request, timeout=30) as response:
                result["http_status"] = response.status
                payload = json.load(response)
            errors = payload.get("errors") or []
            result["error_codes"] = sorted(
                {
                    code if code in CODES else "UNKNOWN"
                    for e in errors
                    for code in [e.get("extensions", {}).get("code", "UNKNOWN")]
                }
            )
            result["error_paths"] = [
                [
                    v if v in FIELDS else "*"
                    for v in e.get("path", [])
                    if isinstance(v, str)
                ]
                for e in errors
            ]
            env = (payload.get("data") or {}).get("projectToken") or {}
            if not errors and (
                env.get("projectId"),
                env.get("environmentId"),
            ) == (PROJECT, ENVIRONMENT):
                result["result"] = "VERIFIED"
            elif not errors:
                result["error_codes"] = ["DESTINATION_UNVERIFIED"]
            payload.clear()
        except urllib.error.HTTPError as error:
            result["http_status"] = error.code
            result["error_codes"] = ["HTTP_FAILURE"]
        except Exception as error:
            result["error_codes"] = ["TRANSPORT_OR_DECODE_FAILURE"]
        results.append(result)
    return {
        "schema_version": 1,
        "target": "staging",
        "secret_name": "STAGING_RAILWAY_TOKEN",
        "status": (
            "VERIFIED" if all(r["result"] == "VERIFIED" for r in results) else "BLOCKED"
        ),
        "probes": results,
        "production_accessed": False,
    }


def cli_probe():
    """Compare the pinned installed CLI without publishing arbitrary stderr."""
    result = {
        "probe": "railway_cli_staging_status",
        "exit_code": None,
        "result": "BLOCKED",
        "error_codes": [],
    }
    try:
        command = subprocess.run(
            [
                "railway",
                "status",
                "--project",
                PROJECT,
                "--environment",
                ENVIRONMENT,
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=40,
        )
        result["exit_code"] = command.returncode
        if command.returncode:
            stderr = command.stderr.lower()
            categories = {
                "authentication": "unauthorized",
                "scope": "forbidden",
                "cli_usage": "unexpected argument",
                "transport": "error sending request",
                "configuration": "no project linked",
            }
            result["error_codes"] = [
                name.upper()
                for name, fragment in categories.items()
                if fragment in stderr
            ] or ["CLI_FAILURE"]
        else:
            payload = json.loads(command.stdout)
            environments = [
                e["node"] for e in payload.get("environments", {}).get("edges", [])
            ]
            if (
                payload.get("id") == PROJECT
                and len(environments) == 1
                and environments[0].get("id") == ENVIRONMENT
                and environments[0].get("name") == "staging"
            ):
                result["result"] = "VERIFIED"
            else:
                result["error_codes"] = ["QUERY_OR_DESTINATION_UNVERIFIED"]
    except Exception:
        result["error_codes"] = ["CLI_UNAVAILABLE_OR_DECODE_FAILURE"]
    return result


def main():
    token = os.environ.get("RAILWAY_TOKEN")
    if not token:
        result = {
            "schema_version": 1,
            "target": "staging",
            "secret_name": "STAGING_RAILWAY_TOKEN",
            "status": "BLOCKED",
            "reason": "UNAVAILABLE",
            "production_accessed": False,
        }
    else:
        result = probe(token)
        cli = cli_probe()
        result["probes"].append(cli)
        if cli["result"] != "VERIFIED":
            result["status"] = "BLOCKED"
    atomic_write(
        Path("docs/agent/evidence/latest-staging-credential-probe.json"),
        json.dumps(result, indent=2) + "\n",
    )
    print(json.dumps(result))
    return 0 if result["status"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
