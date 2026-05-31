# `configtool_db.yml` Schema Guide

This document describes the YAML database schema consumed by `configtool`.

The schema is derived from the code in `configtool`, the repository README, and the example files in HomePi:

- `configtool` expects `database[app_name]['environments']` and `database[app_name]['config']`.
- namespace blocks are resolved by root name plus local namespace name.
- each variable entry is a small object whose required field is `value`.
- app blocks and variable specs are validated through `AppDatabaseModel` and `VariableSpecModel` at interface load time.

## Top-Level Shape

The database is keyed by application name.

```yaml
<app_name>:
  environments:
    <environment_name>:
      - <namespace>
      - <namespace>

  config:
    <root_name>:
      default:
        <var_name>:
          value: <any YAML value>
      <local_namespace_name>:
        <var_name>:
          value: <any YAML value>
```

For example:

```yaml
homepi:
  environments:
    base:
      - homepi.default
      - homepi_shared.network

  config:
    homepi:
      default:
        hpi_local_data_path:
          value: /opt/homepi/local-data

    homepi_shared:
      network:
        hpi_https_port:
          value: '443'
```

## Schema by Section

### Application Key

The top-level key must match the `app` value from the client config file.

```yaml
app: homepi
```

If the client asks for `app: homepi`, then `configtool` reads the `homepi:` object from the database.

### `environments`

`environments` maps an environment name to an ordered list of namespaces.

```yaml
environments:
  base:
    - homepi.default
    - homepi_shared.network
    - homepi_shared.portainer
```

Rules:

- The environment name must match the client's `environment` value.
- The namespace list is ordered.
- Later namespaces overwrite earlier values for the same variable.
- Each namespace string has the form `<root>` or `<root>.<local_namespace>`.
- `<root>` alone is treated the same as `<root>.default`.

### `config`

`config` contains the actual namespace blocks.

```yaml
config:
  <root_name>:
    default:
      ...variables...
    <local_namespace_name>:
      ...variables...
```

Rules:

- `<root_name>` is the library name that will appear in the client under `config.libraries[root_name]`.
- `default` is special. When the first non-default namespace of a root is loaded, `configtool` overlays `default` first, then the requested namespace.
- Additional namespaces under the same root are ordinary overlay blocks.

## Variable Object Schema

Each variable is an object, not a raw scalar.

```yaml
<var_name>:
  value: <value>
  env: <string or list of strings>
  secret_namespace: <namespace reference>
```

### Required Field: `value`

Every variable object must provide `value`.

Examples:

```yaml
hpi_time_zone:
  value: America/Los_Angeles

hpi_vault_token:
  value: null
```

Behavior:

- For normal values, `value` becomes the resolved library value.
- For secret-backed values, `value` is the lookup token passed to the secret handler.
- `null` is allowed and is common when the secret backend does not need a lookup token.
- non-scalar values are also allowed (for example lists or nested mappings), though most runtime env/export paths expect string-like values.

### Optional Field: `env`

`env` declares one or more OS environment variable names to expose.

Accepted forms:

```yaml
env: HPI_TIME_ZONE
```

or:

```yaml
env:
  - HPI_TIME_ZONE
  - TF_VAR_HPI_TIME_ZONE
```

Behavior:

- If the variable is not secret-backed, `configtool.Interface` adds the mapping to `env`.
- If the variable uses `secret_namespace`, `configtool.Interface` adds the mapping to `env_secrets` instead.
- The client exports these with `deploy_env()` or `deploy_env_file()`.

### Optional Field: `secret_namespace`

`secret_namespace` marks the variable as secret-backed.

```yaml
hpi_portainer_token:
  value: null
  secret_namespace: homepi_secrets.hpi_portainer_token
  env:
    - HPI_PORTAINER_TOKEN
    - TF_VAR_HPI_PORTAINER_TOKEN
```

Behavior:

- The variable is not added to `libraries` during initial population.
- Instead, it is recorded in `secrets` under the referenced secret namespace.
- Later, `configtool-client` resolves the secret namespace config block and asks `configtool-secrets` to unlock it.
- The returned secret value is then written back into the library.

`secret_namespace` must point to another namespace block that exists somewhere under `config`.

## Interpolation Behavior

The schema stores raw values; interpolation is a runtime concern in `configtool-client`.

Current behavior:

- `${VAR}` placeholders are resolved via `python-dotenv` in env export paths (`deploy_env` and `deploy_env_file`).
- runtime library reads (`get_value`, `get_library`, and `libraries`) resolve string values against current non-secret env mappings.
- secret config block `value` fields (for example `vault-url.value`) are resolved before secret handler dispatch, including merge-cached secret blocks.

Practical implication:

- values like `https://vault.${HPI_DNS_DOMAIN}:444` are valid and are resolved at runtime when `HPI_DNS_DOMAIN` is available in non-secret env mappings.

## Namespace Resolution Rules

Given a namespace like `homepi_shared.network`:

- root: `homepi_shared`
- local namespace: `network`

Given a namespace like `homepi_shared` or `homepi_shared.default`:

- root: `homepi_shared`
- local namespace used internally: `default`

Overlay behavior for one root is:

1. First load of `root.default`: merge only `default`.
2. First load of `root.something_else`: merge `default`, then `something_else`.
3. Later load of another `root.other_namespace`: merge only `other_namespace` on top of the existing root values.

## Secret Namespace Schema

Secret namespaces live in the same `config` tree as normal namespaces. The difference is that the block describes how to retrieve secrets, not application settings.

General shape:

```yaml
<secret_root>:
  default:
  <secret_name>:
    secret_type:
      value: <handler type>
    ...handler-specific fields...
```

The secret namespace referenced by `secret_namespace` is `<secret_root>.<secret_name>`.

### Supported `secret_type` Values

#### `file`

```yaml
homepi_secrets:
  default:
  hpi_portainer_token:
    secret_type:
      value: file
    file-path:
      value: /run/secrets/hpi_portainer_token
```

Required fields:

- `secret_type.value: file`
- `file-path.value`

How it works:

- The file contents are read and stripped.
- The application variable's own `value` field is ignored.

#### `command`

```yaml
command_secrets:
  default:
  exec_secret_01:
    secret_type:
      value: command
    command:
      value: sudo some-command

# also supported
command_secrets:
  default:
  exec_secret_02:
    secret_type:
      value: command
    command:
      value:
        - sudo
        - some-command
```

Required fields:

- `secret_type.value: command`
- `command.value` (`string` or `list[string]`)

How it works:

- The command's stdout is captured and stripped.
- The application variable's own `value` field is ignored.

#### `keyvault`

```yaml
azure_secrets:
  default:
  my_secret:
    secret_type:
      value: keyvault
    vault-uri:
      value: https://example-kv.vault.azure.net/
```

Required fields:

- `secret_type.value: keyvault`
- `vault-uri.value`

How it works:

- The application variable's `value` is used as the Azure Key Vault secret name.
- The client can optionally inject managed identity credential options before unlock.

#### `vaultwarden`

```yaml
homepi_secrets:
  default:
  vault:
    secret_type:
      value: vaultwarden
    vault-url:
      value: https://vault.example.com:444
    folder-name:
      value: homepi
```

Required fields:

- `secret_type.value: vaultwarden`
- `vault-url.value`

Optional fields:

- `folder-name.value`

How it works:

- The application variable's `value` is treated as a Vaultwarden item name.
- For app variable names containing `username`, the handler returns the item's username.
- Otherwise it returns the item's password.
- The runtime also requires environment variables `CFGT_VAULTWARDEN_USERNAME` and `CFGT_VAULTWARDEN_PASSWORD`.

## End-to-End Example

This example shows both application config and secret backend config together.

```yaml
homepi:
  environments:
    base:
      - homepi.default
      - homepi_shared.network
      - homepi_shared.portainer

  config:
    homepi:
      default:
        hpi_local_data_path:
          value: /opt/homepi/local-data
          env:
            - HPI_LOCAL_DATA_PATH
            - TF_VAR_HPI_LOCAL_DATA_PATH

    homepi_shared:
      network:
        hpi_https_port:
          value: '443'
          env:
            - HPI_HTTPS_PORT
            - TF_VAR_HPI_HTTPS_PORT
      portainer:
        hpi_portainer_token:
          value: null
          secret_namespace: homepi_secrets.hpi_portainer_token
          env:
            - HPI_PORTAINER_TOKEN

    homepi_secrets:
      default:
      hpi_portainer_token:
        secret_type:
          value: file
        file-path:
          value: /run/secrets/hpi_portainer_token
```

What happens at runtime:

1. `base` loads `homepi.default`, `homepi_shared.network`, and `homepi_shared.portainer`.
2. `hpi_local_data_path` and `hpi_https_port` become normal library values.
3. `hpi_portainer_token` is recorded as a pending secret because it has `secret_namespace`.
4. When the client calls `unlock_secrets()`, it resolves `homepi_secrets.hpi_portainer_token`.
5. `configtool-secrets` sees `secret_type: file`, reads `/run/secrets/hpi_portainer_token`, and returns the contents.
6. The client writes that resolved value back into the `homepi_shared` library.

## Related Client Config Schema

This is not part of `configtool_db.yml`, but it is the other half of the runtime contract:

```yaml
app: homepi
environment: base
additional_namespaces: []
```

`additional_namespaces` must be a list of strings when provided. For example:

```yaml
app: homepi
environment: base
additional_namespaces:
  - homepi_shared.extra
  - homepi.runtime_override
```

## Validation Checklist for a New Database

- Top-level app key matches the client `app` value.
- The requested environment exists under `environments`.
- Every namespace listed in an environment exists under `config`.
- Every referenced root includes a `default` namespace block (use `{}` when no defaults are needed).
- Every variable entry is an object with a `value` field.
- Every `secret_namespace` points to a real secret namespace block.
- Every secret namespace block contains `secret_type.value` and the fields required by that handler.
- Every `env` field is either a string or a list of strings.
