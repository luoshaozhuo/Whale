# Repository Policies

This directory contains repository policy documents for the Whale project.

These files define project-specific engineering constraints, review criteria, and implementation expectations for applicable tasks.

---

## 1. What these files are

These documents are:

- repository policy documents
- repository review criteria
- repository implementation constraints when applicable

They are the project’s checked-in source of truth for detailed local conventions.

---

## 2. What these files are not

These documents are not:

- native Codex rule objects
- a replacement for `AGENTS.md`
- a replacement for subagents
- arbitrary prompt storage

Use them as repository-local policy documents.

---

## 3. Relationship to other Codex customization layers

### `AGENTS.md`
Use `AGENTS.md` for short, shared repository guidance:
- working style
- engineering boundaries
- reporting expectations
- task routing

### subagents
Use subagents for thin specialization:
- role identity
- routing target
- concise behavior boundaries for a specific class of work

Subagents should not duplicate the full contents of these policy files.

### skills
Use skills when you need richer reusable workflows, instructions, resources, or scripts.

---

## 4. Applicability

A policy document is mandatory when its scope matches the current task.

Typical examples:
- Python code changes
- typing updates
- docstring work
- test updates
- Python quality remediation

Non-applicable policies should not be treated as universal constraints.

---

## 5. Recommended usage model

For Python work:

1. read the applicable `AGENTS.md` files in scope
2. identify the relevant documents in this directory
3. apply the smallest compliant change
4. run relevant checks and affected tests
5. report both:
   - policy-compliance work
   - tool-validation results

---

## 6. Maintenance rules

When editing these documents:

- keep them concrete and reviewable
- avoid vague motivational text
- avoid duplicating repository-wide guidance already captured in `AGENTS.md`
- avoid copying large portions of these files into subagent definitions
- prefer stable policy language over temporary task instructions

---

## 7. Suggested file meanings

Suggested conventions for files in this directory:

- `engineering-general.md`:
  cross-cutting engineering expectations for applicable implementation work

- `python-style.md`:
  Python code style, implementation shape, and structural preferences

- `python-typing.md`:
  Python typing expectations and boundaries

- `python-docstrings.md`:
  Python docstring expectations and documentation rules

- `testing-policy.md`:
  test-layer expectations, validation requirements, and implementation-state criteria

Adjust filenames if needed, but keep each file narrowly scoped and easy to apply.