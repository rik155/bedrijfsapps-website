import base64
import io
import sqlite3

from PIL import Image, ImageDraw
import pytest

from flask import Flask
from werkbonnen import init_app


def create_app(config):
    instance = Flask(__name__, static_folder=None)
    instance.config.update(config)
    init_app(instance)
    return instance

OFFICE = dict(project='Testproject – glas vervangen', name='Testklant', address='Teststraat 1, Nijmegen',
              phone='0612345678', email='test@example.com', assignment='Vervang de ruit aan de voorzijde.',
              planned_date='2026-11-26', assignee='Testglaszetter')
WORK = dict(work_done='Ruit vervangen en netjes afgewerkt.', materials='HR++ ruit en beglazingskit', hours='2,5', customer_notes='Alles netjes opgeleverd.')


@pytest.fixture
def app(tmp_path):
    return create_app(dict(TESTING=True, WERKBON_DATA_DIR=tmp_path,
                           WERKBON_SECURE_COOKIE=False,
                           WERKBON_KANTOOR_PASSWORD='test-kantoor-1234',
                           WERKBON_GLASZETTER_PASSWORD='test-glaszetter-1234'))


def login(client, role):
    csrf = client.get('/werkbonnen/api/session').json['csrf']
    result = client.post('/werkbonnen/api/login', json={'role': role, 'password': 'test-'+role+'-1234'}, headers={'X-CSRF-Token': csrf})
    assert result.status_code == 200
    return {'X-CSRF-Token': result.json['csrf']}


def image_bytes(signature=False):
    image = Image.new('RGB', (600, 240), 'white')
    draw = ImageDraw.Draw(image)
    draw.line([(20, 150), (150, 70), (300, 180), (450, 50), (550, 130)], fill='black' if signature else 'blue', width=6)
    buffer = io.BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue()


def photo(client, headers, order, category):
    return client.post(f"/werkbonnen/api/orders/{order['id']}/photos", headers=headers,
                       data={'version': order['version'], 'category': category, 'file': (io.BytesIO(image_bytes()), 'photo.png')})


def signed(order):
    return dict(**WORK, version=order['version'], signed_by='Testklant', consent=True,
                signature='data:image/png;base64,'+base64.b64encode(image_bytes(True)).decode())


def test_full_workflow_and_immutable_signature(app):
    office, field = app.test_client(), app.test_client()
    oh, fh = login(office, 'kantoor'), login(field, 'glaszetter')
    created = office.post('/werkbonnen/api/orders', json=OFFICE, headers=oh)
    assert created.status_code == 201
    order = created.json
    assert order['status'] == 'open'
    assert field.get('/werkbonnen/api/orders').json['orders'][0]['id'] == order['id']
    order = field.patch(f"/werkbonnen/api/orders/{order['id']}", json=dict(**WORK, version=order['version']), headers=fh).json
    assert order['status'] == 'in_progress'
    assert field.post(f"/werkbonnen/api/orders/{order['id']}/complete", json=signed(order), headers=fh).status_code == 400
    for category in ('before', 'after'):
        result = photo(field, fh, order, category)
        assert result.status_code == 201
        order = result.json
    result = field.post(f"/werkbonnen/api/orders/{order['id']}/complete", json=signed(order), headers=fh)
    assert result.status_code == 200
    order = result.json
    assert order['status'] == 'completed' and order['signed_at'] and order['signed_by'] == 'Testklant'
    assert office.get(order['signature_url']).mimetype == 'image/jpeg'
    for p in order['photos']:
        assert office.get(p['url']).status_code == 200
    assert office.get(f"/werkbonnen/api/orders/{order['id']}").json['work_done'] == WORK['work_done']
    assert office.patch(f"/werkbonnen/api/orders/{order['id']}", json=dict(**OFFICE, section='office', version=order['version']), headers=oh).status_code == 409
    assert photo(field, fh, order, 'after').status_code == 409
    assert field.delete(f"/werkbonnen/api/orders/{order['id']}/photos/{order['photos'][0]['id']}", json={'version':order['version']}, headers=fh).status_code == 409
    assert field.post(f"/werkbonnen/api/orders/{order['id']}/complete", json=signed(order), headers=fh).status_code == 409


def test_access_controls_and_validation(app):
    client = app.test_client()
    assert client.get('/werkbonnen/api/orders').status_code == 401
    fh = login(client, 'glaszetter')
    assert client.post('/werkbonnen/api/orders', json=OFFICE, headers=fh).status_code == 403
    office = app.test_client()
    oh = login(office, 'kantoor')
    assert office.post('/werkbonnen/api/orders', json=OFFICE).status_code == 403
    assert office.post('/werkbonnen/api/orders', json=dict(OFFICE, email='invalid'), headers=oh).status_code == 400
    assert office.post('/werkbonnen/api/orders', json=dict(OFFICE, planned_date='2026-02-31'), headers=oh).status_code == 400
    order = office.post('/werkbonnen/api/orders', json=OFFICE, headers=oh).json
    assert client.patch(f"/werkbonnen/api/orders/{order['id']}", json=dict(**OFFICE, section='office', version=order['version']), headers=fh).status_code == 403
    assert client.get('/werkbonnen/api/files/../../.session-secret').status_code == 404
    assert office.post(f"/werkbonnen/api/orders/{order['id']}/photos", headers=oh,
                       data={'version':order['version'],'category':'before','file':(io.BytesIO(b'fake image'),'evil.jpg')}).status_code == 400
    assert client.post('/werkbonnen/api/orders', json=[], headers=fh).status_code == 403


def test_conflicts_do_not_overwrite_data(app):
    office, field = app.test_client(), app.test_client()
    oh, fh = login(office, 'kantoor'), login(field, 'glaszetter')
    order = office.post('/werkbonnen/api/orders', json=OFFICE, headers=oh).json
    updated = office.patch(f"/werkbonnen/api/orders/{order['id']}", json=dict(OFFICE, assignment='Nieuwe opdracht', section='office', version=order['version']), headers=oh)
    assert updated.status_code == 200
    stale = field.patch(f"/werkbonnen/api/orders/{order['id']}", json=dict(**WORK, version=order['version']), headers=fh)
    assert stale.status_code == 409
    assert field.get(f"/werkbonnen/api/orders/{order['id']}").json['assignment'] == 'Nieuwe opdracht'
    assert photo(field, fh, order, 'before').status_code == 409


def test_delete_photo_and_blank_signature(app):
    client = app.test_client()
    headers = login(client, 'kantoor')
    order = client.post('/werkbonnen/api/orders', json=OFFICE, headers=headers).json
    order = photo(client, headers, order, 'before').json
    p = order['photos'][0]
    result = client.delete(f"/werkbonnen/api/orders/{order['id']}/photos/{p['id']}", json={'version':order['version']}, headers=headers)
    assert result.status_code == 200 and result.json['photos'] == []
    assert client.get(p['url']).status_code == 404
    image = Image.new('RGB',(600,200),'white')
    out = io.BytesIO();image.save(out,'PNG')
    data = signed(result.json)
    data['signature']='data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()
    assert client.post(f"/werkbonnen/api/orders/{order['id']}/complete", json=data, headers=headers).status_code == 400


def test_data_persists_after_restart(app):
    client = app.test_client()
    headers = login(client, 'kantoor')
    order = client.post('/werkbonnen/api/orders', json=OFFICE, headers=headers).json
    order = photo(client, headers, order, 'before').json
    restarted = create_app(dict(TESTING=True,WERKBON_DATA_DIR=app.config['WERKBON_DATA_DIR'],WERKBON_SECURE_COOKIE=False,
                                WERKBON_KANTOOR_PASSWORD='test-kantoor-1234',WERKBON_GLASZETTER_PASSWORD='test-glaszetter-1234'))
    fresh = restarted.test_client();login(fresh,'kantoor')
    result = fresh.get(f"/werkbonnen/api/orders/{order['id']}")
    assert result.json['photos'] == order['photos']
    assert fresh.get(result.json['photos'][0]['url']).status_code == 200


def test_login_throttle_and_manifest(app):
    client = app.test_client()
    csrf = client.get('/werkbonnen/api/session').json['csrf']
    for _ in range(8):
        assert client.post('/werkbonnen/api/login', json={'role':'kantoor','password':'bad'},headers={'X-CSRF-Token':csrf}).status_code == 401
    assert client.post('/werkbonnen/api/login', json={'role':'kantoor','password':'bad'},headers={'X-CSRF-Token':csrf}).status_code == 429
    manifest = client.get('/werkbonnen/manifest/glaszetter.webmanifest').json
    assert manifest['start_url'] == '/werkbonnen/glaszetter' and manifest['display']=='standalone'
    assert client.get('/werkbonnen/sw.js').status_code == 200


def test_existing_static_portal_cannot_expose_database_or_uploads(tmp_path):
    from flask import Flask
    from werkbonnen import init_app
    portal = Flask(__name__,static_folder=str(tmp_path),static_url_path='')
    portal.config.update(TESTING=True,WERKBON_DATA_DIR=tmp_path/'data',WERKBON_SECURE_COOKIE=False,
                          WERKBON_KANTOOR_PASSWORD='test-kantoor-1234')
    init_app(portal)
    (tmp_path/'.env.werkbonnen').write_text('private configuration')
    client = portal.test_client()
    assert client.get('/data/werkbonnen.sqlite3').status_code == 404
    assert client.get('/data/.session-secret').status_code == 404
    assert client.get('/.env.werkbonnen').status_code == 404
    headers = login(client,'kantoor')
    order = client.post('/werkbonnen/api/orders',json=OFFICE,headers=headers).json
    order = photo(client,headers,order,'before').json
    assert client.get('/data/uploads/'+order['photos'][0]['id']+'.jpg').status_code == 404
    assert client.get(order['photos'][0]['url']).status_code == 200
