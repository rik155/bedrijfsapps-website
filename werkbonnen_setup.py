"""Run on the VPS once. Never uses default or bundled passwords."""
import getpass
import os
import re
from pathlib import Path

target = Path('.env.werkbonnen')
if target.exists():
    raise SystemExit('.env.werkbonnen bestaat al. Pas het bestaande bestand aan; het wordt niet overschreven.')
values = []
for role in ('KANTOOR', 'GLASZETTER'):
    password = getpass.getpass(f'Nieuw wachtwoord voor {role.lower()} (minimaal 12 tekens): ')
    if not re.fullmatch(r'[A-Za-z0-9_!@%+=.,:?-]{12,256}', password):
        raise SystemExit('Gebruik 12 tot 256 tekens: letters, cijfers of _!@%+=.,:?-')
    if getpass.getpass('Herhaal het wachtwoord: ') != password:
        raise SystemExit('De wachtwoorden komen niet overeen.')
    values.append(f"WERKBON_{role}_PASSWORD={password}")
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write('\n'.join(values) + '\nWERKBON_SECURE_COOKIE=1\n')
print('Wachtwoorden ingesteld. Geef .env.werkbonnen mee aan de kantoorcontainer met --env-file.')
