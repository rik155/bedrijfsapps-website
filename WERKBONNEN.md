# Werkbonnen voor Jan Bos

De kantoor-app krijgt één extra tegel **Werkbonnen**. De glaszetter opent een aparte app met eigen icoon. De medewerkers-app is niet aangepast.

| Omgeving | Pad |
| --- | --- |
| Kantoor: aanmaken, bewerken en overzicht | `/werkbonnen/kantoor` |
| Glaszetter: opdracht, uitvoering, foto’s en klantakkoord | `/werkbonnen/glaszetter` |

## Werkwijze

1. Kantoor vult project/projectnummer, naam, adres, telefoon, e-mail en opdracht in. Plandatum en naam glaszetter zijn optioneel.
2. Na opslaan verschijnt de opdracht in de aparte glaszetter-app. De lijst ververst automatisch wanneer deze zichtbaar is, elke 30 seconden, en heeft een knop Vernieuwen.
3. De glaszetter opent de opdracht, vult uitgevoerde werkzaamheden, materialen en uren in en voegt foto’s vóór en na toe. De klant kan opmerkingen invullen.
4. Met Tussentijds opslaan worden de gegevens voor beide omgevingen op de server opgeslagen.
5. De klant controleert de volledige bon inclusief foto’s, vult de naam in, zet een handtekening met vinger of pen en bevestigt het akkoord.
6. De bon wordt definitief. De opdracht, uitvoering, foto’s, naam en datum van ondertekening blijven op kantoor zichtbaar. Afdrukken / PDF gebruikt de afdrukfunctie van de browser.

Afronden vereist een omschrijving van de uitgevoerde werkzaamheden, minimaal één foto vóór en na, naam, akkoord en handtekening. Ook via de API kan een ondertekende bon niet worden aangepast. Bij gelijktijdige wijzigingen wordt overschrijven geweigerd; de gebruiker houdt zijn eigen invoer in beeld. Kopieer bij een conflict de eigen invoer, herlaad de bon en voeg deze toe aan de nieuwste versie.

## Eenmalige VPS-instelling

Deze wijziging is nog niet op de VPS uitgerold. Er staan geen wachtwoorden of voorbeeldklanten in de code.

1. Test en merge de wijziging en haal daarna de nieuwe versie op de VPS op.
2. Voer in de repository `python3 werkbonnen_setup.py` uit. Kies twee verschillende wachtwoorden, voor kantoor en glaszetter. Het script schrijft `.env.werkbonnen` met bestandsrechten 600 en overschrijft geen bestaande configuratie.
3. Geef `.env.werkbonnen` bij het starten van de bestaande container mee met `--env-file .env.werkbonnen` (of een overeenkomstige Compose `env_file`). Behoud de bestaande omgevingsvariabelen en containerinstellingen.
4. Voeg een blijvend volume toe: `-v janbos-werkbonnen:/data/werkbonnen`. De Dockerfile stelt `WERKBON_DATA_DIR=/data/werkbonnen` in. Gebruik hetzelfde volume bij elke update.
5. Bouw en herstart de kantoorcontainer. De bestaande poort, HTTPS reverse proxy en het domein blijven behouden. Stel de uploadlimiet van de reverse proxy voor `/werkbonnen/` zo nodig in op 20 MB.
6. Open op het bestaande domein `/werkbonnen/kantoor` en log in met het kantoorwachtwoord. De nieuwe tegel staat in `kantoor.html`.
7. Open op telefoon of tablet `/werkbonnen/glaszetter` en log in met het glaszetterwachtwoord. Installeer deze aparte app vanaf die pagina.

Er is geen extra server, domein of externe opslagdienst nodig. Alle bestaande apps en het contactformulier blijven beschikbaar. Er worden geen e-mails verstuurd; het e-mailadres is klantinformatie.

### Installeren op telefoon of tablet

- Android: open de glaszetter-ingang in Chrome → menu → App installeren / Toevoegen aan startscherm.
- iPhone/iPad: open de glaszetter-ingang in Safari → Deel → Zet op beginscherm.

## Opslag, toegang en verbinding

Database, foto’s, handtekeningen en sessiesleutel staan onder `WERKBON_DATA_DIR`. Zonder expliciete instelling gebruikt de module `~/.local/share/janbos-werkbonnen`. De module blokkeert directe toegang via de statische bestandsroute van het bestaande portaal. Bestanden zijn alleen via de aangemelde API beschikbaar. Maak consistente back-ups van de database en uploads, bijvoorbeeld door de container kort te stoppen en het hele volume te kopiëren. Verwijder het volume niet bij updates.

Er zijn twee gedeelde rollen, met aparte wachtwoorden. Inloggen wordt 30 dagen onthouden. De glaszetter kan geen werkbonnen aanmaken of kantoorvelden wijzigen. Alle glaszetters kunnen alle werkbonnen zien; de naam glaszetter is een filter en geen persoonlijke autorisatie. Zoek op project, klant, adres of bonnummer en filter op status of glaszetter.

Gebruik HTTPS. De sessiecookie is standaard secure. Alleen voor lokaal testen via HTTP: `WERKBON_SECURE_COOKIE=0`. Bij wijziging van een wachtwoord: roteer ook de sessiesleutel in `WERKBON_DATA_DIR/.session-secret` en herstart alle processen om bestaande sessies af te melden. Als de bestaande app zelf een `SECRET_KEY` heeft, beheert die de sessiesleutel.

Internet is nodig om werkbonnen op te halen, op te slaan en foto’s te uploaden. De app bewaart geen klantgegevens of foto’s in de offlinecache. Houd de pagina open bij verbindingsverlies en sla daarna opnieuw op. Nog niet opgeslagen invoer gaat bij sluiten of herladen verloren; de browser waarschuwt hiervoor waar ondersteund.

Foto’s worden in de browser en op de server verkleind tot maximaal 1800 pixels, opnieuw als JPG opgeslagen en van EXIF-gegevens ontdaan. Kies bij een niet ondersteunde HEIC-afbeelding een JPG-versie. De limiet is 60 foto’s per werkbon en 20 MB per uploadverzoek.

## Controle

Installeer `requirements.txt` en daarnaast `pytest`. Voer uit:

```sh
python -m pytest -q tests/test_werkbonnen.py
node --check werkbonnen/static/app.js
```

De tests controleren de volledige kantoor/glaszetter-workflow, rechten, verplichte velden, CSRF, conflicten, foto’s, ondertekening, vergrendeling, sessie-aanmelding en behoud na een herstart. Een aparte integratietest controleert dat de bestaande statische Flask-route geen database, sessiesleutel, configuratie of uploads kan lekken. De browsercontrole gebruikte uitsluitend lokale testgegevens; die worden niet meegeleverd.
