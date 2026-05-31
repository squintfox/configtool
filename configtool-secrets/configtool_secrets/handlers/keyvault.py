import getpass
import logging
from collections.abc import Mapping, Sequence
from typing import cast

import keyring
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.identity import (
    AuthenticationRecord,
    InteractiveBrowserCredential,
    ManagedIdentityCredential,
    TokenCachePersistenceOptions,
)
from azure.keyvault.secrets import SecretClient

from ..constants import HANDLER_TYPE_KEYVAULT

logger = logging.getLogger(__name__)

KeyVaultCredentialOption = Mapping[str, str]


class AzureKeyVault:
    """Secret handler that retrieves secrets from Azure Key Vault."""

    def __init__(
        self,
        vault_uri: str,
        cred_options: Sequence[KeyVaultCredentialOption] | None = None,
    ):
        """Initialize the azure key vault."""
        if cred_options is None:
            cred_options = []
        credential = self._get_credential_from_opt(vault_uri, cred_options)
        if not credential:
            credential = self._get_interactive_credential()
        self._secret_client = SecretClient(vault_url=vault_uri, credential=credential)

    def _get_credential_from_opt(
        self,
        vault_uri: str,
        cred_options: Sequence[KeyVaultCredentialOption],
    ) -> ManagedIdentityCredential | None:
        """Return managed identity credential from matching credential options."""
        for opt in cred_options:
            if opt.get('secret_type') == HANDLER_TYPE_KEYVAULT:
                if vault_uri == opt.get('vault-uri', ''):
                    cred_type = opt.get('cred_type')
                    if cred_type == 'managed_identity':
                        if 'identity' in opt:
                            return self._get_managed_id_credential(opt['identity'])
                        else:
                            return self._get_managed_id_credential()

    def _get_managed_id_credential(
        self, client_id: str | None = None
    ) -> ManagedIdentityCredential:
        """Create a managed identity credential for optional client ID."""
        return ManagedIdentityCredential(
            client_id=client_id, additionally_allowed_tenants=['*']
        )

    def _get_interactive_credential(self) -> InteractiveBrowserCredential:
        """Gets an Azure credential using Interactive Auth in a web browser. Cached in
        keyring for reuse."""
        username = getpass.getuser()
        deserialized_record: AuthenticationRecord | dict[str, str] = {}
        record = keyring.get_password(HANDLER_TYPE_KEYVAULT, username)
        if record:
            try:
                deserialized_record = AuthenticationRecord.deserialize(record)
            except Exception:
                logger.warning('Invalid cache in keyring. Forcing interactive auth.')
                deserialized_record = {}

        credential = InteractiveBrowserCredential(
            additionally_allowed_tenants=['*'],
            cache_persistence_options=TokenCachePersistenceOptions(),
            authentication_record=cast(AuthenticationRecord | None, deserialized_record),
        )
        record = credential.authenticate()
        # Save the authentication record to keyring for future use
        keyring.set_password(HANDLER_TYPE_KEYVAULT, username, record.serialize())
        return credential

    def unlock(self, secret_config: dict[str, str]) -> dict[str, str]:
        """
        secret_config (example) - namespace is the one used for secret lookup
        {
            'namespace_1': {
                'library.var_name': 'secret_lookup_val',
                'library.var_name_2': 'secret_lookup_val_2',
            },
            'namespace_2': {'library.var_name_3': 'secret_lookup_val_3'},
        }
        """
        rtrn: dict[str, str] = {}
        for app_namespace in secret_config:
            kv_secret_name = secret_config[app_namespace]
            try:
                decrypted_secret = self._secret_client.get_secret(kv_secret_name)
            except ResourceNotFoundError:
                raise ResourceNotFoundError(
                    f'Secret "{kv_secret_name}" not found in Key Vault.'
                )
            except HttpResponseError as e:
                raise HttpResponseError(f'Unknown Key Vault error. {str(e)}')
            if decrypted_secret.value is None:
                raise HttpResponseError(
                    f'Secret "{kv_secret_name}" resolved to an empty value.'
                )
            rtrn[app_namespace] = decrypted_secret.value
        return rtrn
