"""
Flask frontend for the subjectivity analyzer.
Run:  python app.py
Then open http://localhost:5000
"""

import re
import json
import time
from flask import Flask, request, jsonify, render_template, Response, stream_with_context

try:
    import openreview as _or
    OPENREVIEW_AVAILABLE = True
except ImportError:
    OPENREVIEW_AVAILABLE = False

REVIEW_TEXT_FIELDS = [
    "review", "comment", "summary", "soundness", "presentation",
    "contribution", "strengths", "weaknesses", "questions",
    "limitations", "ethics_review", "rating_justification",
    "main_review", "paper_summary", "summary_of_contributions",
    "strengths_and_weaknesses",
]

app = Flask(__name__)

# ── Subjectivity patterns (mirrored from main.py) ─────────────────────────────
CATEGORY_PATTERNS = {
    "author_claim": [
        r"\bthe (authors?|paper|work|manuscript)\s+(claim|argue|suggest|assert|propose|state)s?\b",
        r"\bthe (authors?|paper)\s+(seem|appear)s?\b",
    ],
    "reviewer_belief": [
        r"\bi (believe|think|feel|suspect|perceive|find|consider|would argue)\b",
        r"\bin my (opinion|view|assessment|experience)\b",
        r"\bfrom my perspective\b",
        r"\bit seems (to me)?\b",
        r"\bit appears (to me)?\b",
        r"\bthis feels\b",
    ],
    "positive": [
        r"\b(strong|stronger|strongest)\s+(evidence|contribution|result|baseline|claim|motivation)\b",
        r"\bcompelling\b",
        r"\bimpressive\b",
        r"\belegant\b",
        r"\bsound(ly)?\b",
        r"\bwell[-\s](motivated|written|designed|executed|supported)\b",
        r"\binteresting\b",
        r"\bnovel(ty)?\b",
        r"\b(timely|relevant)\b",
        r"\bpromising\b",
        r"\bvaluable\b",
        r"\bimportant (contribution|work|finding|result)\b",
        r"\bgood (paper|work|contribution|baseline|idea|intuition)\b",
    ],
    "negative": [
        r"\b(underexplored|under-explored)\b",
        r"\bvague(ly|ness)?\b",
        r"\bnot (very|entirely|fully|clearly|well)\b",
        r"\bunlear\b",
        r"\bunclear\b",
        r"\bsimplistic\b",
        r"\brelatively thin\b",
        r"\bthin (contribution|evidence|evaluation|novelty)\b",
        r"\bnothing new\b",
        r"\bincrementally?\b",
        r"\boverclaim(ed|ing|s)?\b",
        r"\bunderexplain(ed|ing|s)?\b",
        r"\bmissing (ablation|baseline|comparison|experiment|discussion)\b",
        r"\blimited (novelty|scope|contribution|evaluation|experiment)\b",
        r"\binsufficient\b",
        r"\bweakly (motivated|supported|justified)\b",
        r"\bpoor(ly)?\s+(written|motivated|evaluated|justified)\b",
        r"\bshould (also|be|have|include|consider)\b",
        r"\bit would be better\b",
        r"\bcould be (improved|stronger|clearer|more)\b",
        r"\backs?\b",
        r"\bfails? to\b",
        r"\bstronger (baseline|experiment|evaluation|motivation)\b",
    ],
    "positioning": [
        r"\b(another|other|different|more appropriate) venue\b",
        r"\bnot a good fit\b",
        r"\bbetter suited\b",
        r"\bworkshop paper\b",
    ],
    "hedging": [
        r"\b(somewhat|rather|quite|fairly|reasonably) (limited|weak|unclear|vague|thin)\b",
        r"\bhard to (tell|say|follow|understand|evaluate|assess)\b",
        r"\bdifficult to (assess|evaluate|follow|understand|reproduce)\b",
        r"\bnot (convinced|sure|clear)\b",
        r"\bunconvincing\b",
        r"\bquestionable\b",
        r"\bdoubtful\b",
    ],
    "enthusiasm": [
        r"\bexcited?\b",
        r"\brecommend (acceptance|rejection|major|minor)\b",
        r"\bwould (accept|reject|like to see)\b",
        r"\bborderline\b",
        r"\bon the fence\b",
    ],
}

_ALL_PATTERNS = [p for patterns in CATEGORY_PATTERNS.values() for p in patterns]
_COMPILED = re.compile(
    "|".join(f"(?:{p})" for p in _ALL_PATTERNS),
    flags=re.IGNORECASE,
)
_CATEGORY_COMPILED = {
    cat: re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)
    for cat, patterns in CATEGORY_PATTERNS.items()
}


def get_category(matched_text: str) -> str:
    for category, compiled in _CATEGORY_COMPILED.items():
        if compiled.search(matched_text):
            return category
    return "general"


def split_sentences(text: str) -> list[str]:
    text = text.replace("\n\n", " ").replace("\n", " ")
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z"\'])', text)
    return [p.strip() for p in parts if len(p.strip()) > 20]


def annotate(text: str) -> dict:
    sentences = split_sentences(text)
    segments = []
    for sentence in sentences:
        phrase_matches = []
        seen: set[str] = set()
        for m in _COMPILED.finditer(sentence):
            key = m.group(0).lower()
            if key not in seen:
                seen.add(key)
                phrase_matches.append({
                    "start": m.start(),
                    "end": m.end(),
                    "text": m.group(0),
                    "category": get_category(m.group(0)),
                })
        segments.append({
            "text": sentence,
            "subjective": len(phrase_matches) > 0,
            "matches": phrase_matches,
        })

    total = len(segments)
    n_subj = sum(1 for s in segments if s["subjective"])
    return {
        "segments": segments,
        "stats": {
            "total": total,
            "subjective": n_subj,
            "pct": round(n_subj / total * 100, 1) if total else 0,
        },
    }


# ── OpenReview helpers ────────────────────────────────────────────────────────

def _extract_text_fields(note) -> dict[str, str]:
    content = note.content if hasattr(note, "content") else {}
    result = {}
    for field in REVIEW_TEXT_FIELDS:
        val = content.get(field)
        if val is None:
            continue
        if isinstance(val, dict) and "value" in val:
            val = val["value"]
        if isinstance(val, str) and val.strip():
            result[field] = val.strip()
    return result


def _note_matches(note, suffix: str) -> bool:
    invs = getattr(note, "invitations", None)
    if invs and isinstance(invs, list):
        return any(suffix in inv for inv in invs)
    return suffix in (getattr(note, "invitation", "") or "")


def _reviewer_name(note) -> str:
    if getattr(note, "signatures", None):
        return note.signatures[0]
    return "Anonymous"


def _paper_title(paper) -> str:
    raw = paper.content.get("title", {})
    return raw.get("value", paper.id) if isinstance(raw, dict) else str(raw)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _pull_reviews_stream(venue_id, username, password, max_papers, delay):
    """Generator yielding SSE strings while pulling and analysing reviews."""
    if not OPENREVIEW_AVAILABLE:
        yield _sse("error", {"message": "openreview-py not installed. Run: pip install openreview-py"})
        return

    yield _sse("status", {"message": "Connecting to OpenReview…"})

    try:
        kwargs = {"baseurl": "https://api2.openreview.net"}
        if username and password:
            kwargs |= {"username": username, "password": password}
        client = _or.api.OpenReviewClient(**kwargs)
    except Exception as e:
        yield _sse("error", {"message": f"Connection failed: {e}"})
        return

    yield _sse("status", {"message": f"Fetching submissions for {venue_id}…"})

    try:
        submissions = client.get_all_notes(invitation=f"{venue_id}/-/Submission")
    except Exception as e:
        yield _sse("error", {"message": f"Failed to fetch submissions: {e}"})
        return

    yield _sse("status", {"message": f"Found {len(submissions)} submissions. Filtering oral papers…"})

    oral_papers = []
    for sub in submissions:
        venueid = ""
        if hasattr(sub, "content"):
            v = sub.content.get("venueid", {})
            venueid = v.get("value", "") if isinstance(v, dict) else str(v)
        if "oral" in venueid.lower():
            oral_papers.append(sub)

    if not oral_papers:
        oral_papers = submissions
        yield _sse("status", {"message": f"No oral filter found – using all {len(oral_papers)} submissions."})
    else:
        yield _sse("status", {"message": f"Found {len(oral_papers)} oral papers."})

    if max_papers:
        oral_papers = oral_papers[:max_papers]

    total = len(oral_papers)
    yield _sse("total", {"total": total})

    venue_inv = f"{venue_id}/-/Official_Review"
    total_sentences = 0

    for idx, paper in enumerate(oral_papers):
        title = _paper_title(paper)
        yield _sse("progress", {"idx": idx + 1, "total": total, "title": title})

        try:
            reviews = client.get_notes(forum=paper.id, invitation=venue_inv)
        except Exception:
            reviews = []

        if not reviews:
            try:
                all_notes = client.get_all_notes(forum=paper.id)
                reviews = [n for n in all_notes if _note_matches(n, "Official_Review")]
            except Exception:
                reviews = []

        paper_payload: dict = {"paper_id": paper.id, "title": title, "reviews": []}

        for review in reviews:
            reviewer = _reviewer_name(review)
            fields_data = []
            for field_name, text in _extract_text_fields(review).items():
                result = annotate(text)
                if result["stats"]["subjective"] > 0:
                    fields_data.append({
                        "field": field_name,
                        "segments": result["segments"],
                        "stats": result["stats"],
                    })
                    total_sentences += result["stats"]["subjective"]
            if fields_data:
                paper_payload["reviews"].append({"reviewer": reviewer, "fields": fields_data})

        yield _sse("paper", paper_payload)
        time.sleep(delay)

    yield _sse("done", {"total_papers": total, "total_sentences": total_sentences})


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "No text provided"}), 400
    return jsonify(annotate(text))


@app.route("/reviews")
def reviews_page():
    return render_template("reviews.html")


@app.route("/stream-reviews")
def stream_reviews():
    venue_id = request.args.get("venue", "ICLR.cc/2026/Conference")
    username = request.args.get("username", "") or None
    password = request.args.get("password", "") or None
    raw_max = request.args.get("max_papers", "")
    max_papers = int(raw_max) if raw_max.isdigit() else None
    delay = float(request.args.get("delay", "0.3"))

    return Response(
        stream_with_context(_pull_reviews_stream(venue_id, username, password, max_papers, delay)),
        content_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
