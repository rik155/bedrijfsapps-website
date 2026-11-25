# Jan Bos Werkbonnen

Kantoor krijgt de tegel **Werkbonnen**. De glaszetter gebruikt een aparte app. De medewerkerspagina wordt niet aangepast.

| Ingang | Pad |
| --- | --- |
| Kantoor | `/werkbonnen/kantoor` |
| Glaszetter | `/werkbonnen/glaszetter` |
| Eenmalige activatie | `/werkbonnen/activeren` |

## Kantoor direct open, glaszetter eenmalig activeren

Kantoor opent rechtstreeks vanuit de bestaande kantoor-app: klik op de tegel Werkbonnen. Er is voor kantoor geen wachtwoord, activatielink of apparaatregistratie nodig. De gebruiker heeft uitdrukkelijk gekozen voor **iedereen**: via de openbare kantoor-ingang kunnen bezoekers klantgegevens, bonnen, foto’s en handtekeningen bekijken en openstaande bonnen aanmaken of wijzigen.

Alleen de aparte glaszetter-ingang vereist eenmalige apparaatactivatie. Die activatie schermt de glaszetter-interface en haar API af; zij maakt de gedeelde gegevens niet privé, omdat dezelfde gegevens via de openbare kantoor-ingang beschikbaar zijn.

Openbare kantoorverzoeken gebruiken de aparte route `/werkbonnen/kantoor-api`. De glaszetter gebruikt `/werkbonnen/api`, met apparaatscontrole. Het openen van kantoor activeert geen glaszetterapparaat en verhoogt geen apparaatrol. CSRF-controle, invoervalidatie, bescherming tegen gelijktijdig overschrijven en vergrendeling van ondertekende bonnen blijven gelden. Ruwe database- en configuratiebestanden blijven afgeschermd.

Een activatielink werkt voor één apparaat en is maximaal 48 uur geldig. De gebruiker opent de link op het bedoelde apparaat en kiest **Dit apparaat activeren**. Pas deze POST-actie verbruikt de link; openen van de pagina zelf verbruikt hem niet. Het token staat in het URL-fragment, wordt niet naar de server in de URL verstuurd en wordt direct uit de browseradresbalk verwijderd. Alleen een SHA-256-hash van het token staat in de database. De server consumeert de link atomair, zodat ook gelijktijdig gebruik maar één apparaat activeert.

Het geactiveerde glaszetterapparaat krijgt een getekende, HttpOnly-, SameSite- en Secure-cookie. De apparaatrol staat op de server en kan op de glaszetter-API niet via een header worden verhoogd. De glaszetter-interface toont uitvoering en geen knoppen voor het aanmaken van opdrachten. De openbare kantoor-ingang blijft voor iedereen bereikbaar.

De installer en de VPS-beheerder maken privélinks voor glaszetterapparaten. Apparaatbeheer is niet openbaar gemaakt; de knop Apparaten is verborgen in de openbare kantoor-interface. De aparte beschermde beheer-API blijft beschikbaar voor reeds geactiveerde beheerdevices uit de vorige versie. Intrekken blokkeert de glaszetter-API bij het volgende verzoek. De bestaande portaalcookies blijven gescheiden van de werkbon-cookie.

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

Een tijdelijke testcontainer krijgt geen gepubliceerde poorten en geen labels voor automatische proxyregistratie. De test controleert kantoor zonder activatie, de CSRF-controle van de openbare kantoor-API, glaszetteractivatie en eenmalig gebruik, en het weigeren van ongeactiveerde aanvragen op de glaszetter-API. Tijdelijke controletokens en apparaten worden na deze test verwijderd. Er worden geen testbonnen in de echte opslag aangemaakt.

Vóór de omschakeling maakt de installer alleen een glaszetteractivatielink. Die blijft in een privébestand op de VPS en wordt pas na een geslaagde uitrol in de terminal getoond. Voor kantoor wordt geen activatielink aangemaakt. Bestaande glaszetteractivaties blijven werken. Privéactivatielinks staan nooit in openbare HTML of broncode.

Daarna wordt de kantoorcontainer vervangen met behoud van poorten, bestaande gegevensmounts, omgevingsvariabelen, netwerk, loginstellingen en herstartbeleid. Achtergebleven werkbon-wachtwoordvariabelen worden verwijderd. Bij een mislukte controle na omschakeling wordt de oorspronkelijke container teruggezet. De oude container blijft als gestopte back-up bewaard.

Een map `~/janbos-werkbonnen-DATUM-NUMMER` met rechten 700 bevat de oude bestanden, privéconfiguratie, `activatielinks.json` met rechten 600 en bij succes `HERSTEL.sh`. Publiceer of deel deze map niet. Bestaande privébroncode en instellingen verlaten de VPS niet.

De ontwikkelomgeving heeft geen Docker-engine. De installer test daarom de echte configuratie op de VPS vóór de omschakeling. Automatische tests simuleren herstel na een mislukte controle en een onderbroken hernoemactie. Het script kan een eerdere versie van dezelfde uitbreiding bijwerken. Als het vorige installatieblok nog om een wachtwoord vraagt, onderbreek dat eerst met Ctrl+C.

### Extra activatielink via de VPS-terminal

```sh
docker exec bedrijfsapps-website python -m werkbonnen.devices invite glaszetter --label 'Tablet 2'
```

Voor kantoor is geen activatiecommando nodig. Deze beheeractie voor de glaszetter vereist bestaande Docker/VPS-beheertoegang. Toon apparaten met `python -m werkbonnen.devices list` en trek toegang in met `python -m werkbonnen.devices revoke APPARAAT_ID`, uitgevoerd via dezelfde `docker exec`.

## Opslag en verbinding

Database, foto’s, handtekeningen, apparaatgegevens en sessiesleutel staan onder `WERKBON_DATA_DIR`, op deze VPS `/data/werkbonnen` in het bestaande blijvende volume. Zonder instelling is het standaardpad `~/.local/share/janbos-werkbonnen`. Ruwe database- en configuratiebestanden zijn niet als statische bestanden beschikbaar. Foto’s op de glaszetter-API vereisen een actief apparaat; de kantoor-API biedt dezelfde foto’s openbaar aan. Maak consistente back-ups van database en uploads en behoud het volume bij updates.

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

De tests controleren de volledige gedeelde werkbon-workflow via openbaar kantoor en geactiveerde glaszetter, alleen glaszetterlinks in de installer, afscherming van apparaatbeheer, apparaatactivatie, weigeren van ongeactiveerde apparaten op de glaszetter-API, gebruik en verval van activatielinks, gelijktijdige claims, onmogelijkheid om de rol via een header te verhogen, direct blokkeren na intrekken, onthouden van apparaten bij herstart, CSRF, verplichte velden, conflicten, foto’s, handtekening, vergrendeling en installatie/herstel.
