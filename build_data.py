#!/usr/bin/env python3
"""Build the PassProfessor MCP server data files from read-only live-site extracts.

Inputs (same dir):  catalog_raw.json, pages_a.json, pages_b.json, samples_raw.json, courses_raw.json
Outputs:            data/programs.json, data/samples.json, data/build_report.json

Nothing is invented: every field traces to an extract. Missing data stays null
and the server reports it as unavailable.
"""
import json, re, sys, html
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"
DATA.mkdir(exist_ok=True)

def core(slug: str) -> str:
    for suf in ("-practice-exams", "-exam-prep"):
        if slug.endswith(suf):
            return slug[: -len(suf)]
    return slug

def strip_tags(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s or "")
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).strip()

def parse_tables(content: str):
    tables = []
    for t in re.findall(r"<table.*?</table>", content or "", re.S):
        rows = []
        for r in re.findall(r"<tr.*?</tr>", t, re.S):
            cells = [strip_tags(x) for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables

GLANCE_LABELS = {"format", "items", "questions", "time", "time limit", "passing standard",
                 "pass standard", "passing", "passing score", "exam fee", "fee", "fees", "cost",
                 "retake wait", "delivery", "vendor", "administered by", "testing vendor",
                 "results", "scoring", "eligibility", "questions administered",
                 "questions you will see", "scored questions", "attempts", "duration",
                 "number of questions"}
GLANCE_ANCHORS = {"format", "time limit", "time", "passing standard", "passing score", "duration"}

# Programs whose sample set must NOT be served yet, with reason (logged in build report):
# - certified-meeting-professional: product drafted 2026-11-12 pending package repair;
#   its launch has not closed, so its sample set is excluded until closeout.
EXCLUDED_SAMPLE_KEYS = {"certified-meeting-professional"}

def parse_page(page):
    content = page["content"] or ""
    tables = parse_tables(content)
    facts, weights = None, None
    for rows in tables:
        labels = {r[0].strip().lower() for r in rows if len(r) >= 2}
        if len(labels & GLANCE_LABELS) >= 2 and (labels & GLANCE_ANCHORS):
            facts = {}
            for r in rows:
                if len(r) >= 2 and r[0].strip() and r[0].strip().lower() in GLANCE_LABELS:
                    facts[r[0].strip()] = r[1].strip()
            # exam short name from header row ['', 'NCLEX-RN']
            for r in rows:
                if len(r) >= 2 and not r[0].strip() and r[1].strip():
                    facts["_exam_name"] = r[1].strip()
                    break
        hdr = " ".join(rows[0]).lower() if rows else ""
        first_col_labels = {r[0].strip().lower() for r in rows if r}
        is_glance = len(first_col_labels & GLANCE_LABELS) >= 2
        if (not is_glance and len(rows) > 2
                and ("weight" in hdr or "range" in hdr or "% of" in hdr)
                and ("practice questions" in hdr or "domain" in hdr or "area" in hdr
                     or "topic" in hdr or "portion" in hdr or "content" in hdr)):
            w = []
            for r in rows[1:]:
                if len(r) >= 2 and r[0].strip() and r[1].strip():
                    w.append({"area": r[0].strip(), "range": r[1].strip()})
            if len(w) >= 3:
                weights = w
    text = strip_tags(content)
    count = None
    m = re.search(r"([\d,]+)\s+original practice questions", text)
    if m:
        count = int(m.group(1).replace(",", ""))
    if count is None:
        m = re.search(r"([\d,]+)\s+practice questions", text)
        if m:
            count = int(m.group(1).replace(",", ""))
    hrefs = re.findall(r'href="([^"]+)"', content)
    sample_url = None
    for h in hrefs:
        if "/quizzes/" in h and "sample" in h:
            sample_url = h
            break
    if sample_url is None:
        for h in hrefs:
            if "free-sample" in h:
                sample_url = h
                break
    return {"facts": facts, "topic_weights": weights, "practice_question_count": count,
            "sample_url": sample_url}

def main():
    catalog = json.loads((HERE / "catalog_raw.json").read_text())
    pages = json.loads((HERE / "pages_a.json").read_text()) + json.loads((HERE / "pages_b.json").read_text())
    samples_raw = json.loads((HERE / "samples_raw.json").read_text())
    courses = json.loads((HERE / "courses_raw.json").read_text())
    quiz_links = {x["quiz_post_id"]: x["permalink"]
                  for x in json.loads((HERE / "quiz_links.json").read_text())}

    course_by_id = {str(c["id"]): c for c in courses}
    page_by_core = {}
    for p in pages:
        page_by_core.setdefault(core(p["slug"]), p)
    parsed_by_core = {core(p["slug"]): parse_page(p) for p in pages}

    programs = {}
    for prod in catalog:
        key = core(prod["slug"])
        page = page_by_core.get(key)
        pp = parsed_by_core.get(key, {}) if page else {}
        programs[key] = {
            "slug": key,
            "name": prod["title"],
            "family": prod["cats"][0] if prod["cats"] else None,
            "categories": prod["cats"],
            "price_usd": float(prod["price"]) if prod["price"] not in (None, "") else None,
            "product_url": prod["url"],
            "program_page_url": page["url"] if page else None,
            "access": "6 months of access from purchase",
            "practice_question_count": pp.get("practice_question_count"),
            "exam_facts": pp.get("facts"),
            "topic_weights": pp.get("topic_weights"),
            "sample_url": pp.get("sample_url"),
            "sample_available": False,
            "sample_question_count": None,
            "_source": {"product_id": prod["id"], "page_id": page["id"] if page else None},
        }

    samples = {}
    unlinked = []
    excluded = []
    attach_methods = {}
    # Title-match index: product name (minus ' Exam Prep') -> core key
    name_index = {}
    for k, p in programs.items():
        nm = re.sub(r"\s+Exam Prep$", "", p["name"]).strip().lower()
        name_index.setdefault(nm, k)

    def resolve_key(qz, course):
        """Authoritative order: the quiz's own _pp_program meta first (the FNP
        sample quiz carries a wrong course_id pointing at NCLEX-PN — course
        keying would mis-serve it), then course slug core, then title match."""
        if qz["program"] and qz["program"] in programs:
            return qz["program"], "program_meta"
        if course:
            k = core(course["slug"])
            if k in programs:
                return k, "course_core"
            alt = re.sub(r"-\d+$", "", k)  # duplicate course slug '...-exam-prep-6'
            if alt in programs:
                return alt, "course_core_stripped"
        t = re.split(r"\s+(?:FREE|Free)\s+", qz["title"])[0].strip().lower()
        t = re.sub(r"\s+exam prep$", "", t).strip()
        if t in name_index:
            return name_index[t], "title_match"
        return (qz["program"] or (core(course["slug"]) if course else "unknown")), "unlinked"

    for qz in samples_raw["quizzes"]:
        course = course_by_id.get(str(qz["course_id"]))
        key, method = resolve_key(qz, course)
        # SAMPLING FENCE (hard): serve ONLY the published fixed sample set —
        # exactly 12 questions and a recorded form of exactly 12. Anything else
        # (e.g. the free DMV full practice exams, 283-299 questions, which carry
        # sample postmeta but are full practice sets) is excluded and logged.
        form = qz["form"] if isinstance(qz["form"], list) else []
        if len(qz["questions"]) != 12 or len(form) != 12:
            excluded.append({"quiz_post_id": qz["quiz_post_id"], "program": qz["program"],
                             "questions": len(qz["questions"]), "form": len(form),
                             "reason": "not a 12-question fixed sample set"})
            continue
        if key in EXCLUDED_SAMPLE_KEYS or qz["program"] in EXCLUDED_SAMPLE_KEYS:
            excluded.append({"quiz_post_id": qz["quiz_post_id"], "program": qz["program"],
                             "questions": len(qz["questions"]), "form": len(form),
                             "reason": "program excluded (see EXCLUDED_SAMPLE_KEYS)"})
            continue
        if key in samples:
            excluded.append({"quiz_post_id": qz["quiz_post_id"], "program": qz["program"],
                             "questions": len(qz["questions"]), "form": len(form),
                             "reason": f"duplicate sample key '{key}' — first set kept"})
            continue
        qs = []
        for q in qz["questions"]:
            answers = []
            letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            correct_letters = []
            for i, a in enumerate(q.get("answers") or []):
                txt = strip_tags(a["answer"]) if a.get("html") else (a["answer"] or "").strip()
                answers.append({"letter": letters[i], "text": txt})
                if a.get("correct"):
                    correct_letters.append(letters[i])
            qs.append({
                "position": q["position"],
                "question": strip_tags(q["question"]),
                "answer_type": q["answer_type"],
                "answers": answers,
                "correct_answer": correct_letters,
                "explanation": strip_tags(q.get("explanation") or "") or None,
            })
        entry = {
            "program_slug": key,
            "quiz_title": qz["title"],
            "question_count": len(qs),
            "sample_url": quiz_links.get(qz["quiz_post_id"]),
            "questions": qs,
            "_source": {"quiz_post_id": qz["quiz_post_id"], "course_id": qz["course_id"],
                        "form_codes": qz["form"], "built_at": qz["built_at"],
                        "attach_method": method},
        }
        attach_methods[method] = attach_methods.get(method, 0) + 1
        if key in programs and method != "unlinked":
            samples[key] = entry
            programs[key]["sample_available"] = True
            programs[key]["sample_question_count"] = len(qs)
            programs[key]["_source"]["quiz_post_id"] = qz["quiz_post_id"]
            if entry["sample_url"]:
                programs[key]["sample_url"] = entry["sample_url"]
        else:
            # Free program (no WooCommerce product): course record is the catalog record.
            entry["free_program"] = True
            entry["course_title"] = course["title"] if course else None
            samples[key] = entry
            unlinked.append(key)

    plist = sorted(programs.values(), key=lambda p: p["name"])
    report = {
        "products_total": len(catalog),
        "programs_with_page": sum(1 for p in plist if p["program_page_url"]),
        "programs_with_facts": sum(1 for p in plist if p["exam_facts"]),
        "programs_with_weights": sum(1 for p in plist if p["topic_weights"]),
        "programs_with_practice_count": sum(1 for p in plist if p["practice_question_count"]),
        "programs_with_sample": sum(1 for p in plist if p["sample_available"]),
        "programs_with_sample_url": sum(1 for p in plist if p["sample_url"]),
        "sample_sets_total": len(samples),
        "free_program_sample_sets": len(unlinked),
        "free_program_keys": sorted(unlinked),
        "excluded_sample_quizzes": excluded,
        "attach_methods": attach_methods,
    }
    (DATA / "programs.json").write_text(json.dumps({"programs": plist}, indent=1))
    (DATA / "samples.json").write_text(json.dumps({"samples": samples}, indent=1))
    (DATA / "build_report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))

if __name__ == "__main__":
    sys.exit(main())
