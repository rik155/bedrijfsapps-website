'use strict';
const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
const mode = document.body.dataset.mode;
const apiPrefix=mode==='kantoor'?'/werkbonnen/kantoor-api':'/werkbonnen/api';
const labels = {open:'Open', in_progress:'In uitvoering', completed:'Afgerond'};
let csrf='', role=null, orders=[], trashedOrders=[], trashMode=false, current=null, dirty=false, officeRecord=null, busy=false, signatureDrawn=false, noticeTimer;
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const date = value => value ? new Intl.DateTimeFormat('nl-NL',{day:'numeric',month:'short',year:'numeric'}).format(new Date(value.length===10?value+'T12:00:00':value)) : 'Nog niet gepland';
const status = order => `<span class="status ${order.status}">${labels[order.status]}</span>`;
function notice(message, error=false){ clearTimeout(noticeTimer); $('#notice').textContent=message; $('#notice').className='notice'+(error?' error':''); $('#notice').hidden=false; noticeTimer=setTimeout(()=>$('#notice').hidden=true,error?12000:5000); }
async function api(path, options={}){
  const headers={'X-CSRF-Token':csrf,'X-Werkbon-Mode':mode,...options.headers};
  if(options.body && !(options.body instanceof FormData)){ headers['Content-Type']='application/json'; options.body=JSON.stringify(options.body); }
  let response;
  try { response=await fetch(apiPrefix+path,{...options,headers,cache:'no-store'}); }
  catch { throw new Error('Geen verbinding. Je invoer blijft in beeld. Maak verbinding en probeer opnieuw.'); }
  const data=await response.json().catch(()=>({error: response.status===413?'De foto is te groot. Kies een kleinere afbeelding.':'De server gaf geen geldig antwoord.'}));
  if(!response.ok) throw new Error(data.error || 'Opslaan is niet gelukt. Probeer opnieuw.');
  return data;
}
async function task(fn, button){
  if(busy) return;
  busy=true;
  if(button) button.disabled=true;
  $$('main, dialog, header').forEach(el=>{el.inert=true;el.setAttribute('aria-busy','true');});
  try { await fn(); } catch(error){ notice(error.message,true); }
  finally { busy=false; if(button) button.disabled=false; $$('main, dialog, header').forEach(el=>{el.inert=false;el.removeAttribute('aria-busy');}); }
}
function show(screen){ for(const id of ['activation-required','dashboard','detail','loading']) $('#'+id).hidden=id!==screen; }
function activationRequired(){
  $('#field-link').hidden=role!=='glaszetter';
  $('#device-message').textContent=role==='glaszetter'?'Dit apparaat is geactiveerd voor de glaszetter-app. Gebruik voor kantoor een kantoorapparaat.':'Open een eenmalige activatielink van kantoor op dit apparaat. Daarna opent de app direct, zonder wachtwoord.';
  show('activation-required');
}
async function refresh(){
  const state=await api('/session');csrf=state.csrf;role=state.role;
  if(!role || mode==='kantoor'&&role!=='kantoor'){activationRequired();return false;}
  $('#new-order').hidden=mode!=='kantoor'||role!=='kantoor';
  $('#manage-devices').hidden=mode!=='kantoor'||role!=='kantoor';
  $('#trash-toggle').hidden=mode!=='kantoor'||role!=='kantoor';
  const data=await api('/orders');orders=data.orders;if(trashMode){const trash=await api('/orders?trash=1');trashedOrders=trash.orders;}renderList();
  $('#sync-info').textContent='Laatst bijgewerkt om '+new Intl.DateTimeFormat('nl-NL',{hour:'2-digit',minute:'2-digit'}).format(new Date())+' · Kantoor en glaszetter gebruiken dezelfde werkbonnen.';
  return true;
}
function renderList(){
  for(const state of Object.keys(labels)) $('#count-'+state).textContent=orders.filter(o=>o.status===state).length;
  const query=$('#search').value.toLocaleLowerCase('nl').trim(), filter=$('#status-filter').value, assignee=$('#assignee-filter').value.toLocaleLowerCase('nl').trim();
  $('#list-title').textContent=trashMode?'Prullenbak':'Opdrachten';$('#trash-toggle').textContent=trashMode?'Terug naar werkbonnen':'Prullenbak';
  const list=(trashMode?trashedOrders:orders).filter(o=>(filter==='all'||filter==='active'&&o.status!=='completed'||o.status===filter)&&(!assignee||o.assignee.toLocaleLowerCase('nl').includes(assignee))&&[o.project,o.name,o.address,o.number,o.phone,o.assignee].join(' ').toLocaleLowerCase('nl').includes(query));
  $('#list-count').textContent=list.length;
  if(trashMode){
    $('#order-list').innerHTML=list.length?list.map(o=>`<div class="order-card trash-card"><div><span class="number">${o.number}</span><h3>${esc(o.project)}</h3><p>${esc(o.address)}</p><div class="order-meta"><span>${esc(o.name)}</span><span>Verwijderd op ${esc(date(o.deleted_at))}</span></div></div><div class="order-right">${status(o)}<button class="secondary small" data-restore="${o.id}">Herstellen</button></div></div>`).join(''):'<div class="empty"><strong>Geen verwijderde werkbonnen</strong>Verwijderde bonnen kun je hier terugzetten.</div>';
    $$('[data-restore]').forEach(button=>button.onclick=()=>task(async()=>{const item=trashedOrders.find(o=>o.id===Number(button.dataset.restore));await api('/orders/'+item.id+'/restore',{method:'POST',body:{version:item.version}});await refresh();notice('Werkbon hersteld.');},button));
    return;
  }

  $('#order-list').innerHTML=list.length?list.map(o=>`<button class="order-card" data-order="${o.id}"><div><span class="number">${o.number}</span><h3>${esc(o.project)}</h3><p>${esc(o.address)}</p><div class="order-meta"><span>${esc(o.name)}</span><span>${esc(date(o.planned_date))}</span>${o.assignee?`<span>Glaszetter: ${esc(o.assignee)}</span>`:''}</div></div><div class="order-right">${status(o)}<span>Werkbon openen</span></div></button>`).join(''):`<div class="empty"><strong>${orders.length?'Geen werkbonnen gevonden':'De eerste werkbon begint hier'}</strong>${orders.length?'Pas je zoekopdracht of filters aan.':mode==='kantoor'?'Maak een werkbon aan. De glaszetter kan de opdracht daarna openen.':'Zodra kantoor een werkbon opslaat, verschijnt de opdracht hier.'}</div>`;
  $$('[data-order]').forEach(el=>el.onclick=()=>task(()=>openOrder(Number(el.dataset.order)),el));
}
async function openOrder(id){ current=await api('/orders/'+id); dirty=false; renderDetail(); show('detail'); window.scrollTo(0,0); }
function contact(caption,value){return `<div class="contact-item"><span class="caption">${caption}</span><div>${value}</div></div>`;}
function photoGallery(category,readonly=false){
  const photos=current.photos.filter(p=>p.category===category);
  return photos.length?photos.map(p=>`<figure class="photo"><a href="${p.url}" target="_blank" rel="noopener"><img src="${p.url}" alt="Foto ${category==='before'?'vóór':'na'} het werk" loading="lazy"></a>${readonly?'':`<button type="button" data-delete="${p.id}" aria-label="Foto verwijderen">×</button>`}</figure>`).join(''):'<div class="no-photos">Nog geen foto’s toegevoegd</div>';
}
function photoSection(category,readonly){const title=category==='before'?'Vóór het werk':'Na het werk';return `<div class="photo-section"><div class="photo-head"><h3>${title}</h3>${readonly?'':`<div><label class="photo-picker">Maak foto<input class="sr-only" type="file" accept="image/*" capture="environment" data-upload="${category}"></label> <label class="photo-picker">Kies foto’s<input class="sr-only" type="file" accept="image/*" multiple data-upload="${category}"></label></div>`}</div><div class="photos">${photoGallery(category,readonly)}</div></div>`;}
function field(name,label,rows=3){return `<label>${label}<textarea name="${name}" rows="${rows}" maxlength="10000">${esc(current[name])}</textarea><span class="print-value" hidden>${esc(current[name])}</span></label>`;}
function renderDetail(){
  const o=current, readonly=o.status==='completed';
  $('#detail').innerHTML=`<button class="text-button back-button" id="back">Terug naar werkbonnen</button><div class="detail-head"><div><span class="number">${o.number}</span><h1>${esc(o.project)}</h1>${status(o)}</div><div class="actions">${mode==='kantoor'&&role==='kantoor'&&!readonly?'<button class="secondary small" id="edit-office">Opdracht bewerken</button>':''}${mode==='kantoor'?'<button class="primary small" id="download-pdf">PDF downloaden</button><button class="danger small" id="delete-order">Werkbon verwijderen</button>':'<button class="secondary small" id="print">Afdrukken</button>'}</div></div><div class="detail-grid"><div class="stack"><section class="panel"><h2>Klant & opdracht</h2><div class="contact-grid">${contact('Naam klant',esc(o.name))}${contact('Werkadres',esc(o.address))}${contact('Telefoon',`<a href="tel:${esc(o.phone.replace(/[^+\d]/g,''))}">${esc(o.phone)}</a>`)}${contact('E-mail',`<a href="mailto:${esc(o.email)}">${esc(o.email)}</a>`)}</div><div class="assignment"><h3>Opdracht van kantoor</h3><p class="preserve">${esc(o.assignment)}</p></div></section><section class="panel"><h2>Uitvoering op locatie</h2>${readonly?`<h3>Uitgevoerde werkzaamheden</h3><p class="preserve">${esc(o.work_done)}</p><h3>Materialen</h3><p class="preserve">${esc(o.materials||'Geen materialen vermeld')}</p><h3>Gewerkte uren</h3><p>${esc(o.hours||'Niet ingevuld')}</p><h3>Opmerkingen klant</h3><p class="preserve">${esc(o.customer_notes||'Geen opmerkingen')}</p>`:`<form id="work-form" class="work-form">${field('work_done','Uitgevoerde werkzaamheden',4)}<div class="form-grid">${field('materials','Gebruikte materialen',2)}<label>Gewerkte uren<input name="hours" inputmode="decimal" maxlength="300" value="${esc(o.hours)}" placeholder="Bijv. 2,5"></label></div>${field('customer_notes','Opmerkingen van de klant',3)}<div class="save-bar"><span class="save-status" id="save-status">Opgeslagen op ${esc(date(o.updated_at))}</span><button class="primary" type="submit">Tussentijds opslaan</button></div></form>`}</section><section class="panel"><h2>Foto’s van de werkzaamheden</h2>${photoSection('before',readonly)}${photoSection('after',readonly)}${readonly?'':'<p class="tip">Voeg foto’s toe van vóór en na het werk. Foto’s worden verkleind voor het uploaden.</p>'}</section></div><aside class="stack"><section class="panel"><h2>Werkbonoverzicht</h2><dl class="summary-list"><div><dt>Bonnummer</dt><dd>${o.number}</dd></div><div><dt>Plandatum</dt><dd>${esc(date(o.planned_date))}</dd></div><div><dt>Glaszetter</dt><dd>${esc(o.assignee||'Nog niet toegewezen')}</dd></div><div><dt>Aangemaakt</dt><dd>${esc(date(o.created_at))}</dd></div><div><dt>Foto’s vóór / na</dt><dd>${o.photos.filter(p=>p.category==='before').length} / ${o.photos.filter(p=>p.category==='after').length}</dd></div></dl></section><section class="panel ${readonly?'complete-panel':''}"><h2>${readonly?'Klant heeft getekend':'Akkoord van de klant'}</h2>${readonly?`<p>Ondertekend door <strong>${esc(o.signed_by)}</strong><br>${esc(date(o.signed_at))} om ${esc(new Intl.DateTimeFormat('nl-NL',{hour:'2-digit',minute:'2-digit'}).format(new Date(o.signed_at)))}</p><img class="signature-saved" src="${o.signature_url}" alt="Handtekening van de klant"><p class="subtle">De klant heeft de werkbon en de uitgevoerde werkzaamheden gecontroleerd. Deze werkbon is definitief opgeslagen.</p>`:'<p>Laat de klant de ingevulde werkbon controleren en op het scherm ondertekenen.</p><button class="primary full" id="sign">Klant laten tekenen</button><p class="tip">De werkzaamheden en minimaal één foto vóór en na het werk zijn nodig om af te ronden.</p>'}</section></aside></div>`;
  $('#back').onclick=()=>task(async()=>{if(dirty&&!confirm('Er zijn nog niet opgeslagen wijzigingen. Teruggaan zonder opslaan?'))return; dirty=false; current=null; if(await refresh())show('dashboard');});
  if($('#print'))$('#print').onclick=()=>{if(dirty){notice('Sla je wijzigingen eerst op voordat je afdrukt.',true);return;} window.print();};
  if($('#download-pdf'))$('#download-pdf').onclick=()=>task(async()=>{
    if(dirty)throw new Error('Sla je wijzigingen eerst op voordat je de PDF downloadt.');
    let response;try{response=await fetch(apiPrefix+'/orders/'+current.id+'/pdf',{headers:{'X-Werkbon-Mode':mode},cache:'no-store'});}catch{throw new Error('Geen verbinding. Probeer de PDF opnieuw te downloaden.');}
    if(!response.ok){const error=await response.json().catch(()=>({error:'De PDF kon niet worden gemaakt.'}));throw new Error(error.error);}
    const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='Werkbon_'+current.number+'.pdf';document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);notice('PDF gedownload.');
  },$('#download-pdf'));
  if($('#delete-order'))$('#delete-order').onclick=()=>task(async()=>{
    if(!confirm('Werkbon '+current.number+' naar de prullenbak verplaatsen?'+(dirty?' Niet opgeslagen wijzigingen gaan verloren.':'')))return;
    await api('/orders/'+current.id,{method:'DELETE',body:{version:current.version}});dirty=false;current=null;trashMode=false;await refresh();show('dashboard');notice('Werkbon verwijderd. Je kunt hem herstellen via de Prullenbak.');
  },$('#delete-order'));
  if($('#edit-office')) $('#edit-office').onclick=()=>task(async()=>{if(dirty)await saveWork();openOffice(current);});
  const form=$('#work-form');
  if(form){ form.oninput=()=>{dirty=true;$('#save-status').textContent='Wijzigingen nog niet opgeslagen';};form.onsubmit=event=>{event.preventDefault();task(async()=>{await saveWork();renderDetail();notice('Werkbon opgeslagen. Kantoor kan de wijzigingen zien.');},$('button[type=submit]',form));}; }
  $$('[data-upload]').forEach(input=>input.onchange=()=>task(async()=>{
    const files=[...input.files]; if(!files.length)return;
    if(dirty) await saveWork();
    let uploaded=0;
    try { for(const file of files){notice(`Foto ${uploaded+1} van ${files.length} uploaden…`); const data=new FormData();data.set('category',input.dataset.upload);data.set('version',current.version);data.set('file',await compress(file),'foto.jpg');current=await api('/orders/'+current.id+'/photos',{method:'POST',body:data});uploaded++;} }
    finally { renderDetail(); }
    notice(`${uploaded} foto${uploaded===1?'':'’s'} opgeslagen.`);
  }));
  $$('[data-delete]').forEach(button=>button.onclick=()=>task(async()=>{
    if(!confirm('Deze foto verwijderen van de werkbon?'))return;
    if(dirty) await saveWork();
    current=await api(`/orders/${current.id}/photos/${button.dataset.delete}`,{method:'DELETE',body:{version:current.version}});renderDetail();notice('Foto verwijderd.');
  },button));
  if($('#sign')) $('#sign').onclick=()=>task(async()=>{
    await saveWork();
    if(!current.work_done.trim()) throw new Error('Beschrijf eerst de uitgevoerde werkzaamheden.');
    if(!['before','after'].every(c=>current.photos.some(p=>p.category===c))) throw new Error('Voeg minimaal één foto vóór en één foto na het werk toe.');
    openSign();
  },$('#sign'));
}
async function saveWork(){
  const form=$('#work-form'); if(!form)return;
  if(!form.reportValidity())throw new Error('Controleer de ingevulde velden.');
  const values=Object.fromEntries(new FormData(form));
  current=await api('/orders/'+current.id,{method:'PATCH',body:{...values,section:'work',version:current.version}});dirty=false;
  $('#save-status').textContent='Alle wijzigingen opgeslagen';
  $$('.print-value').forEach(el=>el.textContent=current[el.previousElementSibling.name]||'');
}
async function compress(file){
  if(file.size>30*1024*1024)throw new Error('Deze foto is groter dan 30 MB. Kies een kleinere foto.');
  let bitmap;
  try { bitmap=await createImageBitmap(file); } catch { return file; }
  const ratio=Math.min(1,1800/Math.max(bitmap.width,bitmap.height)); const canvas=document.createElement('canvas');
  canvas.width=Math.round(bitmap.width*ratio);canvas.height=Math.round(bitmap.height*ratio);const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(bitmap,0,0,canvas.width,canvas.height);bitmap.close();
  return new Promise(resolve=>canvas.toBlob(blob=>resolve(blob||file),'image/jpeg',.85));
}
function openOffice(record=null){
  officeRecord=record?{...record}:null;
  const form=$('#office-form');form.reset();$('#office-title').textContent=record?'Opdracht bewerken':'Nieuwe werkbon';
  if(record) for(const el of form.elements)if(el.name&&el.name in record)el.value=record[el.name];
  $('#office-dialog').showModal();
}
$('#office-form').onsubmit=event=>{event.preventDefault();task(async()=>{
  const values=Object.fromEntries(new FormData(event.target));
  const saved=await api(officeRecord?'/orders/'+officeRecord.id:'/orders',{method:officeRecord?'PATCH':'POST',body:{...values,section:'office',...(officeRecord?{version:officeRecord.version}:{})}});
  $('#office-dialog').close();
  if(officeRecord){current=saved;renderDetail();}else{trashMode=false;$('#status-filter').value='active';await refresh();}
  notice('Werkbon opgeslagen en beschikbaar in de glaszetter-app.');
},$('button[type=submit]',event.target));};
$('#close-office').onclick=$('#cancel-office').onclick=()=>$('#office-dialog').close();
function openSign(){
  const o=current;
  $('#sign-review').innerHTML=`<div class="review"><h3>${o.number} · ${esc(o.project)}</h3><p>${esc(o.name)}<br>${esc(o.address)}<br>${esc(o.phone)} · ${esc(o.email)}</p><dl><dt>Opdracht</dt><dd>${esc(o.assignment)}</dd><dt>Uitgevoerde werkzaamheden</dt><dd>${esc(o.work_done)}</dd><dt>Materialen</dt><dd>${esc(o.materials||'Geen vermeld')}</dd><dt>Gewerkte uren</dt><dd>${esc(o.hours||'Niet ingevuld')}</dd><dt>Opmerkingen klant</dt><dd>${esc(o.customer_notes||'Geen opmerkingen')}</dd></dl><div class="review-block"><h3>Foto’s vóór het werk</h3><div class="photos">${photoGallery('before',true)}</div></div><div class="review-block"><h3>Foto’s na het werk</h3><div class="photos">${photoGallery('after',true)}</div></div></div>`;
  $('#signed-by').value=o.name;$('#consent').checked=false;clearSignature();$('#sign-dialog').showModal();$('#sign-dialog').scrollTop=0;
}
const canvas=$('#signature'), ctx=canvas.getContext('2d');let drawing=false;
function clearSignature(){ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);signatureDrawn=false;$('#signature-hint').hidden=false;}
function point(event){const box=canvas.getBoundingClientRect();return [(event.clientX-box.left)*canvas.width/box.width,(event.clientY-box.top)*canvas.height/box.height];}
canvas.onpointerdown=event=>{event.preventDefault();drawing=true;canvas.setPointerCapture(event.pointerId);const[x,y]=point(event);ctx.beginPath();ctx.moveTo(x,y);ctx.strokeStyle='#152f43';ctx.lineWidth=4;ctx.lineCap='round';};
canvas.onpointermove=event=>{if(!drawing)return;event.preventDefault();const[x,y]=point(event);ctx.lineTo(x,y);ctx.stroke();signatureDrawn=true;$('#signature-hint').hidden=true;};
canvas.onpointerup=canvas.onpointercancel=()=>drawing=false;
$('#clear-signature').onclick=clearSignature;
$('#close-sign').onclick=()=>$('#sign-dialog').close();
$('#finish-order').onclick=()=>task(async()=>{
  if(!signatureDrawn)throw new Error('Zet eerst een handtekening.');
  if(!$('#signed-by').value.trim())throw new Error('Vul de naam van de ondertekenaar in.');
  if(!$('#consent').checked)throw new Error('Vink het akkoord aan nadat de klant de werkbon heeft gecontroleerd.');
  current=await api('/orders/'+current.id+'/complete',{method:'POST',body:{work_done:current.work_done,materials:current.materials,hours:current.hours,customer_notes:current.customer_notes,version:current.version,signed_by:$('#signed-by').value,consent:true,signature:canvas.toDataURL('image/png')}});
  $('#sign-dialog').close();renderDetail();notice('Werkbon ondertekend en afgerond. Kantoor kan de volledige bon bekijken.');window.scrollTo(0,0);
},$('#finish-order'));
$('#trash-toggle').onclick=()=>task(async()=>{trashMode=!trashMode;$('#status-filter').value=trashMode?'all':'active';await refresh();},$('#trash-toggle'));
$('#new-order').onclick=()=>openOffice();$('#search').oninput=$('#assignee-filter').oninput=renderList;$('#status-filter').onchange=renderList;
$$('[data-stat]').forEach(el=>el.onclick=()=>{$('#status-filter').value=el.dataset.stat;renderList();});
$('#refresh').onclick=()=>task(async()=>{if(await refresh())notice('Werkbonnen bijgewerkt.');},$('#refresh'));
$('#check-device').onclick=()=>task(async()=>{if(await refresh())show('dashboard');},$('#check-device'));
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
window.addEventListener('offline',()=>notice('Geen internet. Je invoer blijft in beeld. Opslaan kan zodra je weer verbinding hebt.',true));
window.addEventListener('online',()=>{notice('Verbinding hersteld. Je kunt weer opslaan.');if(!current&&!busy&&role)task(refresh);});
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'&&!current&&!busy&&role&&!$('#office-dialog').open)task(refresh);});
setInterval(()=>{if(role&&!current&&!busy&&!$('#office-dialog').open&&document.visibilityState==='visible'&&navigator.onLine)task(refresh);},30000);
$('#manage-devices').onclick=()=>{$('#invite-result').hidden=true;$('#device-form').reset();$('#devices-dialog').showModal();};
$('#close-devices').onclick=()=>$('#devices-dialog').close();
$('#device-form').onsubmit=event=>{event.preventDefault();task(async()=>{const data=Object.fromEntries(new FormData(event.target));const invite=await api('/activations',{method:'POST',body:data});$('#invite-link').value=new URL(invite.path,location.origin).href;$('#invite-result').hidden=false;},$('button',event.target));};
$('#copy-invite').onclick=()=>task(async()=>{try{await navigator.clipboard.writeText($('#invite-link').value);notice('Activatielink gekopieerd.');}catch{$('#invite-link').focus();$('#invite-link').select();notice('Selecteer en kopieer de link.');}},$('#copy-invite'));
(async()=>{try{if(await refresh())show('dashboard');}catch(error){if(mode==='kantoor'){show('dashboard');$('#order-list').textContent='Werkbonnen konden niet worden geladen. Kies Vernieuwen zodra de verbinding is hersteld.';}else activationRequired();notice(error.message,true);}if('serviceWorker'in navigator)navigator.serviceWorker.register('/werkbonnen/sw.js',{scope:'/werkbonnen/'}).catch(()=>{});})();
