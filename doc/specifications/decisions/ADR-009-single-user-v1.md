# ADR-009 — Single-user, single-profile v1.0

- **Status:** Proposed

## Context

ClipFactory is a private tool for one owner. Multi-user features would add
authentication, authorisation and tenancy complexity without value.

## Decision

- No user accounts or roles. Access control is network exposure (loopback by
  default) plus a single static API token when exposed (CF-NFR-101).
- Exactly one active Content Profile; profiles are stored by ID so that
  multiple profiles remain possible later (CF-REQ-550).
- At most one active Run at a time (CF-REQ-652).

## Consequences

- Simple API and UI; no login flows beyond the optional token exchange.
- Supporting multiple profiles later requires scheduler and UI changes but no
  domain remodelling.

## Alternatives considered

- Full auth (OAuth/OIDC, sessions, roles): unnecessary for one user.
- No protection at all: unsafe if the port is ever exposed.
