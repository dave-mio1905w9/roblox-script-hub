import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

try:
    import rbx_api as rbx_api
except ImportError:
    import rbx_api

def _cache_dir() -> Path:
    p = Path.home() / ".cache" / "hub-rbx"
    p.mkdir(parents=True, exist_ok=True)
    return p

def _token_path() -> Path:
    return _cache_dir() / "token"

def _scripts_path() -> Path:
    return _cache_dir() / "scripts.json"

def _load_cached() -> dict:
    p = _scripts_path()
    if not p.exists():
        return {}
    try:
        with open(p, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

def _save_cached(data: dict) -> None:
    with open(_scripts_path(), "w") as f:
        json.dump(data, f, indent=2)

def _read_token() -> str | None:
    p = _token_path()
    if p.exists():
        return p.read_text().strip()
    return os.environ.get("ROBLOX_API_KEY")

def _write_token(token: str) -> None:
    _token_path().write_text(token)

def _format_script(script: dict) -> str:
    parts = [
        f"[{script.get('scriptId', '?')}]",
        script.get("name", "untitled"),
        f"({script.get('scriptType', 'unknown')})",
    ]
    return " ".join(parts)

def do_fetch(args):
    token = args.token or _read_token()
    if not token:
        print("no token. set ROBLOX_API_KEY or use --token", file=sys.stderr)
        sys.exit(2)

    place_id = args.place_id
    if not place_id:
        print("need --place-id", file=sys.stderr)
        sys.exit(2)

    client = rbx_api.RbxClient(token)
    scripts = client.fetch_scripts(place_id)

    cache = _load_cached()
    old = cache.get(place_id, {}).get("scripts", [])
    old_by_id = {s["scriptId"]: s for s in old if "scriptId" in s}

    merged = []
    for s in scripts:
        sid = s.get("scriptId")
        if not args.force and sid and sid in old_by_id:
            old_s = old_by_id[sid]
            if old_s.get("source") == s.get("source"):
                s = old_s
        merged.append(s)

    cache[place_id] = {
        "fetched_at": time.time(),
        "scripts": merged,
    }
    _save_cached(cache)
    print(f"cached {len(merged)} scripts for place {place_id}")

def do_list(args):
    cache = _load_cached()
    if not cache:
        print("no cached data. run fetch first.")
        return

    for place_id, entry in cache.items():
        scripts = entry.get("scripts", [])
        print(f"place {place_id}: {len(scripts)} scripts")
        for s in scripts:
            print("  " + _format_script(s))

def do_grep(args):
    pattern = re.compile(args.pattern, re.IGNORECASE if args.ignore_case else 0)
    cache = _load_cached()

    if not cache:
        print("no cached data. run fetch first.")
        return

    hits = []
    for place_id, entry in cache.items():
        if args.place and place_id != args.place:
            continue
        for s in entry.get("scripts", []):
            content = s.get("source", "")
            if pattern.search(content):
                hits.append({"place_id": place_id, "script": s})

    if not hits:
        print("no matches")
        sys.exit(1)

    if args.json_output:
        print(json.dumps(hits, indent=2))
        return

    for h in hits:
        place_id = h["place_id"]
        s = h["script"]
        content = s.get("source", "")
        if args.show_source:
            for i, line in enumerate(content.splitlines(), 1):
                if pattern.search(line):
                    print(f"{place_id}/{s.get('name')}:{i}:{line}")
        else:
            print(f"{place_id}/{s.get('name')}")

def do_token(args):
    if args.set_token:
        _write_token(args.set_token)
        print("token saved")
    else:
        t = _read_token()
        if t:
            print(f"token: {t[:8]}...")
        else:
            print("no token set")

def main():
    parser = argparse.ArgumentParser(
        prog="hub",
        description="fetch and grep roblox scripts",
        usage="hub <command> [options]",
    )
    sub = parser.add_subparsers(dest="command")

    p_fetch = sub.add_parser("fetch", help="fetch scripts from a place")
    p_fetch.add_argument("--place-id", required=True)
    p_fetch.add_argument("--token", dest="token")
    p_fetch.add_argument("--force", action="store_true", help="refetch all scripts")

    p_list = sub.add_parser("list", help="list cached scripts")

    p_grep = sub.add_parser("grep", help="grep through cached scripts")
    p_grep.add_argument("pattern")
    p_grep.add_argument("-i", "--ignore-case", action="store_true")
    p_grep.add_argument("-n", "--show-source", action="store_true")
    p_grep.add_argument("--place", dest="place")
    p_grep.add_argument("--json", dest="json_output", action="store_true")

    p_token = sub.add_parser("token", help="manage api token")
    p_token.add_argument("--set", dest="set_token")

    args = parser.parse_args()

    if args.command == "fetch":
        do_fetch(args)
    elif args.command == "list":
        do_list(args)
    elif args.command == "grep":
        do_grep(args)
    elif args.command == "token":
        do_token(args)
    else:
        parser.print_usage()
        sys.exit(2)

if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        sys.exit(130)
