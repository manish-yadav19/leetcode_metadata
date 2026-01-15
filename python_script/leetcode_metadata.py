import json
import csv
from pathlib import Path
from collections import defaultdict

TARGET_OPERATION = "favoriteQuestionList"
TARGET_SLUG = "database"  # change this to "uber", "google", etc. when needed

def load_har_entries(har_path: str):
    har = json.loads(Path(har_path).read_text(encoding="utf-8"))
    return har["log"]["entries"]

def safe_json(s: str):
    try:
        return json.loads(s)
    except Exception:
        return None

def extract_matching_responses(entries):
    """
    Return list of (variables, response_json) for GraphQL calls matching:
    operationName == favoriteQuestionList AND variables.favoriteSlug == TARGET_SLUG
    """
    matched = []

    for e in entries:
        req = e.get("request", {})
        resp = e.get("response", {})
        post = req.get("postData", {})
        payload_text = post.get("text")

        if not payload_text:
            continue

        payload = safe_json(payload_text)
        if not isinstance(payload, dict):
            continue

        if payload.get("operationName") != TARGET_OPERATION:
            continue

        variables = payload.get("variables") or {}
        if variables.get("favoriteSlug") != TARGET_SLUG:
            continue

        # Read response JSON
        content = (resp.get("content") or {})
        text = content.get("text")
        if not text or content.get("encoding") == "base64":
            continue

        response_json = safe_json(text)
        if not isinstance(response_json, dict):
            continue

        matched.append((variables, response_json))

    return matched

def normalize_question(q):
    # your schema includes questionFrontendId
    qnum = q.get("questionFrontendId") or ""
    title = q.get("title") or ""
    difficulty = (q.get("difficulty") or "").strip().title()
    ac_rate = q.get("acRate") if q.get("acRate") is not None else ""

    tags = []
    for t in (q.get("topicTags") or []):
        name = t.get("name")
        if name:
            tags.append(name)

    return {
        "favoriteSlug": TARGET_SLUG,
        "question_number": str(qnum),
        "title": title,
        "difficulty": difficulty,
        "ac_rate": ac_rate,
        "topics": ";".join(sorted(set(tags))),
    }

def write_csv(path, rows, headers):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        w.writerows(rows)

def main(har_path: str):
    entries = load_har_entries(har_path)
    matched = extract_matching_responses(entries)

    all_rows = []
    for variables, response in matched:
        data = (response.get("data") or {}).get("favoriteQuestionList") or {}
        questions = data.get("questions") or []
        for q in questions:
            all_rows.append(normalize_question(q))

    # Deduplicate across pages
    dedup = {}
    for r in all_rows:
        key = (r["favoriteSlug"], r["question_number"], r["title"])
        dedup[key] = r
    rows = list(dedup.values())

    # Sort by question number (numeric)
    def qnum_key(x):
        try:
            return int(x["question_number"])
        except Exception:
            return 10**12
    rows.sort(key=lambda r: qnum_key(r))

    # Output 1: Flat list
    write_csv(
        "questions_flat.csv",
        rows,
        ["favoriteSlug", "question_number", "title", "difficulty", "ac_rate", "topics"]
    )

    # Output 2: Topic summary
    topic_counts = defaultdict(lambda: {"Easy": 0, "Medium": 0, "Hard": 0, "Total": 0})
    for r in rows:
        topics = [t.strip() for t in r["topics"].split(";") if t.strip()]
        for t in topics:
            topic_counts[t][r["difficulty"]] += 1
            topic_counts[t]["Total"] += 1

    summary = []
    for topic, c in topic_counts.items():
        summary.append({
            "favoriteSlug": TARGET_SLUG,
            "topic": topic,
            "total": c["Total"],
            "easy": c["Easy"],
            "medium": c["Medium"],
            "hard": c["Hard"],
        })
    summary.sort(key=lambda r: (-r["total"], r["topic"]))

    write_csv(
        "topics_summary.csv",
        summary,
        ["favoriteSlug", "topic", "total", "easy", "medium", "hard"]
    )

    # Output 3: Topic -> question list mapping
    topic_map = defaultdict(list)
    for r in rows:
        topics = [t.strip() for t in r["topics"].split(";") if t.strip()]
        for t in topics:
            topic_map[t].append(f'{r["question_number"]} - {r["title"]} ({r["difficulty"]})')

    mapping = []
    for topic, qlist in topic_map.items():
        mapping.append({
            "favoriteSlug": TARGET_SLUG,
            "topic": topic,
            "questions": " | ".join(qlist)
        })
    mapping.sort(key=lambda r: r["topic"])

    write_csv(
        "topics_to_questions.csv",
        mapping,
        ["favoriteSlug", "topic", "questions"]
    )

    print(f"Done. Questions exported: {len(rows)}")
    print("Generated: questions_flat.csv, topics_summary.csv, topics_to_questions.csv")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python export_favorite_list_metadata.py <leetcode_database.har>")
        raise SystemExit(1)
    main(sys.argv[1])
