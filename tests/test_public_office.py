import io
from unittest.mock import patch
from test_werkbonnen import app, OFFICE, WORK, open_workspace, photo, signed
from deploy_werkbonnen import initial_activations


def test_office_opens_without_device_and_does_not_activate_field_access(app):
    client=app.test_client()
    state=client.get('/werkbonnen/kantoor-api/session')
    assert state.status_code==200
    assert state.json['role']=='kantoor' and state.json['public_office'] is True
    assert state.json['device_id'] is None
    assert client.get('/werkbonnen/kantoor-api/orders').status_code==200
    assert client.get('/werkbonnen/api/session').json['role'] is None
    assert client.get('/werkbonnen/api/orders').status_code==401
    assert client.post('/werkbonnen/kantoor-api/orders',json=OFFICE).status_code==403
    headers={'X-CSRF-Token':state.json['csrf']}
    created=client.post('/werkbonnen/kantoor-api/orders',json=OFFICE,headers=headers)
    assert created.status_code==201
    assert client.get('/werkbonnen/kantoor-api/orders').json['orders'][0]['id']==created.json['id']


def test_public_office_and_activated_field_share_full_workflow(app):
    office=app.test_client();field=app.test_client()
    state=office.get('/werkbonnen/kantoor-api/session').json
    oh={'X-CSRF-Token':state['csrf']}
    order=office.post('/werkbonnen/kantoor-api/orders',json=OFFICE,headers=oh).json
    fh=open_workspace(field,'glaszetter')
    assert field.get('/werkbonnen/api/orders').json['orders'][0]['id']==order['id']
    order=field.patch(f"/werkbonnen/api/orders/{order['id']}",json=dict(**WORK,version=order['version']),headers=fh).json
    for category in ('before','after'):
        order=photo(field,fh,order,category).json
    result=field.post(f"/werkbonnen/api/orders/{order['id']}/complete",json=signed(order),headers=fh)
    assert result.status_code==200
    completed=office.get(f"/werkbonnen/kantoor-api/orders/{order['id']}").json
    assert completed['status']=='completed' and completed['signed_by']=='Testklant'
    for entry in completed['photos']:
        assert entry['url'].startswith('/werkbonnen/kantoor-api/files/')
        assert app.test_client().get(entry['url']).status_code==200
    assert completed['signature_url'].startswith('/werkbonnen/kantoor-api/files/')
    assert app.test_client().get(completed['signature_url']).status_code==200
    assert app.test_client().get(result.json['signature_url']).status_code==401
    assert office.patch(f"/werkbonnen/kantoor-api/orders/{order['id']}",json=dict(**OFFICE,section='office',version=completed['version']),headers=oh).status_code==409


def test_public_office_does_not_expose_device_management_or_activation(app):
    client=app.test_client()
    state=client.get('/werkbonnen/kantoor-api/session').json
    headers={'X-CSRF-Token':state['csrf']}
    assert client.get('/werkbonnen/kantoor-api/devices').status_code==404
    assert client.post('/werkbonnen/kantoor-api/activations',json={'role':'kantoor'},headers=headers).status_code==404
    assert client.post('/werkbonnen/kantoor-api/activate',json={},headers=headers).status_code==404
    assert client.post('/werkbonnen/api/activations',json={'role':'glaszetter'},headers=headers).status_code==401


def test_installer_generates_only_field_activation_link():
    with patch('deploy_werkbonnen.command',return_value='{"path":"/werkbonnen/activeren#token=fixture","role":"glaszetter"}') as execute:
        links=initial_activations('test-container')
    assert set(links)=={'glaszetter'}
    assert execute.call_count==1
    args=execute.call_args.args[0]
    assert 'glaszetter' in args and 'kantoor' not in args
