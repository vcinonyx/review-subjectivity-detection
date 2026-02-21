from __future__ import annotations

import re
import csv
import sys
import time
import random
import argparse
import textwrap
from pathlib import Path
from collections import Counter
from dataclasses import dataclass, field, asdict
from typing import Optional


#  SUBJECTIVITY MARKER DICTIONARY
#  Each entry is a raw regex pattern (compiled case-insensitive).
PATTERNS: dict[str, list[str]] = {
    "author_claim": [
        r"\bthe (authors?|paper|work|manuscript)\s+(claim|argue|suggest|assert|propose|state)s?\b",
        r"\bthe (authors?|paper)\s+(seem|appear)s?\b",
        r"\bthe (authors?|paper) (do|does) not\b",
        r"\bthe proposed (method|approach|model|framework)\b",
        r"\bas (claimed|argued|stated|proposed) by the authors?\b",
    ],

    "reviewer_belief": [
        r"\bi (believe|think|feel|suspect|perceive|find|consider|would argue|am not convinced)\b",
        r"\bin my (opinion|view|assessment|experience|judgment)\b",
        r"\bfrom my (perspective|point of view|reading)\b",
        r"\bit seems (to me)?\b",
        r"\bit appears (to me)?\b",
        r"\bthis feels\b",
        r"\bmy (main|primary|major|key|biggest|central) concern\b",
        r"\bmy (impression|reading|understanding|take)\b",
        r"\bto me[,\s]\b",
        r"\bi (am|was) (surprised|confused|puzzled|uncertain|unsure)\b",
        r"\bi (cannot|can't|could not|couldn't) (follow|understand|see|tell)\b",
        r"\bi (would|might|may) (expect|argue|suggest|recommend|prefer)\b",
        r"\bi (wonder|question|doubt)\b",
        r"\bi (found|find) (this|it|the paper|the work)\b",
    ],

    "positive_quality": [
        r"\b(strong|stronger|strongest)\s+(evidence|contribution|result|baseline|claim|motivation|paper)\b",
        r"\bcompelling\b",
        r"\bimpressive(ly)?\b",
        r"\belegant(ly)?\b",
        r"\bsound(ly|ness)?\b",
        r"\bwell[-\s](motivated|written|designed|executed|supported|structured|organized|chosen)\b",
        r"\binteresting(ly)?\b",
        r"\bnovel(ty)?\b",
        r"\b(timely|relevant|significant)\b",
        r"\bpromising\b",
        r"\bvaluable\b",
        r"\bimportant (contribution|work|finding|result|step)\b",
        r"\bgood (paper|work|contribution|baseline|idea|intuition|job)\b",
        r"\bexcellent\b",
        r"\bstands? out\b",
        r"\bclearly (written|presented|motivated|explained)\b",
        r"\beasy to follow\b",
        r"\bwell (organized|presented|written|motivated)\b",
        r"\bnice (paper|work|contribution|idea|result)\b",
        r"\bsolid (contribution|work|paper|evaluation|baseline)\b",
    ],

    "negative_quality": [
        r"\b(underexplored|under-explored)\b",
        r"\bvague(ly|ness)?\b",
        r"\bambiguous(ly)?\b",
        r"\bnot (very|entirely|fully|clearly|well|easily|sufficiently)\b",
        r"\bunclear\b",
        r"\bsimplistic\b",
        r"\brelatively thin\b",
        r"\bthin (contribution|evidence|evaluation|novelty|section)\b",
        r"\bnothing new\b",
        r"\bincrementally?\b",
        r"\b(incremental|marginal) (contribution|improvement|novelty|advance)\b",
        r"\boverclaim(ed|ing|s)?\b",
        r"\bunderexplain(ed|ing|s)?\b",
        r"\boverstate(d|s)?\b",
        r"\bmissing (ablation|baseline|comparison|experiment|discussion|analysis|detail|section)\b",
        r"\blimited (novelty|scope|contribution|evaluation|experiment|analysis|insight)\b",
        r"\binsufficient(ly)?\b",
        r"\bweakly? (motivated|supported|justified|evaluated)\b",
        r"\bpoor(ly)?\s+(written|motivated|evaluated|justified|organized|presented)\b",
        r"\bshould (also|be|have|include|consider|provide|add|discuss)\b",
        r"\bit would be better\b",
        r"\bcould be (improved|stronger|clearer|more|further|better)\b",
        r"\blacks?\b",
        r"\bfails? to\b",
        r"\bdoes not (provide|discuss|address|show|demonstrate|compare|include)\b",
        r"\bstronger (baseline|experiment|evaluation|motivation|evidence)\b",
        r"\b(major|significant|key|critical|serious|fundamental|important|main)\s+weakness(es)?\b",
        r"\b(major|significant|key|critical|serious|fundamental|important|main)\s+(concern|issue|problem|limitation|drawback|flaw)\b",
        r"\bnot (convincing|convincingly|convincible)\b",
        r"\bweakness(es)?\b",
    ],

    "venue_fit": [
        r"\b(another|other|different|more appropriate) venue\b",
        r"\bnot a good fit\b",
        r"\bbetter suited\b",
        r"\bworkshop (paper|level|quality)\b",
        r"\bnot (ready|mature|polished) enough\b",
        r"\bnot (ready|suitable) for (publication|this venue|ICLR|NeurIPS)\b",
    ],

    "hedging": [
        r"\b(somewhat|rather|quite|fairly|reasonably|particularly|especially)\s+(limited|weak|unclear|vague|thin|concerning|worrying)\b",
        r"\bhard to (tell|say|follow|understand|evaluate|assess|judge|read)\b",
        r"\bdifficult to (assess|evaluate|follow|understand|reproduce|verify|judge)\b",
        r"\bnot (convinced|sure|certain|clear)\b",
        r"\bunconvincing(ly)?\b",
        r"\bquestionable\b",
        r"\bdoubtful\b",
        r"\bsomewhat\b",
        r"\b(may|might|could|can) (be|have|affect|impact|limit|hinder)\b",
        r"\bseems (to|like|as if|as though)\b",
        r"\bappears (to|like)\b",
        r"\bperhaps\b",
        r"\bpossibly\b",
        r"\bpotentially\b",
        r"\bsupposedly\b",
        r"\ballegedly\b",
    ],

    "recommendation": [
        r"\brecommend (acceptance|rejection|major|minor|revision|this paper)\b",
        r"\bwould (accept|reject|like to see|advocate for|champion)\b",
        r"\bborderline\b",
        r"\bon the fence\b",
        r"\blean (towards?|toward|to)\b",
        r"\bscore of\b",
        r"\brating\b",
        r"\baccept (with|pending|if)\b",
        r"\bweak (accept|reject|acceptance|rejection)\b",
        r"\bstrong (accept|reject|acceptance|rejection)\b",
        r"\bmarginally (above|below)\b",
    ],
}

_ALL_PATTERNS: list[str] = [p for group in PATTERNS.values() for p in group]
_COMPILED = re.compile(
    "|".join(f"(?:{p})" for p in _ALL_PATTERNS),
    flags=re.IGNORECASE,
)

REVIEW_FIELDS = [
    "review", "comment", "summary", "soundness", "presentation",
    "contribution", "strengths", "weaknesses", "questions",
    "limitations", "ethics_review", "rating_justification",
    "main_review", "paper_summary", "summary_of_contributions",
    "strengths_and_weaknesses", "weaknesses_and_questions",
    "comments_to_authors", "official_comment",
]


@dataclass
class Sentence:
    paper_id: str
    paper_title: str
    reviewer: str
    field:   str
    sentence: str
    matched_markers: list[str]
    label:   str   # "subjective" | "objective"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["matched_markers"] = " | ".join(self.matched_markers)
        return d


#  TEXT UTILITIES
def split_sentences(text: str) -> list[str]:
    """Split text (prose or bullets) into individual sentences."""
    out: list[str] = []
    paragraphs = re.split(r'\n{2,}', text)
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        lines = para.split('\n')
        if any(re.match(r'^\s*(?:[-*•]|\d+[.)]) ', line) for line in lines):
            for line in lines:
                clean = re.sub(r'^\s*(?:[-*•]|\d+[.)]) ?', '', line).strip()
                if clean:
                    for part in re.split(r'(?<=[.!?])\s+(?=[A-Z"\'])', clean):
                        out.append(part.strip())
        else:
            collapsed = ' '.join(lines)
            for part in re.split(r'(?<=[.!?])\s+(?=[A-Z"\'])', collapsed):
                out.append(part.strip())
    return [s for s in out if len(s) > 25]


def get_markers(sentence: str) -> list[str]:
    """Return matched subjectivity marker strings (deduped, order-preserving)."""
    seen: set[str] = set()
    result: list[str] = []
    for m in _COMPILED.finditer(sentence):
        key = m.group(0).lower()
        if key not in seen:
            seen.add(key)
            result.append(m.group(0))
    return result


def _token_set(sentence: str) -> set[str]:
    return set(re.findall(r'\b[a-zA-Z]{3,}\b', sentence.lower()))


def jaccard(a: str, b: str) -> float:
    sa, sb = _token_set(a), _token_set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def is_near_duplicate(sentence: str, pool: list[str], threshold: float = 0.72) -> bool:
    """Check if sentence is too similar to any existing sentence in pool."""
    tok = _token_set(sentence)
    for existing in pool[-500:]: # only compare against recent 500 (speed)
        ex_tok = _token_set(existing)
        if not tok or not ex_tok:
            continue
        j = len(tok & ex_tok) / len(tok | ex_tok)
        if j >= threshold:
            return True
    return False


def is_good_objective(sentence: str) -> bool:
    """Quality filter for objective candidates."""
    if len(sentence) < 45 or len(sentence) > 700:
        return False
    if not re.search(r'\b[a-zA-Z]{3,}\b', sentence):
        return False
    alpha = sum(c.isalpha() for c in sentence) / len(sentence)
    if alpha < 0.40:
        return False
    # Reject pure citation sentences like "[1, 2, 3] show that…"
    if re.match(r'^\s*\[[\d,\s]+\]', sentence):
        return False
    # Reject sentences that are just a header or label
    if re.match(r'^\s*\w[\w\s]{0,30}:\s*$', sentence):
        return False
    return True


def get_client(username=None, password=None):
    try:
        import openreview
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "openreview-py", "-q"])
        import openreview
    if username and password:
        return openreview.api.OpenReviewClient(
            baseurl="https://api2.openreview.net",
            username=username, password=password,
        )
    return openreview.api.OpenReviewClient(baseurl="https://api2.openreview.net")


def get_title(paper) -> str:
    t = paper.content.get("title", {})
    return t.get("value", paper.id) if isinstance(t, dict) else str(t)


def get_reviewer(note) -> str:
    if hasattr(note, "signatures") and note.signatures:
        return note.signatures[0]
    return "Anonymous"


def extract_all_text(note) -> dict[str, str]:
    """Pull every readable text field from a review note."""
    content = note.content if hasattr(note, "content") else {}
    out: dict[str, str] = {}
    for key in REVIEW_FIELDS:
        val = content.get(key)
        if val is None:
            continue
        if isinstance(val, dict) and "value" in val:
            val = val["value"]
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()
    return out


def is_review_note(note) -> bool:
    invs = getattr(note, "invitations", None) or []
    if any("Official_Review" in i for i in invs):
        return True
    inv = getattr(note, "invitation", "") or ""
    return "Official_Review" in inv


def fetch_reviews(client, paper_id: str, venue_id: str) -> list:
    """Fetch official review notes for a paper (two-path strategy)."""
    # Path 1: per-submission invitation
    if "Submission" in paper_id:
        num = paper_id.split("Submission")[-1]
        inv = f"{venue_id}/Submission{num}/-/Official_Review"
        try:
            notes = client.get_notes(invitation=inv, limit=25)
            if notes:
                return notes
        except Exception:
            pass
    # Path 2: all forum notes, filter locally
    try:
        notes = client.get_notes(forum=paper_id, limit=100)
        return [n for n in notes if is_review_note(n)]
    except Exception:
        return []


def fetch_submissions_paginated(
    client, invitation: str, page_size: int = 200, max_total: int = 2000
) -> list:
    """Fetch submissions in pages to avoid timeout on large venues."""
    all_subs = []
    offset = 0
    while len(all_subs) < max_total:
        try:
            batch = client.get_notes(
                invitation=invitation,
                limit=min(page_size, max_total - len(all_subs)),
                offset=offset,
            )
        except Exception as e:
            print(f"  Warning: page fetch failed at offset {offset}: {e}")
            break
        if not batch:
            break
        all_subs.extend(batch)
        print(f"  [paginate] offset={offset}  fetched={len(batch)}  total={len(all_subs)}")
        offset += len(batch)
        if len(batch) < page_size:
            break   # last page
        time.sleep(0.2)
    return all_subs


# ══════════════════════════════════════════════════════════════════════════════
#  CORE EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def extract_from_paper(paper, reviews: list) -> tuple[list[Sentence], list[Sentence]]:
    """
    Process all reviews for one paper.
    Returns (subjective_sentences, objective_candidates).
    """
    paper_id  = paper.id
    paper_title = get_title(paper)
    subjective: list[Sentence] = []
    objective: list[Sentence] = []

    for review in reviews:
        reviewer = get_reviewer(review)
        text_map = extract_all_text(review)

        for field_name, text in text_map.items():
            for sentence in split_sentences(text):
                markers = get_markers(sentence)
                if markers:
                    subjective.append(Sentence(
                        paper_id=paper_id,
                        paper_title=paper_title,
                        reviewer=reviewer,
                        field=field_name,
                        sentence=sentence,
                        matched_markers=markers,
                        label="subjective",
                    ))
                elif is_good_objective(sentence):
                    objective.append(Sentence(
                        paper_id=paper_id,
                        paper_title=paper_title,
                        reviewer=reviewer,
                        field=field_name,
                        sentence=sentence,
                        matched_markers=[],
                        label="objective",
                    ))

    return subjective, objective


def build_dataset(
    client,
    venue_id: str,
    target_n: int,
    max_papers: Optional[int],
    delay: float,
    seed: int,
    subjective_csv: Optional[str],
) -> list[Sentence]:
    """
    Main pipeline:
      1. Fetch all submissions (paginated)
      2. For each paper fetch reviews and extract sentences
      3. Merge with optional pre-existing CSV
      4. Deduplicate
      5. Balance and shuffle
    """
    rng = random.Random(seed)

    # ── Step 1: Fetch submissions ────────────────────────────────────────────
    inv = f"{venue_id}/-/Submission"
    print(f"\n{'─'*60}")
    print(f"Fetching submissions from {venue_id} ...")
    submissions = fetch_submissions_paginated(
        client, inv, page_size=250, max_total=max_papers or 3000
    )
    print(f"Total submissions fetched: {len(submissions)}")

    # Separate oral from the rest
    def is_oral(sub) -> bool:
        v = sub.content.get("venueid", {})
        v = v.get("value", "") if isinstance(v, dict) else str(v)
        return "oral" in v.lower()

    oral = [s for s in submissions if is_oral(s)]
    others = [s for s in submissions if not is_oral(s)]
    print(f"  → {len(oral)} oral  |  {len(others)} other accepted/all")

    # Process orals first, then fill from others if needed
    ordered = oral + others
    if max_papers:
        ordered = ordered[:max_papers]

    # ── Step 2: Extract sentences ────────────────────────────────────────────
    all_subj: list[Sentence] = []
    all_obj: list[Sentence] = []

    # Soft dedup pools (keep just text for Jaccard checks)
    subj_pool: list[str] = []
    obj_pool: list[str] = []

    print(f"\nScanning {len(ordered)} papers...")
    for idx, paper in enumerate(ordered):
        _progress(idx + 1, len(ordered), prefix="  Papers")

        reviews = fetch_reviews(client, paper.id, venue_id)
        if not reviews:
            continue

        new_subj, new_obj = extract_from_paper(paper, reviews)

        for s in new_subj:
            if not is_near_duplicate(s.sentence, subj_pool):
                all_subj.append(s)
                subj_pool.append(s.sentence)

        for s in new_obj:
            if not is_near_duplicate(s.sentence, obj_pool):
                all_obj.append(s)
                obj_pool.append(s.sentence)

        time.sleep(delay)

        # Early stop if we have surplus in both pools
        if len(all_subj) >= target_n * 4 and len(all_obj) >= target_n * 4:
            print(f"\n  [early stop] sufficient data collected")
            break

    print(f"\n  Raw subjective pool : {len(all_subj)}")
    print(f"  Raw objective pool  : {len(all_obj)}")

    # ── Step 3: Merge pre-existing subjective CSV ────────────────────────────
    if subjective_csv and Path(subjective_csv).exists():
        extra = _load_subjective_csv(subjective_csv)
        before = len(all_subj)
        for s in extra:
            if not is_near_duplicate(s.sentence, subj_pool):
                all_subj.append(s)
                subj_pool.append(s.sentence)
        print(f"  +{len(all_subj)-before} from {subjective_csv} → subjective pool now {len(all_subj)}")

    # ── Step 4: Balance ──────────────────────────────────────────────────────
    n = min(target_n, len(all_subj), len(all_obj))
    if n < target_n:
        print(
            f"\n  WARNING: could only balance to {n} per class "
            f"(requested {target_n}). Increase --max-papers or lower --n."
        )

    rng.shuffle(all_subj)
    rng.shuffle(all_obj)
    balanced = all_subj[:n] + all_obj[:n]

    # ── Step 5: Shuffle ──────────────────────────────────────────────────────
    rng.shuffle(balanced)
    print(f"\n  Final dataset: {len(balanced)} sentences ({n} subjective + {n} objective)")
    return balanced


def _load_subjective_csv(path: str) -> list[Sentence]:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            markers = [m.strip() for m in row.get("matched_markers", "").split("|") if m.strip()]
            rows.append(Sentence(
                paper_id=row.get("paper_id", ""),
                paper_title=row.get("paper_title", ""),
                reviewer=row.get("reviewer", "Anonymous"),
                field=row.get("field", ""),
                sentence=row.get("sentence", ""),
                matched_markers=markers,
                label="subjective",
            ))
    return rows


# ══════════════════════════════════════════════════════════════════════════════
#  OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

def save_csv(sentences: list[Sentence], path: str):
    fieldnames = ["paper_id", "paper_title", "reviewer", "field",
                  "sentence", "matched_markers", "label"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for s in sentences:
            writer.writerow(s.to_dict())
    print(f"\n✅  Saved {len(sentences)} rows → {path}")


def save_report(sentences: list[Sentence], path: str):
    label_counts = Counter(s.label for s in sentences)
    field_counts = Counter(s.field for s in sentences)
    marker_counts = Counter(m for s in sentences for m in s.matched_markers)

    lines = [
        "# Subjectivity Dataset Report",
        f"\n**Total sentences:** {len(sentences)}",
        f"**Subjective:** {label_counts['subjective']}",
        f"**Objective:** {label_counts['objective']}",
        "\n## Top 30 Triggered Markers\n",
        "| Rank | Marker | Count |",
        "|------|--------|-------|",
    ]
    for rank, (marker, count) in enumerate(marker_counts.most_common(30), 1):
        lines.append(f"| {rank} | `{marker}` | {count} |")

    lines += [
        "\n## Fields Distribution\n",
        "| Field | Count |",
        "|-------|-------|",
    ]
    for field, count in field_counts.most_common():
        lines += [f"| {field} | {count} |"]

    lines += [
        "\n## Sample Subjective Sentences\n"
    ]
    shown = 0
    for s in sentences:
        if s.label == "subjective" and shown < 5:
            lines.append(f"- **[{s.field}]** {s.sentence[:130]}…")
            lines.append(f"  - *markers:* {', '.join(s.matched_markers[:4])}")
            shown += 1

    lines += ["\n## Sample Objective Sentences\n"]
    shown = 0
    for s in sentences:
        if s.label == "objective" and shown < 5:
            lines.append(f"- **[{s.field}]** {s.sentence[:130]}…")
            shown += 1

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅  Report → {path}")


def _progress(current: int, total: int, prefix: str = "", width: int = 40):
    pct = current / total
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    print(f"\r{prefix} |{bar}| {current}/{total} ({pct*100:.0f}%)", end="", flush=True)
    if current == total:
        print()


def print_summary(sentences: list[Sentence]):
    counts = Counter(s.label for s in sentences)
    print(f"\n{'═'*60}")
    print(f"  DATASET SUMMARY  ({len(sentences)} total sentences)")
    print(f"{'═'*60}")
    for label in ("subjective", "objective"):
        n = counts[label]
        bar = "█" * min(n // 2, 50)
        print(f"  {label.upper():12s}  {n:4d}  {bar}")

    top_markers = Counter(m for s in sentences for m in s.matched_markers).most_common(10)
    print(f"\n  Top 10 markers:")
    for marker, count in top_markers:
        print(f"    {count:4d}  {marker}")

    print(f"\n  Sample SUBJECTIVE:")
    for s in [s for s in sentences if s.label == "subjective"][:3]:
        print(f"    [{s.field}] {textwrap.shorten(s.sentence, 110)}")

    print(f"\n  Sample OBJECTIVE:")
    for s in [s for s in sentences if s.label == "objective"][:3]:
        print(f"    [{s.field}] {textwrap.shorten(s.sentence, 110)}")

    print(f"{'═'*60}\n")


# ══════════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Build a large balanced subjective/objective dataset from OpenReview.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python build_eval_dataset.py --n 500 --max-papers 200
              python build_eval_dataset.py --username me@x.com --password s3cr3t --n 1000
        """)
    )
    parser.add_argument("--n", type=int, default=500,
                        help="Target sentences PER CLASS (default: 500 → 1000 total)")
    parser.add_argument("--max-papers", type=int, default=None,
                        help="Cap on papers to scan (default: unlimited)")
    parser.add_argument("--venue", default="ICLR.cc/2026/Conference",
                        help="OpenReview venue ID")
    parser.add_argument("--delay", type=float, default=0.25,
                        help="Delay between API requests in seconds (default: 0.25)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed (default: 42)")
    parser.add_argument("--output", default="eval_dataset.csv",
                        help="Output CSV path (default: eval_dataset.csv)")
    parser.add_argument("--report", default="eval_dataset_report.md",
                        help="Markdown stats report path (default: eval_dataset_report.md)")
    parser.add_argument("--subjective-csv", default=None,
                        help="Optional pre-existing subjective_sentences.csv to merge in")
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    args = parser.parse_args()

    print(f"\n{'═'*60}")
    print(f"  OpenReview Subjectivity Dataset Builder")
    print(f"  Target: {args.n} subjective + {args.n} objective = {args.n*2} total")
    print(f"  Venue : {args.venue}")
    print(f"{'═'*60}")

    client = get_client(args.username, args.password)

    dataset = build_dataset(
        client=client,
        venue_id=args.venue,
        target_n=args.n,
        max_papers=args.max_papers,
        delay=args.delay,
        seed=args.seed,
        subjective_csv=args.subjective_csv,
    )

    print_summary(dataset)
    save_csv(dataset, args.output)
    save_report(dataset, args.report)


if __name__ == "__main__":
    main()