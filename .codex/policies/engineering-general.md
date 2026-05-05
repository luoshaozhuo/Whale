# Engineering General Policy

This document defines repository-wide engineering constraints that apply to implementation work when relevant.

It is a **policy document**, not a general guideline and not a prompt container.

---

## 1. Scope

Apply this document when:

- implementing or modifying code
- refactoring within a defined task boundary
- fixing defects
- updating behavior that affects execution or data flow

Do not apply this document to:

- pure documentation tasks
- non-code exploratory discussions

---

## 2. Core principles

### 2.1 Minimal change

- Prefer the smallest possible change that satisfies the task.
- Do not expand a local change into a global refactor.
- Do not modify unrelated files.

### 2.2 Behavior preservation

- Preserve existing behavior unless the task explicitly requires change.
- Do not introduce silent behavior changes.

### 2.3 Local reasoning

- Make decisions based on the current repository context.
- Do not introduce patterns or abstractions based on hypothetical future needs.

---

## 3. Change boundaries

### 3.1 Allowed changes

- Code directly required by the task
- Necessary wiring to make the change functional
- Minimal supporting changes (imports, types, config adjustments)

### 3.2 Disallowed changes

- Unrelated refactors
- Style-only edits outside the modified scope
- Renaming or restructuring without explicit need
- Large-scale formatting changes

---

## 4. Implementation constraints

### 4.1 Clarity over cleverness

- Prefer direct, readable implementations.
- Avoid implicit behavior chains that are hard to trace.
- Avoid overuse of abstraction layers.

### 4.2 Structural consistency

- Follow existing repository structure and conventions.
- Do not introduce new architectural patterns unless required by the task.

### 4.3 Dependency discipline

- Do not introduce new dependencies without clear need.
- Prefer existing utilities over adding new abstractions.

### 4.4 Data access — SQLAlchemy first

Data access follows a progressive-disclosure rule: start with the simplest
tool that satisfies the query and escalate only when there is a concrete,
demonstrated need.

| Tier | Approach                                          | When                                                                                       |
| ---- | ------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| 1    | SQLAlchemy ORM query builder                      | Default — every new query starts here                                                      |
| 2    | Raw SQL via `text()`                              | Complex queries the ORM cannot express cleanly (CTEs, window functions, vendor-specific DDL) |
| 3    | Dedicated query function / repository method      | The same query is reused in three or more call sites                                       |
| 4    | DAO or query-object class                         | Query carries state, needs multiple execution strategies, or must compose several raw-SQL fragments |

Constraints:

- **Do not create DAO wrappers for single-call-site ORM queries.**
  If a query is a one-liner `select(Model).where(…)` and used in exactly
  one place, it belongs inline at the call site.
- **Raw SQL must live close to its consumer**, not in a generic "utils" or
  "helpers" module, unless it is reused per tier-3 or tier-4.
- **Prefer repository methods over free functions.** If a query is reused,
  add it as a method on the existing repository or adapter that already
  owns that domain concept.  Do not create a standalone DAO for one or two
  queries.
- **Avoid public static query helpers** that take a session as a
  parameter — session-coupled queries belong on instance methods of the
  class that already holds the session.

### 4.5 Avoid speculative abstraction

Do not introduce query methods, views, or path-manipulation utilities
because they *might* be needed.  Add them only when a concrete call site
requires them.

---

## 5. Refactoring rules

- Refactor only when necessary for the current task.
- Keep refactoring local and bounded.
- Do not mix feature changes and large refactors in one step.

---

## 6. Validation requirements

After making changes:

### 6.1 Required validation

- Run relevant checks (lint, typing, etc.)
- Run affected tests

### 6.2 Validation scope

- Only run what is impacted by the change
- Expand scope only if the change affects:
  - shared components
  - entrypoints
  - integration flows

### 6.3 Prohibited validation shortcuts

- Do not treat “no runtime error” as success
- Do not skip validation steps

---

## 7. Test integrity

- Do not change business logic just to make tests pass
- Do not weaken assertions to avoid failures
- Tests must validate behavior, not just execution

---

## 8. Completion criteria

A change is considered complete only if:

- the implementation satisfies the task
- validation steps have been executed
- no unintended behavior changes are introduced
- the change remains within defined boundaries

---

## 9. Reporting expectations

When reporting work:

- state what was changed
- state what was intentionally NOT changed
- state what validation was performed
- separate:
  - policy-compliance reasoning
  - tool-based results

Do not:

- report only “done”
- report only tool outputs
- omit affected scope

---

## 10. Anti-patterns

The following are explicitly disallowed:

- over-engineering small changes
- introducing patterns without necessity
- spreading changes across unrelated modules
- mixing cleanup with functional changes
- relying solely on tool output as proof of correctness

---

## 11. Maintenance rule

When updating this document:

- keep rules concrete and enforceable
- remove duplication with AGENTS.md
- avoid adding language-specific rules (those belong in other policy files)
- prefer fewer, stronger constraints over many weak ones