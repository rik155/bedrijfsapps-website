'use strict';
const token=new URLSearchParams(location.hash.slice(1)).get('token');
history.replaceState(null,'',location.pathname);
const button=document.querySelector('#activate-device');
const status=document.querySelector('#activation-status');
let csrf='';
async function state(){const response=await fetch('/werkbonnen/api/session',{cache:'no-store'});if(!response.ok)throw new Error('De verbinding met de app is niet gelukt.');return response.json();}
(async()=>{try{
  const current=await state();csrf=current.csrf;
  if(!token){if(current.role){location.replace('/werkbonnen/'+current.role);return;}status.textContent='Open de volledige activatielink die je van kantoor hebt ontvangen.';return;}
  status.textContent='Klik hieronder om deze browser te activeren.';button.disabled=false;
}catch(error){status.textContent=error.message;}})();
button.onclick=async()=>{
  button.disabled=true;status.textContent='Apparaat activeren…';
  try{
    const response=await fetch('/werkbonnen/api/activate',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({token}),cache:'no-store'});
    const result=await response.json();if(!response.ok)throw new Error(result.error||'Activeren is niet gelukt.');
    location.replace(result.start_url);
  }catch(error){
    try{const current=await state();if(current.role){location.replace('/werkbonnen/'+current.role);return;}}catch{}
    status.textContent=error.message||'Geen verbinding. Probeer opnieuw.';button.disabled=false;
  }
};
