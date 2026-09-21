#!/usr/bin/env python3
"""Maintenance access to Nova's Firestore data, over the plain REST API.

Why this is a tool and not a screen in the app
----------------------------------------------
Every document in `leaderboard` and `progress` is keyed by the SYNC CODE,
and the sync code IS the account - anyone holding one can link a device
and read or overwrite that person's progress. This project's rules are
open (the app writes with no sign-in at all), so a "username -> code"
lookup shipped inside index.html would be a lookup every one of the ~40
classmates could run against everybody else. It lives out here instead,
where only whoever has the repo can run it.

Usage
-----
  python3 tools/firestore-admin.py list
  python3 tools/firestore-admin.py find <username>
  python3 tools/firestore-admin.py purge --yes
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

PROJECT = "class-26e-study-drill"
BASE = ("https://firestore.googleapis.com/v1/projects/%s"
        "/databases/(default)/documents" % PROJECT)
COLLECTIONS = ("leaderboard", "progress", "vrooms")


def _call(method, url, timeout=30):
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _plain(fields):
    """Firestore's typed values, flattened to something printable."""
    out = {}
    for key, val in (fields or {}).items():
        if "stringValue" in val:
            out[key] = val["stringValue"]
        elif "integerValue" in val:
            out[key] = int(val["integerValue"])
        elif "doubleValue" in val:
            out[key] = float(val["doubleValue"])
        elif "booleanValue" in val:
            out[key] = val["booleanValue"]
        elif "nullValue" in val:
            out[key] = None
        else:
            out[key] = "<%s>" % ",".join(val.keys())
    return out


def docs(collection, mask=None):
    """Every document in a collection, paged. Returns [(code, fields)]."""
    found, token = [], None
    while True:
        qs = {"pageSize": "300"}
        if token:
            qs["pageToken"] = token
        if mask:
            qs["mask.fieldPaths"] = mask
        url = "%s/%s?%s" % (BASE, collection, urllib.parse.urlencode(qs))
        status, body = _call("GET", url)
        if status != 200:
            sys.stderr.write("GET %s -> %s\n%s\n" % (collection, status, body))
            sys.exit(1)
        data = json.loads(body) if body.strip() else {}
        for d in data.get("documents", []):
            found.append((d["name"].rsplit("/", 1)[-1], _plain(d.get("fields"))))
        token = data.get("nextPageToken")
        if not token:
            return found


def cmd_list():
    for coll in COLLECTIONS:
        rows = docs(coll)
        print("\n%s - %d document(s)" % (coll, len(rows)))
        for code, fields in sorted(rows):
            name = fields.get("firstName") or fields.get("host") or ""
            extra = {k: v for k, v in fields.items()
                     if k in ("level", "badges", "hundos", "correct", "points")}
            print("  %-10s %-16s %s" % (code, name, extra or ""))
    return 0


def cmd_find(query):
    """The lookup: a username in, that person's sync code out."""
    want = query.strip().lower()
    entries = docs("leaderboard")
    hits = [(c, f) for c, f in entries
            if (f.get("firstName") or "").strip().lower() == want]
    if not hits:
        hits = [(c, f) for c, f in entries
                if want and want in (f.get("firstName") or "").strip().lower()]
        if not hits:
            print("No rankings entry for %r." % query)
            print("Only people opted in to the rankings appear here - someone")
            print("hidden has no entry to look up.")
            return 1
        print("No exact match. Close ones:")
    for code, fields in hits:
        print("  %s  ->  %s" % (fields.get("firstName", "?"), code))
    if len(hits) > 1:
        print("\nMore than one match - usernames are not unique, so check the")
        print("level/hundos against what the person tells you before handing")
        print("a code over.")
    return 0


def cmd_purge(confirmed):
    if not confirmed:
        print("This deletes EVERY document in: %s" % ", ".join(COLLECTIONS))
        print("Re-run with --yes to actually do it.")
        return 1
    total = 0
    for coll in COLLECTIONS:
        rows = docs(coll, mask="__name__")
        if not rows:
            print("  %-12s (already empty)" % coll)
        for code, _ in rows:
            url = "%s/%s/%s" % (BASE, coll, urllib.parse.quote(code, safe=""))
            status, body = _call("DELETE", url)
            ok = status == 200
            total += 1 if ok else 0
            print("  %-12s %-10s %s"
                  % (coll, code, "deleted" if ok else body.strip()[:120]))
    print("\n%d document(s) deleted." % total)
    for coll in COLLECTIONS:
        print("  %-12s now holds %d" % (coll, len(docs(coll, mask="__name__"))))
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "list":
        return cmd_list()
    if cmd == "find":
        if len(argv) < 3:
            print("usage: firestore-admin.py find <username>")
            return 2
        return cmd_find(" ".join(argv[2:]))
    if cmd == "purge":
        return cmd_purge("--yes" in argv)
    print("Unknown command %r" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
