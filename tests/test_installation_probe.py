import http.client
import sqlite3
from flask import Flask
from deploy_werkbonnen import PROBE
from werkbonnen.portal import attach_to_portal


def test_installer_probe_enrolls_checks_roles_and_removes_test_devices(tmp_path,monkeypatch,capsys):
    portal=Flask(__name__,static_folder=None)
    orders=attach_to_portal(portal,dict(TESTING=True,WERKBON_DATA_DIR=tmp_path,WERKBON_SECURE_COOKIE=False))
    @portal.get('/')
    @portal.get('/kantoor.html')
    def original_page():
        return '<main>Existing portal</main>'

    class Connection:
        def __init__(self,*args,**kwargs):
            pass
        def request(self,method,path,body=None,headers=None):
            self.response=portal.test_client(use_cookies=False).open(path,method=method,data=body,headers=headers)
        def getresponse(self):
            return self
        @property
        def status(self):
            return self.response.status_code
        def read(self):
            return self.response.data
        def getheader(self,name,default=None):
            return self.response.headers.get(name,default)
        def close(self):
            pass

    monkeypatch.setattr(http.client,'HTTPConnection',Connection)
    monkeypatch.setenv('WERKBON_DATA_DIR',str(tmp_path))
    exec(compile(PROBE,'installation_probe','exec'),{})
    assert '"ok": true' in capsys.readouterr().out
    with sqlite3.connect(orders.config['WERKBON_DB']) as db:
        assert db.execute('SELECT COUNT(*) FROM devices').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM activations').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==0
