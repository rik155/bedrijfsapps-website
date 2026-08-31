import os, re, sqlite3, secrets
from datetime import datetime, timedelta, timezone
import requests
from flask import Flask, jsonify, request, send_from_directory, redirect, session

app=Flask(__name__,static_folder='.',static_url_path='')
app.secret_key=os.getenv('SECRET_KEY') or secrets.token_hex(32)
DB_PATH=os.getenv('BOUWFLOW_DB','/data/bouwflow.db')
ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD','').strip()
BREVO_API_KEY=os.getenv('BREVO_API_KEY','').strip(); DEMO_TO_EMAIL=os.getenv('DEMO_TO_EMAIL','fokkerrik@gmail.com').strip(); BREVO_FROM_EMAIL=os.getenv('BREVO_FROM_EMAIL','schilderformulier@gmail.com').strip(); BREVO_FROM_NAME=os.getenv('BREVO_FROM_NAME','BouwFlow').strip()

def db():
 os.makedirs(os.path.dirname(DB_PATH),exist_ok=True); c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; c.execute('CREATE TABLE IF NOT EXISTS customers (slug TEXT PRIMARY KEY, company TEXT NOT NULL, email TEXT, app_url TEXT, started_at TEXT NOT NULL, expires_at TEXT NOT NULL, permanent INTEGER NOT NULL DEFAULT 0, token TEXT NOT NULL UNIQUE)'); c.commit(); return c
def safe_slug(s): return re.sub(r'[^a-z0-9-]','',s.lower().replace(' ','-')) or 'demo'
def now(): return datetime.now(timezone.utc)
def customer(slug): c=db(); r=c.execute('SELECT * FROM customers WHERE slug=?',(slug,)).fetchone(); c.close(); return r
def active(r): return bool(r and (r['permanent'] or datetime.fromisoformat(r['expires_at'])>now()))
def admin_ok(): return bool(session.get('admin'))

@app.get('/')
def index(): return send_from_directory('.','index.html')
@app.get('/download')
@app.get('/download/<slug>')
def download_page(slug=None): return send_from_directory('.','download.html')
@app.get('/install/<slug>')
def install_page(slug):
 r=customer(slug); token=request.args.get('token','')
 if not r or not secrets.compare_digest(token,r['token']) or not active(r): return send_from_directory('.','expired.html'),403
 return send_from_directory('.','install.html')
@app.get('/admin/login')
def login_page(): return redirect('/admin') if admin_ok() else send_from_directory('.','login.html')
@app.post('/api/admin/login')
def login():
 password=str((request.get_json(silent=True) or {}).get('password',''))
 if not ADMIN_PASSWORD: return jsonify(message='ADMIN_PASSWORD is nog niet ingesteld op de server.'),503
 if not secrets.compare_digest(password,ADMIN_PASSWORD): return jsonify(message='Onjuist wachtwoord.'),401
 session['admin']=True; session.permanent=True; return jsonify(ok=True)
@app.post('/api/admin/logout')
def logout(): session.clear(); return jsonify(ok=True)
@app.get('/admin')
def admin(): return send_from_directory('.','admin.html') if admin_ok() else redirect('/admin/login')

@app.post('/api/admin/demo')
def create_demo():
 if not admin_ok(): return jsonify(message='Niet ingelogd.'),401
 d=request.get_json(silent=True) or {}; company=str(d.get('company','')).strip(); email=str(d.get('email','')).strip(); app_url=str(d.get('app_url','')).strip() or request.host_url.rstrip('/')
 if not company:return jsonify(message='Vul een bedrijfsnaam in.'),400
 base=safe_slug(company); slug=base; c=db(); i=2
 while c.execute('SELECT 1 FROM customers WHERE slug=?',(slug,)).fetchone(): slug=f'{base}-{i}'; i+=1
 start=now(); end=start+timedelta(days=7); token=secrets.token_urlsafe(24); c.execute('INSERT INTO customers(slug,company,email,app_url,started_at,expires_at,token) VALUES(?,?,?,?,?,?,?)',(slug,company,email,app_url,start.isoformat(),end.isoformat(),token)); c.commit(); c.close(); url=f'/install/{slug}?token={token}&bedrijf={company}&app={app_url}'; return jsonify(ok=True,message='7-daagse demo aangemaakt.',install_url=url)
@app.get('/api/admin/customers')
def customers():
 if not admin_ok(): return jsonify(message='Niet ingelogd.'),401
 c=db(); rows=c.execute('SELECT * FROM customers ORDER BY started_at DESC').fetchall(); c.close(); out=[]
 for r in rows:
  left=max(0,(datetime.fromisoformat(r['expires_at'])-now()).days+1) if not r['permanent'] else 999; out.append({'slug':r['slug'],'company':r['company'],'email':r['email'],'active':active(r),'permanent':bool(r['permanent']),'days_left':left,'install_url':f"/install/{r['slug']}?token={r['token']}&bedrijf={r['company']}&app={r['app_url']}"})
 return jsonify(out)
@app.get('/manifest/<slug>.webmanifest')
def manifest(slug):
 r=customer(slug); token=request.args.get('token','')
 if not r or not secrets.compare_digest(token,r['token']) or not active(r):return jsonify({}),403
 return jsonify({'id':f'/app/{slug}','name':f"BouwFlow - {r['company']}",'short_name':'BouwFlow','start_url':f'/app/{slug}?token={token}','scope':'/','display':'standalone','background_color':'#071c38','theme_color':'#071c38','icons':[{'src':'/bouwflow-icon.svg','sizes':'any','type':'image/svg+xml','purpose':'any maskable'}]})
@app.get('/app/<slug>')
def customer_app(slug):
 r=customer(slug); token=request.args.get('token','')
 if not r or not secrets.compare_digest(token,r['token']) or not active(r):return send_from_directory('.','expired.html'),403
 return redirect(r['app_url'])
@app.get('/api/client-config/<slug>')
def client_config(slug):
 r=customer(slug); token=request.args.get('token','')
 if not r or not secrets.compare_digest(token,r['token']):return jsonify(active=False),403
 return jsonify(slug=slug,company=r['company'],app_url=r['app_url'],active=active(r),expires_at=r['expires_at'])
@app.post('/api/demo')
def demo():
 d=request.get_json(silent=True) or {}; naam=str(d.get('naam','')).strip(); bedrijf=str(d.get('bedrijf','')).strip(); email=str(d.get('email','')).strip(); telefoon=str(d.get('telefoon','')).strip(); soort=str(d.get('soort','')).strip(); bericht=str(d.get('bericht','')).strip()
 if not naam or not bedrijf or not email or not bericht:return jsonify(ok=False,message='Vul alle verplichte velden in.'),400
 if not BREVO_API_KEY:return jsonify(ok=False,message='E-mailservice is nog niet ingesteld.'),500
 text=f'Nieuwe BouwFlow demo-aanvraag\n\nNaam: {naam}\nBedrijf: {bedrijf}\nE-mail: {email}\nTelefoon: {telefoon or "-"}\nInteresse: {soort or "-"}\n\n{bericht}'; payload={'sender':{'name':BREVO_FROM_NAME,'email':BREVO_FROM_EMAIL},'to':[{'email':DEMO_TO_EMAIL,'name':'BouwFlow'}],'replyTo':{'email':email,'name':naam},'subject':f'Nieuwe gratis demo-aanvraag - {bedrijf}','textContent':text}
 try:r=requests.post('https://api.brevo.com/v3/smtp/email',headers={'api-key':BREVO_API_KEY,'content-type':'application/json'},json=payload,timeout=20)
 except requests.RequestException:return jsonify(ok=False,message='Versturen lukt nu niet.'),502
 if r.status_code>=300:return jsonify(ok=False,message='Versturen lukt nu niet.'),502
 return jsonify(ok=True,message='Bedankt! Je demo-aanvraag is verstuurd.')
@app.get('/health')
def health():return jsonify(ok=True)
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.getenv('PORT','80')))
