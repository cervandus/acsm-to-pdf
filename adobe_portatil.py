"""Adobe sin ADE: autorización propia, canje del .acsm y quitar el DRM.

Usa el código de DeACSM (canje) y de DeDRM (descifrado), copiado sin cambios en terceros\\.
La autorización vive en una carpeta de la app (activation.xml, device.xml, devicesalt) y viaja con ella.
"""
import contextlib
import io
import os
import shutil
import sys
import zipfile

_BASE = os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))), 'terceros')
for _sub in ('deacsm', 'dedrm'):
    _ruta = os.path.join(_BASE, _sub)
    if _ruta not in sys.path:
        sys.path.insert(0, _ruta)

ARCHIVOS_CUENTA = ('activation.xml', 'device.xml', 'devicesalt')
ADE_4_5_11 = 187303          # versión de ADE que se emula (la misma familia que la instalada)


class ErrorAdobe(Exception):
    pass


@contextlib.contextmanager
def _silencio():
    """El código de terceros escribe mucho por consola; en una app sin consola eso puede fallar."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield buf


def _usar_cuenta(carpeta):
    import libadobe
    libadobe.update_account_path(carpeta)
    libadobe.devkey_bytes = None


def hay_cuenta(carpeta):
    return all(os.path.exists(os.path.join(carpeta, f)) for f in ARCHIVOS_CUENTA)


def ade_autorizado_aqui():
    if os.environ.get('ACSM2PDF_SIN_ADE'):          # solo para pruebas: simular un ordenador sin ADE
        return False
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Adobe\Adept\Activation'))
        return True
    except OSError:
        return False


def importar_de_ade(carpeta):
    """Copia la autorización de ADE de este equipo a la carpeta de la app."""
    os.makedirs(carpeta, exist_ok=True)
    with _silencio():
        _usar_cuenta(carpeta)
        import libadobeImportAccount
        libadobeImportAccount.persistent_data.clear()
        ok, msg = libadobeImportAccount.importADEactivationWindows(ADE_4_5_11)
    if not ok or not hay_cuenta(carpeta):
        raise ErrorAdobe(f'No se ha podido copiar la autorización de Adobe Digital Editions ({msg}).')


def crear_anonima(carpeta):
    """Crea una autorización anónima nueva de Adobe (sin cuenta), como «Autorizar sin ID» en ADE."""
    import libadobe
    os.makedirs(carpeta, exist_ok=True)
    indice = libadobe.VAR_VER_BUILD_IDS.index(ADE_4_5_11)
    with _silencio():
        _usar_cuenta(carpeta)
        import libadobeAccount
        from libadobeAccount import createDeviceFile, createUser, signIn, activateDevice
        # Fallo de DeACSM 0.0.16: makeSerial(True) devuelve bytes y makeFingerprint espera texto
        original = libadobe.makeSerial
        texto = lambda aleatorio: (lambda s: s.decode('ascii') if isinstance(s, bytes) else s)(original(aleatorio))
        libadobe.makeSerial = libadobeAccount.makeSerial = texto
        libadobe.createDeviceKeyFile()
        pasos = [lambda: (createDeviceFile(True, indice), ''),
                 lambda: createUser(indice, None),
                 lambda: signIn('anonymous', '', ''),
                 lambda: activateDevice(indice, None)]
        for paso in pasos:
            try:
                ok, resp = paso()
            except Exception as e:
                ok, resp = False, str(e)
            if ok is False:
                break
    if ok is False or not hay_cuenta(carpeta):
        for f in ARCHIVOS_CUENTA:                       # no dejar una autorización a medias
            try:
                os.remove(os.path.join(carpeta, f))
            except OSError:
                pass
        raise ErrorAdobe('Adobe no ha podido crear la autorización de este equipo: ' + _traducir(resp))


def clave_der(carpeta):
    with _silencio():
        _usar_cuenta(carpeta)
        from libadobeAccount import exportAccountEncryptionKeyBytes
        clave = exportAccountEncryptionKeyBytes()
    if not clave:
        raise ErrorAdobe('La autorización de Adobe guardada está dañada.')
    # DeACSM deja el relleno PKCS#7 del descifrado AES al final; DeDRM lo quita (adobekey.py)
    n = clave[-1]
    if 1 <= n <= 16 and clave[-n:] == bytes([n]) * n:
        clave = clave[:-n]
    return clave


def canjear(ruta_acsm, carpeta, temporal):
    """Pide el libro a la tienda como lo haría ADE y lo descarga cifrado. Devuelve la ruta."""
    from lxml import etree
    with _silencio() as log:
        _usar_cuenta(carpeta)
        from libadobeFulfill import fulfill, buildRights
        from libadobe import sendHTTPRequest_DL2FILE
        from libpdf import patch_drm_into_pdf
        try:
            ok, respuesta = fulfill(ruta_acsm, True)
        except Exception as e:
            ok, respuesta = False, str(e)
    if not ok:
        raise ErrorAdobe(_traducir(respuesta))

    ns = lambda t: '{http://ns.adobe.com/adept}' + t
    xml = etree.fromstring(respuesta.encode('utf-8') if isinstance(respuesta, str) else respuesta)
    info = xml.find(f'./{ns("fulfillmentResult")}/{ns("resourceItemInfo")}')
    url = info.find(ns('src')).text
    derechos = buildRights(info.find(ns('licenseToken')))
    if derechos is None:
        raise ErrorAdobe('Adobe ha respondido, pero sin licencia válida para este libro.')

    descarga = os.path.join(temporal, 'descarga.bin')
    with _silencio():
        estado = sendHTTPRequest_DL2FILE(url, descarga)
    if estado != 200:
        raise ErrorAdobe(f'La tienda no ha dejado descargar el libro (error {estado}).')

    with open(descarga, 'rb') as f:
        cabecera = f.read(4)
    if cabecera.startswith(b'PK'):
        libro = os.path.join(temporal, 'cifrado.epub')
        shutil.move(descarga, libro)
        with zipfile.ZipFile(libro, 'a') as z:
            z.writestr('META-INF/rights.xml', derechos)
    elif cabecera.startswith(b'%PDF'):
        libro = os.path.join(temporal, 'cifrado.pdf')
        recurso = etree.fromstring(derechos.encode('utf-8')).find(f'./{ns("licenseToken")}/{ns("resource")}').text
        with _silencio():
            if not patch_drm_into_pdf(descarga, derechos, libro, recurso):
                raise ErrorAdobe('No se ha podido preparar el PDF descargado.')
    else:
        raise ErrorAdobe('La tienda ha entregado un archivo que no es ni EPUB ni PDF.')
    return libro


def tiene_drm(ruta):
    with open(ruta, 'rb') as f:
        cabecera = f.read(5)
    if cabecera == b'%PDF-':
        with open(ruta, 'rb') as f:
            datos = f.read()
        return b'EBX_HANDLER' in datos or b'/ADEPT' in datos
    try:
        with zipfile.ZipFile(ruta) as z:
            return 'META-INF/rights.xml' in z.namelist() and 'META-INF/encryption.xml' in z.namelist()
    except zipfile.BadZipFile:
        return False


def descifrar(libro, clave, salida):
    """Quita el DRM de Adobe (EPUB o PDF). Devuelve 'epub' o 'pdf'."""
    with open(libro, 'rb') as f:
        es_pdf = f.read(5) == b'%PDF-'
    if not tiene_drm(libro):
        shutil.copyfile(libro, salida)
        return 'pdf' if es_pdf else 'epub'
    with _silencio() as log:
        if es_pdf:
            import ineptpdf
            r = ineptpdf.decryptBook(clave, libro, salida)
        else:
            import ineptepub
            r = ineptepub.decryptBook(clave, libro, salida)
    if r != 0 or not os.path.exists(salida) or tiene_drm(salida):
        if 'Wrong key' in log.getvalue() or r == 2:
            raise ErrorAdobe('Este libro se descargó con otra autorización de Adobe y la clave de la app no lo abre.')
        raise ErrorAdobe('No se ha podido quitar la protección.')
    return 'pdf' if es_pdf else 'epub'


def _traducir(respuesta):
    r = str(respuesta)
    if 'E_GOOGLE_DEVICE_LIMIT_REACHED' in r or 'E_ADEPT_DISTRIBUTOR_AUTH' in r:
        return 'La tienda ha rechazado la descarga: el libro ya se descargó con otra cuenta o se ha superado el límite de dispositivos.'
    if 'E_LIC_ALREADY_FULFILLED_BY_ANOTHER_USER' in r:
        return ('Este libro ya se descargó con otra autorización de Adobe (otro ordenador o Adobe Digital Editions). '
                'Conviértelo con la copia de la app, o el ordenador, que lo descargó la primera vez.')
    if 'E_STOP_NOT_FOUND' in r or 'E_ADEPT_REQUEST_EXPIRED' in r or 'expired' in r.lower():
        return 'El ticket ha caducado. Vuelve a descargar el .acsm desde la tienda.'
    if 'Activation not found' in r:
        return 'Esta copia de la app no tiene autorización de Adobe.'
    if 'URLError' in r or 'timed out' in r or 'getaddrinfo' in r:
        return 'No hay conexión con el servidor de la tienda. Revisa internet y vuelve a probar.'
    return 'Adobe no ha entregado el libro: ' + r[:240]
