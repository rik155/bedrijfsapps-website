import os
import re
import requests
from flask import Flask, jsonify, request, send_from_directory, Response

app = Flask(__name__, static_folder='.', static_url_path='')

BREVO_API_KEY = os.getenv('BREVO_API_KEY', '').strip()
DEMO_TO_EMAIL = os.getenv('DEMO_TO_EMAIL', 'fokkerrik@gmail.com').strip()
BREVO_FROM_EMAIL = os.getenv('BREVO_FROM_EMAIL', 'schilderformulier@gmail.com').strip()
BREVO_FROM_NAME = os.getenv('BREVO_FROM_NAME', 'BouwFlow').strip()

@app.get('/')
def index():
    return send_from_directory('.', 'index.html')

@app.get('/download')
@app.get('/download/<slug>')
def download_page(slug=None):
    return send_from_directory('.', 'download.html')

@app.get('/api/client-config/<slug>')
def client_config(slug):
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug) or 'demo'
    company = request.args.get('bedrijf', safe_slug.replace('-', ' ').title()).strip()[:100]
    app_url = request.args.get('app', request.host_url.rstrip('/')).strip()[:500]
    return jsonify({
        'slug': safe_slug,
        'company': company,
        'app_url': app_url,
        'version': 1
    })

@app.get('/downloads/<slug>/BouwFlow-Setup.ps1')
def windows_installer(slug):
    company = request.args.get('bedrijf', slug.replace('-', ' ').title()).strip()
    app_url = request.args.get('app', request.host_url.rstrip('/')).strip()
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug) or 'demo'
    safe_company = company.replace('`', '').replace('"', '').replace("'", '')[:100]
    safe_url = app_url.replace('`', '').replace('"', '').replace("'", '')[:500]
    template_path = os.path.join(app.root_path, 'windows-client', 'install.ps1')
    with open(template_path, 'r', encoding='utf-8') as f:
        script = f.read()
    header = f'$Company = "{safe_company}"\n$Slug = "{safe_slug}"\n$AppUrl = "{safe_url}"\n'
    script = re.sub(r'^param\([\s\S]*?\)\s*', '', script, count=1)
    return Response(header + script, mimetype='application/octet-stream', headers={'Content-Disposition':'attachment; filename="BouwFlow-Setup.ps1"'})

@app.post('/api/demo')
def demo():
    data = request.get_json(silent=True) or {}
    naam = str(data.get('naam', '')).strip(); bedrijf = str(data.get('bedrijf', '')).strip(); email = str(data.get('email', '')).strip(); telefoon = str(data.get('telefoon', '')).strip(); soort = str(data.get('soort', '')).strip(); bericht = str(data.get('bericht', '')).strip()
    if not naam or not bedrijf or not email or not bericht:
        return jsonify(ok=False, message='Vul alle verplichte velden in.'), 400
    if not BREVO_API_KEY:
        return jsonify(ok=False, message='E-mailservice is nog niet ingesteld.'), 500
    subject = f'Nieuwe gratis demo-aanvraag - {bedrijf}'
    text = f'''Nieuwe BouwFlow demo-aanvraag\n\nNaam: {naam}\nBedrijf: {bedrijf}\nE-mail: {email}\nTelefoon: {telefoon or '-'}\nInteresse: {soort or '-'}\n\nHoe het nu werkt / wat ze willen verbeteren:\n{bericht}\n'''
    payload = {'sender':{'name':BREVO_FROM_NAME,'email':BREVO_FROM_EMAIL},'to':[{'email':DEMO_TO_EMAIL,'name':'BouwFlow'}],'replyTo':{'email':email,'name':naam},'subject':subject,'textContent':text}
    try:
        response = requests.post('https://api.brevo.com/v3/smtp/email', headers={'api-key':BREVO_API_KEY,'accept':'application/json','content-type':'application/json'}, json=payload, timeout=20)
    except requests.RequestException:
        return jsonify(ok=False, message='Versturen lukt nu niet. Probeer het later opnieuw.'), 502
    if response.status_code >= 300:
        return jsonify(ok=False, message='Versturen lukt nu niet. Probeer het later opnieuw.'), 502
    return jsonify(ok=True, message='Bedankt! Je demo-aanvraag is verstuurd.')

@app.get('/health')
def health(): return jsonify(ok=True)

if __name__ == '__main__': app.run(host='0.0.0.0', port=int(os.getenv('PORT','80')))
