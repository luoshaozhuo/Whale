# python-docstrings.md

# Python Docstring Policy

This document defines docstring expectations for Python code in this repository.

It is a **policy document**, not a documentation tutorial.

---

## 1. Scope

Apply this document when:

- writing Python code
- modifying Python code
- adding or changing public interfaces
- updating modules, classes, or functions whose interface meaning is part of the task

---

## 2. Core principles

### 2.1 Docstrings explain interface meaning

- Docstrings must explain responsibility, interface meaning, and relevant constraints.
- Do not use docstrings to restate obvious implementation details.

### 2.2 Docstrings should stay proportional

- Keep docstrings concise.
- Add detail only where interface semantics, inputs, outputs, side effects, or exceptions need clarification.

### 2.3 Public surface matters most

- Prioritize module, class, and public function or method docstrings.
- Do not add unnecessary docstrings to trivial private helpers unless the task clearly requires them.

---

## 3. Required coverage

Docstrings are required for the following when they are part of the task scope:

- modules with repository-visible interface meaning
- public classes
- public functions
- public methods

Add or update docstrings when:

- introducing a new public interface
- changing the meaning of an existing public interface
- modifying behavior that affects documented inputs, outputs, exceptions, or side effects

---

## 4. Style requirements

- Use Google-style docstrings.
- Keep wording direct and concrete.
- Describe the interface from the caller’s perspective.
- Prefer repository-consistent wording and terminology.

---

## 5. Content expectations

A docstring should include, when relevant:

- what the object or callable is responsible for
- important input expectations
- return meaning
- important side effects
- raised exceptions that callers should know about
- important behavioral constraints

Do not include sections mechanically when they add no value.

Examples:
- If there are no meaningful parameters, do not force an `Args` section.
- If there is no meaningful return value, do not force a `Returns` section.

---

## 6. Alignment rules

- Docstrings must match the current implementation behavior.
- Do not leave stale docstrings after behavior changes.
- Do not document behavior that the code does not actually provide.
- If typing or naming changes affect interface meaning, update docstrings accordingly.

---

## 7. Prohibited patterns

The following are explicitly discouraged:

- repeating the function name in sentence form without useful meaning
- restating obvious line-by-line behavior
- writing long narrative explanations better suited for external docs
- adding placeholder docstrings with no review value
- preserving outdated docstrings after interface changes

---

## 8. Validation requirements

After relevant changes:

- review affected public docstrings for correctness
- ensure new or updated public interfaces are documented where required
- run repository-configured docstring or lint checks for the affected scope, if configured

Distinguish between:
- docstring policy compliance
- tool-based lint or style results

---

## 9. Reporting requirements

When reporting docstring-related work:

- state which public interfaces had docstrings added or updated
- state whether the change was coverage-related or behavior-alignment-related
- state what validation was performed
- note any remaining documentation gaps that were intentionally left outside the current task scope

Do not report only:
- “docstrings added”
- “docstrings fixed”
- “docstring checks passed”

---

## 10. Maintenance rule

When updating this document:

- keep it short and reviewable
- avoid duplicating typing, style, or testing policy
- avoid turning it into a generic writing guide
- prefer strong interface-focused constraints over broad advice