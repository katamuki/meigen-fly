# Development Guidelines

## Project context

This is a small, independently developed website.

The administration interface is used primarily for viewing data. The project does not handle personal information, payment information, or other sensitive data.

Implement changes in proportion to the project's actual scale and risk.

## Implementation principles

- Prefer the simplest implementation that satisfies the current requirement.
- Do not introduce abstractions, layers, configuration options, or dependencies solely for hypothetical future needs.
- Reuse the existing architecture and conventions unless there is a concrete reason to change them.
- Prefer local, focused changes over broad refactoring.
- Avoid enterprise-oriented designs intended for large teams, high traffic, multi-tenancy, strict auditing, or complex authorization unless explicitly requested.
- Add validation, error handling, logging, and tests according to the likelihood and impact of failure.
- Preserve basic security practices. Do not weaken authentication, authorization, input validation, secret handling, or dependency safety in the name of simplicity.
- If a substantially more complex design is being considered, first explain the concrete problem it solves and why the simpler approach is insufficient.

## Scope discipline

Do not implement speculative features or unrelated improvements.

When multiple approaches are valid, prefer the one with:

1. fewer moving parts;
2. less new code;
3. fewer dependencies;
4. lower maintenance cost;
5. behavior that is easy to understand and verify.
