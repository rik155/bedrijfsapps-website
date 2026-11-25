import ast
import copy
import io
import hashlib
import subprocess
import tarfile
from unittest.mock import patch

import pytest
from flask import Flask, session

from deploy_werkbonnen import download_module, patch_app, patch_office, prepare_config
from werkbonnen.portal import attach_to_portal


def test_separate_cookie_preserves_existing_portal_login(tmp_path):
    portal = Flask(__name__,static_folder=None)
    portal.secret_key = 'original-portal-session-test-key'
    portal.config['SESSION_COOKIE_SECURE'] = False

    @portal.get('/portal-login')
    def login_original():
        session['original_user'] = 'office-user'
        return {'ok':True}

    @portal.before_request
    def original_auth_gate():
        from flask import request
        if request.path != '/portal-login' and not session.get('original_user'):
            return 'Original portal login required',401

    @portal.get('/')
    def homepage():
        return {'user':session['original_user']}

    config = dict(TESTING=True,WERKBON_DATA_DIR=tmp_path,WERKBON_SECURE_COOKIE=False,
                  WERKBON_KANTOOR_PASSWORD='office-workorder-test-key')
    orders = attach_to_portal(portal,config)
    assert attach_to_portal(portal,config) is orders
    client = portal.test_client()
    assert client.get('/').status_code == 401
    assert client.get('/werkbonnen/kantoor').status_code == 200
    assert client.get('/werkbonnen/__init__.py').status_code == 404
    client.get('/portal-login')
    session_result = client.get('/werkbonnen/api/session')
    assert 'janbos_werkbon_session=' in session_result.headers['Set-Cookie']
    assert 'Path=/werkbonnen' in session_result.headers['Set-Cookie']
    result = client.post('/werkbonnen/api/login',json={'role':'kantoor','password':'office-workorder-test-key'},
                         headers={'X-CSRF-Token':session_result.json['csrf']})
    assert result.status_code == 200
    assert client.get('/werkbonnen/api/orders').status_code == 200
    assert client.get('/').json == {'user':'office-user'}
    assert portal.secret_key == 'original-portal-session-test-key'
    assert portal.config['SESSION_COOKIE_SECURE'] is False


def test_patch_preserves_existing_routes_and_imports():
    source = '''from flask import Flask
from existing_inventory import register_inventory
app = Flask(__name__)
register_inventory(app)
@app.get('/')
def index():
    return 'unchanged portal'
if __name__ == '__main__':
    app.run(host='0.0.0.0',port=80)
'''
    updated = patch_app(source)
    assert source.replace("if __name__ == '__main__':",'') in updated.replace(updated[updated.index('\n# Jan Bos'):updated.index("if __name__ == '__main__':")], '').replace("if __name__ == '__main__':",'')
    tree = ast.parse(updated)
    assert any(isinstance(n,ast.ImportFrom) and n.module=='existing_inventory' for n in tree.body)
    assert updated.index('attach_to_portal(app)') < updated.index("if __name__ == '__main__':")
    with pytest.raises(RuntimeError):
        patch_app(updated)
    with pytest.raises(RuntimeError):
        patch_app('print("no app")')
    with pytest.raises(RuntimeError):
        patch_app('app=Flask(__name__)\napp.run()')


def test_office_patch_keeps_all_old_content():
    original = '<main><section class="grid"><a href="/uren">Uren</a><a href="/voorraad">Voorraad</a></section></main>'
    result = patch_office(original)
    assert 'href="/werkbonnen/kantoor"' in result
    assert '<a href="/uren">Uren</a>' in result and '<a href="/voorraad">Voorraad</a>' in result
    assert patch_office(result) == result
    assert 'Werkbonnen' in patch_office('<main><p>Andere indeling</p></main>')
    with pytest.raises(RuntimeError):
        patch_office('<body>Onbekende pagina</body>')


def original_container():
    return {'Id':'a'*64,'Image':'sha256:'+'b'*64,'Config':{'Image':'old-image','Env':['EXISTING_KEY=value=with=equals','MULTILINE=first\nsecond'],
            'Labels':{'existing':'keep'},'Cmd':['python','app.py'],'Entrypoint':None,'Hostname':'original-host',
            'WorkingDir':'/app','Volumes':{'/data':{}}},
            'HostConfig':{'AutoRemove':False,'ContainerIDFile':'','Binds':['original-volume:/data'],
            'Mounts':[],'VolumesFrom':None,'PortBindings':{'80/tcp':[{'HostIp':'0.0.0.0','HostPort':'8090'}]},
            'RestartPolicy':{'Name':'unless-stopped','MaximumRetryCount':0},'NetworkMode':'bridge',
            'LogConfig':{'Type':'json-file','Config':{'max-size':'10m'}}},
            'Mounts':[{'Type':'volume','Name':'original-volume','Source':'/var/lib/docker/volumes/original-volume/_data',
                       'Destination':'/data','RW':True}],
            'NetworkSettings':{'Networks':{'bridge':{'Aliases':None,'IPAMConfig':None}}}}


def test_replacement_preserves_actual_storage_env_ports_and_runtime():
    original = original_container()
    snapshot = copy.deepcopy(original)
    result = prepare_config(original,'new-image',{'WERKBON_DATA_DIR':'/data/werkbonnen'})
    assert original == snapshot
    assert result['Cmd'] == original['Config']['Cmd']
    assert result['Env'][:2] == original['Config']['Env']
    assert result['Labels'] == {'existing':'keep'}
    host = result['HostConfig']
    assert host['Mounts'] == [{'Type':'volume','Source':'original-volume','Target':'/data','ReadOnly':False,'VolumeOptions':{'NoCopy':True}}]
    assert host['PortBindings'] == original['HostConfig']['PortBindings']
    assert host['RestartPolicy'] == original['HostConfig']['RestartPolicy']
    assert host['LogConfig'] == original['HostConfig']['LogConfig']
    candidate = prepare_config(original,'new-image',{},candidate=True)
    assert candidate['HostConfig']['PortBindings'] == {}
    assert candidate['HostConfig']['RestartPolicy']['Name'] == 'no'
    assert candidate['Labels'] == {}
    assert candidate['HostConfig']['Mounts'] == host['Mounts']
    assert candidate['Env'] == original['Config']['Env']


def test_container_bind_and_network_configuration():
    original = original_container()
    original['Mounts'] = [{'Type':'bind','Source':'/srv/data','Destination':'/data','RW':False,'Propagation':'rprivate'}]
    original['HostConfig']['NetworkMode']='company-network'
    original['NetworkSettings']['Networks']={'company-network':{'Aliases':['a'*12,'bedrijfsapps-website'],'IPAMConfig':None}}
    result=prepare_config(original,'new',{})
    assert result['HostConfig']['Mounts'][0] == {'Type':'bind','Source':'/srv/data','Target':'/data','ReadOnly':True,'BindOptions':{'Propagation':'rprivate'}}
    assert result['NetworkingConfig']=={'EndpointsConfig':{'company-network':{'Aliases':['bedrijfsapps-website']}}}
    original['NetworkSettings']['Networks']['company-network']['IPAMConfig']={'IPv4Address':'10.0.0.2'}
    with pytest.raises(RuntimeError):
        prepare_config(original,'new',{})


def test_download_never_extracts_symlinks_or_other_project_files(tmp_path):
    raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w:gz') as archive:
        for name,content in [('root/werkbonnen/portal.py',b'allowed'),('root/index.html',b'never-overwrite')]:
            member=tarfile.TarInfo(name);member.size=len(content);archive.addfile(member,io.BytesIO(content))
        link=tarfile.TarInfo('root/werkbonnen/unsafe');link.type=tarfile.SYMTYPE;link.linkname='/etc/passwd';archive.addfile(link)
    raw.seek(0)
    with patch('urllib.request.urlopen',return_value=raw):
        with pytest.raises(RuntimeError):
            download_module('a'*40,tmp_path)
    assert not (tmp_path/'index.html').exists()
    assert not (tmp_path/'werkbonnen/unsafe').exists()


@pytest.mark.parametrize('failure', ['readiness','interrupted-rename'])
def test_deployment_failure_restores_original_container(tmp_path,monkeypatch,failure):
    import deploy_werkbonnen as deploy
    from pathlib import Path
    original=original_container()
    original.update(Name='/bedrijfsapps-website',State={'Running':True})
    original['Config']['Env'] += ['WERKBON_KANTOOR_PASSWORD=original-office-test-key','WERKBON_GLASZETTER_PASSWORD=original-field-test-key']
    snapshot=copy.deepcopy(original)
    containers={original['Id']:original}
    removed=[]
    interrupted=False

    def fake_inspect(name):
        for item in containers.values():
            if item['Id']==name or item['Name'].lstrip('/')==name:
                return copy.deepcopy(item)
        raise subprocess.CalledProcessError(1,['docker','inspect',name])

    class Engine:
        def create(self,name,settings):
            identity=('t' if 'werkbon-test' in name else 'n')*64
            containers[identity]={'Id':identity,'Name':'/'+name,'Config':copy.deepcopy(settings),'State':{'Running':False}}
            return identity

        def request(self,method,path,data=None):
            nonlocal interrupted
            identity=path.split('/')[2].split('?')[0]
            if method=='DELETE':
                removed.append(identity);containers.pop(identity);return {}
            if '/stop' in path:
                containers[identity]['State']['Running']=False
            elif '/start' in path:
                containers[identity]['State']['Running']=True
            elif '/rename?name=' in path:
                name=path.split('/rename?name=')[1]
                containers[identity]['Name']='/'+name
                if failure=='interrupted-rename' and not interrupted:
                    interrupted=True
                    raise KeyboardInterrupt()
            return {}

    def fake_command(args,*,capture=False):
        if args[1]=='cp':
            filename=args[2].rsplit('/',1)[1]
            content={'app.py':"from flask import Flask\napp=Flask(__name__)\nif __name__=='__main__':\n    app.run(port=80)\n",
                     'kantoor.html':'<main><section class="grid"></section></main>',
                     'index.html':'unchanged employees'}[filename]
            Path(args[3]).write_text(content)
        if args[1]=='exec':
            return hashlib.sha256(b'unchanged employees').hexdigest()+'\n'
        return ''

    def fake_download(release,destination):
        (destination/'werkbonnen').mkdir()
        (destination/'werkbonnen/portal.py').write_text('# test fixture')

    def fake_ready(name):
        if 'werkbon-test' not in name:
            raise RuntimeError('Readiness failed for replacement')
        return {'ok':True}

    monkeypatch.setattr(deploy,'inspect',fake_inspect)
    monkeypatch.setattr(deploy,'command',fake_command)
    monkeypatch.setattr(deploy,'DockerAPI',Engine)
    monkeypatch.setattr(deploy,'download_module',fake_download)
    monkeypatch.setattr(deploy,'wait_ready',fake_ready)
    monkeypatch.setattr(deploy.Path,'home',lambda:tmp_path)
    monkeypatch.setattr(deploy.sys,'argv',['deploy_werkbonnen.py','--release','b'*40])
    with pytest.raises((RuntimeError,KeyboardInterrupt)):
        deploy.main()
    assert containers=={snapshot['Id']:snapshot}
    assert 't'*64 in removed
    if failure=='readiness':
        assert 'n'*64 in removed
