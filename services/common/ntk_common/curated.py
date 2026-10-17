"""Questions the editor approved for the questions page, and other wordings of them (17.10.2026).

A visitor who asks an approved question — word for word, or in other words — gets the approved (and edited) answer,
not a new one written from scratch:

1. the same question (after normalisation) as an approved one → its answer;
2. a wording matched before → that answer (the editor can reject a match; the model's answer to the same request
   is stored, so asking again costs nothing);
3. otherwise the question's embedding is compared with the approved questions'; the closest ones above
   ``SIMILAR`` go to the small model, which says whether one of them asks the same thing. A match is recorded
   (``same``); the others are recorded as ``related`` and suggested under a new answer.

Nothing here writes an answer: a miss falls through to the Ask engine.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine

from .db.core import execute, row, rows


def normalize_question(q: str) -> str:
    from .ask import normalize_question as n

    return n(q)

SIMILAR = 0.80  # cosine similarity for a question to be a candidate at all
MAX_CANDIDATES = 3
CACHE_SECONDS = 60


@dataclass
class Match:
    answer_id: str | None = None  # the approved answer that answers this question
    related: list[str] = field(default_factory=list)  # approved answers on nearby questions
    how: str = "none"  # exact | remembered | model | none
    similarity: float | None = None


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def sync(conn, items: list[dict], embedder: Any) -> dict:
    """Replace the approved set with ``items`` ({answer_id, question}); embed the questions that are new or reworded."""
    have = {r["answer_id"]: r for r in rows(conn, "SELECT answer_id, question, embedding_model FROM ntk.curated_questions")}
    model = getattr(embedder, "model_id", None) if embedder is not None else None
    keep: set[str] = set()
    todo: list[dict] = []
    for it in items:
        aid, q = str(it.get("answer_id") or "").strip(), str(it.get("question") or "").strip()
        if not aid or not q:
            continue
        keep.add(aid)
        old = have.get(aid)
        if old is None or old["question"] != q or (model and old["embedding_model"] != model):
            todo.append({"answer_id": aid, "question": q})
    vecs: list[list[float] | None] = [None] * len(todo)
    if todo and embedder is not None:
        batch = getattr(embedder, "batch", None)
        vecs = list(batch([t["question"] for t in todo])) if batch else [embedder(t["question"]) for t in todo]
    import json

    for t, v in zip(todo, vecs):
        execute(conn, """INSERT INTO ntk.curated_questions (answer_id, question, normalized, embedding, embedding_model, updated_at)
                         VALUES (:a, :q, :n, CAST(:e AS jsonb), :m, now())
                         ON CONFLICT (answer_id) DO UPDATE SET question = EXCLUDED.question, normalized = EXCLUDED.normalized,
                           embedding = EXCLUDED.embedding, embedding_model = EXCLUDED.embedding_model, updated_at = now()""",
                {"a": t["answer_id"], "q": t["question"], "n": normalize_question(t["question"]),
                 "e": json.dumps(v) if v is not None else None, "m": model if v is not None else None})
    gone = [a for a in have if a not in keep]
    if gone:
        execute(conn, "DELETE FROM ntk.curated_questions WHERE answer_id = ANY(:g)", {"g": gone})
    return {"approved": len(keep), "embedded": len([v for v in vecs if v is not None]), "removed": len(gone)}


class Matcher:
    def __init__(self, engine: Engine, embedder: Any, runner: Any, corpus_version=lambda: "cv"):
        self.engine, self.embedder, self.runner, self.corpus_version = engine, embedder, runner, corpus_version
        self._cache: tuple[float, list[dict]] | None = None

    def invalidate(self) -> None:
        self._cache = None

    def approved(self) -> list[dict]:
        if self._cache and time.monotonic() - self._cache[0] < CACHE_SECONDS:
            return self._cache[1]
        with self.engine.connect() as conn:
            items = rows(conn, "SELECT answer_id, question, normalized, embedding FROM ntk.curated_questions")
        self._cache = (time.monotonic(), items)
        return items

    def match(self, question: str) -> Match:
        items = self.approved()
        if not items:
            return Match()
        norm = normalize_question(question)
        by_id = {i["answer_id"]: i for i in items}
        for i in items:
            if i["normalized"] == norm:
                return Match(i["answer_id"], how="exact", similarity=1.0)
        with self.engine.connect() as conn:
            seen = rows(conn, "SELECT answer_id, decision, similarity FROM ntk.question_matches WHERE normalized = :n",
                        {"n": norm})
        rejected = {s["answer_id"] for s in seen if s["decision"] == "rejected"}
        for s in seen:
            if s["decision"] == "same" and s["answer_id"] in by_id:
                return Match(s["answer_id"], [x["answer_id"] for x in seen if x["decision"] == "related"
                                              and x["answer_id"] in by_id], "remembered", s["similarity"])
        if self.embedder is None:
            return Match()
        vec = self.embedder(question)
        scored = sorted(((cosine(vec, i["embedding"]), i) for i in items
                         if i.get("embedding") and i["answer_id"] not in rejected), key=lambda x: -x[0])
        cands = [(s, i) for s, i in scored[:MAX_CANDIDATES] if s >= SIMILAR]
        if not cands:
            return Match()
        chosen = self._ask_model(question, cands)
        decided = []
        for s, i in cands:
            decided.append({"a": i["answer_id"], "s": round(s, 4),
                            "d": "same" if chosen is not None and i["answer_id"] == chosen else "related"})
        with self.engine.begin() as conn:
            for d in decided:
                execute(conn, """INSERT INTO ntk.question_matches (normalized, question, answer_id, similarity, decision, decided_by)
                                 VALUES (:n, :q, :a, :s, :d, 'model') ON CONFLICT (normalized, answer_id) DO UPDATE
                                 SET decision = EXCLUDED.decision, similarity = EXCLUDED.similarity
                                 WHERE ntk.question_matches.decision <> 'rejected'""",
                        {"n": norm, "q": question, **d})
        related = [d["a"] for d in decided if d["d"] == "related"]
        if chosen:
            return Match(chosen, related, "model", next(d["s"] for d in decided if d["a"] == chosen))
        return Match(None, related, "model", decided[0]["s"])

    def _ask_model(self, question: str, cands: list[tuple[float, dict]]) -> str | None:
        if self.runner is None:
            return None
        payload = {"question": question,
                   "candidates": [{"n": k + 1, "question": i["question"]} for k, (_s, i) in enumerate(cands)]}
        run = self.runner.run("question_match", payload, input_source_ids=[], corpus_version=self.corpus_version(),
                              role="qa_relation")
        if not run.ok:
            return None
        n = run.output.get("match")
        if isinstance(n, int) and 1 <= n <= len(cands) and float(run.output.get("confidence") or 0) >= 0.6:
            return cands[n - 1][1]["answer_id"]
        return None


def reject(conn, match_id: str, actor: str) -> bool:
    r = row(conn, "SELECT id FROM ntk.question_matches WHERE id = CAST(:i AS uuid)", {"i": match_id})
    if r is None:
        return False
    execute(conn, "UPDATE ntk.question_matches SET decision = 'rejected', decided_by = :by WHERE id = CAST(:i AS uuid)",
            {"i": match_id, "by": actor})
    return True


def matches(conn, limit: int = 200) -> list[dict]:
    return rows(conn, """SELECT m.id::text AS id, m.question, m.answer_id, m.similarity, m.decision, m.decided_by,
                                m.created_at::text AS created_at, c.question AS approved_question
                         FROM ntk.question_matches m LEFT JOIN ntk.curated_questions c ON c.answer_id = m.answer_id
                         ORDER BY m.created_at DESC LIMIT :l""", {"l": limit})
