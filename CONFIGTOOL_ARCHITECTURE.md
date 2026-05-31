# Configtool Architecture and API Guide

This repository contains three closely related Python packages:

- `configtool`: reads a configuration database and flattens namespaces into library values.
- `configtool-client`: gives applications a higher-level runtime API for loading config, unlocking secrets, exporting environment variables, and tracking config changes.
- `configtool-secrets`: resolves secret placeholders into concrete values using pluggable secret handlers.

## Quick Reference

| Package | Main entry point | Primary job |
| --- | --- | --- |
| `configtool` | `configtool.Interface` | Load the database, overlay namespaces, and split normal values from secret-backed values. |
| `configtool-client` | `configtool_client.Config` | Provide the application runtime API for reads, secret unlock, env export, merges, and namespace reloads. |
| `configtool-secrets` | `configtool_secrets.Secrets` | Dispatch secret requests to a handler backend and return resolved values. |

## Current State Snapshot (May 2026)

- Runtime state in `configtool.Interface` is class-based (`Libraries`, `Secrets`, `EnvMappings`) with mapping compatibility.
- `configtool_client.Config.merge()` now uses centralized merge helpers with deep-copy fallback semantics for safer state transfer.
- Package `__init__` modules now use explicit exports via `__all__` instead of wildcard re-exports.
- Command-backed adapters use package-specific exception types:
  - `configtool.CommandExecutionError`
  - `configtool_secrets.SecretCommandExecutionError`
- Breaking-change command policy is active:
  - command strings are blocked by default
  - sequence commands are the default safe mode
  - legacy shell-string compatibility requires `CFGT_ALLOW_SHELL_COMMANDS=true`
- `configtool_client.Config` now exposes read-only runtime views and explicit mutation methods.
- Secret dispatch in `configtool_secrets.Secrets` now uses a provider registry.
- Client config load now validates into `LocalClientConfigModel` before orchestration.
- `configtool_secrets.Secrets.unlock()` now requires typed secret config block models.
- Dict-to-model parsing for secret config blocks now occurs in `configtool_client` boundary logic.
- Secret cache lifecycle is now instance-owned by default with explicit shared-cache opt-in.
- Command-backed DB payloads now undergo strict schema validation at load boundary.
- Command execution mode can be controlled through an explicit `CommandExecutionPolicy` shared across adapters.
- Secret provider registration now supports explicit extension via `Secrets.register_provider(...)`.
- Strict pyright checks are enforced in CI on critical architecture modules via `pyrightconfig.strict.json`.
- Local validation is standardized through `build/run_all_tests.ps1`, which syncs the full uv workspace before running strict pyright and pytest.
- `configtool_client` internals are now split across focused modules:
  - `config.py` compatibility facade
  - `core.py` composition/root class
  - `services.py` orchestration helpers
  - `types.py` protocol/type aliases
  - `mixins/` package for runtime/env/secrets/merge behaviors

### Runtime Data Models

| Name | Shape | Meaning |
| --- | --- | --- |
| `libraries` | `Libraries` model wrapping `{ library: { var: value } }` | Fully resolved non-secret values, plus secret values after unlock. |
| `secrets` | `Secrets` model wrapping `{ secret_namespace: { 'library.var': lookup_value } }` | Deferred secret lookups grouped by secret namespace. |
| `env` | `EnvMappings` model wrapping `{ ENV_NAME: 'library.var' }` | Non-secret exports for environment-variable deployment. |
| `env_secrets` | `EnvMappings` model wrapping `{ ENV_NAME: 'library.var' }` | Secret-backed exports that become usable after unlock. |

These runtime models expose mapping behavior for compatibility and add explicit model methods/properties (for example `merge_from` and `data`) so state transitions can be expressed as model operations instead of ad hoc dictionary mutation.

## How the Three Parts Interact

At runtime, the flow is:

1. An application creates `configtool_client.Config` with a local client config file and either a database file path or a database command.
2. `Config` reads the local client file through `LocalConfigFile` to get `app`, `environment`, and `additional_namespaces`.
3. `Config` creates `configtool.Interface`.
4. `Interface` loads the selected environment namespaces from the database, optionally overlays additional namespaces, and categorizes the flattened values into:
   - `libraries`: normal resolved values
   - `secrets`: placeholders grouped by `secret_namespace`
   - `env`: normal values that should be exported to OS environment variables
   - `env_secrets`: secret-backed values that should be exported after unlocking
5. When the caller invokes `unlock_secrets()`, `Config` lazily creates `configtool_secrets.Secrets`.
6. `Secrets` looks up each secret namespace's config block, groups requests by secret type and backend instance, calls the matching handler, and returns resolved values.
7. `Config.update()` writes the resolved secret values back into the loaded libraries and refreshes each affected library hash.
8. The caller can then read `libraries`, call `get_value()`, or export variables with `deploy_env()` or `deploy_env_file()`.

In short: `configtool` decides what should be loaded, `configtool-client` manages the application-facing lifecycle, and `configtool-secrets` turns secret references into actual values.

## Package: `configtool`

### Export Surface (`configtool-client`)

- `configtool.__init__` explicitly exports:
  - `Interface`
  - `CommandExecutionPolicy`
  - `DatabaseNotFoundError`
  - `CommandExecutionError`
  - `InvalidCommandOutputError`
  - `InterfaceSourceError`

### Module: `configtool.db`

#### `FileDB`

Wrapper around a YAML file database.

- `__init__(database_path: str)`
  - Verifies the file exists.
  - Loads YAML with `yaml.safe_load()` into memory.
  - Raises `ImportError` if the file cannot be found.
- `database`
  - Property returning the loaded Python dictionary.

#### `CommandDB`

Wrapper around a command that returns the database as JSON.

- `__init__(command: str | Sequence[str], policy: CommandExecutionPolicy | None = None)`
  - Executes the command immediately and stores the parsed JSON result.
  - Applies explicit command policy when provided.
- `_resolve_run_mode(command: str | Sequence[str]) -> tuple[str | list[str], bool]`
  - Uses sequence commands with `shell=False` by default.
  - Rejects string commands unless `CFGT_ALLOW_SHELL_COMMANDS=true` is set.
- `_run_command(command: str | Sequence[str]) -> str`
  - Runs `subprocess.run(...)` with resolved shell mode.
  - Raises `CommandExecutionError` on policy violations or non-zero exit.
- `_execute(command: str | Sequence[str])`
  - Delegates command invocation to `_run_command()`.
  - Parses stdout as JSON.
  - Raises `InvalidCommandOutputError` if stdout is not valid JSON.
  - Validates command payload shape through strict schema models:
    - `CommandDatabasePayloadModel`
    - `AppDatabaseModel`
    - `VariableSpecModel`
- `database`
  - Property returning the parsed dictionary.

### Module: `configtool.helpers`

#### `namespace_is_default(namespace: str) -> bool`

Utility that treats both `root` and `root.default` as the default namespace for a root library.

#### `split_namespace(namespace: str) -> tuple[str, str]`

Shared helper that splits `root.local` style namespace strings into `(root, local)` and
normalizes implicit defaults to `default`.

#### `should_include_library(library: str, selected_libraries: list[str]) -> bool`

Shared filter helper used by projection paths to decide whether a library should be included.

#### `as_env_var_list(env_vars: str | list[str]) -> list[str]`

Shared normalization helper that converts a single env var or list into a list.

## Local Validation Workflow

Use the repository test runner when validating the full workspace locally:

- `build/run_all_tests.ps1`
  - Runs `uv sync --all-packages --group dev` so workspace package dependencies from `configtool-client` and `configtool-secrets` are installed.
  - Runs `uv run pyright -p pyrightconfig.strict.json`.
  - Runs `uv run pytest` using the repository pytest configuration.

Common usage:

- `./build/run_all_tests.ps1`
- `./build/run_all_tests.ps1 -SkipSync`

On Windows PowerShell, if launching through `powershell -File`, pass script path and arguments separately:

- `powershell -ExecutionPolicy ByPass -File c:\git\configtool\build\run_all_tests.ps1 -SkipSync`

### Module: `configtool.internal`

#### `AppConfig`

Core namespace overlay engine.

- `__init__(app_name: str, database: dict)`
  - Reads `database[app_name]['environments']` and `database[app_name]['config']`.
  - Initializes an empty flattened `_config` map.
- `environments`
  - Property exposing the environment-to-namespace list mapping.
- `config`
  - Property exposing the flattened, currently loaded configuration.
- `load_namespace(namespace: str, force_default=False) -> None`
  - Splits the namespace into a root library name and a local namespace name.
  - Ensures a root entry exists in `_config`.
  - If the namespace is `default`, merges it directly.
  - If the namespace is not default:
    - overlays root `default` plus the target namespace the first time that root is loaded
    - overlays only the target namespace on later loads for the same root
  - This is the method that turns ordered namespaces into a single effective library configuration.
- `get_config_block(namespace: str, overlay_default=False) -> dict`
  - Returns one namespace block from the raw config tree.
  - If `overlay_default=True`, merges the root `default` block before the target block.
  - This is used both by `load_namespace()` and by the client when it needs raw secret namespace definitions later.

### Module: `configtool.public`

#### `Interface`

Public facade over database loading and namespace flattening.

- `__init__(app_name, environment, additional_namespaces, local_db_path=None, local_command_path=None, command_policy=None)`
  - Creates either `FileDB` or `CommandDB`.
  - Normalizes and validates app database structure through `AppDatabaseModel` before constructing `AppConfig`.
  - Creates `AppConfig` for the selected app.
  - Loads all namespaces defined by the chosen environment, in order.
  - Loads any `additional_namespaces` after the environment namespaces.
  - Initializes and populates four runtime model objects:
    - `_libraries` as `Libraries`
    - `_secrets` as `Secrets`
    - `_env` as `EnvMappings`
    - `_env_secrets` as `EnvMappings`
- `secrets`
  - Property exposing `_secrets`.
- `libraries`
  - Property exposing `_libraries`.
- `env`
  - Property exposing `_env`.
- `env_secrets`
  - Property exposing `_env_secrets`.
- `get_config_block(namespace: str, overlay_default=False)`
  - Pass-through to `AppConfig.get_config_block()`.
- `load_namespace(namespace: str, **kwargs)`
  - Pass-through to `AppConfig.load_namespace()`.
  - This only changes the flattened app config; callers usually follow it with `populate()`.
- `populate(libraries=[])`
  - Walks the flattened config and refreshes `_libraries`, `_secrets`, `_env`, and `_env_secrets`.
  - If `libraries` is provided, only repopulates those roots.
- `_pop(library: str)`
  - Internal worker used by `populate()`.
  - For each variable in the library:
    - if `secret_namespace` exists, store the placeholder in `_secrets`
    - otherwise store the concrete value in `_libraries`
    - if `env` exists, register the export target in `_env` or `_env_secrets`

## Package: `configtool-client`

### Export Surface (`configtool-secrets`)

- `configtool_client.__init__` explicitly exports:
  - `Config`
  - `LocalConfigFile`
  - `BackendDependencyError`
  - `SourceConfigurationError`
  - `SecretConfigResolutionError`
  - `SecretsNotInitializedError`

### Modules: `configtool_client.config`, `configtool_client.core`, and `configtool_client.mixins.*`

#### `Config`

Primary application-facing API.

- `__init__(local_file_path, local_db_path=None, local_command_path=None, command_policy=None, secrets_cache_manager=None)`
  - Reads and validates client-side config through `LocalConfigFile` and `LocalClientConfigModel`.
  - Imports `configtool` and constructs `configtool.Interface`.
  - Can pass one shared command policy through both DB and secret command adapters.
  - Can opt into explicit shared secret cache lifecycle with `secrets_cache_manager`.
  - Initializes secret state, cached secret config blocks, merged config blocks, and per-library MD5 hashes.
  - Immediately hashes all initially loaded libraries.
- `libraries`
  - Read-only view over current libraries.
- `secrets`
  - Read-only view over current secret lookup mappings.
- `env`
  - Read-only view over environment mappings.
- `env_secrets`
  - Read-only view over secret environment mappings.
- `set_library_value(library: str, var_name: str, value)`
  - Explicit mutation API for library values.
  - Refreshes library hash.
- `set_secret_lookup(namespace: str, lib_var: str, lookup_value)`
  - Explicit mutation API for secret lookup mappings.
- `set_env_mapping(env_var: str, lib_var: str, secret=False)`
  - Explicit mutation API for env and env-secret mapping targets.
- `secret_config_blocks`
  - Property that resolves and caches the raw config blocks for all currently referenced secret namespaces.
  - Missing namespaces are skipped here, but `unlock_secrets()` enforces them later.
- `update(var_dict: dict)`
  - Accepts a flat map like `{ 'library.var': value }`.
  - Writes new values into loaded libraries.
  - Recomputes hashes only for affected libraries.
- `merge(merge_config: Config)`
  - Delegates merge behavior to `MergeService`.
  - Merges libraries, secret placeholder maps, env exports, and env-secret exports.
  - Preserves raw config blocks and resolved secret blocks so secret namespaces remain resolvable after a merge.
- `deploy_env(enable_secrets=True, libraries=[])`
  - Delegates environment export to `EnvironmentExportService`.
  - Writes loaded values into `os.environ`.
  - If `libraries` is supplied, restricts exports to those library roots.
  - If `enable_secrets=True`, includes values coming from `env_secrets`.
- `_format_env_file_value(value) -> str`
  - Converts a Python value to `str(value)` for dotenv stream parsing.
- `deploy_env_file(file_path: str, enable_secrets=True, libraries=[])`
  - Delegates file export to `EnvironmentExportService`.
  - Uses the same resolved entry set as `deploy_env()`.
  - Resolves interpolation in-memory through `dotenv_values(stream=..., interpolate=True)`.
  - Writes the resolved environment-variable view into a `.env` file.
  - Overwrites any existing file.
- `get_value(library: str, var: str)`
  - Returns one resolved value from `libraries`.
- `get_library(library: str) -> dict`
  - Returns a whole resolved library dictionary.
- `get_library_hash(library: str) -> str`
  - Returns the MD5 hash for the current library state.
- `unlock_secrets(libraries=[])`
  - Delegates secret resolution flow to `SecretUnlockService`.
  - Creates a `Secrets` instance on demand.
  - Filters pending secrets if a library subset is requested.
  - Resolves raw config blocks for referenced secret namespaces.
  - Raises `SecretConfigResolutionError` (a `KeyError` subtype) when namespace blocks are missing.
  - Calls `configtool_secrets.Secrets.unlock()` and updates library values.
- `add_secrets_cred(cred_option: dict)`
  - Initializes secrets support if needed.
  - Appends one credential option to `Secrets.cred_options`.
  - This is mainly for non-interactive Key Vault authentication.
- `load_namespace(namespace: str, unlock=True, **kwargs)`
  - Loads one additional namespace through `Interface.load_namespace()`.
  - Repopulates only the affected root library.
  - Optionally unlocks secrets for that root immediately.
  - Recomputes that library hash.
- `_init_secrets()`
  - Lazy-imports `configtool_secrets` and instantiates `Secrets`.
- `_resolve_secret_config_block(namespace: str, *configs)`
  - Static helper that tries several `Config` objects until one can return the requested namespace block.
- `_get_config_block(namespace: str)`
  - Reads a raw config block from the active interface.
  - Falls back to `_merged_config_blocks` when the active interface cannot provide it.
- `_get_all_config_blocks() -> dict`
  - Returns a deep copy of all known config blocks, including merged ones.
- `_merge_config_blocks(blocks: dict)`
  - Deep-merges raw config blocks into `_merged_config_blocks`.
- `_update_library_hash(library: str)`
  - Recomputes and stores `dict_hash.md5()` for the target library.

### Module: `configtool_client.local_config`

#### `LocalConfigFile`

Thin wrapper around the client-side YAML file.

- `__init__(file_path: str)`
  - Loads YAML from disk and validates shape through `LocalClientConfigModel`.
- `app`
  - Property returning the `app` key.
- `environment`
  - Property returning the `environment` key.
- `additional_namespaces`
  - Property returning `additional_namespaces` or `[]` if absent.

## Package: `configtool-secrets`

### Export Surface

- `configtool_secrets.__init__` explicitly exports:
  - `Secrets`
  - `SecretTypeError`
  - `SecretCredentialError`
  - `SecretCommandExecutionError`

### Module: `configtool_secrets.constants`

Defines the supported secret backend names:

- `keyvault`
- `command`
- `file`
- `vaultwarden`

The constants define built-in provider names. Dispatch itself is provider-registry driven.

### Module: `configtool_secrets.secrets`

#### `Secrets`

Dispatcher and lifecycle manager for secret handlers.

- `__init__()`
  - Initializes `cred_options`.
  - Uses instance-owned caches (`SecretCacheManager`) for Vaultwarden clients and unlock cache.
  - Accepts explicit shared-cache opt-in by passing `cache_manager=`.
  - Builds a provider registry (`ProviderRegistration`) for type-to-provider resolution.
  - Registers `close()` with `atexit`.
- `unlock(secret_config: dict, config: dict[str, SecretConfigBlock])`
  - Receives:
    - `secret_config`: mapping of secret namespace to `{ library.var: lookup_value }`
    - `config`: mapping of secret namespace to typed secret config block models
  - For each secret namespace:
    - reads `secret_type`
    - resolves provider registration by registry entry
    - groups operations by backend type and backend instance
  - Backend grouping keys are:
    - Key Vault: `vault-uri`
    - File: `file-path`
    - Command: `command`
    - Vaultwarden: `(vault-url, username, password, folder-name)`
  - Executes each grouped handler and returns a flat `{ library.var: resolved_value }` map.
  - Raises `SecretTypeError` for unknown secret types.
- `_build_cache_key(secret_config: dict) -> str | None`
  - Serializes the request deterministically. Present in the code but not currently used by `unlock()`.
- `register_provider(secret_type, target_key_resolver, provider_factory, override=False)`
  - Public extension hook for third-party providers.
  - Rejects duplicate registrations unless `override=True`.
- `_get_vaultwarden(vault_key: tuple)`
  - Reuses an existing logged-in `Vaultwarden` client when possible.
  - Otherwise constructs, logs in, caches, and returns a new one.
- `close()`
  - Closes and clears all cached Vaultwarden clients.
  - Clears the unlock cache.

#### Provider Extension Lifecycle and Conflict Policy

Recommended plugin lifecycle for third-party providers:

1. Register providers once during application startup.
2. Avoid per-request registration to prevent accidental override churn.
3. Reuse a shared `SecretCacheManager` only when cross-instance reuse is explicitly desired.
4. Treat `override=True` as a migration tool only; prefer unique provider names for additive extensions.
5. Invoke `Secrets.close()` on shutdown to release cached backend resources.

- `_get_config_block(namespace: str) -> SecretConfigBlock`
  - Returns a typed secret config block for one secret namespace from the supplied `config` map.

## Secret Types and Their Implementations

### `keyvault`

Implementation: `configtool_secrets.handlers.keyvault.AzureKeyVault`

- Constructor: `AzureKeyVault(vault_uri: str, cred_options=[])`
  - Chooses a credential source first from `cred_options`, then falls back to interactive browser auth.
- `_get_credential_from_opt(vault_uri, cred_options)`
  - Looks for a matching option with:
    - `secret_type: keyvault`
    - matching `vault-uri`
    - `cred_type: managed_identity`
  - Supports default managed identity or a specific client ID via `identity`.
- `_get_managed_id_credential(client_id=None)`
  - Creates `ManagedIdentityCredential`.
- `_get_interactive_credential()`
  - Uses `InteractiveBrowserCredential`.
  - Persists the `AuthenticationRecord` in the OS keyring under the current username.
  - Reuses cached auth when available.
- `unlock(secret_config: dict)`
  - Treats each lookup value as an Azure Key Vault secret name.
  - Fetches each secret with `SecretClient.get_secret()`.
  - Returns `{ library.var: secret_value }`.

Required config block fields:

- `secret_type.value: keyvault`
- `vault-uri.value: <vault URL>`

Optional runtime credential input:

- `Config.add_secrets_cred({ 'secret_type': 'keyvault', 'vault-uri': '...', 'cred_type': 'managed_identity', 'identity': '...' })`

### `file`

Implementation: `configtool_secrets.handlers.file.File`

- Constructor: `File(file_path: str)`
- `_read_file(file_path: str)`
  - Reads the entire file as text.
  - Raises `FileNotFoundError` if the file does not exist.
- `unlock(secret_config: dict)`
  - Ignores each lookup value.
  - Reads the configured file once per requested app variable and returns the stripped file contents.

Required config block fields:

- `secret_type.value: file`
- `file-path.value: <path to secret file>`

This is the secret type used in the HomePi `configtool_db.yml` example.

### `command`

Implementation: `configtool_secrets.handlers.command.Command`

- Constructor: `Command(command: str | Sequence[str], policy: CommandPolicy | None = None)`
- `_resolve_run_mode(command: str | Sequence[str])`
  - Uses sequence commands with `shell=False` by default.
  - Rejects string commands unless `CFGT_ALLOW_SHELL_COMMANDS=true` is set.
  - Accepts injected command policy when provided by `Secrets`.
- `_execute(command: str | Sequence[str])`
  - Runs subprocess with resolved shell mode.
  - Raises `SecretCommandExecutionError` on policy violations and non-zero exit.
- `unlock(secret_config: dict)`
  - Ignores each lookup value.
  - Runs the configured command once per requested app variable and returns stripped stdout.

Required config block fields:

- `secret_type.value: command`
- `command.value: <shell command>`

### `vaultwarden`

Implementation: `configtool_secrets.handlers.vaultwarden.Vaultwarden`

- Constructor: `Vaultwarden(vault_url, username, password, folder_name='')`
  - Stores connection/auth data.
  - Creates a persistent `requests.Session()`.
- `_bw_env()`
  - Supplies `BW_PASSWORD` to the Bitwarden CLI.
- `_run_bw(args, session_key='')`
  - Executes `bw ... --nointeraction` and returns stdout.
- `_get_status(session_key='')`
  - Reads vault status from `bw status` JSON.
  - Handles debug-noisy stdout by parsing from the last JSON-looking line.
- `_find_free_port()`
  - Finds a local loopback port for the API server.
- `_request(method, path)`
  - Talks to the `bw serve` local HTTP API.
  - Unwraps the `{ success, data }` response shape.
- `_start_api_server()`
  - Launches `bw serve` on a local port.
  - Waits until `/status` reports `unlocked`.
- `close()`
  - Closes HTTP resources and stops the `bw serve` subprocess.
- `login()`
  - Ensures the CLI points at the configured server.
  - Logs in or unlocks as needed.
  - Syncs the vault and starts the API server.
- `unlock(secret_config: dict)`
  - Requires an already logged-in and unlocked client.
  - Optionally filters items by folder.
  - Loads items from the Bitwarden API.
  - For names containing `username` in the app variable path, returns the item username.
  - Otherwise returns the item password.

Required config block fields:

- `secret_type.value: vaultwarden`
- `vault-url.value: <Vaultwarden base URL>`

Optional config block fields:

- `folder-name.value: <folder name>`

Required environment variables for `Secrets.unlock()` when using Vaultwarden:

- `CFGT_VAULTWARDEN_USERNAME`
- `CFGT_VAULTWARDEN_PASSWORD`

## Practical Usage Pattern

Typical application code looks like this:

```python
from configtool_client import Config

config = Config(
    local_file_path='configtool.yml',
    local_db_path='configtool_db.yml',
)

config.unlock_secrets()
config.deploy_env()

db_host = config.get_value('database', 'host')
db_library = config.get_library('database')
db_hash = config.get_library_hash('database')
```

If the application needs a non-interactive Azure credential, call `add_secrets_cred()` before `unlock_secrets()`.

If the application wants to swap overlays at runtime, call `load_namespace()` for the new namespace and then consume the updated library values and hashes.

## Minimal Local Example

See [examples/minimal-file-secret/README.md](examples/minimal-file-secret/README.md) for a runnable example that uses:

- `configtool.Interface` indirectly through `configtool_client.Config`
- `configtool_client.Config` as the application API
- `configtool_secrets.Secrets` with the `file` handler

## Notes and Constraints from the Current Implementation

- The backend database loader accepts YAML only from `FileDB`, but command-based loading must return JSON, not YAML.
- Secret values are represented in loaded config as placeholders until `unlock_secrets()` is called.
- `deploy_env()` and `deploy_env_file()` can export unresolved secret placeholders if called before secrets are unlocked.
- Secret config blocks are resolved from the raw config tree, not from already-flattened libraries.
- Secret config blocks are parsed to typed models by `configtool_client` before calling `configtool_secrets.Secrets.unlock()`.
- Runtime maps are model classes with mapping compatibility; external callers can still treat them like dicts.
- Package exports are explicit through `__all__` declarations.
- Public runtime access in `configtool_client.Config` is read-only; callers should use explicit mutation methods.
- String command execution now requires explicit compatibility opt-in (`CFGT_ALLOW_SHELL_COMMANDS=true`).
