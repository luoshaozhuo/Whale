# CLAUDE.md

# Whale Repository Guide

This file defines repository-wide guidance for Claude Code in the Whale project.
It is aligned with AGENTS.md (the Codex equivalent) and references the same shared policy documents.

---

## 1. Scope

- This file applies to the whole repository.
- Language-specific constraints live in `.codex/policies/` — shared across Codex and Claude Code.

---

## 2. Working style

- Keep responses concise and decision-oriented.
- Prioritize conclusions, next steps, impact scope, and constraints.
- Do not dump large code blocks unless explicitly requested.

---

## 3. Engineering approach

- Prefer incremental delivery and the smallest useful change.
- Avoid over-design and avoid introducing abstractions before they are needed.
- Preserve existing behavior unless the task explicitly changes it.
- Refactor in stages after behavior is stable, not preemptively.
- Validate changes with relevant checks and tests.

---

## 4. Change boundaries

- Do not perform unrelated refactors.
- Do not modify files outside the current task without clear need.
- Avoid formatting churn unrelated to the requested change.
- Keep new implementations consistent with the existing repository structure.

---

## 5. Task routing

- For Python implementation and validation, use Agent tool with subagent_type="general-purpose" and provide the `.codex/policies/` documents as context.
- Non-Python tasks should not inherit Python-specific policy details.

---

## 6. Repository policy documents

For Python tasks, Claude Code must follow the documents under `.codex/policies/`:
- `engineering-general.md` — cross-cutting engineering constraints
- `python-style.md` — Python code style and structure
- `python-typing.md` — Python typing expectations
- `python-docstrings.md` — Python docstring expectations
- `testing-policy.md` — test layers, validation, and completion criteria

These are mandatory project constraints when the task scope matches.

---

## 7. Reporting requirements

After completing a task, report:

1. what guidance and policy documents were followed
2. what files or sections were changed
3. what checks and tests were run
4. what conclusions come from policy compliance work
5. what conclusions come from tool-based validation
6. any remaining risks, environment limits, or unresolved ambiguities

Do not report completion using only "done", "passed", or raw tool output.

---

## 8. Prohibited behavior

- Do not skip repository guidance and jump straight to editing.
- Do not treat tool defaults as the source of truth.
- Do not equate "checks passed" with "all repository requirements satisfied".
- Do not claim completion without validation.
- Do not expand a local task into a broad redesign without need.
