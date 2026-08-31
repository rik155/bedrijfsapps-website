const form=document.getElementById('demoForm');

form?.addEventListener('submit',e=>{
  e.preventDefault();

  const naam=document.getElementById('naam').value.trim();
  const bedrijf=document.getElementById('bedrijf').value.trim();
  const email=document.getElementById('email').value.trim();
  const telefoon=document.getElementById('telefoon').value.trim();
  const soort=document.getElementById('soort').value;
  const bericht=document.getElementById('bericht').value.trim();

  const subject=encodeURIComponent(`Gratis demo BouwFlow - ${bedrijf}`);
  const body=encodeURIComponent(`Hallo,\n\nIk wil graag een gratis BouwFlow-demo aanvragen.\n\nNaam: ${naam}\nBedrijf: ${bedrijf}\nE-mail: ${email}\nTelefoon: ${telefoon||'-'}\nInteresse: ${soort}\n\nHoe het nu werkt / wat ik wil verbeteren:\n${bericht}\n\nMet vriendelijke groet,\n${naam}`);

  window.location.href=`mailto:fokkerrik@gmail.com?subject=${subject}&body=${body}`;
});