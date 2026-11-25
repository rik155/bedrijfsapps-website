#!/usr/bin/env python3
"""Extend the *running* portal image, test it, then switch with rollback.

Run on the VPS as the account that can already use Docker. No SSH credentials
are collected. Existing portal source and environment never leave the VPS.
"""
import argparse
import ast
import copy
from datetime import datetime, timezone
import getpass
import hashlib
import http.client
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shlex
import socket
import subprocess
import sys
import tarfile
import time
import urllib.parse
import urllib.request


def command(args, *, capture=False):
    return subprocess.run(args, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None).stdout


def inspect(name):
    return json.loads(command(['docker', 'inspect', name], capture=True))[0]


def private_json(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as target:
        json.dump(value, target)


class UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__('localhost', timeout=60)
        self.socket_path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


class DockerAPI:
    def __init__(self):
        endpoint = os.getenv('DOCKER_HOST')
        if not endpoint:
            context = json.loads(command(['docker', 'context', 'inspect'], capture=True))[0]
            endpoint = context['Endpoints']['docker']['Host']
        if not endpoint.startswith('unix://'):
            raise RuntimeError('Deze installer verwacht de lokale Docker-socket. Er is niets gewijzigd.')
        self.path = endpoint[len('unix://'):]
        version = self.request('GET', '/version', versioned=False)['ApiVersion']
        self.prefix = '/v' + version

    def request(self, method, path, data=None, *, versioned=True):
        connection = UnixHTTP(self.path)
        try:
            payload = json.dumps(data).encode() if data is not None else None
            connection.request(method, (self.prefix if versioned else '') + path,
                               body=payload, headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            raw = response.read()
            value = json.loads(raw) if raw else {}
            if response.status >= 300:
                # Engine errors can contain copied settings; do not print them.
                raise RuntimeError(f'Docker kon {method} {path.split("?")[0]} niet uitvoeren (HTTP {response.status}).')
            return value
        finally:
            connection.close()

    def create(self, name, settings):
        return self.request('POST', '/containers/create?name=' + urllib.parse.quote(name, safe=''), settings)['Id']


def prepare_config(original, image, additions, *, candidate=False):
    config = copy.deepcopy(original['Config'])
    host = copy.deepcopy(original['HostConfig'])
    config['Image'] = image
    environment = dict(item.split('=', 1) for item in (config.get('Env') or []) if '=' in item)
    environment.update(additions)
    config['Env'] = [key + '=' + value for key, value in environment.items()]
    if host.get('AutoRemove') or host.get('ContainerIDFile'):
        raise RuntimeError('Deze container heeft een bijzondere levenscyclus; automatische vervanging is overgeslagen.')
    # Resolve every volume to its current name/source, including anonymous ones.
    old_mount_options = {m.get('Target'): m for m in host.get('Mounts', []) or []}
    mounts = []
    for mounted in original.get('Mounts', []):
        kind, target = mounted['Type'], mounted['Destination']
        if kind == 'tmpfs':
            continue
        if kind not in ('bind', 'volume'):
            raise RuntimeError('Er is een niet ondersteunde mount; er is niets vervangen.')
        options = copy.deepcopy(old_mount_options.get(target, {}))
        options.update(Type=kind, Target=target, ReadOnly=not mounted.get('RW', True),
                       Source=mounted['Name'] if kind == 'volume' else mounted['Source'])
        if kind == 'bind' and mounted.get('Propagation'):
            options.setdefault('BindOptions', {})['Propagation'] = mounted['Propagation']
        if kind == 'volume':
            options.setdefault('VolumeOptions', {})['NoCopy'] = True
        mounts.append(options)
    host['Binds'] = None
    host['VolumesFrom'] = None
    host['Mounts'] = mounts
    networks = original.get('NetworkSettings', {}).get('Networks', {})
    endpoints = {}
    for network, settings in networks.items():
        if settings.get('IPAMConfig'):
            raise RuntimeError('De container heeft een vast netwerkadres; automatische vervanging is overgeslagen.')
        if network not in ('bridge', 'host', 'none'):
            aliases = [a for a in settings.get('Aliases') or [] if a != original['Id'][:12]]
            endpoints[network] = {} if candidate else {'Aliases': aliases}
    if host.get('NetworkMode', '').startswith('container:'):
        raise RuntimeError('Deze container deelt een ander netwerk; automatische vervanging is overgeslagen.')
    if candidate:
        if host.get('NetworkMode') == 'host':
            raise RuntimeError('Een testcontainer met host-netwerk kan niet veilig naast de huidige app draaien.')
        host['PortBindings'] = {}
        host['PublishAllPorts'] = False
        host['RestartPolicy'] = {'Name': 'no', 'MaximumRetryCount': 0}
        config['Labels'] = {}  # Do not register a test instance in a Docker proxy.
        config.pop('Hostname', None)
        config.pop('Domainname', None)
    config['HostConfig'] = host
    if endpoints:
        config['NetworkingConfig'] = {'EndpointsConfig': endpoints}
    return config


def patch_app(source):
    marker = '# Jan Bos werkbonnen: aparte sessie en behoud bestaand portaal'
    if marker in source or re.search(r'^\s*from werkbonnen\b', source, re.M):
        raise RuntimeError('Er staat al een werkbon-uitbreiding in deze app. Er is niets overschreven.')
    tree = ast.parse(source)
    has_app = any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'app' for t in n.targets)
                  for n in tree.body)
    if not has_app:
        raise RuntimeError('Het verwachte Flask-object app is niet gevonden. Er is niets gewijzigd.')
    guards = [n for n in tree.body if isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
              and isinstance(n.test.left, ast.Name) and n.test.left.id == '__name__'
              and any(isinstance(c, ast.Constant) and c.value == '__main__' for c in n.test.comparators)]
    if len(guards) > 1:
        raise RuntimeError('De opstartcode is niet eenduidig. Er is niets gewijzigd.')
    if any(isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
           and isinstance(n.value.func, ast.Attribute) and n.value.func.attr == 'run' for n in tree.body):
        raise RuntimeError('De app start vóór de uitbreidingshaak. Er is niets gewijzigd.')
    lines = source.splitlines(keepends=True)
    index = guards[0].lineno - 1 if guards else len(lines)
    insertion = '\n' + marker + '\nfrom werkbonnen.portal import attach_to_portal\nattach_to_portal(app)\n\n'
    lines.insert(index, insertion)
    result = ''.join(lines)
    compile(result, 'app.py', 'exec')
    return result


def patch_office(source):
    if 'id="werkbonnen-kantoor"' in source or "id='werkbonnen-kantoor'" in source:
        return source
    tile = '\n<a class="card" id="werkbonnen-kantoor" href="/werkbonnen/kantoor"><span class="icon">▤</span><h3>Werkbonnen</h3><p>Opdrachten aanmaken, uitvoering volgen en ondertekende bonnen bekijken.</p></a>\n'
    grids = list(re.finditer(r'<(?:section|div)\b[^>]*\bclass=["\'][^"\']*\bgrid\b[^"\']*["\'][^>]*>', source, re.I))
    if len(grids) == 1:
        offset = grids[0].end()
        return source[:offset] + tile + source[offset:]
    endings = list(re.finditer(r'</main\s*>', source, re.I))
    if len(endings) != 1:
        raise RuntimeError('De kantoorindeling is niet herkend. Er is niets gewijzigd.')
    offset = endings[0].start()
    return source[:offset] + '<section aria-label="Werkbonnen">' + tile + '</section>' + source[offset:]


def download_module(release, destination):
    url = 'https://codeload.github.com/rik155/bedrijfsapps-website/tar.gz/' + release
    with urllib.request.urlopen(url, timeout=60) as response:
        content = response.read(64 * 1024 * 1024 + 1)
    if len(content) > 64 * 1024 * 1024:
        raise RuntimeError('Het bronpakket is groter dan verwacht.')
    count = 0
    with tarfile.open(fileobj=io.BytesIO(content), mode='r:gz') as archive:
        for member in archive.getmembers():
            parts = PurePosixPath(member.name).parts[1:]
            if not parts or parts[0] != 'werkbonnen':
                continue
            if '..' in parts or member.issym() or member.islnk():
                raise RuntimeError('Het bronpakket bevat een onveilig pad.')
            target = destination.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as data:
                    target.write_bytes(data.read())
                count += 1
    if count < 7 or not (destination / 'werkbonnen' / 'portal.py').is_file():
        raise RuntimeError('Het bronpakket is onvolledig.')


PROBE = r'''
import http.client, json, os
from http.cookies import SimpleCookie

def call(path, method='GET', payload=None, cookie='', csrf=''):
    connection=http.client.HTTPConnection('127.0.0.1',80,timeout=5)
    headers={'Content-Type':'application/json'}
    if cookie: headers['Cookie']=cookie
    if csrf: headers['X-CSRF-Token']=csrf
    connection.request(method,path,body=json.dumps(payload) if payload is not None else None,headers=headers)
    response=connection.getresponse();body=response.read();status=response.status
    jar=SimpleCookie();jar.load(response.getheader('Set-Cookie',''))
    new_cookie='; '.join(key+'='+value.value for key,value in jar.items())
    connection.close()
    return status,body,new_cookie

result={}
for path in ('/','/kantoor.html'):
    result[path]=call(path)[0]
    assert result[path] in (200,301,302,303,307,308,401,403), 'Bestaande portaalroute geeft een fout'
assert call('/werkbonnen/kantoor')[0]==200
assert call('/werkbonnen/glaszetter')[0]==200
assert call('/werkbonnen/api/orders')[0]==401
assert call('/werkbonnen/__init__.py')[0]==404
for role in ('kantoor','glaszetter'):
    status,body,cookie=call('/werkbonnen/api/session')
    assert status==200 and 'janbos_werkbon_session=' in cookie
    csrf=json.loads(body)['csrf']
    status,body,cookie=call('/werkbonnen/api/login','POST',
        {'role':role,'password':os.environ['WERKBON_'+role.upper()+'_PASSWORD']},cookie,csrf)
    assert status==200, 'Aanmelden mislukt'
    csrf=json.loads(body)['csrf']
    assert call('/werkbonnen/api/orders',cookie=cookie)[0]==200
    if role=='glaszetter':
        assert call('/werkbonnen/api/orders','POST',{},cookie,csrf)[0]==403
print(json.dumps({'ok':True,'portal':result}))
'''


def wait_ready(name):
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline:
        try:
            result = command(['docker', 'exec', name, 'python', '-c', PROBE], capture=True)
            return json.loads(result.strip())
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            time.sleep(2)
    raise RuntimeError('De app doorstaat de opstart- en aanmeldcontrole niet.')


def delete_test(api, container_id):
    api.request('DELETE', '/containers/' + container_id + '?force=true')  # No volume deletion.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', required=True)
    parser.add_argument('--container', default='bedrijfsapps-website')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-f0-9]{40}', args.release) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]+', args.container):
        raise RuntimeError('Ongeldige release of containernaam.')
    os.umask(0o077)
    original = inspect(args.container)
    if not original['State']['Running']:
        raise RuntimeError('De bestaande kantoorcontainer draait niet. Er is niets gewijzigd.')
    if original['Config'].get('WorkingDir') != '/app':
        raise RuntimeError('De werkmap verschilt van de gecontroleerde installatie. Er is niets gewijzigd.')
    if not any(m['Destination'] == '/data' and m.get('RW') for m in original.get('Mounts', [])):
        raise RuntimeError('Het verwachte blijvende /data-volume ontbreekt. Er is niets gewijzigd.')
    if any(m['Destination'] == '/app' or m['Destination'].startswith('/app/') for m in original.get('Mounts', [])):
        raise RuntimeError('De broncode wordt apart gemount. Er is niets gewijzigd.')
    if not original['HostConfig'].get('PortBindings', {}).get('80/tcp'):
        raise RuntimeError('De verwachte interne poort 80 is niet gevonden. Er is niets gewijzigd.')
    prepare_config(original, original['Image'], {}, candidate=True)
    api = DockerAPI()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(2)
    stage = Path.home() / ('janbos-werkbonnen-' + stamp)
    stage.mkdir(mode=0o700)
    build = stage / 'build'; build.mkdir(mode=0o700)
    private_json(stage / 'oude-container.json', original)
    print('1/5 Huidige versie bewaren en alleen app.py + kantoor.html uitbreiden.', flush=True)
    for filename in ('app.py', 'kantoor.html', 'index.html'):
        command(['docker', 'cp', args.container + ':/app/' + filename, str(stage / filename)])
    source = (stage / 'app.py').read_text()
    office = (stage / 'kantoor.html').read_text()
    (build / 'app.py').write_text(patch_app(source))
    (build / 'kantoor.html').write_text(patch_office(office))
    index_hash = hashlib.sha256((stage / 'index.html').read_bytes()).hexdigest()
    download_module(args.release, build)
    additions = {'WERKBON_DATA_DIR': '/data/werkbonnen', 'WERKBON_SECURE_COOKIE': '1'}
    old_env = dict(v.split('=', 1) for v in original['Config'].get('Env', []) if '=' in v)
    for role in ('KANTOOR', 'GLASZETTER'):
        key = 'WERKBON_' + role + '_PASSWORD'
        password = old_env.get(key, '')
        if len(password) < 12:
            password = getpass.getpass('Kies wachtwoord voor ' + role.lower() + ' (minimaal 12 tekens): ')
            if len(password) < 12 or len(password) > 256 or any(c in password for c in '\r\n\0'):
                raise RuntimeError('Gebruik een wachtwoord van 12 tot 256 tekens zonder regeleinden.')
            if getpass.getpass('Herhaal het wachtwoord: ') != password:
                raise RuntimeError('De wachtwoorden verschillen. De bestaande app is niet gewijzigd.')
        additions[key] = password
    if additions['WERKBON_KANTOOR_PASSWORD'] == additions['WERKBON_GLASZETTER_PASSWORD']:
        raise RuntimeError('Kies verschillende wachtwoorden voor kantoor en glaszetter.')
    private_json(stage / 'werkbon-configuratie.json', additions)
    base_tag = args.container.lower() + ':voor-werkbonnen-' + stamp
    new_image = args.container.lower() + ':werkbonnen-' + stamp
    # Snapshot writable container files too: a past hotfix may not be in its
    # original image. Docker excludes mounted data; those mounts are preserved.
    command(['docker', 'commit', original['Id'], base_tag], capture=True)
    (build / 'Dockerfile').write_text('FROM ' + base_tag + '\nWORKDIR /app\n'
        'RUN python -m pip install --no-cache-dir Pillow==11.3.0\n'
        'COPY werkbonnen /app/werkbonnen\nCOPY app.py kantoor.html /app/\n')
    print('2/5 Nieuwe image bouwen vanuit de huidige image; overige apps blijven draaien.', flush=True)
    command(['docker', 'build', '-t', new_image, str(build)])
    test_name = args.container + '-werkbon-test-' + stamp
    test_id = None
    print('3/5 Aparte testcontainer controleren, inclusief beide aanmeldingen.', flush=True)
    try:
        test_id = api.create(test_name, prepare_config(original, new_image, additions, candidate=True))
        api.request('POST', '/containers/' + test_id + '/start')
        wait_ready(test_name)
        actual = command(['docker', 'exec', test_name, 'python', '-c',
            "import hashlib;print(hashlib.sha256(open('/app/index.html','rb').read()).hexdigest())"], capture=True).strip()
        if actual != index_hash:
            raise RuntimeError('De medewerkerspagina wijkt af; er wordt niet overgeschakeld.')
    finally:
        if test_id:
            delete_test(api, test_id)
    # Finish every check and prepare the replacement before stopping the portal.
    live_config = prepare_config(original, new_image, additions)
    current = inspect(args.container)
    if current['Id'] != original['Id'] or current['Image'] != original['Image']:
        raise RuntimeError('De huidige container is intussen gewijzigd. Er wordt niet overgeschakeld.')
    backup = args.container + '-voor-werkbonnen-' + stamp
    new_id = None
    print('4/5 Kantoor kort herstarten met dezelfde poorten, volumes en instellingen.', flush=True)
    try:
        api.request('POST', '/containers/' + original['Id'] + '/stop?t=20')
        api.request('POST', '/containers/' + original['Id'] + '/rename?name=' + backup)
        new_id = api.create(args.container, live_config)
        api.request('POST', '/containers/' + new_id + '/start')
        wait_ready(args.container)
    except BaseException:
        print('Controle niet geslaagd; de oorspronkelijke kantoorcontainer wordt teruggezet.', flush=True)
        # Reconcile actual engine state, including an interrupted API response.
        try:
            occupant = inspect(args.container)
        except subprocess.CalledProcessError:
            occupant = None
        if occupant and occupant['Id'] != original['Id']:
            if occupant['Config']['Image'] != new_image:
                raise RuntimeError('Een andere container gebruikt intussen de naam; automatisch herstel is gestopt.')
            api.request('DELETE', '/containers/' + occupant['Id'] + '?force=true')
        previous = inspect(original['Id'])
        if previous['Name'].lstrip('/') != args.container:
            api.request('POST', '/containers/' + original['Id'] + '/rename?name=' + args.container)
        if not previous['State']['Running']:
            api.request('POST', '/containers/' + original['Id'] + '/start')
        raise
    private_json(stage / 'resultaat.json', {'container': args.container, 'backup': backup, 'image': new_image,
                                          'release': args.release, 'old_id': original['Id'], 'new_id': new_id})
    restore = stage / 'HERSTEL.sh'
    moved = args.container + '-werkbonnen-bewaard-' + stamp
    restore.write_text('#!/bin/sh\nset -eu\n' + '\n'.join(shlex.join(cmd) for cmd in [
        ['docker', 'stop', args.container], ['docker', 'rename', args.container, moved],
        ['docker', 'rename', backup, args.container], ['docker', 'start', args.container]]) + '\n')
    restore.chmod(0o700)
    print('5/5 Gereed. Kantoor en glaszetter gecontroleerd; medewerkerspagina identiek.', flush=True)
    print('Kantoor: https://apps.93-119-6-183.sslip.io/werkbonnen/kantoor')
    print('Glaszetter: https://apps.93-119-6-183.sslip.io/werkbonnen/glaszetter')
    print('Oorspronkelijke versie bewaard als: ' + backup)
    print('Instellingen en herstelbestand: ' + str(stage))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nInstallatie onderbroken. Controleer of de oorspronkelijke kantoorcontainer draait.', file=sys.stderr)
        sys.exit(130)
    except subprocess.CalledProcessError:
        print('Een Docker-stap is niet gelukt. Deel alleen de foutmelding; geen configuratiebestanden.', file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print('Installatie gestopt: ' + str(error), file=sys.stderr)
        sys.exit(1)
