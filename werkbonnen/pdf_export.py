"""Downloadable A4 work orders, with stored photos and customer signature."""
from datetime import datetime
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from PIL import Image as PillowImage
import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Table, TableStyle

NAVY = colors.HexColor('#123b5d')
PALE = colors.HexColor('#f0f4f7')
MUTED = colors.HexColor('#627584')
LINE = colors.HexColor('#dce5eb')
FONT_ROOT = Path(reportlab.__file__).parent / 'fonts'
pdfmetrics.registerFont(TTFont('Werkbon', str(FONT_ROOT / 'Vera.ttf')))
pdfmetrics.registerFont(TTFont('WerkbonBold', str(FONT_ROOT / 'VeraBd.ttf')))
pdfmetrics.registerFontFamily('Werkbon', normal='Werkbon', bold='WerkbonBold', italic='Werkbon', boldItalic='WerkbonBold')


def date_text(value, with_time=False):
    if not value:
        return 'Niet ingevuld'
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo:
        parsed = parsed.astimezone(ZoneInfo('Europe/Amsterdam'))
    return parsed.strftime('%d-%m-%Y %H:%M' if with_time else '%d-%m-%Y')


def build_work_order_pdf(order, data_directory):
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, leftMargin=42, rightMargin=42,
                                 topMargin=94, bottomMargin=48, title=order['number'] + ' - ' + order['project'],
                                 author='Jan Bos Glas- en Schilderwerken')
    width = A4[0] - 84
    base = ParagraphStyle('Body', fontName='Werkbon', fontSize=9.5, leading=14, textColor=NAVY,
                          spaceAfter=6, splitLongWords=True)
    caption = ParagraphStyle('Caption', parent=base, fontSize=8, leading=11, textColor=MUTED, spaceAfter=4)
    heading = ParagraphStyle('Heading', parent=base, fontName='WerkbonBold', fontSize=12.5, leading=17,
                              spaceBefore=15, spaceAfter=9, keepWithNext=True)
    title = ParagraphStyle('Title', parent=base, fontName='WerkbonBold', fontSize=23, leading=29, spaceAfter=8)
    project = ParagraphStyle('Project', parent=base, fontName='WerkbonBold', fontSize=14, leading=20, spaceAfter=13)

    def paragraph(value, style=base):
        clean = ''.join(c for c in str(value or '') if c in '\n\t' or ord(c) >= 32)
        return Paragraph(escape(clean).replace('\n', '<br/>') or '-', style)

    def field(label, value):
        return [paragraph(label.upper(), caption), paragraph(value)]

    def section(label, value):
        return [paragraph(label, heading), paragraph(value or 'Niet ingevuld')]

    def scaled_image(path, maximum_width, maximum_height):
        try:
            content = path.read_bytes()
            with PillowImage.open(BytesIO(content)) as image:
                factor = min(maximum_width / image.width, maximum_height / image.height)
                return Image(BytesIO(content), width=image.width * factor, height=image.height * factor, hAlign='LEFT')
        except OSError:
            return paragraph('Afbeelding niet beschikbaar', caption)

    states = {'open': 'Open', 'in_progress': 'In uitvoering', 'completed': 'Afgerond en ondertekend'}
    flow = [paragraph('Werkbon', title), paragraph(order['project'], project)]
    summary = Table([[paragraph(order['number']), paragraph(states[order['status']]),
                       paragraph('Plandatum: ' + date_text(order['planned_date']))]], colWidths=[105, 180, width - 285])
    summary.setStyle(TableStyle([('BACKGROUND', (0,0),(-1,-1),PALE),('TOPPADDING',(0,0),(-1,-1),10),
                                 ('BOTTOMPADDING',(0,0),(-1,-1),6),('VALIGN',(0,0),(-1,-1),'TOP')]))
    flow += [summary, paragraph('Klant & project', heading)]
    customer = Table([[field('Naam klant',order['name']), field('Werkadres',order['address'])],
                      [field('Telefoon',order['phone']), field('E-mail',order['email'])],
                      [field('Glaszetter',order['assignee'] or 'Niet toegewezen'),field('Aangemaakt',date_text(order['created_at']))]],
                     colWidths=[width/2, width/2], hAlign='LEFT')
    customer.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),
                                  ('RIGHTPADDING',(0,0),(-1,-1),16),('BOTTOMPADDING',(0,0),(-1,-1),10)]))
    flow.append(customer)
    flow += section('Opdracht van kantoor', order['assignment'])
    flow += section('Uitgevoerde werkzaamheden', order['work_done'])
    flow += section('Gebruikte materialen', order['materials'])
    flow += section('Gewerkte uren', order['hours'])
    flow += section('Opmerkingen van de klant', order['customer_notes'])
    uploads = Path(data_directory) / 'uploads'
    for category, label in (('before', 'Foto’s vóór het werk'), ('after', 'Foto’s na het werk')):
        flow.append(paragraph(label, heading))
        photos = [photo for photo in order['photos'] if photo['category'] == category]
        if not photos:
            flow.append(paragraph('Geen foto’s toegevoegd', caption))
        for index in range(0, len(photos), 2):
            cells = []
            for offset, photo in enumerate(photos[index:index+2], start=index+1):
                path = uploads / (photo['id'] + '.jpg')
                content = [paragraph('Foto ' + str(offset), caption)]
                content.append(scaled_image(path, width/2-14, 175) if path.is_file() else paragraph('Foto niet beschikbaar', caption))
                cells.append(content)
            if len(cells) == 1:
                cells.append('')
            table = Table([cells], colWidths=[width/2, width/2], hAlign='LEFT')
            table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),
                                       ('RIGHTPADDING',(0,0),(-1,-1),14),('BOTTOMPADDING',(0,0),(-1,-1),14)]))
            flow.append(table)
    signature = [paragraph('Klantakkoord', heading)]
    if order['status'] == 'completed':
        signature += [paragraph('Ondertekend door ' + order['signed_by']),
                      paragraph('Datum en tijd: ' + date_text(order['signed_at'], True), caption)]
        signature_id = (order.get('signature_url') or '').rsplit('/',1)[-1]
        path = uploads / (signature_id + '.jpg')
        if path.is_file():
            signature.append(scaled_image(path, 245, 90))
        else:
            signature.append(paragraph('De afbeelding van de handtekening is niet beschikbaar.', caption))
        signature.append(paragraph('De klant heeft de werkbon, de uitgevoerde werkzaamheden en de opmerkingen gecontroleerd en is akkoord met deze vastlegging.', caption))
    else:
        signature.append(paragraph('Deze werkbon is nog niet ondertekend.'))
    flow.append(KeepTogether(signature))

    def brand(canvas, doc):
        canvas.saveState()
        logo = Path(__file__).parent / 'static' / 'janbos-logo.png'
        if logo.is_file():
            canvas.drawImage(ImageReader(str(logo)), 42, A4[1]-76, width=120, height=58, preserveAspectRatio=True, mask='auto', anchor='w')
        canvas.setFillColor(NAVY);canvas.setFont('WerkbonBold', 10)
        canvas.drawRightString(A4[0]-42,A4[1]-36,order['number'])
        canvas.setFont('Werkbon',8);canvas.setFillColor(MUTED)
        canvas.drawRightString(A4[0]-42,A4[1]-51,'Jan Bos Glas- en Schilderwerken')
        canvas.setStrokeColor(LINE);canvas.line(42,A4[1]-82,A4[0]-42,A4[1]-82)
        canvas.line(42,36,A4[0]-42,36)
        canvas.drawString(42,23,order['number'] + ' | ' + states[order['status']])
        canvas.drawRightString(A4[0]-42,23,'Pagina ' + str(doc.page))
        canvas.restoreState()

    document.build(flow, onFirstPage=brand, onLaterPages=brand)
    return output.getvalue()
