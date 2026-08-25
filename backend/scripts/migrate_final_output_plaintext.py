from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / '.env')

sys.path.insert(0, str(PROJECT_ROOT))

from utils.file_security import migrate_plaintext_output, encrypted_output_path

PROTECTED_EXTENSIONS = {'.csv', '.xlsx', '.xls'}
DOMAINS = ('gst', 'swt', 'cit')


def main() -> int:
    migrated_any = False
    for domain in DOMAINS:
        output_dir = PROJECT_ROOT / domain / 'final_output'
        if not output_dir.exists():
            continue

        for path in sorted(output_dir.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() not in PROTECTED_EXTENSIONS:
                continue

            encrypted_path = migrate_plaintext_output(output_dir, path.name)
            if encrypted_path is None:
                continue

            migrated_any = True
            print(f'MIGRATED {path} -> {encrypted_path}')

        for path in sorted(output_dir.iterdir()):
            if not path.is_file() or not path.name.endswith('.enc'):
                continue
            logical_name = path.name[:-4]
            plain_path = output_dir / logical_name
            if plain_path.exists():
                raise RuntimeError(f'Plaintext artifact still exists after migration: {plain_path}')
            if not encrypted_output_path(output_dir, logical_name).is_file():
                raise RuntimeError(f'Encrypted artifact missing after migration: {path}')

    if not migrated_any:
        print('NO_PLAINTEXT_FINAL_OUTPUT_FILES_FOUND')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
