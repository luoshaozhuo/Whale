# Python Style Policy

This document defines Python implementation and code structure expectations for this repository.

It is a **policy document**, not a tutorial and not a design pattern catalog.

---

## 1. Scope

Apply this document when:

- writing Python code
- modifying Python code
- refactoring Python code within task scope

---

## 2. Core principles

### 2.1 Prefer clarity

- Prefer direct, readable code over clever or highly abstract code.
- Keep control flow easy to trace.
- Avoid deeply nested logic when a simpler structure is possible.

### 2.2 Prefer local changes

- Keep changes small and task-bounded.
- Do not introduce broad structural changes unless required by the task.

### 2.3 Prefer consistency

- Follow existing repository structure and local conventions.
- Do not introduce a new style in one file when the surrounding code follows another established style.

---

## 3. Formatting and tooling

- Follow repository formatting and lint configuration.
- Use repository-configured tools as the default formatting and lint baseline.
- Do not introduce formatting-only churn outside the changed scope.

---

## 4. Imports and module hygiene

- Remove unused imports.
- Keep imports consistent with repository tooling and local file conventions.
- Do not leave debug code, dead variables, or commented-out implementation fragments.

---

## 5. Function and method design

- Prefer small functions with clear responsibility.
- Split logic when a function contains clearly separable stages.
- Do not extract helpers so aggressively that the main flow becomes harder to read.
- Public functions and methods should present stable and clear interfaces.

---

## 6. Class design

- Introduce a class only when state, lifecycle, or clear responsibility grouping justifies it.
- Do not create classes for logic that is clearer as functions.
- Keep class responsibilities narrow.
- Avoid large utility classes with unrelated behavior.

---

## 7. Composition and inheritance

- Prefer composition by default.
- Use inheritance only when there is a clear and stable is-a relationship.
- Avoid inheritance chains created only for small-scale reuse.
- If inheritance makes behavior order difficult to understand, use composition instead.

---

## 8. External boundary handling

- Isolate external protocol, library, storage, or schema differences at clear boundaries.
- Do not leak third-party or transport-specific structures into core business logic unless that is already the established repository pattern.
- Keep translation and normalization logic close to the boundary where it is needed.

---

## 9. Data modeling

- Use explicit data objects when stable structure matters.
- Do not rely on loosely shaped dictionaries where a clear data structure is needed for readability or safety.
- Keep transport objects, domain objects, and persistence-facing structures conceptually separate when the task requires that distinction.

---

## 10. Error handling

- Handle errors at an appropriate boundary.
- Do not silently swallow exceptions.
- Do not introduce broad exception handling without a clear purpose.
- Error handling should preserve debuggability and expected behavior.

---

## 11. Prohibited patterns

The following are explicitly discouraged unless the task clearly requires them:

- introducing patterns for very small problems
- adding abstraction layers without immediate benefit
- mixing unrelated refactoring with functional changes
- hiding core business logic behind excessive indirection
- preserving dead compatibility code without need

---

## 12. Maintenance rule

When updating this document:

- keep it short and enforceable
- avoid duplicating typing, docstring, or testing policy
- avoid turning it into a pattern handbook
- prefer strong, reviewable constraints over many weak suggestions