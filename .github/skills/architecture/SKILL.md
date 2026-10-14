---
name: architecture
description: "ClipFactory architecture checklist. Use when designing a module, adding a dependency, creating a port/adapter, placing logic in a layer, deciding whether an abstraction is justified, or writing an ADR."
---
# Architecture skill

Canonical sources (do not duplicate them — read them):
[architecture/README.md](../../../doc/specifications/architecture/README.md),
[application-architecture.md](../../../doc/specifications/architecture/application-architecture.md),
[provider-architecture.md](../../../doc/specifications/architecture/provider-architecture.md),
[decisions/](../../../doc/specifications/decisions/README.md).

## Where does this logic go?

| If the logic… | Put it in |
|---|---|
| Is a rule over domain data, no I/O | `domain/` (entity method or pure function) |
| Coordinates repositories/providers for one stage | a feature package use case |
| Decides workflow routing | `workflow/` edges using state + Evaluation flags (routing table lives in `domain`) |
| Talks to an external service, DB, filesystem, subprocess | `infrastructure/` behind a port |
| Translates HTTP ↔ use case | `api/` |
| Wires implementations together | `bootstrap.py` |

## Before adding an abstraction

- [ ] Is there a consumer **now** (not "later")?
- [ ] Does a requirement or ADR need it?
- [ ] Would a function or module suffice instead of a class hierarchy?
- [ ] Does it duplicate an existing port or helper?
If any answer is weak, don't add it.

## Before adding a dependency

- [ ] Not on the prohibited list ([system-architecture § Prohibited technology](../../../doc/specifications/architecture/system-architecture.md#prohibited-technology)).
- [ ] Solves a concrete requirement; one-line justification ready.
- [ ] Used only in the allowed layer.
- [ ] Architectural impact? → write an ADR.

## Adding a provider

Follow [provider-architecture § Adding a provider](../../../doc/specifications/architecture/provider-architecture.md#adding-a-provider):
adapter + fake + contract tests + configuration + opt-in live tests, no
domain/application changes.

## Writing an ADR

Copy an existing ADR's structure (Status, Context, Decision, Consequences,
Alternatives considered), take the next number, add it to the ADR index,
link it from affected specs, run `python3 scripts/check_docs.py`.
