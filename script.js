const form = document.getElementById('demoForm');

form?.addEventListener('submit', async (e) => {
  e.preventDefault();

  const button = form.querySelector('button[type="submit"]');
  const help = form.querySelector('.form-help');
  const originalText = button.textContent;

  const payload = {
    naam: document.getElementById('naam').value.trim(),
    bedrijf: document.getElementById('bedrijf').value.trim(),
    email: document.getElementById('email').value.trim(),
    telefoon: document.getElementById('telefoon').value.trim(),
    soort: document.getElementById('soort').value,
    bericht: document.getElementById('bericht').value.trim()
  };

  button.disabled = true;
  button.textContent = 'Aanvraag versturen...';
  help.textContent = '';

  try {
    const response = await fetch('/api/demo', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });

    const result = await response.json();
    if (!response.ok) throw new Error(result.message || 'Versturen mislukt.');

    form.reset();
    button.textContent = 'Aanvraag verstuurd ✓';
    help.textContent = 'Bedankt! Ik neem zo snel mogelijk contact met je op.';
    help.style.color = '#16845c';

    setTimeout(() => {
      button.textContent = originalText;
      button.disabled = false;
    }, 4000);
  } catch (error) {
    help.textContent = error.message || 'Er ging iets mis. Mail anders naar fokkerrik@gmail.com.';
    help.style.color = '#c43d4d';
    button.textContent = originalText;
    button.disabled = false;
  }
});
