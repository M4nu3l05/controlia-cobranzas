from __future__ import annotations

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "Manual_Usuario_Controlia_Cobranzas.docx"
LOGO = ROOT / "outputs" / "controlia_logo.png"

BLUE = "2563EB"
BLUE_DARK = "1D4ED8"
NAVY = "0F172A"
SLATE = "475569"
MUTED = "64748B"
PALE = "EFF6FF"
BG = "F6F8FB"
BORDER = "E2E8F0"
GREEN = "059669"
AMBER = "B45309"
RED = "DC2626"
WHITE = "FFFFFF"


def rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color)


def shade(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=90, start=120, bottom=90, end=120) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for m, v in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{m}"))
        if node is None:
            node = OxmlElement(f"w:{m}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(v))
        node.set(qn("w:type"), "dxa")


def set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    flag = OxmlElement("w:tblHeader")
    flag.set(qn("w:val"), "true")
    tr_pr.append(flag)


def cant_split(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tr_pr.append(OxmlElement("w:cantSplit"))


def set_cell_width(cell, dxa: int) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.find(qn("w:tcW"))
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(dxa))
    tc_w.set(qn("w:type"), "dxa")


def set_table_geometry(table, widths: list[int], indent=120) -> None:
    table.autofit = False
    tbl_pr = table._tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(sum(widths)))
    tbl_w.set(qn("w:type"), "dxa")
    tbl_ind = tbl_pr.find(qn("w:tblInd"))
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:w"), str(indent))
    tbl_ind.set(qn("w:type"), "dxa")
    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(width))
        grid.append(col)
    for row in table.rows:
        for i, cell in enumerate(row.cells):
            set_cell_width(cell, widths[min(i, len(widths) - 1)])
            set_cell_margins(cell)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def set_run(run, size=None, color=NAVY, bold=None, italic=None, font="Segoe UI"):
    run.font.name = font
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), font)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), font)
    if size is not None:
        run.font.size = Pt(size)
    if color:
        run.font.color.rgb = rgb(color)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    return run


def page_number(paragraph):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run("Página ")
    set_run(run, 8.5, MUTED)
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    paragraph._p.append(fld)


def configure(doc: Document) -> None:
    sec = doc.sections[0]
    sec.page_width = Inches(8.5)
    sec.page_height = Inches(11)
    sec.top_margin = Inches(0.78)
    sec.bottom_margin = Inches(0.72)
    sec.left_margin = Inches(0.82)
    sec.right_margin = Inches(0.82)
    sec.header_distance = Inches(0.35)
    sec.footer_distance = Inches(0.35)

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = "Segoe UI"
    normal._element.rPr.rFonts.set(qn("w:ascii"), "Segoe UI")
    normal._element.rPr.rFonts.set(qn("w:hAnsi"), "Segoe UI")
    normal.font.size = Pt(10.2)
    normal.font.color.rgb = rgb(NAVY)
    normal.paragraph_format.space_after = Pt(5)
    normal.paragraph_format.line_spacing = 1.18

    for name, size, color, before, after in (
        ("Title", 28, NAVY, 0, 6),
        ("Subtitle", 13, SLATE, 0, 8),
        ("Heading 1", 18, BLUE_DARK, 15, 8),
        ("Heading 2", 13.5, NAVY, 12, 5),
        ("Heading 3", 11.5, BLUE_DARK, 8, 3),
    ):
        st = styles[name]
        st.font.name = "Segoe UI"
        st._element.rPr.rFonts.set(qn("w:ascii"), "Segoe UI")
        st._element.rPr.rFonts.set(qn("w:hAnsi"), "Segoe UI")
        st.font.size = Pt(size)
        st.font.color.rgb = rgb(color)
        st.font.bold = name != "Subtitle"
        st.paragraph_format.space_before = Pt(before)
        st.paragraph_format.space_after = Pt(after)
        st.paragraph_format.keep_with_next = True

    for sec in doc.sections:
        header = sec.header
        p = header.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        r = p.add_run("CONTROLIA COBRANZAS  |  MANUAL DE USUARIO")
        set_run(r, 8, BLUE_DARK, True)
        footer = sec.footer
        page_number(footer.paragraphs[0])


def title(doc, text, subtitle=None):
    p = doc.add_paragraph(style="Heading 1")
    p.add_run(text)
    if subtitle:
        q = doc.add_paragraph()
        q.paragraph_format.space_after = Pt(8)
        set_run(q.add_run(subtitle), 10, MUTED, italic=True)
    return p


def h2(doc, text):
    return doc.add_paragraph(text, style="Heading 2")


def h3(doc, text):
    return doc.add_paragraph(text, style="Heading 3")


def para(doc, text, bold_lead=None):
    p = doc.add_paragraph()
    if bold_lead and text.startswith(bold_lead):
        set_run(p.add_run(bold_lead), bold=True)
        p.add_run(text[len(bold_lead):])
    else:
        p.add_run(text)
    return p


def bullet(doc, text, level=0):
    p = doc.add_paragraph(style="List Bullet" if level == 0 else "List Bullet 2")
    p.paragraph_format.left_indent = Inches(0.28 + 0.22 * level)
    p.paragraph_format.first_line_indent = Inches(-0.16)
    p.paragraph_format.space_after = Pt(3)
    p.add_run(text)
    return p


def step(doc, n, action, detail):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.32)
    p.paragraph_format.first_line_indent = Inches(-0.32)
    p.paragraph_format.space_after = Pt(5)
    set_run(p.add_run(f"{n}. "), 10.2, BLUE_DARK, True)
    set_run(p.add_run(action + ". "), 10.2, NAVY, True)
    p.add_run(detail)
    return p


def callout(doc, label, text, kind="info"):
    colors = {
        "info": (PALE, BLUE_DARK),
        "warn": ("FFF7ED", AMBER),
        "danger": ("FEF2F2", RED),
        "ok": ("ECFDF5", GREEN),
    }
    fill, accent = colors[kind]
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    set_table_geometry(table, [9360])
    cell = table.cell(0, 0)
    shade(cell, fill)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    set_run(p.add_run(label.upper() + "  "), 9.5, accent, True)
    set_run(p.add_run(text), 9.5, NAVY)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def table(doc, headers, rows, widths=None, font_size=8.7):
    t = doc.add_table(rows=1, cols=len(headers))
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    t.style = "Table Grid"
    if widths is None:
        widths = [9360 // len(headers)] * len(headers)
        widths[-1] += 9360 - sum(widths)
    hdr = t.rows[0]
    set_repeat_table_header(hdr)
    for i, text in enumerate(headers):
        shade(hdr.cells[i], BLUE)
        p = hdr.cells[i].paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        set_run(p.add_run(str(text)), font_size, WHITE, True)
    for row in rows:
        cells = t.add_row().cells
        cant_split(t.rows[-1])
        for i, value in enumerate(row):
            if len(t.rows) % 2 == 1:
                shade(cells[i], "F8FAFC")
            p = cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            set_run(p.add_run(str(value)), font_size, NAVY)
    set_table_geometry(t, widths)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)
    return t


def page_break(doc):
    doc.add_page_break()


def cover(doc: Document):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(32)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if LOGO.exists():
        imagen = p.add_run().add_picture(str(LOGO), width=Inches(1.35))
        # Texto alternativo para lectores de pantalla. Antes se agregaba en un
        # paso posterior que generaba una copia "_a11y" del documento; hacerlo
        # aqui deja el manual accesible desde el propio generador.
        imagen._inline.docPr.set("descr", "Logotipo de Controlia Cobranzas")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(20)
    set_run(p.add_run("MANUAL DE USUARIO"), 12, BLUE_DARK, True)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(8)
    set_run(p.add_run("Controlia Cobranzas"), 31, NAVY, True)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run("Guía completa para usuarios no técnicos"), 14, SLATE)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(34)
    set_run(p.add_run("Gestión de carteras · deudores · cobranzas · comunicaciones · conciliación"), 10, MUTED)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(72)
    set_run(p.add_run("Versión del manual: 1.2  |  Agosto de 2026  |  Aplicación 2.2.0"), 10, BLUE_DARK, True)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run("Documento de entrega de la aplicación"), 9.5, MUTED)
    callout(doc, "Uso previsto", "Este manual explica el uso cotidiano de la aplicación. No requiere conocimientos técnicos ni acceso al código fuente.", "info")
    page_break(doc)


def contents(doc):
    title(doc, "Contenido y ruta de aprendizaje")
    para(doc, "Puede leer el manual completo o comenzar por el capítulo correspondiente a su rol. Los nombres de botones y pestañas aparecen tal como se muestran en la aplicación.")
    sections = [
        ("1", "Conocer la aplicación", "Propósito, conceptos, interfaz, seguridad, acceso y trabajo sin conexión."),
        ("2", "Roles y permisos", "Qué puede ver y hacer cada perfil."),
        ("3", "Dashboard", "Indicadores, prioridades, filtros y acciones directas sobre la cola."),
        ("4", "Conciliación de Nóminas", "Comparación mensual y reporte Excel."),
        ("5", "Búsqueda de Deudores", "Carga, consulta, filtros y tareas."),
        ("6", "Ficha del deudor", "Gestiones, pagos, datos, correo y WhatsApp."),
        ("7", "Envíos Programados", "SMTP, plantillas, segmentación y envío masivo."),
        ("8", "Administración de carteras", "Asignaciones, reemplazos y limpiezas."),
        ("9", "Usuarios y recuperación", "Altas, roles, estados y contraseñas."),
        ("10", "Procedimientos por rol", "Rutinas recomendadas y controles."),
        ("11", "Solución de problemas", "Mensajes frecuentes y acciones seguras."),
        ("12", "Glosario y anexos", "Conceptos, formatos y lista de verificación."),
    ]
    table(doc, ["Capítulo", "Tema", "Qué encontrará"], sections, [900, 2700, 5760], 9)
    callout(doc, "Consejo", "Si es la primera vez que usa Controlia Cobranzas, revise primero los capítulos 1 y 2 y luego vaya al procedimiento de su rol en el capítulo 10.", "ok")
    page_break(doc)


def chapter_1(doc):
    title(doc, "1. Conocer la aplicación", "Qué resuelve Controlia Cobranzas y cómo orientarse en pantalla")
    h2(doc, "1.1 ¿Para qué sirve Controlia Cobranzas?")
    para(doc, "Controlia Cobranzas centraliza el trabajo operativo de cobranza en una sola aplicación de escritorio. Permite controlar carteras por compañía, consultar deudores, registrar gestiones y pagos, preparar comunicaciones, comparar nóminas mensuales y observar indicadores de productividad.")
    bullet(doc, "Evita trabajar con información dispersa en múltiples planillas.")
    bullet(doc, "Mantiene trazabilidad de gestiones, pagos, asignaciones y sesiones.")
    bullet(doc, "Restringe información y acciones según el rol y la cartera asignada.")
    bullet(doc, "Genera reportes Excel para conciliación, gestiones y actividad.")
    h2(doc, "1.2 Conceptos básicos")
    table(doc, ["Concepto", "Explicación sencilla"], [
        ("Cartera", "Conjunto de deudores asociado a una compañía, por ejemplo Colmena, Consalud, Cruz Blanca o Cart-56."),
        ("Deudor", "Persona o registro cuya deuda y datos de contacto se gestionan en la aplicación."),
        ("Expediente / licencia", "Detalle individual que compone la deuda de un deudor. Un deudor puede tener más de uno."),
        ("Gestión", "Contacto o acción registrada: email, llamada, carta, WhatsApp, pago u otra."),
        ("Estado deudor", "Situación vigente calculada desde la gestión más reciente: Sin Gestión, Gestionado, Contactado, Inubicable, etc."),
        ("Conciliación", "Comparación entre la nómina del mes anterior y la del mes actual para detectar altas, bajas, coincidencias y duplicados."),
        ("Plantilla", "Texto reutilizable de correo con variables que se completan automáticamente."),
    ], [1900, 7460], 9)
    h2(doc, "1.3 Estructura de la ventana principal")
    table(doc, ["Zona", "Uso"], [
        ("Barra superior", "Muestra el usuario y rol, el estado de sincronización, acceso a Notificaciones, Recuperaciones cuando corresponde y Cerrar sesión."),
        ("Pestañas principales", "Permiten cambiar de módulo. Las pestañas visibles dependen del rol."),
        ("Área central", "Contiene tarjetas, filtros, tablas, formularios y resultados del módulo seleccionado."),
        ("Menú legal", "Permite volver a consultar Términos y Condiciones y Política de Privacidad."),
    ], [1900, 7460], 9)
    callout(doc, "Importante", "Si una función descrita no aparece en su pantalla, normalmente se debe a los permisos de su rol o a que la cartera no está asignada a su usuario.", "warn")
    h2(doc, "1.4 Inicio de sesión")
    step(doc, 1, "Abra Controlia Cobranzas", "Espere a que aparezca la ventana de acceso.")
    step(doc, 2, "Ingrese su correo", "Use el correo asociado a su cuenta. Puede conservarlo en el equipo si la opción de recordarlo está disponible.")
    step(doc, 3, "Ingrese su contraseña", "Respete mayúsculas, minúsculas y caracteres especiales.")
    step(doc, 4, "Pulse Iniciar sesión", "La aplicación validará la cuenta y abrirá los módulos autorizados.")
    h3(doc, "Primer ingreso con contraseña temporal")
    para(doc, "Cuando un administrador crea o restablece una cuenta, entrega una contraseña temporal. En el primer ingreso la aplicación obliga a crear una contraseña personal antes de continuar.")
    bullet(doc, "No comparta la contraseña temporal ni la definitiva.")
    bullet(doc, "Use una contraseña distinta de la que emplea en servicios personales.")
    bullet(doc, "Si el sistema informa que la cuenta está inactiva, contacte al administrador.")
    h2(doc, "1.5 Aceptación de documentos legales")
    para(doc, "Cuando existe una versión nueva de los Términos y Condiciones o de la Política de Privacidad, se abre una ventana obligatoria. Lea ambas pestañas y pulse Aceptar y continuar. Si elige Salir, la aplicación se cerrará sin habilitar el trabajo.")
    table(doc, ["Documento", "Versión vigente", "Dónde consultarlo"], [
        ("Términos y Condiciones", "v1.0", "Menú legal de la barra superior, en cualquier momento."),
        ("Política de Privacidad y Confidencialidad", "v2.0", "Menú legal y también durante la instalación, antes de instalar."),
    ], [3000, 1700, 4660], 8.8)
    para(doc, "La aceptación queda registrada con el usuario, la fecha y la versión del documento. Si se publica una versión posterior, la aplicación volverá a solicitar la aceptación aunque usted ya haya aceptado la anterior.")
    h2(doc, "1.6 Cierre seguro")
    para(doc, "Para terminar, pulse Cerrar sesión en la barra superior. Esto registra el término de la sesión y vuelve a la pantalla de acceso. Evite dejar la aplicación abierta en un equipo compartido.")
    h2(doc, "1.7 Si se corta la conexión")
    para(doc, "La aplicación necesita conexión con el servidor para trabajar. Si Internet se cae o el servidor deja de responder mientras usted registra una gestión manual, el trabajo no se pierde: queda guardado en el equipo y se envía solo cuando el servicio vuelve.")
    table(doc, ["Lo que verá", "Qué significa", "Qué hacer"], [
        ("Mensaje Gestión guardada sin conexión", "La gestión quedó en este equipo, todavía no llegó al servidor.", "Continúe trabajando con normalidad. No la registre de nuevo."),
        ("Aviso N por sincronizar", "Hay gestiones esperando que vuelva la conexión.", "Nada. El número baja solo a medida que se envían."),
        ("Aviso N sin enviar", "El servidor rechazó una gestión y no se reintentará sola.", "Informe al Administrador con la fecha y el RUT antes de volver a registrarla."),
    ], [2600, 3500, 3260], 8.4)
    callout(doc, "No duplique el registro", "Una gestión guardada sin conexión ya está registrada. Volver a ingresarla genera dos gestiones para el mismo contacto y distorsiona los indicadores de la cartera.", "warn")
    para(doc, "Mientras no hay conexión, la consulta de deudores y el envío de correos no están disponibles, porque esa información vive en el servidor. Vuelven a funcionar en cuanto se restablece el servicio.")
    page_break(doc)


def chapter_2(doc):
    title(doc, "2. Roles y permisos", "Acceso efectivo según Administrador, Supervisor o Ejecutivo")
    h2(doc, "2.1 Matriz de acceso a módulos")
    table(doc, ["Módulo / función", "Administrador", "Supervisor", "Ejecutivo"], [
        ("Dashboard: Mi trabajo y Vista general", "Sí", "Sí", "Sí"),
        ("Conciliación de Nóminas", "Sí", "Sí", "No"),
        ("Búsqueda de Deudores", "Sí", "Sí", "Consulta todas; opera solo las asignadas"),
        ("Cargar base de deudores", "Sí", "Sí", "No"),
        ("Cargar / exportar gestiones", "Sí", "Sí", "No"),
        ("Envíos: Configuración SMTP", "Sí", "Sí", "Sí"),
        ("Envíos: Plantillas", "Sí", "Sí", "Sí"),
        ("Envío masivo", "No visible", "Sí", "No visible"),
        ("Administración de carteras", "Sí", "Sí", "No"),
        ("Gestión de usuarios", "Sí", "No", "No"),
        ("Recuperaciones pendientes", "Sí", "Sí, según ámbito", "No"),
    ], [3660, 1900, 1900, 1900], 8.1)
    h2(doc, "2.2 Administrador")
    para(doc, "Es el perfil de mayor alcance. Administra usuarios, puede asignar carteras, ejecutar acciones de limpieza, cargar información y consultar los módulos de control. Debe usar con especial cuidado las funciones que eliminan datos.")
    h2(doc, "2.3 Supervisor")
    para(doc, "Coordina la operación. Puede conciliar nóminas, cargar bases y gestiones, asignar o reemplazar responsables de cartera, utilizar el envío masivo y consultar productividad. No puede administrar usuarios.")
    h2(doc, "2.4 Ejecutivo")
    para(doc, "Trabaja la cobranza diaria. Puede consultar la ficha de cualquier deudor, incluso de una cartera que no tenga asignada, para atender una llamada y derivar el caso. En cambio, las acciones operativas -registrar gestión o pago- quedan limitadas a sus carteras asignadas y a los reemplazos temporales vigentes. No puede cargar bases ni usar módulos administrativos.")
    callout(doc, "Seguridad por cartera", "Una ejecutiva sin cartera asignada verá el mensaje Sin carteras asignadas. Un supervisor o administrador debe realizar la asignación; cerrar sesión y volver a ingresar ayuda a actualizar el alcance.", "warn")
    h2(doc, "2.5 Acciones sensibles")
    bullet(doc, "Eliminar deudor: borra el registro y sus gestiones asociadas.")
    bullet(doc, "Limpiar una empresa o todas las cargas: elimina datos importados, no solo la vista.")
    bullet(doc, "Limpiar gestiones: elimina el historial de gestiones del sistema.")
    bullet(doc, "Reiniciar datos de prueba: limpia cargas, gestiones y asignaciones.")
    bullet(doc, "Revertir pagos confirmados: está reservado al Supervisor.")
    callout(doc, "Regla de control", "Antes de confirmar una eliminación, verifique compañía, RUT y alcance. La confirmación de pantalla es la última barrera antes de ejecutar la acción.", "danger")
    page_break(doc)


def chapter_3(doc):
    title(doc, "3. Dashboard", "Lectura de la cartera, prioridades y productividad")
    h2(doc, "3.1 Cambiar entre Mi trabajo y Vista general")
    para(doc, "En la parte superior del Dashboard se encuentran dos modos. Mi trabajo prioriza la gestión diaria; Vista general muestra la lectura consolidada. El perfil Ejecutivo abre por defecto Mi trabajo y los perfiles de coordinación abren Vista general.")
    h2(doc, "3.2 Mi trabajo")
    table(doc, ["Elemento", "Qué indica / cómo usarlo"], [
        ("Salud operativa", "Resumen automático del estado de la cartera visible."),
        ("Foco del día", "Recomendación de atención inmediata basada en datos disponibles."),
        ("Alertas críticas", "Acceso rápido a casos que requieren prioridad."),
        ("Oportunidades de contacto", "Casos con canales de contacto disponibles."),
        ("Colas inteligentes", "Agrupaciones de trabajo calculadas para orientar la jornada."),
        ("Filtros de trabajo", "Búsqueda libre, compañía, estado, antigüedad, saldo y disponibilidad de contacto."),
        ("Cola priorizada", "Lista ordenada de casos; muestra RUT, estado, motivo de prioridad, saldo y antigüedad."),
        ("Embudo de cartera", "Distribución de deudores por estado."),
    ], [2250, 7110], 8.8)
    h3(doc, "Filtros de antigüedad")
    bullet(doc, "Nunca gestionados; 0 a 6 días; 7 a 13 días; 14 a 29 días; 30 días o más.")
    h3(doc, "Filtros de saldo")
    bullet(doc, "Menos de $500.000; entre $500.000 y $2.000.000; más de $2.000.000.")
    h3(doc, "Filtros de contacto")
    bullet(doc, "Algún canal disponible; teléfono y email; sin datos de contacto.")
    step(doc, 1, "Defina los filtros", "Seleccione los criterios que representen el objetivo del día.")
    step(doc, 2, "Revise la cola", "Comience por los casos con mayor prioridad y saldo relevante.")
    step(doc, 3, "Abra el caso", "Haga clic sobre la fila para desplegar los datos de contacto y las acciones disponibles.")
    step(doc, 4, "Registre el resultado", "Toda llamada, mensaje, pago o acuerdo debe quedar como gestión.")
    h2(doc, "3.3 Acciones directas sobre un caso de la cola")
    para(doc, "Al hacer clic sobre una fila de la cola priorizada se despliegan el RUT, el último estado, el teléfono, el correo, la dirección y la cartera, junto con los botones de acción. Los botones de contacto aparecen solo cuando el deudor tiene ese canal disponible; Registrar gestión está siempre disponible.")
    table(doc, ["Botón", "Qué hace"], [
        ("Enviar email", "Abre la ventana Correo al deudor, con las mismas opciones que la ficha del deudor: plantilla, tipo de envío, trabajador/licencia, vista previa, envío de correo y envío por WhatsApp."),
        ("Registrar gestión", "Abre el formulario Agregar gestión manual del deudor: tipo, estado, fecha y observación."),
        ("Llamar / Generar carta", "Muestran un aviso con el caso seleccionado. El teléfono y la dirección para trabajarlos fuera de la aplicación están en el detalle desplegado de la fila."),
    ], [2000, 7360], 8.8)
    h3(doc, "Enviar un correo desde la cola")
    step(doc, 1, "Pulse Enviar email", "Se abre Correo al deudor con el nombre, el RUT y los expedientes del caso.")
    step(doc, 2, "Seleccione plantilla y tipo de envío", "Individual usa un trabajador/licencia; Consolidado reúne todas las licencias del deudor.")
    step(doc, 3, "Revise el destino", "Si aparece Sin correo disponible, corrija los datos del cliente antes de continuar.")
    step(doc, 4, "Use Vista previa", "Confirme Para, Asunto y el detalle antes de enviar.")
    step(doc, 5, "Pulse Enviar email", "Si la sesión SMTP no está activa, la aplicación solicita únicamente la contraseña del servidor.")
    para(doc, "El envío queda registrado automáticamente como gestión Email / Enviado y la cola se recalcula al cerrar la ventana. Los detalles de plantillas, variables y resultados están en el capítulo 6.")
    h3(doc, "Registrar una gestión desde la cola")
    para(doc, "El botón Registrar gestión abre exactamente el mismo formulario descrito en la sección 6.3, con Tipo, Estado, Fecha y Observación. Al guardar, la prioridad y la antigüedad del caso se actualizan en la cola.")
    callout(doc, "Cartera no asignada", "Si la cartera del deudor no está asignada a su usuario, dentro de la ventana Correo al deudor los botones de vista previa y envío aparecen deshabilitados con el aviso Bloqueado: cartera no asignada a tu usuario. En ese caso use Asignar tarea desde la ficha del deudor para derivar el caso a la ejecutiva responsable.", "warn")
    h2(doc, "3.4 Vista general")
    table(doc, ["Indicador", "Interpretación"], [
        ("Cartera total", "Cantidad de deudores visibles en el período."),
        ("Saldo actual", "Suma de saldos pendientes."),
        ("Cobertura de gestión", "Proporción de la cartera que registra gestiones."),
        ("Gestiones hoy", "Acciones registradas durante la fecha actual."),
        ("Conexiones hoy / del mes", "Actividad de acceso al sistema."),
        ("Ejecutivas activas", "Usuarios ejecutivos únicos con actividad."),
        ("Duración promedio", "Tiempo medio de sesiones cerradas calculables."),
    ], [2250, 7110], 8.8)
    para(doc, "Seleccione el período disponible y pulse Actualizar para recalcular los indicadores. El Supervisor puede usar Descargar Excel mensual para obtener el reporte de conexiones de ejecutivas.")
    callout(doc, "Lectura responsable", "Los indicadores reflejan la información cargada y visible para la sesión. Si una cartera, gestión o asignación aún no está disponible, el Dashboard puede mostrar valores parciales o el mensaje Sin datos.", "info")
    page_break(doc)


def chapter_4(doc):
    title(doc, "4. Conciliación de Nóminas", "Comparar el mes anterior con el mes actual y generar un reporte")
    h2(doc, "4.1 Objetivo")
    para(doc, "Este módulo compara dos archivos Excel de una misma compañía. Construye un identificador con las dos primeras columnas de la hoja DETALLE —normalmente RUT y DV— y clasifica los registros que aparecen solo en un mes, en ambos o duplicados.")
    h2(doc, "4.2 Requisitos de los archivos")
    bullet(doc, "Formato .xlsx y hoja llamada DETALLE.")
    bullet(doc, "La hoja no debe estar vacía y debe contener al menos dos columnas.")
    bullet(doc, "Los dos archivos deben pertenecer a la misma compañía y usar una estructura comparable.")
    bullet(doc, "Cierre el archivo de salida en Excel antes de generar o reemplazar el reporte.")
    h2(doc, "4.3 Procedimiento")
    step(doc, 1, "Seleccione la compañía", "Elija Colmena, Consalud, Cruz Blanca o Cart-56.")
    step(doc, 2, "Seleccione Mes Anterior", "Busque el archivo de origen correspondiente al período anterior.")
    step(doc, 3, "Seleccione Mes Actual", "Busque la nómina vigente.")
    step(doc, 4, "Defina Guardar como", "Elija una carpeta y un nombre para resultado_conciliacion.xlsx o el nombre que prefiera.")
    step(doc, 5, "Revise las opciones", "Active la exportación de coincidencias solo si necesita las pestañas En ambos.")
    step(doc, 6, "Pulse Ejecutar conciliación", "Observe el progreso y no cierre la aplicación durante el proceso.")
    step(doc, 7, "Abra el reporte", "Confirme que el estado indique conciliación finalizada y revise la ruta mostrada.")
    h2(doc, "4.4 Contenido del reporte")
    table(doc, ["Hoja", "Contenido"], [
        ("RESUMEN", "Filas, IDs únicos, altas, bajas, coincidencias y duplicados de ambos meses."),
        ("Solo_en_Anterior", "Registros que estaban antes y no aparecen en el mes actual: bajas potenciales."),
        ("Solo_en_Actual", "Registros nuevos del mes actual: altas potenciales."),
        ("Duplicados_Anterior", "Filas cuyo identificador está repetido en el mes anterior."),
        ("Duplicados_Actual", "Filas cuyo identificador está repetido en el mes actual."),
        ("En_ambos_Anterior / Actual", "Coincidencias, solo cuando se activó la opción correspondiente."),
    ], [2500, 6860], 8.8)
    callout(doc, "Control previo", "Una conciliación identifica diferencias; no modifica las bases de deudores. Revise duplicados antes de interpretar altas o bajas como definitivas.", "info")
    h2(doc, "4.5 Nueva conciliación")
    para(doc, "Pulse Nueva conciliación para limpiar rutas, resultados y estado del proceso. Esto no borra reportes ya guardados en el equipo.")
    page_break(doc)


def chapter_5(doc):
    title(doc, "5. Búsqueda de Deudores", "Carga, consulta, filtros, gestiones importadas y tareas")
    h2(doc, "5.1 Finalidad del módulo")
    para(doc, "Es el centro de consulta operativa. Muestra la base de deudores, permite buscar por texto o columna, filtrar por compañía y abrir la ficha detallada. Los administradores y supervisores también pueden cargar bases y gestiones y exportar información.")
    h2(doc, "5.2 Cargar una base de deudores")
    step(doc, 1, "Seleccione la compañía", "La compañía elegida determina la estructura esperada y el destino de la carga.")
    step(doc, 2, "Pulse Seleccionar", "Busque el archivo Excel .xlsx.")
    step(doc, 3, "Pulse Cargar base", "La aplicación leerá, validará y preparará los datos.")
    step(doc, 4, "Asocie columnas si se solicita", "En la ventana Asociar columnas del archivo Excel, vincule cada campo requerido con la columna correcta y continúe con la vista previa.")
    step(doc, 5, "Revise la vista previa", "Confirme compañía, cantidad y datos principales antes de aceptar la carga.")
    step(doc, 6, "Espere el resultado", "La tabla y el Dashboard se actualizarán cuando finalice.")
    callout(doc, "Duplicados", "La aplicación puede bloquear una base ya cargada aunque el archivo tenga otro nombre, si detecta el mismo contenido. Revise el período y evite insistir con copias idénticas.", "warn")
    h2(doc, "5.3 Buscar y filtrar")
    table(doc, ["Control", "Uso"], [
        ("Buscar", "Escriba RUT, nombre u otro valor visible. Los resultados cambian mientras escribe."),
        ("Compañía", "Muestra Todas o una compañía específica. El Ejecutivo puede consultar cualquier cartera, pero solo gestiona las asignadas."),
        ("Columna", "Limita la búsqueda a una columna; Todas las columnas busca de forma global."),
        ("X / limpiar", "Borra el texto de búsqueda y vuelve al conjunto filtrado por compañía."),
        ("Tabla", "Haga doble clic o use la acción disponible para abrir el detalle del deudor."),
    ], [2000, 7360], 8.8)
    h2(doc, "5.4 Cargar gestiones desde Excel")
    para(doc, "La carga de gestiones admite un libro con hojas SMS, Email y Carta. Cada fila utiliza RUT, nombre, estado, fecha y observación. Los registros idénticos ya existentes se omiten para evitar duplicación.")
    step(doc, 1, "Descargue la plantilla", "Use Descargar plantilla para trabajar con la estructura correcta.")
    step(doc, 2, "Complete las hojas aplicables", "No cambie los encabezados. Deje las hojas sin uso vacías si corresponde.")
    step(doc, 3, "Seleccione el archivo", "Pulse Seleccionar en la tarjeta de carga de gestiones.")
    step(doc, 4, "Pulse Cargar gestiones", "Revise el resumen de insertados, omitidos y errores.")
    h2(doc, "5.5 Descargar gestiones")
    para(doc, "Defina Desde y Hasta y pulse Descargar Excel. El rango permite acotar la salida; use un rango amplio cuando necesite una exportación completa.")
    h2(doc, "5.6 Mis tareas — perfil Ejecutivo")
    para(doc, "La tarjeta de tareas muestra Realizada, RUT, Nombre y Plazo. Pulse Actualizar para obtener la lista vigente. Seleccione la tarea completada y pulse Gestión realizada para cerrarla.")
    callout(doc, "Trazabilidad", "Cerrar una tarea no reemplaza el registro de la gestión. Abra el deudor y registre también el contacto, acuerdo o resultado obtenido.", "info")
    page_break(doc)


def chapter_6(doc):
    title(doc, "6. Ficha del deudor", "Datos del cliente, deuda, gestiones, pagos y comunicaciones")
    h2(doc, "6.1 Qué muestra la ficha")
    table(doc, ["Área", "Contenido"], [
        ("Encabezado", "Nombre, RUT y cantidad de expedientes."),
        ("Datos del cliente", "Correo, teléfonos, dirección, comuna, ciudad y otros campos disponibles."),
        ("Resumen financiero", "Copago, pagos acumulados y saldo actual."),
        ("Detalle de deuda", "Expedientes, licencias o conceptos asociados, con montos y fechas."),
        ("Gestiones", "Historial por tipo, estado, fecha, observación y origen."),
        ("Comunicaciones", "Plantilla, tipo de envío, vista previa, correo y WhatsApp."),
    ], [2050, 7310], 8.8)
    h2(doc, "6.2 Editar datos del cliente")
    para(doc, "Cuando el botón Editar datos del cliente esté habilitado, puede corregir RUT, nombre, correos, teléfonos, dirección, comuna y ciudad. Revise cuidadosamente el correo y teléfono porque se utilizarán para comunicaciones.")
    step(doc, 1, "Pulse Editar datos del cliente", "Se abrirá un formulario con los valores actuales.")
    step(doc, 2, "Corrija únicamente lo necesario", "No elimine datos válidos que no pretende modificar.")
    step(doc, 3, "Pulse Guardar cambios", "Espere la confirmación antes de cerrar la ficha.")
    h2(doc, "6.3 Agregar una gestión manual")
    para(doc, "Este mismo formulario se abre con el botón Registrar gestión de la cola priorizada del Dashboard, descrito en la sección 3.3.")
    step(doc, 1, "Pulse Agregar gestión manual", "Se abrirá el formulario del deudor actual.")
    step(doc, 2, "Seleccione Tipo", "Opciones: SMS, Email, Carta, Manual, Llamada, Visita, WhatsApp, Pago u Otro.")
    step(doc, 3, "Seleccione Estado", "Use el resultado que describa lo ocurrido, por ejemplo Sin Respuesta, Respondido, Acuerdo de pago, Promesa de pago o Cliente Sin deuda.")
    step(doc, 4, "Defina Fecha", "Use la fecha real de la acción.")
    step(doc, 5, "Escriba la observación", "Registre información útil, objetiva y sin datos personales innecesarios.")
    step(doc, 6, "Pulse Guardar", "La gestión aparecerá en el historial y podrá actualizar el estado del deudor.")
    h3(doc, "Eliminar una gestión")
    para(doc, "Solo se pueden eliminar gestiones de origen manual. Seleccione la fila y pulse Eliminar manual. Los registros provenientes de Excel o integraciones se conservan. Los pagos confirmados tienen controles adicionales; solo el Supervisor puede revertirlos.")
    h2(doc, "6.4 Registrar un pago")
    step(doc, 1, "Pulse Registrar pago", "Revise el saldo actual mostrado.")
    step(doc, 2, "Seleccione expediente o destino", "Elija a qué expediente, licencia o concepto se aplicará.")
    step(doc, 3, "Seleccione el tipo", "Abono a la deuda o Pago total de la deuda.")
    step(doc, 4, "Indique distribución", "Active Distribuir el pago entre varios conceptos si necesita repartir el monto y complete Monto a aplicar por fila.")
    step(doc, 5, "Ingrese monto y fecha efectiva", "El monto debe ser positivo y coherente con el saldo.")
    step(doc, 6, "Añada observaciones", "Incluya referencia, forma de pago, número de operación o antecedente del comprobante recibido.")
    step(doc, 7, "Pulse Registrar pago", "Revise la confirmación y los nuevos valores de Pagos y Saldo Actual.")
    callout(doc, "Antes de confirmar", "Compruebe RUT, compañía, expediente, fecha y monto. Un pago mal asignado afecta saldos y reportes; la reversa está restringida al Supervisor.", "danger")
    h2(doc, "6.5 Asignar una tarea")
    para(doc, "Cuando una cartera no pueda ser gestionada directamente por el usuario, el botón Asignar tarea permite derivarla a la ejecutiva responsable. Seleccione la ejecutiva disponible para esa compañía, defina plazo y escriba una observación clara.")
    h2(doc, "6.6 Vista previa y envío de correo individual")
    para(doc, "Estas mismas opciones están disponibles sin abrir la ficha, con el botón Enviar email de la cola priorizada del Dashboard (sección 3.3).")
    step(doc, 1, "Seleccione la plantilla", "Elija el texto apropiado para el objetivo del contacto.")
    step(doc, 2, "Seleccione el tipo de envío", "Individual usa un trabajador/licencia; Consolidado reúne todas las licencias del deudor.")
    step(doc, 3, "Revise el destino", "Si aparece Sin correo disponible, corrija los datos antes de continuar.")
    step(doc, 4, "Pulse Vista previa", "Revise Para, Asunto, montos, nombre, empresa y detalle de licencias.")
    step(doc, 5, "Pulse Enviar email", "Si la sesión SMTP no está activa, la aplicación puede solicitar la contraseña.")
    para(doc, "El resultado del envío queda registrado como gestión Enviado o Fallido. No repita el envío sin revisar el historial.")
    h2(doc, "6.7 Enviar WhatsApp")
    para(doc, "Verifique el número mostrado en Destino y pulse Enviar WhatsApp. La aplicación abre el canal disponible con el mensaje preparado. Confirme el destinatario antes de enviarlo y registre el resultado de la conversación.")
    h2(doc, "6.8 Estados y efecto operativo")
    table(doc, ["Estado de gestión", "Estado deudor resultante habitual"], [
        ("Respondido / Contactado", "Contactado"),
        ("No Entregado", "Inubicable"),
        ("Enviado / Entregado / Sin Respuesta", "Gestionado"),
        ("Birlado", "Birlado"),
        ("CIP Con intención de pago", "CIP Con intención de pago"),
        ("SIP Sin intención de pago", "SIP Sin intención de pago"),
        ("Fallecido", "Fallecido"),
        ("Cliente Sin deuda", "Cliente Sin deuda"),
    ], [3800, 5560], 8.6)
    page_break(doc)


def chapter_7(doc):
    title(doc, "7. Envíos Programados", "Configuración SMTP, plantillas y campañas masivas")
    h2(doc, "7.1 Configuración SMTP")
    para(doc, "SMTP es el servicio utilizado para enviar correos. La aplicación permite escoger un proveedor preconfigurado o completar host, puerto, STARTTLS, usuario, contraseña y nombre del remitente.")
    table(doc, ["Campo", "Qué ingresar"], [
        ("Proveedor / preset", "El proveedor de correo utilizado por la organización."),
        ("Host", "Servidor SMTP entregado por el proveedor."),
        ("Puerto", "Puerto recomendado por el proveedor, normalmente asociado a STARTTLS."),
        ("Usar STARTTLS", "Manténgalo activo cuando así lo requiera el proveedor."),
        ("Usuario", "Cuenta de correo remitente."),
        ("Contraseña", "Contraseña o clave de aplicación. Se usa en la sesión y no se guarda en disco."),
        ("Nombre remitente", "Nombre visible para los destinatarios, por ejemplo Controlia Cobranzas."),
    ], [2200, 7160], 8.7)
    step(doc, 1, "Complete los datos", "Use la información autorizada por su organización.")
    step(doc, 2, "Pulse Probar conexión", "Espere el mensaje de conexión correcta.")
    step(doc, 3, "Pulse Guardar configuración", "Se guardan los datos no sensibles; la contraseña no se almacena.")
    callout(doc, "Privacidad", "Nunca escriba contraseñas SMTP en plantillas, observaciones, archivos Excel ni capturas de soporte.", "danger")
    h2(doc, "7.2 Plantillas")
    para(doc, "Las plantillas contienen Nombre, Asunto y Cuerpo. Los botones Nueva plantilla, Eliminar y Guardar plantilla están disponibles para roles autorizados. Una variable entre llaves se reemplaza con datos del deudor al generar el mensaje.")
    table(doc, ["Variable", "Valor que inserta"], [
        ("{nombre}", "Nombre del deudor"), ("{rut}", "RUT"), ("{saldo}", "Saldo pendiente en formato monetario"),
        ("{copago}", "Copago original"), ("{total_pagos}", "Pagos acumulados"), ("{empresa}", "Compañía"),
        ("{nro_expediente}", "Número de expediente"), ("{No_Licencia}", "Número de licencia Cart-56"),
        ("{detalle_licencias}", "Detalle consolidado de licencias o folios"),
        ("{primera_emision} / {ultima_emision}", "Fechas de primera y última emisión"),
    ], [3000, 6360], 8.4)
    callout(doc, "Buena práctica", "Use Vista previa antes de enviar. Si una variable permanece entre llaves, el dato no estaba disponible o el nombre de la variable no es válido.", "warn")
    h2(doc, "7.3 Envío masivo — solo Supervisor")
    h3(doc, "Preparar el segmento")
    step(doc, 1, "Elija la compañía", "Seleccione Todas las compañías o una cartera específica.")
    step(doc, 2, "Defina calidad de destinatarios", "Mantenga Solo emails válidos y active Excluir emails ya enviados en esta carga cuando corresponda.")
    step(doc, 3, "Seleccione Estado deudor", "Filtre por la situación que desea trabajar.")
    step(doc, 4, "Seleccione la métrica de monto", "Aplique mínimo, máximo o priorización de montos altos.")
    step(doc, 5, "Use Top montos si corresponde", "Active la opción e indique cuántos destinatarios de mayor monto incluir.")
    step(doc, 6, "Pulse Cargar destinatarios filtrados", "Revise el resumen de campaña y la cantidad total.")
    h3(doc, "Seleccionar mensaje y ejecutar")
    step(doc, 7, "Seleccione la plantilla", "Revise la vista previa del asunto.")
    step(doc, 8, "Seleccione modo", "Individual (actual) o Consolidado (todas las licencias).")
    step(doc, 9, "Defina la pausa", "Una pausa entre envíos reduce bloqueos del proveedor y evita una ráfaga excesiva.")
    step(doc, 10, "Pulse Iniciar envío", "Controle progreso, enviados, no enviados, sin email y pendientes.")
    step(doc, 11, "Revise el log", "Cada destinatario muestra Email, Nombre, Estado y Detalle.")
    para(doc, "Cancelar envío detiene los pendientes, pero no recupera mensajes que ya fueron enviados. Limpiar log limpia la visualización de la campaña; no borra correos ya despachados ni gestiones registradas.")
    callout(doc, "Control de campaña", "Antes de iniciar, valide segmento, cantidad, plantilla, asunto, modo y cuenta remitente. Haga una prueba controlada cuando cambie una plantilla o configuración SMTP.", "danger")
    page_break(doc)


def chapter_8(doc):
    title(doc, "8. Administración de carteras", "Asignaciones, reemplazos, limpieza y bitácora")
    h2(doc, "8.1 Alcance")
    para(doc, "Este módulo restringido está disponible para Administrador y Supervisor. Centraliza acciones sensibles sobre cargas, gestiones y responsables de cartera. La bitácora inferior registra las operaciones ejecutadas desde la pantalla con fecha y hora.")
    h2(doc, "8.2 Asignar carteras")
    step(doc, 1, "Ubique la compañía", "Cada compañía tiene una lista de ejecutivos activos.")
    step(doc, 2, "Seleccione responsable", "Elija el ejecutivo o Sin asignación.")
    step(doc, 3, "Revise todas las compañías", "Evite sobrescribir por error una asignación existente.")
    step(doc, 4, "Pulse Guardar asignaciones", "Espere el mensaje de confirmación.")
    para(doc, "La asignación controla la información que ve y opera el Ejecutivo. Cuando cambie, solicite al usuario cerrar sesión y volver a ingresar.")
    h2(doc, "8.3 Reemplazos temporales")
    para(doc, "Un reemplazo entrega acceso operativo durante un intervalo definido sin compartir credenciales ni cambiar permanentemente la asignación titular.")
    step(doc, 1, "Seleccione cartera", "Elija la compañía del titular ausente.")
    step(doc, 2, "Seleccione reemplazante", "Debe ser una ejecutiva activa.")
    step(doc, 3, "Defina inicio y término", "Use fechas y horas que cubran únicamente el período necesario.")
    step(doc, 4, "Indique motivo", "Ejemplo: vacaciones o licencia, sin incorporar información médica sensible.")
    step(doc, 5, "Pulse Crear reemplazo temporal", "Revise la nueva fila y su estado Activo.")
    para(doc, "Para terminar antes de plazo, seleccione la fila activa y pulse Finalizar reemplazo seleccionado. Un reemplazo finalizado no puede finalizarse nuevamente.")
    h2(doc, "8.4 Limpieza controlada")
    table(doc, ["Acción", "Efecto", "Cuándo usar"], [
        ("Eliminar deudor individual", "Borra el deudor de la compañía y sus gestiones asociadas.", "Corrección excepcional de un registro identificado por RUT."),
        ("Limpiar empresa", "Elimina todos los deudores cargados para una compañía.", "Reemplazo total de una carga errónea."),
        ("Limpiar todas las cargas", "Elimina cargas de deudores de todas las compañías.", "Solo con autorización y respaldo."),
        ("Limpiar gestiones", "Elimina todo el historial de gestiones.", "Uso excepcional y controlado."),
        ("Reiniciar datos de prueba", "Limpia deudores, gestiones y asignaciones.", "Ambientes de prueba; no para operación real."),
    ], [2300, 3400, 3660], 8.2)
    callout(doc, "Acción irreversible", "La bitácora confirma que una acción se ejecutó, pero no restaura los datos. Antes de limpiar, confirme que existe un respaldo válido y que el alcance fue autorizado.", "danger")
    h2(doc, "8.5 Bitácora administrativa")
    para(doc, "Use la bitácora para comprobar qué acción se ejecutó, cuándo y con qué alcance. Si una operación falla o informa Sin cambios, no la repita sin revisar el mensaje y los datos seleccionados.")
    page_break(doc)


def chapter_9(doc):
    title(doc, "9. Usuarios, notificaciones y recuperación", "Administración del acceso y mensajes operativos")
    h2(doc, "9.1 Gestión de usuarios — solo Administrador")
    para(doc, "La pestaña Usuarios lista cuentas, roles y estados. Permite crear usuarios, modificar su rol, activar o inactivar, restablecer contraseña y eliminar cuando las reglas de seguridad lo permiten.")
    h3(doc, "Crear usuario")
    step(doc, 1, "Pulse Nuevo usuario", "Se abrirá el formulario de alta.")
    step(doc, 2, "Complete datos", "Ingrese correo, nombre y la información solicitada con datos institucionales.")
    step(doc, 3, "Seleccione rol", "Administrador, Supervisor o Ejecutivo según responsabilidades reales.")
    step(doc, 4, "Pulse Crear usuario", "La aplicación generará una contraseña temporal.")
    step(doc, 5, "Copie la contraseña", "Use Copiar contraseña y entréguela por un canal seguro. El usuario deberá cambiarla al primer acceso.")
    h3(doc, "Cambiar rol o estado")
    para(doc, "Cambiar el rol modifica los módulos disponibles. Inactivar bloquea el inicio de sesión sin borrar el historial. Use esta opción para ausencias o término de funciones cuando se necesite conservar trazabilidad.")
    h3(doc, "Eliminar usuario")
    para(doc, "La eliminación requiere confirmación. La aplicación impide eliminar el último administrador, para evitar que el sistema quede sin capacidad de administración.")
    h2(doc, "9.2 Restablecer contraseña")
    para(doc, "El administrador puede restablecer una cuenta desde Usuarios. La aplicación muestra una nueva contraseña temporal que debe copiarse y entregarse de forma segura. El usuario creará una contraseña definitiva en el siguiente inicio.")
    h2(doc, "9.3 Recuperación asistida desde la pantalla de acceso")
    step(doc, 1, "Pulse ¿Olvidaste tu contraseña?", "Ingrese el correo de la cuenta.")
    step(doc, 2, "Solicite recuperación", "La petición será registrada para el rol autorizado.")
    step(doc, 3, "Espere la atención", "Un Administrador o Supervisor, según el ámbito mostrado, verá la solicitud en Recuperaciones.")
    step(doc, 4, "Use la contraseña temporal", "Al recibirla, ingrese y cree una nueva contraseña personal.")
    h2(doc, "9.4 Notificaciones")
    para(doc, "El botón Notificaciones puede mostrar avisos de derivaciones, tareas, ediciones u otros eventos operativos. Seleccione una notificación y pulse Marcar seleccionada como leída para ordenar la bandeja.")
    callout(doc, "No comparta credenciales", "Asignaciones y reemplazos existen precisamente para dar acceso sin compartir contraseñas. Cada persona debe utilizar su propia cuenta.", "danger")
    page_break(doc)


def chapter_10(doc):
    title(doc, "10. Procedimientos recomendados por rol", "Rutinas de trabajo claras y verificables")
    h2(doc, "10.1 Rutina del Ejecutivo")
    table(doc, ["Momento", "Acción recomendada", "Control final"], [
        ("Inicio", "Abrir Dashboard > Mi trabajo; revisar salud, foco, alertas y tareas.", "Confirmar que aparecen las carteras correctas."),
        ("Priorización", "Aplicar filtros por antigüedad, saldo y contacto; comenzar por la cola priorizada.", "Evitar saltar casos críticos sin dejar motivo."),
        ("Gestión", "Desplegar el caso en la cola y usar Enviar email o Registrar gestión; abrir la ficha del deudor cuando se necesite el detalle completo.", "Registrar tipo, estado, fecha y observación."),
        ("Pagos", "Registrar monto, fecha y expediente; dejar el respaldo en la observación.", "Validar nuevo saldo y pagos acumulados."),
        ("Cierre", "Cerrar tareas realizadas, revisar pendientes y cerrar sesión.", "No dejar la aplicación abierta."),
    ], [1350, 5260, 2750], 8.4)
    h2(doc, "10.2 Rutina del Supervisor")
    bullet(doc, "Revisar Vista general, conexiones, cobertura y gestiones del día.")
    bullet(doc, "Atender recuperaciones, notificaciones y derivaciones pendientes.")
    bullet(doc, "Comprobar asignaciones y reemplazos antes de la jornada.")
    bullet(doc, "Controlar cargas de deudores y gestiones; revisar duplicados y resultados.")
    bullet(doc, "Preparar campañas masivas con prueba previa, segmentación y revisión del log.")
    bullet(doc, "Revertir pagos solo con antecedente verificable y autorización interna.")
    h2(doc, "10.3 Rutina del Administrador")
    bullet(doc, "Gestionar altas, bajas, roles y cuentas inactivas con criterio de mínimo acceso necesario.")
    bullet(doc, "Mantener al menos dos administradores operativos cuando la política interna lo permita.")
    bullet(doc, "Revisar asignaciones y solicitudes de recuperación.")
    bullet(doc, "Autorizar y respaldar antes de cualquier limpieza de datos.")
    bullet(doc, "Verificar que las cuentas SMTP y configuraciones correspondan a servicios institucionales.")
    h2(doc, "10.4 Flujo mensual sugerido")
    step(doc, 1, "Respaldar", "Conservar archivos y respaldos autorizados antes de reemplazar información.")
    step(doc, 2, "Conciliar", "Comparar nómina anterior y actual; revisar altas, bajas y duplicados.")
    step(doc, 3, "Corregir origen", "Resolver inconsistencias en la planilla fuente, no mediante ediciones improvisadas posteriores.")
    step(doc, 4, "Cargar cartera", "Seleccionar compañía, validar vista previa y confirmar carga.")
    step(doc, 5, "Cargar gestiones", "Importar el archivo con hojas SMS, Email y Carta y revisar omitidos.")
    step(doc, 6, "Asignar", "Confirmar responsables y reemplazos vigentes.")
    step(doc, 7, "Validar Dashboard", "Comparar totales, saldos y cobertura con los controles internos.")
    callout(doc, "Principio operativo", "Toda acción relevante debe terminar con una comprobación visible: mensaje de éxito, cambio en la tabla, actualización del saldo, archivo exportado o registro en la bitácora.", "ok")
    page_break(doc)


def chapter_11(doc):
    title(doc, "11. Solución de problemas", "Qué revisar antes de solicitar soporte")
    table(doc, ["Situación", "Causa probable", "Qué hacer"], [
        ("Usuario o contraseña incorrectos", "Credencial errónea o correo distinto.", "Revise escritura; si persiste, solicite recuperación asistida."),
        ("Cuenta inactiva", "La cuenta fue deshabilitada.", "Contacte al Administrador; no cree otra cuenta para el mismo usuario."),
        ("Sesión expirada", "La conexión o token dejó de ser válido.", "Cierre sesión, vuelva a ingresar y repita solo la acción no confirmada."),
        ("Sin carteras asignadas", "El Ejecutivo no tiene cartera o reemplazo vigente.", "Solicite asignación y vuelva a iniciar sesión."),
        ("No aparece un módulo", "El rol no tiene permiso.", "Revise la matriz del capítulo 2; pida cambio de rol solo si corresponde."),
        ("Excel no contiene DETALLE", "Nombre de hoja incorrecto.", "Renombre o prepare una copia con la hoja esperada."),
        ("Columnas faltantes", "Encabezados distintos o campos obligatorios ausentes.", "Use Asociar columnas o corrija el archivo de origen."),
        ("Base duplicada", "El contenido ya fue cargado.", "Verifique período y no cargue una copia idéntica."),
        ("No se puede guardar Excel", "Archivo abierto, ruta sin permisos o nombre inválido.", "Cierre Excel y guarde en una carpeta autorizada."),
        ("Sin correo disponible", "El deudor no tiene email válido.", "Edite datos con una fuente autorizada o use otro canal."),
        ("Falla SMTP", "Host, puerto, STARTTLS, usuario o clave incorrectos.", "Revise configuración y pulse Probar conexión; use clave de aplicación si aplica."),
        ("Variable visible en el correo", "Dato ausente o variable mal escrita.", "Corrija la plantilla o complete el dato; vuelva a abrir la vista previa."),
        ("Pago no se refleja", "No se confirmó, fue rechazado o la vista está desactualizada.", "Revise mensaje, historial y actualice; no duplique el pago."),
        ("Tarea no aparece", "No está asignada, fue cerrada o la lista no se actualizó.", "Pulse Actualizar y revise notificaciones y cartera."),
        ("Gestión guardada sin conexión", "Se cortó Internet o el servidor no respondió.", "El trabajo quedó guardado en el equipo. No la registre de nuevo: se enviará sola al volver la conexión."),
        ("Aviso N sin enviar", "Una gestión en cola fue rechazada por el servidor.", "Informe al Administrador antes de volver a registrarla."),
    ], [2200, 3000, 4160], 7.8)
    h2(doc, "11.1 Información útil para soporte")
    bullet(doc, "Fecha y hora aproximada del problema.")
    bullet(doc, "Rol del usuario y módulo donde ocurrió.")
    bullet(doc, "Texto exacto del mensaje mostrado, sin contraseñas ni datos sensibles.")
    bullet(doc, "Pasos realizados antes del error.")
    bullet(doc, "Compañía y RUT solo por el canal institucional autorizado.")
    bullet(doc, "Ruta del archivo de origen y una copia anonimizada si se solicita.")
    callout(doc, "Evite duplicar acciones", "Si no está seguro de que un pago, envío o carga terminó, revise historial, log, tabla o Dashboard antes de volver a ejecutar.", "warn")
    h2(doc, "11.2 Protección de datos")
    para(doc, "Controlia Cobranzas maneja datos personales, financieros y de contacto. Use únicamente equipos, cuentas y carpetas autorizadas. No copie bases reales a servicios personales, mensajería no autorizada ni soportes externos sin aprobación.")
    page_break(doc)


def chapter_12(doc):
    title(doc, "12. Glosario y anexos", "Referencia rápida para operación y capacitación")
    h2(doc, "12.1 Glosario")
    table(doc, ["Término", "Definición"], [
        ("Alta", "ID que aparece en el mes actual y no en el anterior."),
        ("Baja", "ID que aparece en el mes anterior y no en el actual."),
        ("Birlado", "Estado operativo disponible en la gestión y en procesos mensuales específicos."),
        ("CIP", "Clasificación con intención de pago."),
        ("SIP", "Clasificación sin intención de pago."),
        ("STARTTLS", "Protección de la conexión SMTP durante el envío."),
        ("Top montos", "Selección de una cantidad limitada de deudores con valores más altos."),
        ("Reemplazo", "Acceso temporal a una cartera sin cambiar el titular ni compartir credenciales."),
        ("Trazabilidad", "Capacidad de saber qué se hizo, cuándo, por quién y con qué resultado."),
    ], [2100, 7260], 8.7)
    h2(doc, "12.2 Lista de verificación antes de una carga")
    for item in [
        "El archivo corresponde a la compañía y período correctos.",
        "La hoja requerida existe y los encabezados son reconocibles.",
        "El archivo no está abierto en Excel.",
        "Existe respaldo del estado anterior cuando la operación lo exige.",
        "La vista previa muestra cantidades y columnas razonables.",
        "El resultado final fue confirmado y el Dashboard se actualizó.",
    ]:
        bullet(doc, "☐ " + item)
    h2(doc, "12.3 Lista de verificación antes de una campaña")
    for item in [
        "La cuenta SMTP fue probada y corresponde al remitente autorizado.",
        "El segmento, compañía, estado y rango de montos son correctos.",
        "La cantidad de destinatarios coincide con lo esperado.",
        "La plantilla y el asunto fueron revisados en vista previa.",
        "Las variables se reemplazan y los montos están en formato CLP.",
        "El modo individual o consolidado es el adecuado.",
        "La pausa entre envíos cumple la política del proveedor.",
        "El log final fue revisado y los fallidos quedaron identificados.",
    ]:
        bullet(doc, "☐ " + item)
    h2(doc, "12.4 Paleta visual de la aplicación")
    para(doc, "Este manual utiliza la identidad visual observada en Controlia Cobranzas: azul para acciones principales, azul marino para información, grises claros para fondos y bordes, verde para resultados correctos, ámbar para precauciones y rojo para riesgos.")
    table(doc, ["Uso", "Color"], [
        ("Acción principal", "Azul #2563EB"), ("Texto principal", "Azul marino #0F172A"),
        ("Texto secundario", "Gris pizarra #64748B"), ("Fondos", "Gris muy claro #F6F8FB"),
        ("Correcto", "Verde #059669"), ("Precaución", "Ámbar #B45309"), ("Riesgo", "Rojo #DC2626"),
    ], [3900, 5460], 9)
    h2(doc, "12.5 Cierre")
    para(doc, "El uso consistente de roles, asignaciones, registros de gestión y verificaciones posteriores permite que Controlia Cobranzas sea una fuente operativa confiable. Ante una duda, detenga la acción sensible, revise este manual y solicite apoyo por el canal institucional.")
    callout(doc, "Versión del documento", "Manual de Usuario Controlia Cobranzas, versión 1.0, preparado para la entrega de la aplicación en agosto de 2026.", "info")


def core_properties(doc):
    cp = doc.core_properties
    cp.title = "Manual de Usuario - Controlia Cobranzas"
    cp.subject = "Guía detallada para usuarios no técnicos"
    cp.author = "Controlia Cobranzas"
    cp.keywords = "Controlia, cobranzas, manual, usuarios, carteras, deudores"
    cp.comments = "Documento de entrega de la aplicación"


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    configure(doc)
    core_properties(doc)
    cover(doc)
    contents(doc)
    chapter_1(doc)
    chapter_2(doc)
    chapter_3(doc)
    chapter_4(doc)
    chapter_5(doc)
    chapter_6(doc)
    chapter_7(doc)
    chapter_8(doc)
    chapter_9(doc)
    chapter_10(doc)
    chapter_11(doc)
    chapter_12(doc)
    doc.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
