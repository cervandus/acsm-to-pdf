"""Motor de conversión .acsm -> PDF, portátil.

Etapas: 1) leer el ticket, 2) canjearlo con la autorización de Adobe que lleva la app,
3) quitar el DRM, 4) maquetar el PDF con la copia de Calibre que lleva la app.
Si el canje propio falla y el ordenador tiene Adobe Digital Editions, se usa ADE como plan B.
"""
import ctypes
import datetime as dt
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

import adobe_portatil as adobe

SIN_VENTANA = 0x08000000  # CREATE_NO_WINDOW

# Carpeta de la app: junto al .exe cuando está empaquetada, junto al código en desarrollo.
APP_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
DATOS = os.environ.get('ACSM2PDF_DATOS') or os.path.join(APP_DIR, 'datos')   # la variable solo se usa en pruebas
CUENTA = os.path.join(DATOS, 'cuenta adobe')

CALIBRE_DIRS = [os.path.join(APP_DIR, 'calibre'), r'C:\Program Files\Calibre2', r'C:\Program Files (x86)\Calibre2']
ADE_EXES = [
    r'C:\Program Files (x86)\Adobe\Adobe Digital Editions 4.5\DigitalEditions.exe',
    r'C:\Program Files\Adobe\Adobe Digital Editions 4.5\DigitalEditions.exe',
]
CARPETA_ADE = os.path.join(os.path.expanduser('~'), 'Documents', 'My Digital Editions')

# Tamaños de página en centímetros (ancho, alto). «original» se calcula con la portada.
TAMANOS = {'a4': (21.0, 29.7), 'a5': (14.8, 21.0), 'lector': (9.0, 12.2)}
ANCHO_ORIGINAL_CM = 14.0


class ErrorConversion(Exception):
    def __init__(self, mensaje, atencion=False):
        super().__init__(mensaje)
        self.atencion = atencion


def recurso(nombre):
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, nombre)


def buscar(rutas):
    return next((r for r in rutas if os.path.exists(r)), None)


def calibre():
    return next((d for d in CALIBRE_DIRS if os.path.exists(os.path.join(d, 'ebook-convert.exe'))), None)


def entorno_calibre():
    """Calibre guarda su configuración en una carpeta temporal: no deja rastro en el ordenador ni lee la del usuario."""
    env = dict(os.environ)
    env['CALIBRE_CONFIG_DIRECTORY'] = os.path.join(tempfile.gettempdir(), 'acsm2pdf_calibre')
    return env


def nombre_seguro(texto):
    texto = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', texto).strip().rstrip('.')
    return texto[:150] or 'Libro'


# ---------------------------------------------------------------- 1. ticket

NS = {'a': 'http://ns.adobe.com/adept', 'dc': 'http://purl.org/dc/elements/1.1/'}


def leer_ticket(ruta):
    try:
        raiz = ET.parse(ruta).getroot()
    except ET.ParseError:
        raise ErrorConversion('Este archivo no es un ticket .acsm válido.')
    if raiz.tag != '{http://ns.adobe.com/adept}fulfillmentToken':
        raise ErrorConversion('Este archivo no es un ticket .acsm de Adobe.')

    def txt(xpath):
        nodo = raiz.find(xpath, NS)
        return (nodo.text or '').strip() if nodo is not None else ''

    caduca = None
    try:
        caduca = dt.datetime.fromisoformat(txt('a:expiration'))
    except ValueError:
        pass
    return {
        'titulo': txt('.//dc:title') or os.path.splitext(os.path.basename(ruta))[0],
        'autor': txt('.//dc:creator'),
        'recurso': txt('a:resourceItemInfo/a:resource'),
        'caduca': caduca,
    }


# ---------------------------------------------------------------- 2. Adobe

def asegurar_cuenta(avisar):
    """La app necesita una autorización de Adobe en datos\\cuenta adobe.
    Si falta: copia la de Adobe Digital Editions si este equipo la tiene; si no, crea una anónima nueva."""
    if adobe.hay_cuenta(CUENTA):
        return
    try:
        if adobe.ade_autorizado_aqui():
            avisar('Copiando tu autorización de Adobe a la app')
            adobe.importar_de_ade(CUENTA)
        else:
            avisar('Creando tu autorización de Adobe (solo la primera vez)')
            adobe.crear_anonima(CUENTA)
    except adobe.ErrorAdobe as e:
        raise ErrorConversion(str(e), atencion=True)


def canjear(ruta_acsm, ticket, temporal, avisar):
    asegurar_cuenta(avisar)
    avisar('Pidiendo el libro a la tienda')
    try:
        return adobe.canjear(ruta_acsm, CUENTA, temporal)
    except adobe.ErrorAdobe as e:
        if buscar(ADE_EXES) and adobe.ade_autorizado_aqui():
            avisar('Probando con Adobe Digital Editions')
            return canjear_con_ade(ruta_acsm, ticket, avisar)
        raise ErrorConversion(str(e))


def libro_en_ade(recurso_urn):
    """Devuelve la ruta del libro ya canjeado en My Digital Editions, o None."""
    if not recurso_urn:
        return None
    for ficha in glob.glob(os.path.join(CARPETA_ADE, 'Manifest', '*.xml')):
        try:
            with open(ficha, encoding='utf-8', errors='replace') as f:
                if recurso_urn not in f.read():
                    continue
        except OSError:
            continue
        libro = os.path.join(CARPETA_ADE, os.path.basename(ficha)[:-4])
        if os.path.exists(libro):
            return libro
    return None


def ade_abierto():
    salida = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq DigitalEditions.exe', '/NH'],
                            capture_output=True, text=True, creationflags=SIN_VENTANA).stdout
    return 'DigitalEditions.exe' in salida


def _ventanas_ade(mostrar):
    """Minimiza (mostrar=False) o restaura (mostrar=True) las ventanas de ADE."""
    user32 = ctypes.windll.user32
    pids = set()
    salida = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq DigitalEditions.exe', '/FO', 'CSV', '/NH'],
                            capture_output=True, text=True, creationflags=SIN_VENTANA).stdout
    for linea in salida.splitlines():
        partes = linea.split('","')
        if len(partes) > 1 and partes[1].isdigit():
            pids.add(int(partes[1]))
    if not pids:
        return
    PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cada(hwnd, _):
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(hwnd):
            if mostrar:
                user32.ShowWindow(hwnd, 9)          # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
            else:
                user32.ShowWindow(hwnd, 7)          # SW_SHOWMINNOACTIVE
        return True
    user32.EnumWindows(PROC(cada), 0)


def canjear_con_ade(ruta_acsm, ticket, avisar, espera_normal=150, espera_atencion=600):
    ya = libro_en_ade(ticket['recurso'])
    if ya:
        return ya
    ade = buscar(ADE_EXES)
    estaba_abierto = ade_abierto()
    subprocess.Popen([ade, ruta_acsm])
    avisar('Adobe Digital Editions está validando la compra')

    inicio = time.time()
    atencion = False
    while True:
        if not atencion and time.time() - inicio < 20:
            _ventanas_ade(False)                     # mantenerlo en segundo plano
        libro = libro_en_ade(ticket['recurso'])
        if libro and _tamano_estable(libro):
            break
        transcurrido = time.time() - inicio
        if not atencion and transcurrido > espera_normal:
            atencion = True
            _ventanas_ade(True)
            avisar('Adobe necesita que mires su ventana', atencion=True)
        if atencion and (transcurrido > espera_atencion or not ade_abierto()):
            raise ErrorConversion('Adobe no ha entregado el libro. Revisa su ventana: puede que el ticket '
                                  'ya se usara en otro equipo o que haya que autorizar este.', atencion=True)
        time.sleep(1)

    if not estaba_abierto:
        subprocess.run(['taskkill', '/IM', 'DigitalEditions.exe', '/F'],
                       capture_output=True, creationflags=SIN_VENTANA)
    return libro


def _tamano_estable(ruta, segundos=1.5):
    try:
        a = os.path.getsize(ruta)
        time.sleep(segundos)
        return a > 0 and a == os.path.getsize(ruta)
    except OSError:
        return False


# ---------------------------------------------------------------- 3. DRM y datos del libro

def quitar_drm(libro, temporal, avisar):
    with open(libro, 'rb') as f:
        ext = 'pdf' if f.read(5) == b'%PDF-' else 'epub'
    libre = os.path.join(temporal, 'libre.' + ext)
    if adobe.tiene_drm(libro):
        asegurar_cuenta(avisar)
        try:
            adobe.descifrar(libro, adobe.clave_der(CUENTA), libre)
        except adobe.ErrorAdobe as e:
            raise ErrorConversion(str(e))
    else:
        shutil.copyfile(libro, libre)
    return libre, ext


def datos_libro(libre, temporal):
    """Título, autor y portada con ebook-meta de Calibre."""
    info = {}
    portada = os.path.join(temporal, 'portada.jpg')
    r = subprocess.run([os.path.join(calibre(), 'ebook-meta.exe'), libre, '--get-cover=' + portada],
                       capture_output=True, creationflags=SIN_VENTANA, env=entorno_calibre(), timeout=120)
    texto = r.stdout.decode('utf-8', errors='replace')
    for linea in texto.splitlines():
        clave, _, valor = linea.partition(':')
        clave = clave.strip()
        if clave == 'Title':
            info['titulo'] = valor.strip()
        elif clave.startswith('Author'):
            info['autor'] = re.sub(r'\s*\[.*?\]\s*$', '', valor.strip())
    if os.path.exists(portada) and os.path.getsize(portada) > 0:
        info['portada'] = portada
        try:
            from PIL import Image
            with Image.open(portada) as img:
                info['portada_ancho'], info['portada_alto'] = img.size
        except Exception:
            pass
    return info


def colores_portada(ruta, n=3):
    """Tres colores vivos de la portada para teñir el fondo de la app. None si no se puede."""
    import colorsys
    try:
        from PIL import Image
        img = Image.open(ruta).convert('RGB')
        img.thumbnail((128, 128))
        # solo píxeles con color: el blanco o el gris del fondo enturbiarían la media
        vivos = [p for p, (h, s, v) in zip(img.getdata(), img.convert('HSV').getdata()) if s > 90 and v > 50]
        if len(vivos) >= 40:
            img = Image.new('RGB', (len(vivos), 1))
            img.putdata(vivos)
        paleta = img.quantize(colors=12, method=Image.Quantize.MEDIANCUT)
        rgb = paleta.getpalette()[:36]
        cuentas = sorted(paleta.getcolors(), reverse=True)
    except Exception:
        return None
    candidatos = []
    for cuenta, i in cuentas:
        r, g, b = (c / 255 for c in rgb[i * 3:i * 3 + 3])
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        if l > .92 or l < .08:                       # blancos y negros no tiñen
            continue
        candidatos.append((cuenta * (.25 + s), h, l, s))
    if not candidatos:
        return None
    candidatos.sort(reverse=True)
    elegidos = []
    for _, h, l, s in candidatos:                    # tonos distintos entre sí
        if all(min(abs(h - e[0]), 1 - abs(h - e[0])) > .06 for e in elegidos):
            elegidos.append((h, l, s))
        if len(elegidos) == n:
            break
    while len(elegidos) < n:                         # portada de un solo color: variaciones del tono
        h, l, s = elegidos[0]
        elegidos.append(((h + .07 * len(elegidos)) % 1, l, s))
    salida = []
    for h, l, s in elegidos:
        l = min(max(l, .38), .58)                    # que brille sobre el fondo oscuro
        s = max(s, .55)
        r, g, b = colorsys.hls_to_rgb(h, l, s)
        salida.append('#%02x%02x%02x' % (int(r * 255), int(g * 255), int(b * 255)))
    return salida


# ---------------------------------------------------------------- 4. PDF

def tamano_pagina(ajustes, info):
    clave = ajustes.get('tamano', 'original')
    if clave in TAMANOS:
        return TAMANOS[clave]
    ancho, alto = info.get('portada_ancho'), info.get('portada_alto')
    proporcion = (alto / ancho) if ancho and alto else 1.55
    proporcion = min(max(proporcion, 1.25), 1.75)    # portadas raras no dan páginas absurdas
    return ANCHO_ORIGINAL_CM, round(ANCHO_ORIGINAL_CM * proporcion, 1)


def maquetar_pdf(epub, destino, ajustes, info, avisar_pct):
    ancho, alto = tamano_pagina(ajustes, info)
    margen = '42' if ancho >= 12 else '20'
    letra = '17' if ancho >= 20 else ('15' if ancho >= 12 else '13')
    orden = [os.path.join(calibre(), 'ebook-convert.exe'), epub, destino,
             '--custom-size', f'{ancho}x{alto}', '--unit', 'centimeter',
             '--pdf-page-margin-left', margen, '--pdf-page-margin-right', margen,
             '--pdf-page-margin-top', margen, '--pdf-page-margin-bottom', margen,
             '--pdf-default-font-size', letra, '--pdf-page-numbers', '--preserve-cover-aspect-ratio']
    if info.get('titulo'):
        orden += ['--title', info['titulo']]
    if info.get('autor'):
        orden += ['--authors', info['autor']]
    proc = subprocess.Popen(orden, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=entorno_calibre(),
                            creationflags=SIN_VENTANA, text=True, encoding='utf-8', errors='replace')
    ultimas = []
    for linea in proc.stdout:
        ultimas = (ultimas + [linea.strip()])[-15:]
        m = re.match(r'^\s*(\d{1,3})%', linea)
        if m:
            avisar_pct(int(m.group(1)))
    proc.wait()
    if proc.returncode != 0 or not os.path.exists(destino):
        raise ErrorConversion('Calibre no ha podido crear el PDF.\n' + '\n'.join(ultimas[-4:]))
    return ancho, alto


# ---------------------------------------------------------------- todo junto

def destino_libre(carpeta, nombre, ext):
    ruta = os.path.join(carpeta, f'{nombre}.{ext}')
    n = 2
    while os.path.exists(ruta):
        ruta = os.path.join(carpeta, f'{nombre} ({n}).{ext}')
        n += 1
    return ruta


def convertir(ruta, ajustes, progreso):
    """progreso(etapa, porcentaje_total, mensaje, **extra). Devuelve dict con el resultado."""
    if not calibre():
        raise ErrorConversion('Falta la carpeta «calibre» junto a la app. Copia la carpeta completa, no solo el .exe.')
    temporal = tempfile.mkdtemp(prefix='acsm2pdf_')
    try:
        # 1-2. ticket y canje (también se admite un .epub/.pdf protegido directamente)
        if os.path.splitext(ruta)[1].lower() == '.acsm':
            ticket = leer_ticket(ruta)
            progreso('ticket', 8, 'Ticket leído', titulo=ticket['titulo'], autor=ticket['autor'])
            libro = canjear(ruta, ticket, temporal,
                            lambda m, atencion=False: progreso('adobe', 20, m, atencion=atencion))
        else:
            ticket = {'titulo': os.path.splitext(os.path.basename(ruta))[0], 'autor': ''}
            progreso('ticket', 8, 'Libro recibido', titulo=ticket['titulo'], autor='')
            libro = ruta
        progreso('adobe', 40, 'Libro descargado')

        # 3. DRM
        progreso('drm', 45, 'Quitando la protección…')
        libre, formato = quitar_drm(libro, temporal, lambda m, atencion=False: progreso('drm', 45, m, atencion=atencion))
        progreso('drm', 52, 'Leyendo portada y datos…')
        info = datos_libro(libre, temporal)
        titulo = info.get('titulo') or ticket['titulo']
        autor = info.get('autor') or ticket['autor']
        colores = colores_portada(info['portada']) if info.get('portada') else None
        progreso('drm', 60, 'Protección eliminada', titulo=titulo, autor=autor,
                 portada=info.get('portada'), colores=colores)

        carpeta = ajustes.get('carpeta') or os.path.join(os.path.expanduser('~'), 'Documents', 'Libros PDF')
        os.makedirs(carpeta, exist_ok=True)
        nombre = nombre_seguro(f'{titulo} - {autor}' if autor else titulo)
        pdf = destino_libre(carpeta, nombre, 'pdf')

        # 4. PDF
        if formato == 'pdf':
            progreso('pdf', 90, 'El libro ya era un PDF: se guarda tal cual')
            shutil.copyfile(libre, pdf)
            pagina = 'formato original del PDF'
        else:
            progreso('pdf', 62, 'Maquetando el PDF…')
            ancho, alto = maquetar_pdf(libre, pdf, ajustes, info,
                                       lambda p: progreso('pdf', 62 + p * 0.37, 'Maquetando el PDF…'))
            pagina = f'{ancho:g} × {alto:g} cm'.replace('.', ',')
        epub = None
        if ajustes.get('guardar_epub') and formato == 'epub':
            epub = destino_libre(carpeta, nombre, 'epub')
            shutil.copyfile(libre, epub)

        portada = None
        if info.get('portada'):
            portada = os.path.join(tempfile.gettempdir(), 'acsm2pdf_portada.jpg')
            shutil.copyfile(info['portada'], portada)
        return {'pdf': pdf, 'epub': epub, 'titulo': titulo, 'autor': autor, 'pagina': pagina,
                'tamano_mb': round(os.path.getsize(pdf) / 1048576, 1), 'portada': portada, 'colores': colores}
    finally:
        shutil.rmtree(temporal, ignore_errors=True)
