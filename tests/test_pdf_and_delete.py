from io import BytesIO
import json
import sqlite3
from pypdf import PdfReader

from test_werkbonnen import app, create_app, open_workspace, OFFICE, WORK, photo, signed


def office_session(client):
    state=client.get('/werkbonnen/kantoor-api/session').json
    return {'X-CSRF-Token':state['csrf']}


def completed_order(app):
    office=app.test_client();headers=office_session(office)
    record=office.post('/werkbonnen/kantoor-api/orders',json=OFFICE,headers=headers).json
    field=app.test_client();fh=open_workspace(field,'glaszetter')
    record=field.patch(f"/werkbonnen/api/orders/{record['id']}",json=dict(**WORK,version=record['version']),headers=fh).json
    for category in ('before','after'):
        record=photo(field,fh,record,category).json
    record=field.post(f"/werkbonnen/api/orders/{record['id']}/complete",json=signed(record),headers=fh).json
    return office,headers,record


def test_pdf_download_contains_record_photos_signature_and_filename(app):
    office,headers,record=completed_order(app)
    response=office.get(f"/werkbonnen/kantoor-api/orders/{record['id']}/pdf")
    assert response.status_code==200 and response.mimetype=='application/pdf'
    assert response.data.startswith(b'%PDF-')
    assert 'attachment;' in response.headers['Content-Disposition'] and '.pdf' in response.headers['Content-Disposition']
    reader=PdfReader(BytesIO(response.data))
    text='\n'.join(page.extract_text() for page in reader.pages)
    for expected in (record['number'],OFFICE['name'],OFFICE['address'],OFFICE['phone'],OFFICE['email'],
                     WORK['work_done'],WORK['materials'],WORK['customer_notes'],'Ondertekend door Testklant',
                     'Foto’s vóór het werk','Foto’s na het werk','Afgerond en ondertekend'):
        assert expected in text
    # Unique image objects include branding, work photo and the signature.
    images=set()
    for page in reader.pages:
        for reference in page['/Resources'].get('/XObject',{}).get_object().values():
            if reference.get_object().get('/Subtype')=='/Image':
                images.add(reference.idnum)
    assert len(images)>=3
    field=app.test_client();fh=open_workspace(field,'glaszetter')
    assert field.get(f"/werkbonnen/api/orders/{record['id']}/pdf",headers=fh).status_code==403
    assert app.test_client().get(f"/werkbonnen/api/orders/{record['id']}/pdf").status_code==401


def test_open_pdf_unicode_escaping_and_long_text_pagination(app):
    client=app.test_client();headers=office_session(client)
    values=dict(OFFICE,name='José van Dijk',assignment='Letterlijk <b>glas</b> & kit.\n'+'Uitvoeren en zorgvuldig afwerken. '*180)
    record=client.post('/werkbonnen/kantoor-api/orders',json=values,headers=headers).json
    response=client.get(f"/werkbonnen/kantoor-api/orders/{record['id']}/pdf")
    assert response.status_code==200
    reader=PdfReader(BytesIO(response.data))
    text='\n'.join(page.extract_text() for page in reader.pages)
    assert len(reader.pages)>=2
    assert 'José van Dijk' in text and 'Letterlijk <b>glas</b> & kit.' in text
    assert 'Deze werkbon is nog niet ondertekend.' in text
    assert all(record['number'] in page.extract_text() and 'Pagina ' in page.extract_text() for page in reader.pages)


def test_delete_hides_record_pdf_photos_and_signature_restore_preserves_them(app):
    office,headers,record=completed_order(app)
    public=office.get(f"/werkbonnen/kantoor-api/orders/{record['id']}").json
    image_urls=[p['url'] for p in public['photos']]+[public['signature_url']]
    image_data=[office.get(url).data for url in image_urls]
    deleted=office.delete(f"/werkbonnen/kantoor-api/orders/{record['id']}",json={'version':public['version']},headers=headers)
    assert deleted.status_code==200
    assert office.get('/werkbonnen/kantoor-api/orders').json['orders']==[]
    assert office.get(f"/werkbonnen/kantoor-api/orders/{record['id']}").status_code==404
    assert office.get(f"/werkbonnen/kantoor-api/orders/{record['id']}/pdf").status_code==404
    assert all(office.get(url).status_code==404 for url in image_urls)
    field=app.test_client();fh=open_workspace(field,'glaszetter')
    assert field.get('/werkbonnen/api/orders').json['orders']==[]
    assert field.get('/werkbonnen/api/orders?trash=1',headers=fh).status_code==403
    assert field.get(record['signature_url']).status_code==404
    trashed=office.get('/werkbonnen/kantoor-api/orders?trash=1').json['orders'][0]
    assert trashed['deleted_at'] and trashed['version']==public['version']+1
    assert office.post(f"/werkbonnen/kantoor-api/orders/{record['id']}/restore",json={'version':public['version']},headers=headers).status_code==409
    restored=office.post(f"/werkbonnen/kantoor-api/orders/{record['id']}/restore",json={'version':trashed['version']},headers=headers)
    assert restored.status_code==200 and restored.json['deleted_at'] is None
    for key in (*OFFICE.keys(),*WORK.keys(),'status','signed_by','signed_at'):
        assert restored.json[key]==public[key]
    assert [office.get(url).data for url in image_urls]==image_data
    assert office.get(f"/werkbonnen/kantoor-api/orders/{record['id']}/pdf").status_code==200
    assert office.patch(f"/werkbonnen/kantoor-api/orders/{record['id']}",json=dict(**OFFICE,section='office',version=restored.json['version']),headers=headers).status_code==409


def test_delete_is_office_only_checks_csrf_and_refuses_stale_versions(app):
    office=app.test_client();headers=office_session(office)
    record=office.post('/werkbonnen/kantoor-api/orders',json=OFFICE,headers=headers).json
    assert office.delete(f"/werkbonnen/kantoor-api/orders/{record['id']}",json={'version':record['version']}).status_code==403
    field=app.test_client();fh=open_workspace(field,'glaszetter');fh['X-Werkbon-Mode']='kantoor'
    assert field.delete(f"/werkbonnen/api/orders/{record['id']}",json={'version':record['version']},headers=fh).status_code==403
    assert field.post(f"/werkbonnen/api/orders/{record['id']}/restore",json={'version':record['version']},headers=fh).status_code==403
    updated=office.patch(f"/werkbonnen/kantoor-api/orders/{record['id']}",json=dict(**OFFICE,section='office',version=record['version']),headers=headers).json
    assert office.delete(f"/werkbonnen/kantoor-api/orders/{record['id']}",json={'version':record['version']},headers=headers).status_code==409
    assert office.get('/werkbonnen/kantoor-api/orders').json['orders'][0]['version']==updated['version']


def test_existing_database_migrates_without_changing_orders(tmp_path):
    directory=tmp_path/'legacy';directory.mkdir()
    values=dict(**OFFICE,**WORK)
    with sqlite3.connect(directory/'werkbonnen.sqlite3') as db:
        db.execute("CREATE TABLE orders(id INTEGER PRIMARY KEY AUTOINCREMENT,data TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',version INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,signed_at TEXT,signed_by TEXT,signature_id TEXT)")
        db.execute('INSERT INTO orders(data,created_at,updated_at) VALUES(?,?,?)',(json.dumps(values),'2026-11-25T12:00:00+00:00','2026-11-25T12:00:00+00:00'))
    migrated=create_app(dict(TESTING=True,WERKBON_DATA_DIR=directory,WERKBON_SECURE_COOKIE=False))
    record=migrated.test_client().get('/werkbonnen/kantoor-api/orders').json['orders'][0]
    assert record['id']==1 and record['deleted_at'] is None and record['version']==1
    assert all(record[key]==value for key,value in values.items())
