from concurrent.futures import ThreadPoolExecutor
import sqlite3
from werkbonnen.access import issue_activation, token_hash
from test_werkbonnen import app, create_app, open_workspace, OFFICE, photo


def activate(client, token):
    csrf=client.get('/werkbonnen/api/session').json['csrf']
    return client.post('/werkbonnen/api/activate',json={'token':token},headers={'X-CSRF-Token':csrf})


def test_unactivated_device_cannot_read_records_uploads_or_enroll_others(app):
    client=app.test_client()
    for headers in ({},{'X-Werkbon-Mode':'kantoor'},{'X-Werkbon-Mode':'glaszetter'}):
        assert client.get('/werkbonnen/api/orders',headers=headers).status_code==401
        assert client.get('/werkbonnen/api/files/anything',headers=headers).status_code==401
        assert client.post('/werkbonnen/api/orders',json=OFFICE,headers=headers).status_code==401
        assert client.post('/werkbonnen/api/activations',json={'role':'kantoor'},headers=headers).status_code==401
    assert client.get('/werkbonnen/api/session').json['role'] is None


def test_activation_is_single_use_and_stored_as_hash(app):
    invite=issue_activation(app.config['WERKBON_DB'],'glaszetter','Tablet')
    first=app.test_client()
    assert first.get('/werkbonnen/activeren?token='+invite['token']).status_code==200
    assert first.get('/werkbonnen/api/orders').status_code==401
    assert activate(first,invite['token']).status_code==200
    assert first.get('/werkbonnen/api/orders').status_code==200
    assert activate(app.test_client(),invite['token']).status_code==410
    with sqlite3.connect(app.config['WERKBON_DB']) as db:
        row=db.execute('SELECT token_hash,consumed_at FROM activations').fetchone()
        assert row[0]==token_hash(invite['token']) and row[0]!=invite['token'] and row[1]
        assert db.execute('SELECT COUNT(*) FROM devices').fetchone()[0]==1


def test_expired_or_unapproved_activation_does_not_enroll(app):
    invite=issue_activation(app.config['WERKBON_DB'],'kantoor')
    with sqlite3.connect(app.config['WERKBON_DB']) as db:
        db.execute("UPDATE activations SET expires_at='2000-01-01T00:00:00+00:00'")
    assert activate(app.test_client(),invite['token']).status_code==410
    fresh=issue_activation(app.config['WERKBON_DB'],'kantoor')
    assert app.test_client().post('/werkbonnen/api/activate',json={'token':fresh['token']}).status_code==403
    with sqlite3.connect(app.config['WERKBON_DB']) as db:
        assert db.execute('SELECT COUNT(*) FROM devices').fetchone()[0]==0


def test_only_one_concurrent_device_claim_succeeds(app):
    invite=issue_activation(app.config['WERKBON_DB'],'glaszetter')
    def claim(_):
        return activate(app.test_client(),invite['token']).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(claim,range(4)))
    assert sorted(results)==[200,410,410,410]


def test_field_device_cannot_spoof_office_or_create_activation_links(app):
    client=app.test_client()
    headers=open_workspace(client,'glaszetter')
    headers['X-Werkbon-Mode']='kantoor'
    assert client.get('/werkbonnen/api/session',headers=headers).json['role']=='glaszetter'
    assert client.post('/werkbonnen/api/orders',json=OFFICE,headers=headers).status_code==403
    assert client.post('/werkbonnen/api/activations',json={'role':'kantoor'},headers=headers).status_code==403
    assert client.get('/werkbonnen/api/devices',headers=headers).status_code==403


def test_office_can_enroll_and_revoke_device_with_immediate_data_block(app):
    office=app.test_client();headers=open_workspace(office,'kantoor')
    invite=office.post('/werkbonnen/api/activations',json={'role':'glaszetter','label':'Tablet 2'},headers=headers)
    assert invite.status_code==201 and invite.json['path'].startswith('/werkbonnen/activeren#token=')
    field=app.test_client()
    assert activate(field,invite.json['path'].split('token=')[1]).status_code==200
    identity=field.get('/werkbonnen/api/session').json['device_id']
    order=office.post('/werkbonnen/api/orders',json=OFFICE,headers=headers).json
    order=photo(office,headers,order,'before').json
    assert field.get(order['photos'][0]['url']).status_code==200
    assert office.post('/werkbonnen/api/devices/'+identity+'/revoke',headers=headers).status_code==200
    assert field.get('/werkbonnen/api/orders').status_code==401
    assert field.get(order['photos'][0]['url']).status_code==401
    assert field.get('/werkbonnen/api/session').json['role'] is None
    assert office.get('/werkbonnen/api/orders').status_code==200


def test_device_remembered_after_browser_and_server_restart(app):
    client=app.test_client();open_workspace(client,'kantoor')
    cookie=client.get_cookie('session')
    restarted=create_app(dict(TESTING=True,WERKBON_DATA_DIR=app.config['WERKBON_DATA_DIR'],WERKBON_SECURE_COOKIE=False))
    browser=restarted.test_client();browser.set_cookie('session',cookie.value)
    assert browser.get('/werkbonnen/api/session').json['role']=='kantoor'
    assert browser.get('/werkbonnen/api/orders').status_code==200
