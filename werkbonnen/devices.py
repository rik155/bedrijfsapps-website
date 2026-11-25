"""VPS administrator command; prints private one-use setup links only here."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
from .access import issue_activation, timestamp


def main():
    parser = argparse.ArgumentParser(description='Apparaten voor de werkbon-app beheren zonder wachtwoorden.')
    parser.add_argument('--database', default=str(Path(os.getenv('WERKBON_DATA_DIR', '/data/werkbonnen')) / 'werkbonnen.sqlite3'))
    commands = parser.add_subparsers(dest='action', required=True)
    invite = commands.add_parser('invite')
    invite.add_argument('role', choices=('kantoor', 'glaszetter'))
    invite.add_argument('--label', default='')
    invite.add_argument('--json', action='store_true')
    revoke = commands.add_parser('revoke')
    revoke.add_argument('device_id')
    commands.add_parser('list')
    args = parser.parse_args()
    if args.action == 'invite':
        result = issue_activation(args.database, args.role, args.label)
        result['path'] = '/werkbonnen/activeren#token=' + result.pop('token')
        if args.json:
            print(json.dumps(result))
        else:
            origin = os.getenv('WERKBON_PUBLIC_ORIGIN', 'https://apps.93-119-6-183.sslip.io').rstrip('/')
            print(origin + result['path'])
            print('Eenmalig te gebruiken; geldig tot ' + result['expires_at'])
    else:
        with sqlite3.connect(args.database, timeout=15) as connection:
            if args.action == 'revoke':
                changed = connection.execute('UPDATE devices SET revoked_at=? WHERE id=? AND revoked_at IS NULL',
                                             (timestamp(), args.device_id)).rowcount
                print('Apparaat ingetrokken.' if changed else 'Geen actief apparaat gevonden.')
            else:
                for device in connection.execute('SELECT id,role,label,revoked_at FROM devices ORDER BY created_at'):
                    print(json.dumps({'id': device[0], 'role': device[1], 'label': device[2], 'revoked': bool(device[3])}))


if __name__ == '__main__':
    main()
