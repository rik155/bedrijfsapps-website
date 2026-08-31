const params = new URLSearchParams(location.search);
const pathParts = location.pathname.split('/').filter(Boolean);
const slug = params.get('slug') || (pathParts[0] === 'install' && pathParts[1]) || 'demo';
const company = params.get('bedrijf') || slug.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
const appUrl = params.get('app') || location.origin;

const title = document.getElementById('title');
const button = document.getElementById('installButton');
const status = document.getElementById('status');
const iosHelp = document.getElementById('iosHelp');
const manifest = document.getElementById('manifestLink');

manifest.href = `/manifest/${encodeURIComponent(slug)}.webmanifest?bedrijf=${encodeURIComponent(company)}&app=${encodeURIComponent(appUrl)}`;
title.textContent = `BouwFlow voor ${company}`;

localStorage.setItem('bouwflow_customer', JSON.stringify({slug, company, appUrl}));

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register(`/sw.js?slug=${encodeURIComponent(slug)}`).catch(() => {});
}

const standalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
const isiOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
let deferredPrompt = null;

if (standalone) {
  button.textContent = 'BouwFlow openen';
  status.textContent = 'BouwFlow is al geinstalleerd op dit apparaat.';
  button.onclick = () => location.href = `/app/${encodeURIComponent(slug)}?bedrijf=${encodeURIComponent(company)}&app=${encodeURIComponent(appUrl)}`;
} else if (isiOS) {
  button.textContent = 'Bekijk installatie-uitleg';
  iosHelp.style.display = 'block';
  status.textContent = 'Op iPhone en iPad gebruikt Apple de knop Zet op beginscherm.';
  button.onclick = () => iosHelp.scrollIntoView({behavior:'smooth', block:'center'});
} else {
  button.disabled = true;
  button.textContent = 'Installatie voorbereiden...';
  status.textContent = 'Een moment, BouwFlow wordt klaargezet.';
}

window.addEventListener('beforeinstallprompt', event => {
  event.preventDefault();
  deferredPrompt = event;
  button.disabled = false;
  button.textContent = 'Installeer BouwFlow';
  status.textContent = 'Klaar om te installeren.';
});

button.addEventListener('click', async () => {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  const result = await deferredPrompt.userChoice;
  if (result.outcome === 'accepted') {
    status.textContent = 'BouwFlow wordt geinstalleerd...';
  } else {
    status.textContent = 'Installatie geannuleerd. Je kunt het opnieuw proberen.';
  }
  deferredPrompt = null;
});

window.addEventListener('appinstalled', () => {
  button.disabled = false;
  button.textContent = 'BouwFlow is geinstalleerd ✓';
  status.textContent = 'Klaar. Open BouwFlow voortaan via het BouwFlow-icoon.';
});

setTimeout(() => {
  if (!standalone && !isiOS && !deferredPrompt) {
    button.disabled = false;
    button.textContent = 'Open BouwFlow';
    status.textContent = 'Automatische installatie wordt op deze browser niet aangeboden. Je kunt BouwFlow wel direct openen.';
    button.onclick = () => location.href = `/app/${encodeURIComponent(slug)}?bedrijf=${encodeURIComponent(company)}&app=${encodeURIComponent(appUrl)}`;
  }
}, 3000);