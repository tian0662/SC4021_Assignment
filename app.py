import os
import time
import re
import unicodedata
from typing import Any

import requests
from flask import Flask, render_template, request

app = Flask(__name__)

SOLR_URL = os.getenv("SOLR_URL", "http://localhost:8983/solr/reddit_ai/select")
DEFAULT_ROWS = 20

STOPWORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "be",
    "to",
    "of",
    "in",
    "on",
    "for",
    "at",
    "by",
    "with",
    "and",
    "or",
}
RELATIONAL_STOPWORDS = {"to", "of", "in", "on"}


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def lemmatize_token(token: str) -> str:
    if len(token) <= 3:
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("ly") and len(token) > 5:
        return token[:-2]
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 4:
        return token[:-1]
    return token


def extract_concepts(raw_query: str) -> list[str]:
    query = strip_accents(raw_query)
    phrases = re.findall(r"\"[^\"]+\"", query)
    query_without_phrases = re.sub(r"\"[^\"]+\"", " ", query)

    tokens = re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)?", query_without_phrases)
    concepts: list[str] = []
    for idx, token in enumerate(tokens):
        lower = token.lower()
        if lower not in STOPWORDS:
            concepts.append(lower)
            continue

        next_token = tokens[idx + 1].lower() if idx + 1 < len(tokens) else ""
        prev_token = tokens[idx - 1].lower() if idx > 0 else ""
        if lower in RELATIONAL_STOPWORDS and prev_token and next_token and next_token not in STOPWORDS:
            concepts.append(lower)

    return phrases + concepts


def build_flexible_query(raw_query: str) -> str:
    concepts = extract_concepts(raw_query)
    lemma_terms: list[str] = []

    for concept in concepts:
        if concept.startswith('"') and concept.endswith('"'):
            continue
        lemma = lemmatize_token(concept)
        if lemma and lemma != concept:
            lemma_terms.append(lemma)

    concept_set = {c for c in concepts if not c.startswith('"')}
    if "artificially" in concept_set and "intelligent" in concept_set:
        concepts.extend(["artificial", "intelligence", "\"artificial intelligence\""])

    merged: list[str] = []
    seen = set()
    for item in concepts + lemma_terms:
        if item not in seen:
            merged.append(item)
            seen.add(item)

    return " ".join(merged).strip()


@app.get("/")
def index() -> str:
    q = request.args.get("q", "").strip()
    doc_type = request.args.get("type", "")
    subreddit = request.args.get("subreddit", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    sort = request.args.get("sort", "score desc")

    results: list[dict[str, Any]] = []
    response_ms = None
    num_found = 0
    facets: dict[str, Any] = {}
    error = ""
    processed_query = ""

    if q:
        processed_query = build_flexible_query(q)
        effective_query = q
        if processed_query and processed_query.lower() != q.lower():
            effective_query = f"({q}) OR ({processed_query})"

        fq = []
        if doc_type:
            fq.append(f"type:{doc_type}")
        if subreddit:
            fq.append(f"subreddit:{subreddit}")
        if date_from or date_to:
            date_from_safe = date_from + "T00:00:00Z" if date_from else "*"
            date_to_safe = date_to + "T23:59:59Z" if date_to else "*"
            fq.append(f"created_date:[{date_from_safe} TO {date_to_safe}]")

        params = {
            "q": effective_query,
            "defType": "edismax",
            "qf": "title^2 body full_text^3",
            "pf": "full_text^6 title^3",
            "mm": "2<75%",
            "fl": "id,type,title,body,subreddit,score,created_date,thread_id",
            "rows": DEFAULT_ROWS,
            "start": 0,
            "wt": "json",
            "hl": "true",
            "hl.fl": "title,body,full_text",
            "hl.simple.pre": "<mark>",
            "hl.simple.post": "</mark>",
            "facet": "true",
            "facet.field": ["type", "subreddit"],
            "sort": sort,
        }
        if fq:
            params["fq"] = fq

        start = time.perf_counter()
        try:
            resp = requests.get(SOLR_URL, params=params, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
            elapsed = (time.perf_counter() - start) * 1000
            response_ms = round(elapsed, 2)

            docs = payload.get("response", {}).get("docs", [])
            num_found = payload.get("response", {}).get("numFound", 0)
            highlighting = payload.get("highlighting", {})

            for doc in docs:
                hl = highlighting.get(doc["id"], {})
                snippet = ""
                for field in ("full_text", "body", "title"):
                    if hl.get(field):
                        snippet = hl[field][0]
                        break
                if not snippet:
                    snippet = (doc.get("body") or doc.get("title") or "")[:260]

                results.append(
                    {
                        **doc,
                        "snippet": snippet,
                    }
                )

            facets = payload.get("facet_counts", {}).get("facet_fields", {})
        except requests.RequestException as exc:
            error = f"Failed to query Solr: {exc}"

    return render_template(
        "index.html",
        q=q,
        doc_type=doc_type,
        subreddit=subreddit,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
        results=results,
        response_ms=response_ms,
        num_found=num_found,
        facets=facets,
        error=error,
        processed_query=processed_query,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
