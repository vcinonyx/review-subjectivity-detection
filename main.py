"""
OpenReview Subjectivity Extractor
==================================
Pulls reviews from ICLR 2026 Oral papers on OpenReview and extracts
subjective sentences based on an extensible dictionary of subjectivity markers.

Usage:
    pip install openreview-py
    python openreview_subjectivity.py

    # With optional auth (for full access):
    python openreview_subjectivity.py --username you@email.com --password yourpass

    # Save results to CSV:
    python openreview_subjectivity.py --output results.csv
"""

import re
import csv
import sys
import time
import argparse
from dataclasses import dataclass, field
from typing import Optional

try:
    import openreview
except ImportError:
    print("Installing openreview-py...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "openreview-py", "--quiet"])
    import openreview


# SUBJECTIVITY MARKER DICTIONARY
# Extend this freely. Each entry is a regex pattern (case-insensitive).
SUBJECTIVITY_PATTERNS = [
    # Author/paper claims (hedging about source)
    r"\bthe (authors?|paper|work|manuscript)\s+(claim|argue|suggest|assert|propose|state)s?\b",
    r"\bthe (authors?|paper)\s+(seem|appear)s?\b",

    # Reviewer belief / perception
    r"\bi (believe|think|feel|suspect|perceive|find|consider|would argue)\b",
    r"\bin my (opinion|view|assessment|experience)\b",
    r"\bfrom my perspective\b",
    r"\bit seems (to me)?\b",
    r"\bit appears (to me)?\b",
    r"\bthis feels\b",

    # Positive markers
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

    # Negative markers
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
    r"\blacks?\b",
    r"\bfails? to\b",
    r"\bstronger (baseline|experiment|evaluation|motivation)\b",

    # Venue / positioning
    r"\b(another|other|different|more appropriate) venue\b",
    r"\bnot a good fit\b",
    r"\bbetter suited\b",
    r"\bworkshop paper\b",

    # Hedging / uncertainty language
    r"\b(somewhat|rather|quite|fairly|reasonably) (limited|weak|unclear|vague|thin)\b",
    r"\bhard to (tell|say|follow|understand|evaluate|assess)\b",
    r"\bdifficult to (assess|evaluate|follow|understand|reproduce)\b",
    r"\bnot (convinced|sure|clear)\b",
    r"\bunconvincing\b",
    r"\bquestionable\b",
    r"\bdoubtful\b",

    # Enthusiasm markers
    r"\bexcited?\b",
    r"\brecommend (acceptance|rejection|major|minor)\b",
    r"\bwould (accept|reject|like to see)\b",
    r"\bborderline\b",
    r"\bon the fence\b",
]

# Compile all patterns into one master regex for speed
_COMPILED = re.compile(
    "|".join(f"(?:{p})" for p in SUBJECTIVITY_PATTERNS),
    flags=re.IGNORECASE
)

# Fields in reviews that typically contain free-text
REVIEW_TEXT_FIELDS = [
    "review", "comment", "summary", "soundness", "presentation",
    "contribution", "strengths", "weaknesses", "questions",
    "limitations", "ethics_review", "rating_justification",
    "main_review", "paper_summary", "summary_of_contributions",
    "strengths_and_weaknesses",
]


@dataclass
class SubjectiveSentence:
    paper_id: str
    paper_title: str
    reviewer: str
    field_name: str
    sentence: str
    matched_markers: list[str] = field(default_factory=list)


def split_sentences(text: str) -> list[str]:
    """Simple sentence splitter that handles common academic writing patterns."""
    text = text.replace("\n\n", " ").replace("\n", " ")
    # Split on '. ', '! ', '? ' but keep abbreviations mostly intact
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z\"\'])', text)
    return [p.strip() for p in parts if len(p.strip()) > 20]


def _self_test():
    """Sanity-check that patterns compile and match known examples."""
    test_cases = [
        "I think this paper is very interesting.",
        "The contribution is novel but the evaluation is insufficient.",
        "In my opinion, the authors should also include more ablations.",
        "The paper fails to demonstrate compelling results.",
        "This work is not convincing and lacks strong baselines.",
    ]
    print("[self-test] Verifying subjectivity patterns on sample sentences...")
    all_ok = True
    for text in test_cases:
        hits = [(s, ms) for s, ms in _find_subjective_sentences_impl(text)]
        status = "OK  " if hits else "MISS"
        markers = [m for _, ms in hits for m in ms]
        print(f"  [{status}] {text[:65]}")
        if hits:
            print(f"         markers: {markers}")
        else:
            all_ok = False
            print(f"         *** no markers found – check patterns ***")
    print(f"[self-test] {'PASSED' if all_ok else 'SOME MISSES – patterns may need adjustment'}\n")


def _find_subjective_sentences_impl(text: str, debug: bool = False) -> list[tuple[str, list[str]]]:
    """Core implementation using finditer so capturing groups don't corrupt results."""
    results = []
    sentences = split_sentences(text)
    if debug:
        print(f"        [dbg] {len(sentences)} sentence(s) after split")
    for sentence in sentences:
        seen: set[str] = set()
        markers: list[str] = []
        for m in _COMPILED.finditer(sentence):
            key = m.group(0).lower()
            if key not in seen:
                seen.add(key)
                markers.append(m.group(0))
        if markers:
            results.append((sentence, markers))
            if debug:
                print(f"        [dbg] HIT: {sentence[:80]}  → {markers}")
    return results


def find_subjective_sentences(text: str, debug: bool = False) -> list[tuple[str, list[str]]]:
    """Returns list of (sentence, matched_markers) tuples."""
    return _find_subjective_sentences_impl(text, debug=debug)


def extract_review_text(note, debug: bool = False) -> dict[str, str]:
    """Extract all text fields from a review note."""
    content = note.content if hasattr(note, "content") else {}
    extracted = {}

    if debug:
        all_keys = list(content.keys()) if isinstance(content, dict) else []
        print(f"        [dbg] review content keys: {all_keys}")

    for field_name in REVIEW_TEXT_FIELDS:
        val = content.get(field_name, None)
        if val is None:
            continue
        # openreview-py v2 wraps values in {"value": ...}
        if isinstance(val, dict) and "value" in val:
            val = val["value"]
        if isinstance(val, str) and len(val.strip()) > 0:
            extracted[field_name] = val.strip()

    if debug and not extracted:
        print(f"        [dbg] WARNING: no known text fields found in review!")
    return extracted


def _note_invitation_str(note) -> str:
    """Return a single invitation string from a note.

    OpenReview API v2 stores invitations as a list in `note.invitations`.
    API v1 uses a scalar `note.invitation`.
    """
    # v2: list attribute
    invs = getattr(note, "invitations", None)
    if invs:
        return invs[0] if isinstance(invs, list) else str(invs)
    # v1: scalar attribute
    return getattr(note, "invitation", "") or ""


def _note_matches_invitation(note, suffix: str) -> bool:
    """Return True if any of the note's invitations contains `suffix`."""
    invs = getattr(note, "invitations", None)
    if invs and isinstance(invs, list):
        return any(suffix in inv for inv in invs)
    inv = getattr(note, "invitation", "") or ""
    return suffix in inv


def get_reviewer_name(note) -> str:
    """Best-effort reviewer identifier (anonymised or username)."""
    if hasattr(note, "signatures") and note.signatures:
        return note.signatures[0]
    if hasattr(note, "writers") and note.writers:
        return note.writers[0]
    return "Anonymous"


def pull_reviews(
    venue_id: str = "ICLR.cc/2026/Conference",
    submission_invitation: str = "ICLR.cc/2026/Conference/-/Submission",
    review_invitation_suffix: str = "Official_Review",
    username: Optional[str] = None,
    password: Optional[str] = None,
    max_papers: Optional[int] = None,
    delay: float = 0.3,
    debug: bool = False,
) -> list[SubjectiveSentence]:
    """
    Main function: connects to OpenReview, iterates over accepted oral papers,
    pulls all reviews and extracts subjective sentences.
    """
    print("Connecting to OpenReview...")
    if username and password:
        client = openreview.api.OpenReviewClient(
            baseurl="https://api2.openreview.net",
            username=username,
            password=password,
        )
    else:
        client = openreview.api.OpenReviewClient(
            baseurl="https://api2.openreview.net"
        )

    # ── Fetch accepted oral papers ──────────────────────────────────────────
    print(f"Fetching accepted oral submissions for {venue_id} ...")
    all_results: list[SubjectiveSentence] = []

    try:
        submissions = client.get_all_notes(invitation=submission_invitation)
        print(f"  Total submissions found: {len(submissions)}")
    except Exception as e:
        print(f"  Error fetching submissions: {e}")
        return all_results

    # Filter to oral accepts only (decision note content)
    oral_papers = []
    sample_venueids: list[str] = []
    for sub in submissions:
        venueid = ""
        # v2 API stores venueid in content
        if hasattr(sub, "content"):
            v = sub.content.get("venueid", {})
            venueid = v.get("value", "") if isinstance(v, dict) else str(v)
        if len(sample_venueids) < 5 and venueid:
            sample_venueids.append(venueid)
        if "oral" in venueid.lower():
            oral_papers.append(sub)

    if debug and sample_venueids:
        print(f"  [dbg] sample venueid values: {sample_venueids}")

    if not oral_papers:
        print("  Could not find oral papers via venueid filter; using all accepted papers instead.")
        oral_papers = submissions

    if max_papers:
        oral_papers = oral_papers[:max_papers]

    print(f"  Processing {len(oral_papers)} oral papers...")

    # ── Iterate papers and pull reviews ─────────────────────────────────────
    for idx, paper in enumerate(oral_papers):
        paper_id = paper.id
        title_raw = paper.content.get("title", {})
        title = title_raw.get("value", paper_id) if isinstance(title_raw, dict) else str(title_raw)

        print(f"  [{idx+1}/{len(oral_papers)}] {title[:70]}...")

        # Fetch all official reviews for this paper.
        # OpenReview v2 uses per-paper invitations like:
        #   {venue_id}/Submission{N}/-/Official_Review
        # The venue-level invitation {venue_id}/-/Official_Review returns nothing,
        # so we fetch all forum notes and filter by invitation suffix instead.
        venue_level_inv = f"{venue_id}/-/{review_invitation_suffix}"
        if debug:
            print(f"      [dbg] trying venue-level invitation: {venue_level_inv}")
        try:
            reviews = client.get_notes(forum=paper_id, invitation=venue_level_inv)
        except Exception as e:
            print(f"    Warning: venue-level invitation failed ({e})")
            reviews = []

        if not reviews:
            # Fallback: pull all notes for this forum and filter by suffix.
            # OpenReview API v2 uses `invitations` (list) not `invitation` (str).
            if debug:
                print(f"      [dbg] 0 results – falling back to get_all_notes + filter")
            try:
                all_forum_notes = client.get_all_notes(forum=paper_id)
                reviews = [
                    n for n in all_forum_notes
                    if _note_matches_invitation(n, review_invitation_suffix)
                ]
                if debug:
                    invitations_seen = list({_note_invitation_str(n) for n in all_forum_notes})
                    print(f"      [dbg] all invitation types in forum: {invitations_seen[:10]}")
            except Exception as e:
                print(f"    Warning: get_all_notes fallback failed ({e})")
                reviews = []

        print(f"      reviews found: {len(reviews)}")

        for review in reviews:
            reviewer = get_reviewer_name(review)
            text_fields = extract_review_text(review, debug=debug)

            if debug:
                print(f"      [dbg] reviewer={reviewer}  text fields extracted: {list(text_fields.keys())}")

            if not text_fields:
                print(f"      WARNING: review by {reviewer} had no extractable text fields")

            for field_name, text in text_fields.items():
                hits = find_subjective_sentences(text, debug=debug)
                if debug:
                    print(f"      [dbg] field={field_name}: {len(hits)} subjective sentence(s)")
                for sentence, markers in hits:
                    all_results.append(SubjectiveSentence(
                        paper_id=paper_id,
                        paper_title=title,
                        reviewer=reviewer,
                        field_name=field_name,
                        sentence=sentence,
                        matched_markers=markers,
                    ))

        time.sleep(delay)  # be polite to the API

    return all_results


def save_to_csv(results: list[SubjectiveSentence], path: str):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["paper_id", "paper_title", "reviewer",
                         "field", "sentence", "matched_markers"])
        for r in results:
            writer.writerow([
                r.paper_id,
                r.paper_title,
                r.reviewer,
                r.field_name,
                r.sentence,
                " | ".join(r.matched_markers),
            ])
    print(f"\nSaved {len(results)} subjective sentences → {path}")


def print_summary(results: list[SubjectiveSentence], top_n: int = 30):
    print(f"\n{'='*70}")
    print(f"  SUBJECTIVE SENTENCES FOUND: {len(results)}")
    print(f"{'='*70}\n")

    # Group by paper
    from collections import defaultdict
    by_paper: dict[str, list[SubjectiveSentence]] = defaultdict(list)
    for r in results:
        by_paper[r.paper_title].append(r)

    shown = 0
    for title, items in list(by_paper.items())[:top_n]:
        print(f"📄 {title[:80]}")
        for item in items[:5]:  # max 5 sentences per paper in preview
            markers_str = ", ".join(f"[{m}]" for m in item.matched_markers[:3])
            print(f"   🔹 ({item.field_name}) {item.sentence[:120]}...")
            print(f"      ↳ markers: {markers_str}")
        print()
        shown += 1
        if shown >= top_n:
            break

    from collections import Counter
    all_markers = [m for r in results for m in r.matched_markers]
    print(f"\n{'─'*50}")
    print("TOP 20 TRIGGERED MARKERS:")
    for marker, count in Counter(all_markers).most_common(20):
        bar = "█" * min(count, 40)
        print(f"  {count:4d} {bar}  {marker[:50]}")


def main():
    parser = argparse.ArgumentParser(
        description="Extract subjective sentences from OpenReview ICLR 2026 oral reviews."
    )
    parser.add_argument("--username", default=None, help="OpenReview username (email)")
    parser.add_argument("--password", default=None, help="OpenReview password")
    parser.add_argument("--output", default="subjective_sentences.csv",
                        help="Output CSV file path (default: subjective_sentences.csv)")
    parser.add_argument("--max-papers", type=int, default=None,
                        help="Limit number of papers (for testing)")
    parser.add_argument("--venue", default="ICLR.cc/2026/Conference",
                        help="OpenReview venue ID")
    parser.add_argument("--delay", type=float, default=0.3,
                        help="Delay between API requests in seconds (default: 0.3)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable verbose debug output to trace the pipeline")
    args = parser.parse_args()

    if args.debug:
        _self_test()

    results = pull_reviews(
        venue_id=args.venue,
        username=args.username,
        password=args.password,
        max_papers=args.max_papers,
        delay=args.delay,
        debug=args.debug,
    )

    if not results:
        print("\nNo subjective sentences found. This may mean:")
        print("  • Reviews are not yet public (conference in progress)")
        print("  • The venue ID needs adjustment")
        print("  • Authentication is required (use --username/--password)")
        return

    print_summary(results)

    if args.output:
        save_to_csv(results, args.output)


if __name__ == "__main__":
    main()