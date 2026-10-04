"""Run on the destination server. Creates secrets once, without printing them."""
import argparse
from pathlib import Path
import re
import secrets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--domain', required=True, help='DNS hostname resolving to this server (no https://)')
    args = parser.parse_args()
    domain = args.domain.lower()
    if len(domain) > 253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', domain):
        parser.error('A valid public DNS hostname is required')
    target = Path(__file__).resolve().parent.parent / 'production.env'
    try:
        with target.open('x', encoding='utf-8', newline='\n') as handle:
            target.chmod(0o600)
            handle.write(f'DOMAIN={domain}\n')
            for name in ('SECRET_KEY', 'POSTGRES_PASSWORD', 'AI_CREDENTIAL_KEY'):
                handle.write(f'{name}={secrets.token_hex(48)}\n')
    except FileExistsError:
        parser.exit(1, 'production.env already exists; preserved. Edit DOMAIN manually if needed.\n')
    print('Created production.env with private secrets. Keep an offline backup; never commit or share it.')


if __name__ == '__main__':
    main()
