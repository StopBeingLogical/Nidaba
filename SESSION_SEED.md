# NIDABA Session Seed
**Last Updated:** 2026-03-18
**Project:** NIDABA — The Scribe & Archivist
**Purpose:** Canonical context for the corpus deconstruction and smelting pipeline.

---

## 1. Project Intent
Nidaba is the bridge between a sprawling, heterogeneous legacy corpus (~900MB) and a high-signal, refined knowledge base. It uses local-first embedding (Ollama/Metal) to atomize unstructured data into a queryable vector store.

## 2. Technical Stack
- **Engine:** Python 3.14 (AsyncIO / high-concurrency)
- **Embedding:** `nomic-embed-text` via local Ollama server
- **Database:** ChromaDB (Persistent local store)
- **Orchestration:** Gemini CLI (Analyst) & Claude Code (Developer)

## 3. The Workflow (Propagated from Seshat)
1. **Staging:** Raw documents added to `/staging`.
2. **Crush:** `nidaba_crush.py` atomizes and embeds new content.
3. **Enrich:** `nidaba_enrich_metadata.py` restores historical timestamps.
4. **Smelt:** (Future) Refinement interviews to create canonical seeds.

## 4. Current State
- **Corpus Resolution:** 400k+ atoms embedded.
- **Milestone:** Successfully implemented recursive splitting for extra-long conversational atoms.
- **Repository:** Mirrored to Forgejo (Atlas) and GitHub (External).

---
*Follow the Seshat bootstrap protocol before modifying this project.*
