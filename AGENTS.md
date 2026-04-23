# AGENTS.md

# Whale Repository Guide

This file defines repository-wide guidance for Codex in the Whale project.

Keep this file short and practical.
Use it for shared repository expectations, not as a replacement for language-specific policy documents or task workflows.

---

## 1. Scope

- This file applies to the whole repository.
- It defines shared repository guidance across tasks and languages.
- Language-specific constraints should live in repository policy documents and, when useful, specialized subagents.

---

## 2. Working style

- Keep responses concise and decision-oriented.
- Prioritize conclusions, next steps, impact scope, and constraints.
- Do not dump large code blocks unless explicitly requested.
- Prefer outputs that are easy to review, copy, and continue from.

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
- Do not modify files that are outside the current task without clear need.
- Avoid formatting churn unrelated to the requested change.
- Keep new implementations consistent with the existing repository structure.

---

## 5. Task routing

- Use the Python subagent for Python-specific implementation and validation work.
- Non-Python tasks should not automatically inherit Python-specific policy details.

---

## 6. Repository policy documents

- For Python tasks, also follow the documents under `.codex/policies/`.
- These files are repository policy documents and review criteria.
- They are not native Codex rule objects, but they are mandatory project constraints when applicable.

---

## 7. Reporting requirements

After completing a task, report clearly:

1. what guidance and policy documents were followed
2. what files or sections were changed
3. what checks and tests were run
4. what conclusions come from policy compliance work
5. what conclusions come from tool-based validation
6. any remaining risks, environment limits, or unresolved ambiguities

Do not report completion using only “done”, “passed”, or raw tool output.

---

## 8. Prohibited behavior

- Do not skip repository guidance and jump straight to editing.
- Do not treat tool defaults as the source of truth.
- Do not equate “checks passed” with “all repository requirements satisfied”.
- Do not claim completion without validation.
- Do not expand a local task into a broad redesign without need.