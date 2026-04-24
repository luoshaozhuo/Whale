# Python Typing Policy

This document defines Python typing expectations for this repository.

It is a **policy document**, not a typing tutorial.

---

## 1. Scope

Apply this document when:

- writing Python code
- modifying Python code
- updating public interfaces
- changing function, method, class, or data-object signatures

---

## 2. Core principles

### 2.1 Typing should clarify interfaces

- Use type annotations to make interfaces explicit.
- Prefer annotations that improve readability and maintenance.
- Do not add types mechanically if they make code harder to understand.

### 2.2 Type changes must stay local

- Do not rewrite unrelated logic only to satisfy typing.
- Keep typing fixes scoped to the task unless a broader fix is clearly necessary.

### 2.3 Repository configuration is authoritative

- Follow the repository typing configuration.
- Use repository-configured type checking as the baseline validation tool.

---

## 3. Required annotations

- Public functions must have parameter types.
- Public functions must have return types.
- Public methods must have parameter types.
- Public methods must have return types.
- Internal functions with clear input/output contracts should also be annotated.
- Data objects should expose clear field types when their structure is part of the task.

---

## 4. Preferred typing style

- Use Python 3.10+ type syntax.
- Prefer precise types over vague umbrella types when the shape is known.
- Prefer explicit optionality instead of leaving absence implicit.
- Prefer stable interface types over overly implementation-specific details when appropriate.

---

## 5. Use of broad escape hatches

The following should be avoided unless clearly necessary:

- `Any`
- `type: ignore`
- `cast(...)`
- broad untyped containers when structure is known

If one of them is necessary:

- keep the scope minimal
- use it only at the constrained location
- do not spread it through unrelated code

---

## 6. Function and method boundaries

- Parameter and return types should match actual behavior.
- Do not declare a broader or narrower contract than the implementation really supports.
- If a signature changes observable behavior or compatibility, update affected call sites and validation accordingly.

---

## 7. Data structure typing

- Use explicit types for structured data when structure matters to the task.
- Do not leave stable multi-field payloads effectively untyped.
- Prefer named and understandable typed structures over opaque nested containers when clarity is needed.

---

## 8. Error-prone typing patterns

The following are explicitly discouraged unless required:

- adding annotations that do not reflect runtime behavior
- using `Any` to bypass interface clarity
- silencing type errors without understanding the cause
- expanding a local typing issue into a large unrelated refactor

---

## 9. Validation requirements

After relevant changes:

- run the repository-configured type checks for the affected scope
- address typing issues introduced by the current change
- distinguish between:
  - typing policy compliance
  - tool-reported type-check results

---

## 10. Reporting requirements

When reporting typing-related work:

- state what interfaces were typed or updated
- state any narrow exceptions such as `type: ignore`, `cast`, or unavoidable `Any`
- state what type validation was run
- state any remaining typing limits caused by existing code or repository constraints

Do not report only:
- “typing fixed”
- “mypy passed”

---

## 11. Maintenance rule

When updating this document:

- keep rules concrete and reviewable
- avoid duplicating style, docstring, or testing policy
- prefer a small number of strong constraints
- avoid turning this file into a general typing guide