# Jan Bos Werkbonnen

Kantoor krijgt de tegel **Werkbonnen**. De glaszetter gebruikt een aparte app. De medewerkerspagina wordt niet aangepast.

| Ingang | Pad |
| --- | --- |
| Kantoor | `/werkbonnen/kantoor` |
| Glaszetter | `/werkbonnen/glaszetter` |
| Eenmalige activatie | `/werkbonnen/activeren` |

## Eenmalige activatie, daarna direct openen

Er zijn geen app-wachtwoorden, pincodes of accounts. Elk apparaat of elke browser wordt eenmalig geactiveerd via een privélink. Daarna opent de app direct. Zonder geactiveerd apparaat blijven klantgegevens, bonnen, foto’s en handtekeningen afgeschermd.

Een activatielink werkt voor één apparaat en is maximaal 48 uur geldig. De gebruiker opent de link op het bedoelde apparaat en kiest **Dit apparaat activeren**. Pas deze POST-actie verbruikt de link; openen van de pagina zelf verbruikt hem niet. Het token staat in het URL-fragment, wordt niet naar de server in de URL verstuurd en wordt direct uit de browseradresbalk verwijderd. Alleen een SHA-256-hash van het token staat in de database. De server consumeert de link atomair, zodat ook gelijktijdig gebruik maar één apparaat activeert.

Het geactiveerde apparaat krijgt een getekende, HttpOnly-, SameSite- en Secure-cookie. De apparaatrol staat op de server en kan niet via een header of de browser worden verhoogd. Een kantoorapparaat kan kantoor en uitvoering gebruiken. Een glaszetterapparaat kan geen opdracht aanmaken, kantoorvelden wijzigen, nieuwe activatielinks maken of apparaten beheren.

Kantoor kan onder **Apparaten** nieuwe eenmalige links maken en toegang intrekken. Intrekken blokkeert ook reeds geopende werkbonnen en foto-API’s bij het volgende verzoek. De bestaande portaalcookies blijven gescheiden van de werkbon-cookie.

De cookie wordt bij gebruik verlengd, met een looptijd van één jaar. Bij het wissen van browsergegevens, een andere browser, sommige afzonderlijke PWA-installaties of na verlopen van de cookie is opnieuw activeren nodig.

## Werkwijze

1. Kantoor vult project/projectnummer, klantnaam, adres, telefoon, e-mail en opdracht in. Plandatum en glaszetter zijn optioneel.
2. De opdracht verschijnt in de aparte glaszetter-app. De lijst ververst elke 30 seconden wanneer deze zichtbaar is, en heeft een knop Vernieuwen.
3. De glaszetter vult werkzaamheden, materialen en uren in en voegt foto’s vóór en na toe. De klant kan opmerkingen invullen.
4. Tussentijds opslaan bewaart de invoer op de server voor beide ingangen.
5. De klant controleert de hele bon inclusief foto’s, vult de naam in, tekent met vinger of pen en bevestigt het akkoord.
6. De bon wordt definitief. Kantoor kan de hele bon bekijken en via de browser afdrukken of als PDF opslaan.

Afronden vereist een omschrijving van het uitgevoerde werk, minimaal één foto vóór en na, naam, akkoord en handtekening. Ook via de API kan een definitieve bon niet meer worden aangepast. Er worden geen e-mails verstuurd; het e-mailadres is klantinformatie. Er worden geen voorbeeldklanten meegeleverd.

## Installatie op de bestaande VPS

De draaiende kantoorversie is nieuwer dan de oorspronkelijke GitHub-basis en bevat extra voorraad- en medewerkersmodules. Gebruik `deploy_werkbonnen.py --release VOLLEDIGE_COMMIT_SHA` op de VPS. Het script stelt geen wachtwoordvragen. De daadwerkelijke VPS-uitrol moet nog plaatsvinden.

De installer maakt lokaal een snapshot van de draaiende container, inclusief eerdere bestandswijzigingen. Daarop bouwt hij verder met de werkbon-module en wijzigingen aan alleen `app.py` en `kantoor.html`. De module gebruikt een aparte Flask-instantie en cookiepad via een WSGI-koppeling. De medewerkerspagina wordt op inhoud vergeleken met het origineel.

Een tijdelijke testcontainer krijgt geen gepubliceerde poorten en geen labels voor automatische proxyregistratie. De test controleert activeren, eenmalig gebruik, beide rollen en het weigeren van ongeactiveerde apparaten. Tijdelijke controletokens en apparaten worden na deze test verwijderd. Er worden geen testbonnen in de echte opslag aangemaakt.

Vóór de omschakeling maakt de installer de eerste kantoor- en glaszetteractivatielink. Ze blijven in een privébestand op de VPS en worden pas na een geslaagde uitrol in de terminal getoond. Deze links staan nooit in openbare HTML of broncode.

Daarna wordt de kantoorcontainer vervangen met behoud van poorten, bestaande gegevensmounts, omgevingsvariabelen, netwerk, loginstellingen en herstartbeleid. Achtergebleven werkbon-wachtwoordvariabelen worden verwijderd. Bij een mislukte controle na omschakeling wordt de oorspronkelijke container teruggezet. De oude container blijft als gestopte back-up bewaard.

Een map `~/janbos-werkbonnen-DATUM-NUMMER` met rechten 700 bevat de oude bestanden, privéconfiguratie, `activatielinks.json` met rechten 600 en bij succes `HERSTEL.sh`. Publiceer of deel deze map niet. Bestaande privébroncode en instellingen verlaten de VPS niet.

De ontwikkelomgeving heeft geen Docker-engine. De installer test daarom de echte configuratie op de VPS vóór de omschakeling. Automatische tests simuleren herstel na een mislukte controle en een onderbroken hernoemactie. Het script kan een eerdere versie van dezelfde uitbreiding bijwerken. Als het vorige installatieblok nog om een wachtwoord vraagt, onderbreek dat eerst met Ctrl+C.

### Extra activatielink via de VPS-terminal

```sh
docker exec bedrijfsapps-website python -m werkbonnen.devices invite glaszetter --label 'Tablet 2'
```

Gebruik `kantoor` in plaats van `glaszetter` voor een nieuw kantoorapparaat. Deze beheeractie vereist bestaande Docker/VPS-beheertoegang. Toon apparaten met `python -m werkbonnen.devices list` en trek toegang in met `python -m werkbonnen.devices revoke APPARAAT_ID`, uitgevoerd via dezelfde `docker exec`.

## Opslag en verbinding

Database, foto’s, handtekeningen, apparaatgegevens en sessiesleutel staan onder `WERKBON_DATA_DIR`, op deze VPS `/data/werkbonnen` in het bestaande blijvende volume. Zonder instelling is het standaardpad `~/.local/share/janbos-werkbonnen`. Ruwe database- en configuratiebestanden zijn niet als statische bestanden beschikbaar. Foto’s vereisen een actief apparaat. Maak consistente back-ups van database en uploads en behoud het volume bij updates.

Internet is nodig voor ophalen, opslaan en foto’s uploaden. Houd bij verbindingsverlies de pagina open en sla opnieuw op zodra de verbinding terug is. Nog niet opgeslagen invoer gaat bij sluiten of herladen verloren; de browser waarschuwt waar ondersteund. Klantgegevens en foto’s worden niet offline gecachet. Alleen voor lokaal HTTP-testen kan `WERKBON_SECURE_COOKIE=0` worden ingesteld; op de VPS gebruikt de app HTTPS.

Foto’s worden verkleind tot maximaal 1800 pixels, opnieuw opgeslagen als JPG en ontdaan van EXIF-gegevens. Gebruik bij een niet ondersteunde HEIC-afbeelding een JPG-versie. De limiet is 60 foto’s per bon en 20 MB per uploadverzoek.

## App installeren

- Android: open de glaszetter-ingang in Chrome, kies menu → App installeren / Toevoegen aan startscherm.
- iPhone/iPad: open de glaszetter-ingang in Safari, kies Deel → Zet op beginscherm.

## Controle

Installeer `requirements.txt` en daarnaast `pytest`. Voer uit:

```sh
python -m pytest -q tests
node --check werkbonnen/static/app.js
node --check werkbonnen/static/activate.js
```

De tests controleren de volledige werkbon-workflow, apparaatactivatie, weigeren van ongeactiveerde apparaten, gebruik en verval van activatielinks, gelijktijdige claims, onmogelijkheid om de rol via een header te verhogen, direct blokkeren na intrekken, onthouden van apparaten bij herstart, CSRF, verplichte velden, conflicten, foto’s, handtekening, vergrendeling en installatie/herstel.
