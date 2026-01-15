import json
import csv
import re
from pathlib import Path

OP_NAME = "favoriteQuestionList"

def safe_json(s: str):
    try:
        return json.loads(s)
    except Exception:
        return None

def safe_filename(slug: str) -> str:
    slug = slug.strip().lower()
    slug = re.sub(r"[^a-z0-9\-]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return f"questions_{slug}.csv"

def load_entries(har_path: str):
    har = json.loads(Path(har_path).read_text(encoding="utf-8"))
    return har["log"]["entries"]

def extract(entry):
    req = entry.get("request", {})
    resp = entry.get("response", {})

    post = req.get("postData", {}) or {}
    payload_text = post.get("text")
    if not payload_text:
        return None

    payload = safe_json(payload_text)
    if not isinstance(payload, dict):
        return None

    if payload.get("operationName") != OP_NAME:
        return None

    variables = payload.get("variables") or {}
    slug = variables.get("favoriteSlug")
    if not slug:
        return None

    content = (resp.get("content") or {})
    text = content.get("text")
    if not text or content.get("encoding") == "base64":
        return None

    response_json = safe_json(text)
    if not isinstance(response_json, dict):
        return None

    data = (response_json.get("data") or {}).get("favoriteQuestionList") or {}
    questions = data.get("questions") or []

    return slug, questions

def normalize(q, slug):
    qnum = q.get("questionFrontendId") or q.get("questionId") or ""
    title = q.get("title") or ""
    difficulty = (q.get("difficulty") or "").strip().title()  # EASY -> Easy
    ac_rate = q.get("acRate") if q.get("acRate") is not None else ""

    tags = []
    for t in (q.get("topicTags") or []):
        name = t.get("name")
        if name:
            tags.append(name)

    return {
        "favoriteSlug": slug,
        "question_number": str(qnum),
        "title": title,
        "difficulty": difficulty,
        "ac_rate": ac_rate,
        "topics": ";".join(sorted(set(tags))),
        "paidOnly": q.get("paidOnly", ""),
        "status": q.get("status", ""),
        "titleSlug": q.get("titleSlug", "")
    }

def write_csv(path, rows):
    headers = ["favoriteSlug","question_number","title","difficulty","ac_rate","topics","paidOnly","status","titleSlug"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        w.writerows(rows)

def main(har_path: str, allowed_slugs=None):
    by_slug = {}

    for e in load_entries(har_path):
        out = extract(e)
        if not out:
            continue
        slug, questions = out

        if allowed_slugs and slug not in allowed_slugs:
            continue

        by_slug.setdefault(slug, [])
        for q in questions:
            by_slug[slug].append(normalize(q, slug))

    if not by_slug:
        print("No favoriteQuestionList calls found in this HAR.")
        print("Open each company list page, scroll a bit, then export HAR with content.")
        return

    for slug, rows in by_slug.items():
        # Dedup across pagination
        dedup = {}
        for r in rows:
            key = (r["question_number"], r["title"])
            dedup[key] = r
        final_rows = list(dedup.values())

        # Sort by question number
        def qnum_key(x):
            try:
                return int(x["question_number"])
            except Exception:
                return 10**12

        final_rows.sort(key=lambda r: (qnum_key(r), r["title"]))

        out_file = safe_filename(slug)
        write_csv(out_file, final_rows)
        print(f"Wrote {out_file} ({len(final_rows)} questions)")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 export_companies.py <combined.har>")
        print("Optional (restrict slugs):")
        print("  python3 export_companies.py <combined.har> google-thirty-days facebook-three-months")
        raise SystemExit(1)

    har_path = sys.argv[1]
    allowed = set(sys.argv[2:]) if len(sys.argv) > 2 else None
    main(har_path, allowed_slugs=allowed)
