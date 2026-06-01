# Configtool (a Configuration tool of sorts)

## Reference Docs

- Architecture and API guide: [CONFIGTOOL_ARCHITECTURE.md](CONFIGTOOL_ARCHITECTURE.md)
- `configtool_db.yml` schema guide: [CONFIGTOOL_DB_SCHEMA.md](CONFIGTOOL_DB_SCHEMA.md)
- Minimal working example: [examples/minimal-file-secret/README.md](examples/minimal-file-secret/README.md)

## Configtool

Implements the "backend service" part of a configuration management solution.  Loads a YAML
file as a database and allows the Configtool Client retrieve configuration for:

- a Namespace (in)
- an Environment (for)
- an Application

The database defines for each application, any number of environments.  Each application
comprises a list of namespaces also defined in the database.  Each namespace loads in order
on top of the previous, overwriting defined values and adding ones that don't exist.  Each
top-level namespace defines a default that is included in all other sub-namespaces (but
can be overwritten).

Allows defining a "secret_namespace" which returns a configuration that can be used at the
client (via configtool_secrets) to retrieve a secret from a vault (only Azure KeyVault is
supported at this time).

Allows using the `env` key to provide a list of values (secret and non, secret in same
format to be interpreted by the client) that will be mapped to OS environment variables.  All
`env` mapped values exist as both as gettable from the interface and an OS environment
variable.  These need not be the same variable name.

The client may specify additional namespaces to load beyond what the environment configuration
specifies.  These are loaded at the completion of the database load.

## Configtool Client

The client implementation of Configtool.  

Provides path to local YAML file to be read by Configtool as the database.  It will also read
it's own YAML file to define which application, environment and any additional namespaces to
be retreived from Configtool.

Will load first without secrets or environment variables and then unlock_secrets() and/or
deploy_env() can be called.  Both will load all configurations by default, but also can
specify an override list of specific libaries.

Allows loading cred_options before calling unlock_secrets() (for non-interactive unlock) via
add_secrets_cred().

Current internal package layout (May 2026):

- `configtool_client/config.py`: compatibility facade for stable imports.
- `configtool_client/core.py`: `Config` composition and adapter factory logic.
- `configtool_client/services.py`: extracted merge/unlock/env-export orchestration services.
- `configtool_client/types.py`: shared protocol and type aliases.
- `configtool_client/mixins/`: behavioral split of `Config` into runtime, env, secrets, and merge concerns.

Environment export behavior is unified:

- `deploy_env()` and `deploy_env_file()` both use the same in-memory dotenv interpolation pipeline.
- Interpolation is resolved via `python-dotenv` (`dotenv_values`) before either writing `os.environ` or writing `.env` files.

Adds an MD5 hash to each library that updates any time any value in the library is updated.

Configuration is loadable and re-loadable on-the-fly, per library.  On-the-fly updates to
the configuration are stored only in memory.  The database will not be updated.

A typical on-the-fly usage would be to reload a library with different namespaces that define
the same values.  So target_system.instance_01, do work on instance 1, then load
target_system.instance_02 and re-run the same code.  Hashes provide a way to know if a
library has changed since you last retrieved it and can signal you to reload your code
(presumably a different part of the program changed the configuration that you should now
follow, like "hey we've moved to instance 2").

## Configtool Secrets

Optional part of Configtool, used to retrieve secret values through pluggable handlers.

Unlocking requires a:

- config: the Configtool configuration retrieved by the client
- secret_config: a mapping between the secret name in the vault and the returned output
(this mapping is also retrieved from Configtool)

Supported `secret_type` handlers:

- `file`: read the secret from a local file path
- `command`: run a command and use trimmed stdout as the secret value
- `vaultwarden`: read the secret from a Vaultwarden item
- `keyvault`: read the secret from Azure KeyVault

### File secrets

Use `secret_type: file` when your secret is available as a file (for example Docker secrets
mounted at `/run/secrets/...`).

Typical secret backend block:

```yaml
homepi_secrets:
  hpi_portainer_token:
    secret_type:
      value: file
    file-path:
      value: /run/secrets/hpi_portainer_token
```

### Command secrets

Use `secret_type: command` when the secret must be produced dynamically by a command.

Typical secret backend blocks:

```yaml
command_secrets:
  exec_secret_01:
    secret_type:
      value: command
    command:
      value: sudo some-command

command_secrets:
  exec_secret_02:
    secret_type:
      value: command
    command:
      value:
        - sudo
        - some-command
```

`command.value` supports either a single string or a list of command arguments.

Why this is useful:

- You can run one or more setup commands that produce no output, then run a final command
  that prints only the secret value consumed by Configtool.
- Common pattern: refresh/login/unlock first, then emit the resolved secret on stdout.
- For multi-step shell chaining in one string command, enable `CFGT_ALLOW_SHELL_COMMANDS=true`
  (or call a wrapper script/binary from list-arg mode).

### Vaultwarden secrets

Use `secret_type: vaultwarden` when secrets are stored in a Vaultwarden folder/item model.
The application variable's `value` is treated as the Vaultwarden item name.

Typical secret backend block:

```yaml
homepi_secrets:
  vault:
    secret_type:
      value: vaultwarden
    vault-url:
      value: https://vault.example.com
    folder-name:
      value: homepi
```

Vaultwarden runtime requires:

- `CFGT_VAULTWARDEN_USERNAME`
- `CFGT_VAULTWARDEN_PASSWORD`

### KeyVault secrets

`keyvault` continues to support interactive local auth and managed identity flows.

In its default handling mode, KeyVault attempts interactive credential login. On Windows,
your browser opens for SAML authentication. In non-interactive contexts (builds/services),
use managed identity credentials via `cred_options`.

When in interactive mode, your SAML token is cached so when testing locally, you do not need
to log in each time. This does however require you to do it twice, the first time. Also,
as a developer, your computer that is running the code must be able to connect to KeyVault
over the network.

## Minimal Example

For a local end-to-end example that exercises all three packages with the `file` secret handler,
see [examples/minimal-file-secret/README.md](examples/minimal-file-secret/README.md).
