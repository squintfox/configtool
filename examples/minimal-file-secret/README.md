# Minimal File-Secret Example

This example shows all three packages working together with the `file` secret handler:

- `configtool` loads and overlays the YAML database
- `configtool-client` exposes the runtime API
- `configtool-secrets` resolves a secret from a local file

## Files

- `configtool.yml`: client-side app selection
- `configtool_db.yml`: database with one normal value and one secret-backed value
- `app.py`: example program
- `secrets/api_token.txt`: local file used by the `file` secret handler

## Run

From the repository root:

```powershell
uv run .\examples\minimal-file-secret\app.py
```

Expected behavior:

1. The app loads the `demo.default` and `demo.service` namespaces.
2. `service_name` is available immediately as a normal library value.
3. `api_token` starts as a pending secret reference.
4. `unlock_secrets()` reads `secrets/api_token.txt` through the `file` handler.
5. `deploy_env()` exports both values into the process environment.

## Notes

- The secret backend here is intentionally local and dependency-light; no cloud service or external vault is required.
