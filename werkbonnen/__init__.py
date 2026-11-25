import base64
import functools
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import warnings
from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, current_app, g, jsonify, render_template, request, send_file, session
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.utils import secure_filename
from .access import consume_activation, ensure_schema, issue_activation, timestamp

bp = Blueprint('werkbonnen', __name__, url_prefix='/werkbonnen', static_folder='static', template_folder='templates')
OFFICE_FIELDS = ('project', 'name', 'address', 'phone', 'email', 'assignment', 'planned_date', 'assignee')
WORK_FIELDS = ('work_done', 'materials', 'hours', 'customer_notes')
Image.MAX_IMAGE_PIXELS = 40_000_000


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def db():
    if 'werkbon_db' not in g:
        conn = sqlite3.connect(current_app.config['WERKBON_DB'], timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        g.werkbon_db = conn
    return g.werkbon_db


def init_app(app):
    default_root = Path.home() / '.local' / 'share' / 'janbos-werkbonnen'
    root = Path(app.config.get('WERKBON_DATA_DIR', os.getenv('WERKBON_DATA_DIR', str(default_root)))).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / 'uploads').mkdir(exist_ok=True)
    app.config['WERKBON_DATA_DIR'] = root
    app.config['WERKBON_DB'] = str(root / 'werkbonnen.sqlite3')
    secret_path = root / '.session-secret'
    if not secret_path.exists():
        with tempfile.NamedTemporaryFile(mode='w', dir=root, delete=False) as temp:
            temp.write(secrets.token_hex(32))
            temp_path = Path(temp.name)
        try:
            os.link(temp_path, secret_path)
        except FileExistsError:
            pass
        finally:
            temp_path.unlink(missing_ok=True)
    if not app.secret_key:
        app.secret_key = secret_path.read_text()
    app.config.setdefault('WERKBON_SECURE_COOKIE', os.getenv('WERKBON_SECURE_COOKIE', '1') != '0')
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=app.config['WERKBON_SECURE_COOKIE'], PERMANENT_SESSION_LIFETIME=timedelta(days=365))
    if not app.config.get('MAX_CONTENT_LENGTH'):
        app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024
    with sqlite3.connect(app.config['WERKBON_DB']) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript('''
          CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open', version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            signed_at TEXT, signed_by TEXT, signature_id TEXT);
          CREATE TABLE IF NOT EXISTS photos (
            id TEXT PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
            category TEXT NOT NULL, filename TEXT NOT NULL, created_at TEXT NOT NULL);
        ''')
        conn.execute('BEGIN IMMEDIATE')
        if 'deleted_at' not in {column[1] for column in conn.execute('PRAGMA table_info(orders)')}:
            conn.execute('ALTER TABLE orders ADD COLUMN deleted_at TEXT')
        conn.commit()
        ensure_schema(conn)
    app.register_blueprint(bp)
    # The user explicitly chose public access for the office work-order pages.
    # Public office can issue field-device links, as requested by the user.
    # Device listing/revocation and office-device enrollment remain excluded.
    office_api = Blueprint('werkbonnen_office', __name__, url_prefix='/werkbonnen/kantoor-api')
    prefix = '/werkbonnen/api'
    for rule in list(app.url_map.iter_rules()):
        if not rule.rule.startswith(prefix + '/'):
            continue
        suffix = rule.rule[len(prefix):]
        if suffix not in ('/session', '/activations') and not suffix.startswith(('/orders', '/files/')):
            continue
        office_api.add_url_rule(suffix, endpoint=rule.endpoint.rsplit('.', 1)[-1],
                                view_func=app.view_functions[rule.endpoint],
                                methods=sorted(rule.methods - {'HEAD', 'OPTIONS'}))
    office_api.after_request(headers)
    for code in (400,401,403,404,409,410,413,429):
        office_api.register_error_handler(code, error_response)
    app.register_blueprint(office_api)

    @app.before_request
    def protect_werkbon_storage():
        # The existing portal serves its root folder as static files. Never let
        # that route expose the new database, uploads or configuration files.
        if request.endpoint == 'static' and app.static_folder:
            target = (Path(app.static_folder) / (request.view_args or {}).get('filename', '')).resolve()
            if target.is_relative_to(root) or target.name.startswith('.env') or target.is_relative_to(Path(__file__).parent):
                abort(404)

    @app.teardown_appcontext
    def close_db(error=None):
        conn = g.pop('werkbon_db', None)
        if conn:
            conn.close()


@bp.after_request
def headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Cache-Control'] = 'no-store' if request.path.find('/static/') == -1 else 'public, max-age=3600'
    if response.mimetype == 'text/html':
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
    return response


@bp.errorhandler(400)
@bp.errorhandler(401)
@bp.errorhandler(403)
@bp.errorhandler(404)
@bp.errorhandler(409)
@bp.errorhandler(410)
@bp.errorhandler(413)
@bp.errorhandler(429)
def error_response(error):
    return jsonify(error=error.description), error.code


def checked_request(office=False):
    def decorate(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            if public_office_request():
                g.werkbon_mode = 'kantoor'
            else:
                device = active_device()
                if not device:
                    abort(401, 'Dit apparaat is nog niet geactiveerd. Open een eenmalige activatielink.')
                mode = request.headers.get('X-Werkbon-Mode', 'glaszetter')
                if mode not in ('kantoor', 'glaszetter'):
                    abort(400, 'Ongeldige werkbon-omgeving.')
                g.werkbon_mode = 'kantoor' if device['role'] == 'kantoor' and mode == 'kantoor' else 'glaszetter'
            if office and g.werkbon_mode != 'kantoor':
                abort(403, 'Alleen een geactiveerd kantoorapparaat kan dit aanpassen.')
            if request.method not in ('GET', 'HEAD'):
                check_csrf()
            return fn(*args, **kwargs)
        return inner
    return decorate


def public_office_request():
    return request.blueprint == 'werkbonnen_office'


def api_base():
    return '/werkbonnen/kantoor-api' if public_office_request() else '/werkbonnen/api'


def active_device():
    identity = session.get('werkbon_device')
    if not isinstance(identity, str):
        return None
    return db().execute('SELECT * FROM devices WHERE id=? AND revoked_at IS NULL', (identity,)).fetchone()


def check_csrf():
    token = session.get('werkbon_csrf', '')
    if not token or not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), token):
        abort(403, 'De sessie is vernieuwd. Vernieuw de pagina en probeer opnieuw.')


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, 'Ongeldige gegevens.')
    return data


def row(order_id, include_deleted=False):
    result = db().execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
    if not result or result['deleted_at'] and not include_deleted:
        abort(404, 'Werkbon niet gevonden.')
    return result


def unlocked(record, version):
    if record['status'] == 'completed':
        abort(409, 'Deze werkbon is ondertekend en kan niet meer worden aangepast.')
    check_version(record, version)


def check_version(record, version):
    if version != record['version']:
        abort(409, 'Iemand heeft deze werkbon intussen aangepast. Herlaad de werkbon; je invoer blijft in beeld.')


def payload(record):
    data = json.loads(record['data'])
    data.update({k: record[k] for k in ('id', 'status', 'version', 'created_at', 'updated_at', 'signed_at', 'signed_by', 'deleted_at')})
    data['number'] = f"WB-{record['id']:05d}"
    data['photos'] = [{'id': p['id'], 'category': p['category'], 'url': f"{api_base()}/files/{p['id']}"}
                      for p in db().execute("SELECT * FROM photos WHERE order_id=? AND category IN ('before','after') ORDER BY created_at,id", (record['id'],))]
    data['signature_url'] = f"{api_base()}/files/{record['signature_id']}" if record['signature_id'] else None
    return data


def text_fields(data, fields):
    result = {}
    for name in fields:
        value = data.get(name, '')
        if not isinstance(value, str) or len(value) > (10000 if name in ('assignment', *WORK_FIELDS) else 300):
            abort(400, 'Een veld is ongeldig of te lang.')
        result[name] = value.strip()
    if 'email' in fields:
        if any(not result[x] for x in ('project', 'name', 'address', 'phone', 'email', 'assignment')):
            abort(400, 'Vul project, naam, adres, telefoon, e-mail en opdracht in.')
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', result['email']):
            abort(400, 'Vul een geldig e-mailadres in.')
        if result['planned_date']:
            try:
                datetime.strptime(result['planned_date'], '%Y-%m-%d')
            except ValueError:
                abort(400, 'Kies een geldige plandatum.')
    return result


@bp.get('/kantoor')
@bp.get('/glaszetter')
def page():
    return render_template('werkbon.html', mode='kantoor' if request.path.endswith('/kantoor') else 'glaszetter')


@bp.get('/activeren')
def activate_page():
    return render_template('activate.html')


@bp.get('/manifest/<mode>.webmanifest')
def manifest(mode):
    if mode not in ('kantoor', 'glaszetter'):
        abort(404)
    return jsonify(id=f'/werkbonnen/{mode}', name='Jan Bos Werkbonnen' + (' Kantoor' if mode == 'kantoor' else ''),
                   short_name='Werkbonnen', lang='nl', start_url=f'/werkbonnen/{mode}', scope='/werkbonnen/',
                   display='standalone', background_color='#f3f6f8', theme_color='#123b5d',
                   icons=[{'src': '/werkbonnen/static/icon-192.png', 'sizes': '192x192', 'type': 'image/png'},
                          {'src': '/werkbonnen/static/icon-512.png', 'sizes': '512x512', 'type': 'image/png'}])


@bp.get('/sw.js')
def service_worker():
    response = send_file(Path(__file__).parent / 'static' / 'sw.js', mimetype='application/javascript')
    response.headers['Service-Worker-Allowed'] = '/werkbonnen/'
    return response


@bp.get('/api/session')
def get_session():
    device = active_device()
    if 'werkbon_csrf' not in session:
        session['werkbon_csrf'] = secrets.token_urlsafe(32)
    session.permanent = True
    public = public_office_request()
    return jsonify(role='kantoor' if public else device['role'] if device else None,
                   public_office=public, csrf=session['werkbon_csrf'],
                   device_id=None if public else device['id'] if device else None,
                   device_label=None if public else device['label'] if device else None)


@bp.post('/api/activate')
def activate():
    check_csrf()
    with db():
        db().execute('BEGIN IMMEDIATE')
        device = consume_activation(db(), body().get('token'))
        if not device:
            abort(410, 'Deze activatielink is verlopen of al gebruikt. Vraag kantoor om een nieuwe link.')
    session.clear()
    session.permanent = True
    session['werkbon_device'] = device['id']
    session['werkbon_csrf'] = secrets.token_urlsafe(32)
    return jsonify(role=device['role'], device_id=device['id'], start_url='/werkbonnen/' + device['role'])


@bp.post('/api/activations')
@checked_request(office=True)
def create_activation():
    data = body()
    role = data.get('role', 'glaszetter')
    if public_office_request() and role != 'glaszetter':
        abort(403, 'Via kantoor kun je alleen een glaszetter activeren.')
    try:
        result = issue_activation(current_app.config['WERKBON_DB'], role, data.get('label', ''))
    except ValueError as error:
        abort(400, str(error))
    return jsonify(path='/werkbonnen/activeren#token=' + result['token'], role=result['role'],
                   label=result['label'], expires_at=result['expires_at']), 201


@bp.get('/api/devices')
@checked_request(office=True)
def list_devices():
    return jsonify(devices=[dict(d) for d in db().execute('SELECT id,role,label,created_at,revoked_at FROM devices ORDER BY created_at DESC')],
                   current_device_id=session['werkbon_device'])


@bp.post('/api/devices/<device_id>/revoke')
@checked_request(office=True)
def revoke_device(device_id):
    with db():
        changed = db().execute('UPDATE devices SET revoked_at=? WHERE id=? AND revoked_at IS NULL', (timestamp(), device_id)).rowcount
    if not changed:
        abort(404, 'Geen actief apparaat gevonden.')
    return jsonify(ok=True)


@bp.get('/api/orders')
@checked_request()
def orders():
    trash = request.args.get('trash') == '1'
    if trash and g.werkbon_mode != 'kantoor':
        abort(403, 'De prullenbak is alleen beschikbaar op kantoor.')
    condition = 'IS NOT NULL' if trash else 'IS NULL'
    return jsonify(orders=[payload(r) for r in db().execute('SELECT * FROM orders WHERE deleted_at ' + condition + ' ORDER BY created_at DESC,id DESC')])


@bp.post('/api/orders')
@checked_request(office=True)
def create_order():
    values = text_fields(body(), OFFICE_FIELDS)
    values.update({k: '' for k in WORK_FIELDS})
    with db():
        cur = db().execute('INSERT INTO orders(data,created_at,updated_at) VALUES(?,?,?)', (json.dumps(values), now(), now()))
    return jsonify(payload(row(cur.lastrowid))), 201


@bp.get('/api/orders/<int:order_id>')
@checked_request()
def get_order(order_id):
    return jsonify(payload(row(order_id)))


@bp.get('/api/orders/<int:order_id>/pdf')
@checked_request(office=True)
def download_pdf(order_id):
    from .pdf_export import build_work_order_pdf
    record = row(order_id)
    document = build_work_order_pdf(payload(record), current_app.config['WERKBON_DATA_DIR'])
    project = secure_filename(json.loads(record['data'])['project'])[:70] or 'project'
    return send_file(io.BytesIO(document), mimetype='application/pdf', as_attachment=True,
                     download_name=f'Werkbon_WB-{order_id:05d}_{project}.pdf', max_age=0)


@bp.delete('/api/orders/<int:order_id>')
@checked_request(office=True)
def delete_order(order_id):
    data = body()
    with db():
        db().execute('BEGIN IMMEDIATE')
        record = row(order_id)
        check_version(record, data.get('version'))
        stamp = now()
        db().execute('UPDATE orders SET deleted_at=?,updated_at=?,version=version+1 WHERE id=?', (stamp, stamp, order_id))
    return jsonify(ok=True)


@bp.post('/api/orders/<int:order_id>/restore')
@checked_request(office=True)
def restore_order(order_id):
    data = body()
    with db():
        db().execute('BEGIN IMMEDIATE')
        record = row(order_id, include_deleted=True)
        if not record['deleted_at']:
            abort(409, 'Deze werkbon staat niet in de prullenbak.')
        check_version(record, data.get('version'))
        db().execute('UPDATE orders SET deleted_at=NULL,updated_at=?,version=version+1 WHERE id=?', (now(), order_id))
    return jsonify(payload(row(order_id)))


@bp.patch('/api/orders/<int:order_id>')
@checked_request()
def update_order(order_id):
    data = body()
    with db():
        db().execute('BEGIN IMMEDIATE')
        record = row(order_id)
        unlocked(record, data.get('version'))
        fields = OFFICE_FIELDS if data.get('section') == 'office' else WORK_FIELDS
        if fields == OFFICE_FIELDS and g.werkbon_mode != 'kantoor':
            abort(403, 'Alleen kantoor kan klantgegevens en opdracht wijzigen.')
        values = json.loads(record['data'])
        values.update(text_fields(data, fields))
        status = 'in_progress' if data.get('start') or fields == WORK_FIELDS else record['status']
        if record['status'] == 'in_progress':
            status = 'in_progress'
        db().execute('UPDATE orders SET data=?,status=?,version=version+1,updated_at=? WHERE id=?',
                     (json.dumps(values), status, now(), order_id))
    return jsonify(payload(row(order_id)))


def image_bytes(stream, signature=False):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(stream) as original:
                original.load()
                img = ImageOps.exif_transpose(original).convert('RGB')
                img.thumbnail((1800, 1800))
                if signature:
                    extrema = img.convert('L').getextrema()
                    if extrema[1] - extrema[0] < 20:
                        abort(400, 'Zet eerst een handtekening.')
                out = io.BytesIO()
                img.save(out, 'JPEG', quality=85)
                return out.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        abort(400, 'Gebruik een geldige JPG-, PNG- of WebP-afbeelding. Kies bij HEIC eerst JPG.')


@bp.post('/api/orders/<int:order_id>/photos')
@checked_request()
def upload_photo(order_id):
    category = request.form.get('category')
    photo = request.files.get('file')
    if category not in ('before', 'after') or not photo:
        abort(400, 'Kies een foto en vóór of na het werk.')
    content = image_bytes(photo.stream)
    photo_id = secrets.token_hex(16)
    path = current_app.config['WERKBON_DATA_DIR'] / 'uploads' / (photo_id + '.jpg')
    with db():
        db().execute('BEGIN IMMEDIATE')
        record = row(order_id)
        unlocked(record, request.form.get('version', type=int))
        count = db().execute('SELECT COUNT(*) FROM photos WHERE order_id=?', (order_id,)).fetchone()[0]
        if count >= 60:
            abort(400, 'Deze werkbon bevat al 60 foto’s.')
        path.write_bytes(content)
        db().execute('INSERT INTO photos VALUES(?,?,?,?,?)', (photo_id, order_id, category, path.name, now()))
        db().execute("UPDATE orders SET version=version+1,status='in_progress',updated_at=? WHERE id=?", (now(), order_id))
    return jsonify(payload(row(order_id))), 201


@bp.delete('/api/orders/<int:order_id>/photos/<photo_id>')
@checked_request()
def delete_photo(order_id, photo_id):
    data = body()
    with db():
        db().execute('BEGIN IMMEDIATE')
        unlocked(row(order_id), data.get('version'))
        photo = db().execute("SELECT * FROM photos WHERE id=? AND order_id=? AND category!='signature'", (photo_id, order_id)).fetchone()
        if not photo:
            abort(404, 'Foto niet gevonden.')
        db().execute('DELETE FROM photos WHERE id=?', (photo_id,))
        db().execute('UPDATE orders SET version=version+1,updated_at=? WHERE id=?', (now(), order_id))
    (current_app.config['WERKBON_DATA_DIR'] / 'uploads' / photo['filename']).unlink(missing_ok=True)
    return jsonify(payload(row(order_id)))


@bp.get('/api/files/<file_id>')
@checked_request()
def file(file_id):
    photo = db().execute('SELECT * FROM photos WHERE id=?', (file_id,)).fetchone()
    if not photo:
        abort(404, 'Bestand niet gevonden.')
    row(photo['order_id'])
    return send_file(current_app.config['WERKBON_DATA_DIR'] / 'uploads' / photo['filename'], mimetype='image/jpeg')


@bp.post('/api/orders/<int:order_id>/complete')
@checked_request()
def complete(order_id):
    data = body()
    signed_by = data.get('signed_by', '')
    if not isinstance(signed_by, str) or not signed_by.strip() or len(signed_by) > 300 or data.get('consent') is not True:
        abort(400, 'Vul de naam van de klant in en bevestig het akkoord.')
    signature = data.get('signature', '')
    if not isinstance(signature, str) or len(signature) > 2_000_000 or not signature.startswith('data:image/png;base64,'):
        abort(400, 'Zet eerst een handtekening.')
    try:
        content = image_bytes(io.BytesIO(base64.b64decode(signature.split(',', 1)[1], validate=True)), signature=True)
    except (ValueError, base64.binascii.Error):
        abort(400, 'De handtekening is ongeldig.')
    photo_id = secrets.token_hex(16)
    path = current_app.config['WERKBON_DATA_DIR'] / 'uploads' / (photo_id + '.jpg')
    with db():
        db().execute('BEGIN IMMEDIATE')
        record = row(order_id)
        unlocked(record, data.get('version'))
        work = text_fields(data, WORK_FIELDS)
        if not work['work_done']:
            abort(400, 'Beschrijf eerst de uitgevoerde werkzaamheden.')
        categories = {p[0] for p in db().execute('SELECT category FROM photos WHERE order_id=?', (order_id,))}
        if not {'before', 'after'} <= categories:
            abort(400, 'Voeg minimaal één foto vóór en één foto na het werk toe.')
        values = json.loads(record['data'])
        values.update(work)
        path.write_bytes(content)
        stamp = now()
        db().execute('INSERT INTO photos VALUES(?,?,?,?,?)', (photo_id, order_id, 'signature', path.name, stamp))
        db().execute("UPDATE orders SET data=?,status='completed',version=version+1,updated_at=?,signed_at=?,signed_by=?,signature_id=? WHERE id=?",
                     (json.dumps(values), stamp, stamp, signed_by.strip(), photo_id, order_id))
    return jsonify(payload(row(order_id)))
