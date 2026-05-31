import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / 'configtool-client'))
sys.path.insert(0, str(REPO_ROOT / 'configtool-secrets'))

from configtool_client import Config


def main():
    example_dir = Path(__file__).resolve().parent

    config = Config(
        local_file_path=str(example_dir / 'configtool.yml'),
        local_db_path=str(example_dir / 'configtool_db.yml'),
    )

    print('Before unlock:')
    print(f"  libraries = {config.libraries}")
    print(f"  secrets = {config.secrets}")

    config.unlock_secrets()
    config.deploy_env()

    print('After unlock:')
    print(f"  service_name = {config.get_value('demo', 'service_name')}")
    print(f"  api_token = {config.get_value('demo', 'api_token')}")
    print(f"  DEMO_SERVICE_NAME = {os.environ['DEMO_SERVICE_NAME']}")
    print(f"  DEMO_API_TOKEN = {os.environ['DEMO_API_TOKEN']}")
    print(f"  demo hash = {config.get_library_hash('demo')}")


if __name__ == '__main__':
    main()
