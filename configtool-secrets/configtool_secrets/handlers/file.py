from collections.abc import Mapping


class File:
    """Secret handler that reads secret values from a local file."""

    def __init__(self, file_path: str):
        """Initialize file handler with path to secret file."""
        self._file_path = file_path

    def _read_file(self, file_path: str) -> str:
        """Reads the content of a file and returns it."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            raise FileNotFoundError(f'File "{file_path}" not found.')

    def unlock(self, secret_config: Mapping[str, Mapping[str, str]]) -> dict[str, str]:
        """
        secret_config (example) - namespace is the one used for secret lookup
        {
            'namespace_1': {
                'library.var_name': 'secret_lookup_val',
                'library.var_name_2': 'secret_lookup_val_2',
            },
            'namespace_2': {'library.var_name_3': 'secret_lookup_val_3'},
        }

        secret_lookup_val is not used for file handler since the file path is already provided
        in the config block, but it is still required in the secret_config for consistency
        with other handlers and to allow for potential future use cases where the lookup value
        might be needed.
        """
        rtrn: dict[str, str] = {}
        for app_namespace in secret_config:
            rtrn[app_namespace] = self._read_file(self._file_path).strip()
        return rtrn
