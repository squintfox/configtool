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

Optional part of Configtool, used to connect to a vault (Azure KeyVault) and retrieve a secret.

Unlocking requires a:

- config: the Configtool configuration retrieved by the client
- secret_config: a mapping between the secret name in the vault and the returned output
(this mapping is also retrieved from Configtool)

Secrets specify a type (keyvault) and an optional cred_options.  In it's default handling
mode, the KeyVault will attempt to be unlocked by interactive credential (on Windows, your
browser opens and asks you to SAML authenticate).  When running in a non-interactive context
(build, application), you must supply a managed identity (either default or user) in order
to unlock the vault.

When in interactive mode, your SAML token is cached so when testing locally, you do not need
to log in each time.  This does however require you to do it twice, the first time.  Also,
as a developer, your computer that is running the code must be able to connect to the KeyVault
over the network.

## Minimal Example

For a local end-to-end example that exercises all three packages with the `file` secret handler,
see [examples/minimal-file-secret/README.md](examples/minimal-file-secret/README.md).
