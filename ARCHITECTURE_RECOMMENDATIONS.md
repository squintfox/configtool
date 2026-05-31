# Python Architecture Recommendations for Configtool

## Scope

This document tracks what remains to be improved across:

- configtool
- configtool-client
- configtool-secrets

It intentionally excludes items already completed.

## Completed Work Removed From This Plan

The following earlier recommendations are now complete and removed from active planning:

- mutable-default cleanup in core paths
- explicit export surfaces in package `__init__` modules
- explicit exception classes for command-backed adapters
- initial runtime model classes for `libraries`, `secrets`, and env mappings
- centralized merge helpers with deep-copy fallback behavior
- strict local client-config boundary validation model (`LocalClientConfigModel`)
- service extraction for merge/unlock/env-export paths
- provider-registry based secret dispatch
- safer default command execution policy (`shell=False` sequence-first, opt-in shell strings)
- read-only runtime views with explicit mutation APIs
- typed secret config block contract for `configtool_secrets.Secrets.unlock` with client-side parse boundary
- second-pass client modularization (`Config` split into runtime/env/secrets/merge mixins under `configtool_client/mixins`)
- local validation runner aligned with CI and uv workspace package installation (`build/run_all_tests.ps1` using `uv sync --all-packages --group dev`)

## Current Gaps Worth Addressing Next

### 1. `Config` public surface is still broad

Internal modularization is now in place (`core.py`, `services.py`, `types.py`, `mixins/*`), but
the external API remains intentionally facade-oriented for compatibility.

### 2. Command policy lacks granular controls

Command policy now defaults to safe mode and uses an explicit policy object shared by command adapters, but there is no allow-list or trusted-origin policy.

### 3. Provider registry extension contracts need lifecycle guidance

`Secrets.register_provider(...)` now supports third-party registration, but operational guidance for plugin lifecycle and conflict management is not yet documented.

Status: completed.

- lifecycle and conflict-handling guidance is now documented.

### 4. Strict type checking rollout is intentionally partial

Strict type-checking expansion across remaining production modules is now complete.

Status: completed.

## Updated Recommendations (Post-Implementation)

### Recommendation 1: Replace global secret caches with owned lifecycle objects

Move cache state from module globals to instance-owned cache managers.

Status: completed.

### Recommendation 2: Extend strict schema validation across all data boundaries

Apply strict typed validation to:

- command-loaded database payloads
- namespace block and variable specification shapes
- secret provider block config by provider type

Status: completed.

- command-loaded database payloads use strict schema validation model.
- namespace block and variable specification validation is now enforced.

### Recommendation 3: Promote services to first-class public APIs

Service classes and mixins now exist and are stable internally, but are still mostly internal.

Breaking-change option:

- publish services as stable APIs and de-emphasize direct use of `Config` facade methods.

### Recommendation 4: Introduce centralized command policy objects

Consolidate command execution constraints into one policy object consumed by both `CommandDB` and command secret handlers.

Status: completed.

- `CommandExecutionPolicy` is now a public object in `configtool`.
- client can inject one policy object consumed by both `CommandDB` and command secret handlers.

### Recommendation 5: Open provider registry extension contract

Make provider registration a supported extension mechanism.

Status: completed.

- `Secrets.register_provider(...)` is now public and tested.

### Recommendation 6: Strengthen typed contracts and CI enforcement

Add and enforce:

- `pyright --strict` or equivalent on changed modules
- contract tests for provider and database-source protocols
- integration tests for model validation failures and command policy behavior

Status: completed.

- added contract tests for database-source and provider contracts.
- added strict pyright CI workflow on architecture-touching modules.
- added schema validation integration tests for malformed variable specs.
- local full-repo validation is now documented and scriptable through `build/run_all_tests.ps1`.
- strict pyright now gates all production modules in:
  - `configtool/*`
  - `configtool-client/configtool_client/*`
  - `configtool-client/configtool_client/mixins/*`
  - `configtool-secrets/configtool_secrets/*`
  - `configtool-secrets/configtool_secrets/handlers/*`

## Proposed Phased Plan

### Phase A: Validation completion

1. Add schema models for database and secret namespace/provider blocks.
2. Add typed validation errors consistently at every boundary.
3. Add failure-path integration tests.

### Phase B: Runtime lifecycle hardening

1. Replace global secret caches with owned lifecycle objects.
2. Add explicit shared-cache opt-in API.
3. Add lifecycle stress tests.

### Phase C: Policy and extension contracts

1. Add centralized command policy object used across adapters.
2. Publish provider registry extension contract.
3. Add contract tests for third-party provider registration.

### Phase D: Public API rationalization

1. Promote service APIs as primary public surface.
2. Keep `Config` as migration facade for one major cycle.
3. Publish migration guide with service-based usage examples.

## Recommended Next PR Set

The previous next PR set is now complete. The next high-value set is:

1. Promote service classes as explicit public APIs and publish migration examples.
2. Add command allow-list and trusted-origin enforcement in command policy.
3. Document stable extension contracts for provider plugins (registration, lifecycle, conflict handling).
