# Testing Policy

This document defines test expectations and validation requirements for code changes in this repository.

It is a **policy document**, not a workflow script.

---

## 1. Scope

Apply this document when:

- modifying existing code
- adding new behavior
- fixing defects
- changing data flow or integration boundaries

---

## 2. Core principles

### 2.1 Tests validate behavior

- Tests must verify observable behavior, not internal implementation details.
- “runs without error” is not a valid assertion.

---

### 2.2 Tests follow change impact

- Only test what is affected by the current change.
- Do not run or modify unrelated tests.

---

### 2.3 Tests do not define behavior

- Do not change business logic to make tests pass.
- Fix either:
  - implementation (if incorrect), or
  - test (if invalid)

---

## 3. Test layers

Tests must follow this structure:

```text
tests/
├── unit/
├── integration/
├── e2e/
```

### 3.1 Unit

- Verifies small, isolated logic
- No external dependencies

### 3.2 Integration

- Verifies interaction between components
- Covers a meaningful processing step

### 3.3 E2E

- Verifies a complete user-visible or system-visible flow
- Represents real usage paths

---

## 4. When to run tests

### 4.1 Always required

After any code change:

- run affected unit tests
- run affected integration tests (if applicable)

---

### 4.2 Required when scope increases

Run E2E tests when:

- modifying main flow or pipeline
- fixing issues reported in E2E scenarios
- completing a feature that affects end-to-end behavior

---

### 4.3 Broader validation

Run broader test scopes when:

- shared components are modified
- public interfaces change
- multiple modules are affected

---

## 5. Adding or updating tests

### 5.1 When required

Add or update tests when:

- introducing new behavior
- fixing a bug
- changing observable behavior

---

### 5.2 Minimum requirements

A valid test must include:

- clear input
- execution step
- meaningful assertion

---

### 5.3 Avoid

- empty tests
- tests without assertions
- tests that only check execution success

---

## 6. Test integrity rules

- Do not weaken assertions to avoid failure.
- Do not delete failing tests without justification.
- Do not bypass test execution.

---

## 7. Completion criteria

A change involving behavior is not complete unless:

- relevant tests pass
- required new or updated tests are present (if applicable)
- no unintended failures are introduced

---

## 8. Reporting requirements

When reporting test results:

- specify which tests were executed
- specify why those tests were selected
- identify any skipped or missing validation
- distinguish:
  - test-based validation
  - reasoning-based validation

Do not report only:

- “tests passed”
- raw pytest output

---

## 9. Anti-patterns

The following are explicitly disallowed:

- changing logic to satisfy tests
- using weak or irrelevant assertions
- ignoring failing tests
- treating lack of failure as success
- expanding test scope without reason

---

## 10. Maintenance rule

When updating this document:

- keep rules minimal and enforceable
- avoid duplicating content from AGENTS.md or other policy files
- avoid introducing workflow-style instructions
- prefer clear constraints over detailed procedures