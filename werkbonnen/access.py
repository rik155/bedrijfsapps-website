"""One-use device enrollment. Only token hashes are stored on the server."""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import sqlite3


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def ensure_schema(connection):
    connection.executescript('''
        CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('kantoor','glaszetter')),
            label TEXT NOT NULL, created_at TEXT NOT NULL, revoked_at TEXT);
        CREATE TABLE IF NOT EXISTS activations (
            token_hash TEXT PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('kantoor','glaszetter')),
            label TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
            consumed_at TEXT);
    ''')


def issue_activation(database_path, role, label='', hours=48):
    if role not in ('kantoor', 'glaszetter'):
        raise ValueError('Kies kantoor of glaszetter.')
    if not isinstance(label, str) or len(label) > 200 or not 0 < hours <= 168:
        raise ValueError('Ongeldige apparaatnaam of geldigheidsduur.')
    token = secrets.token_urlsafe(32)
    expiry = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec='seconds')
    with sqlite3.connect(str(database_path), timeout=15) as connection:
        ensure_schema(connection)
        connection.execute('INSERT INTO activations VALUES(?,?,?,?,?,NULL)',
                           (token_hash(token), role, label.strip() or role.capitalize(), timestamp(), expiry))
    return {'token': token, 'role': role, 'label': label.strip() or role.capitalize(), 'expires_at': expiry}


def consume_activation(connection, token):
    if not isinstance(token, str) or len(token) != 43:
        return None
    record = connection.execute('SELECT * FROM activations WHERE token_hash=?', (token_hash(token),)).fetchone()
    stamp = timestamp()
    if not record or record['consumed_at'] or record['expires_at'] <= stamp:
        return None
    device_id = secrets.token_hex(16)
    connection.execute('INSERT INTO devices VALUES(?,?,?,?,NULL)',
                       (device_id, record['role'], record['label'], stamp))
    connection.execute('UPDATE activations SET consumed_at=? WHERE token_hash=?', (stamp, token_hash(token)))
    return {'id': device_id, 'role': record['role'], 'label': record['label']}
