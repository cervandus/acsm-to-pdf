"""ACSM a PDF · ventana estilo iPhone sobre el motor de conversión."""
import base64
import ctypes
import json
import mimetypes
import os
import queue
import subprocess
import sys
import threading
import traceback
import winreg

import webview
from webview.dom import DOMEventHandler

import motor

import adobe_portatil

NOMBRE = 'ACSM a PDF'
VERSION = '1.2.0'
FICHERO_AJUSTES = os.path.join(motor.DATOS, 'ajustes.json')   # viaja con la app (portátil)
PROGID = 'ACSMaPDF.acsm'
EXTENSIONES = ('.acsm', '.epub', '.pdf')


def registrar(texto):
    """Errores inesperados a datos\\registro.log: la app no tiene consola donde verlos."""
    try:
        import datetime
        os.makedirs(motor.DATOS, exist_ok=True)
        with open(os.path.join(motor.DATOS, 'registro.log'), 'a', encoding='utf-8') as f:
            f.write(f'--- {datetime.datetime.now():%Y-%m-%d %H:%M:%S} · versión {VERSION}\n{texto}\n')
    except OSError:
        pass


# ---------------------------------------------------------------- ajustes

def ajustes_por_defecto():
    return {'tamano': 'original', 'guardar_epub': False, 'progid_anterior': None,
            'carpeta': os.path.join(os.path.expanduser('~'), 'Documents', 'Libros PDF')}


def cargar_ajustes():
    a = ajustes_por_defecto()
    try:
        with open(FICHERO_AJUSTES, encoding='utf-8') as f:
            a.update(json.load(f))
    except (OSError, ValueError):
        pass
    # en otro ordenador la carpeta guardada puede no existir: se vuelve a Documentos\Libros PDF
    if not os.path.isdir(os.path.dirname(a['carpeta'].rstrip('\\/')) or '?'):
        a['carpeta'] = ajustes_por_defecto()['carpeta']
    a['asociado'] = esta_asociado()
    return a


def guardar_ajustes(a):
    os.makedirs(motor.DATOS, exist_ok=True)
    datos = {k: v for k, v in a.items() if k != 'asociado'}
    with open(FICHERO_AJUSTES, 'w', encoding='utf-8') as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- asociación .acsm (solo HKCU, reversible)

def orden_abrir():
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}" "%1"'
    pythonw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    return f'"{pythonw}" "{os.path.abspath(__file__)}" "%1"'


def _avisar_explorador():
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)


def esta_asociado():
    """Se mira en el registro de ESTE ordenador y para ESTA copia de la app (la carpeta puede haberse movido)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Classes\.acsm') as k:
            if winreg.QueryValue(k, None) != PROGID:
                return False
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf'Software\Classes\{PROGID}\shell\open\command') as k:
            return winreg.QueryValue(k, None) == orden_abrir()
    except OSError:
        return False


def asociar_acsm(activar, ajustes):
    clases = r'Software\Classes'
    if activar:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, clases + r'\.acsm') as k:
                actual = winreg.QueryValue(k, None) or None
            if actual != PROGID:
                ajustes['progid_anterior'] = actual
        except OSError:
            ajustes['progid_anterior'] = None
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, clases + '\\' + PROGID) as k:
            winreg.SetValue(k, None, winreg.REG_SZ, 'Ticket de libro electrónico (ACSM)')
        icono = sys.executable if getattr(sys, 'frozen', False) else motor.recurso('icono.ico')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, clases + '\\' + PROGID + r'\DefaultIcon') as k:
            winreg.SetValue(k, None, winreg.REG_SZ, f'"{icono}",0')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, clases + '\\' + PROGID + r'\shell\open\command') as k:
            winreg.SetValue(k, None, winreg.REG_SZ, orden_abrir())
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, clases + r'\.acsm') as k:
            winreg.SetValue(k, None, winreg.REG_SZ, PROGID)
    else:
        anterior = ajustes.get('progid_anterior')
        try:
            if anterior and anterior != PROGID:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, clases + r'\.acsm') as k:
                    winreg.SetValue(k, None, winreg.REG_SZ, anterior)
            else:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, clases + r'\.acsm', 0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, '')
        except OSError:
            pass
        for sub in (r'\shell\open\command', r'\shell\open', r'\shell', r'\DefaultIcon', ''):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, clases + '\\' + PROGID + sub)
            except OSError:
                pass
    _avisar_explorador()
    ajustes['asociado'] = esta_asociado()
    guardar_ajustes(ajustes)


# ---------------------------------------------------------------- puente con la interfaz

def a_data_uri(ruta):
    if not ruta or not os.path.exists(ruta):
        return None
    tipo = mimetypes.guess_type(ruta)[0] or 'image/jpeg'
    with open(ruta, 'rb') as f:
        return f'data:{tipo};base64,' + base64.b64encode(f.read()).decode()


class Api:
    def __init__(self, iniciales):
        self._ventana = None
        self._ajustes = cargar_ajustes()
        self._cola = queue.Queue()
        self._iniciales = iniciales
        threading.Thread(target=self._trabajador, daemon=True).start()

    # --- llamadas desde JavaScript
    def estado_inicial(self):
        cuenta = adobe_portatil.hay_cuenta(motor.CUENTA)
        comprobaciones = [
            ['Autorización de Adobe', 'dentro de la app' if cuenta else
             ('se copiará de Adobe Digital Editions' if adobe_portatil.ade_autorizado_aqui()
              else 'se creará al convertir el primer libro'), True],
            ['Motor de PDF (Calibre)', 'dentro de la app' if os.path.exists(os.path.join(motor.APP_DIR, 'calibre'))
             else ('el de este equipo' if motor.calibre() else 'falta'), bool(motor.calibre())],
        ]
        if self._iniciales:
            threading.Timer(0.6, self.convertir, [self._iniciales]).start()
            self._iniciales = []
        return {'ajustes': self._ajustes, 'comprobaciones': comprobaciones, 'version': VERSION}

    def elegir_archivo(self):
        r = self._ventana.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
                                             file_types=('Libros (*.acsm;*.epub;*.pdf)', 'Todos (*.*)'))
        return list(r) if r else []

    def elegir_carpeta(self):
        r = self._ventana.create_file_dialog(webview.FileDialog.FOLDER, directory=self._ajustes['carpeta'])
        return r[0] if r else None

    def convertir(self, rutas):
        for r in rutas:
            if r and r.lower().endswith(EXTENSIONES) and os.path.exists(r):
                self._cola.put(r)
        self._enviar({'tipo': 'cola', 'pendientes': max(0, self._cola.qsize() - (0 if self._libre else 1))})

    def guardar_ajustes(self, nuevos):
        for k in ('tamano', 'guardar_epub', 'carpeta'):
            if k in nuevos:
                self._ajustes[k] = nuevos[k]
        guardar_ajustes(self._ajustes)

    def asociar(self, activar):
        try:
            asociar_acsm(bool(activar), self._ajustes)
            return {'ok': True, 'asociado': self._ajustes['asociado']}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def abrir(self, ruta):
        os.startfile(ruta)

    def mostrar(self, ruta):
        subprocess.Popen(f'explorer /select,"{ruta}"')

    def minimizar(self):
        self._ventana.minimize()

    def cerrar(self):
        self._ventana.destroy()

    # --- interno
    _libre = True

    def _enviar(self, ev):
        if self._ventana:
            self._ventana.evaluate_js(f'window.evento({json.dumps(ev, ensure_ascii=False)})')

    def _trabajador(self):
        while True:
            ruta = self._cola.get()
            self._libre = False
            self._enviar({'tipo': 'cola', 'pendientes': self._cola.qsize()})
            self._enviar({'tipo': 'inicio', 'nombre': os.path.splitext(os.path.basename(ruta))[0]})

            def progreso(etapa, pct, msg, portada=None, **extra):
                ev = {'tipo': 'progreso', 'etapa': etapa, 'pct': round(pct), 'msg': msg, **extra}
                if portada:
                    ev['portada'] = a_data_uri(portada)
                self._enviar(ev)
            try:
                r = motor.convertir(ruta, dict(self._ajustes), progreso)
                r['portada'] = a_data_uri(r.get('portada'))
                self._enviar({'tipo': 'hecho', **r})
            except motor.ErrorConversion as e:
                self._enviar({'tipo': 'error', 'msg': str(e), 'atencion': e.atencion, 'ruta': ruta})
            except Exception as e:
                registrar(traceback.format_exc())
                self._enviar({'tipo': 'error', 'msg': f'Error inesperado: {e}', 'detalle': traceback.format_exc(), 'ruta': ruta})
            finally:
                self._libre = True


# ---------------------------------------------------------------- ventana

def esquinas_redondeadas(ventana):
    try:
        hwnd = ventana.native.Handle.ToInt64()
        valor = ctypes.c_int(2)  # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(valor), ctypes.sizeof(valor))
    except Exception:
        pass


def enlazar(ventana, api):
    esquinas_redondeadas(ventana)

    def al_soltar(e):
        archivos = (e.get('dataTransfer') or {}).get('files') or []
        api.convertir([f.get('pywebviewFullPath') for f in archivos])

    nada = lambda e: None
    ventana.dom.document.events.dragenter += DOMEventHandler(nada, True, True)
    ventana.dom.document.events.dragover += DOMEventHandler(nada, True, True, debounce=500)
    ventana.dom.document.events.drop += DOMEventHandler(al_soltar, True, True)


def main():
    if '--asociar' in sys.argv or '--desasociar' in sys.argv:
        asociar_acsm('--asociar' in sys.argv, cargar_ajustes())
        return
    if '--importar-adobe' in sys.argv:          # lo usa construir.ps1 para que el .zip ya lleve la autorización
        try:
            adobe_portatil.importar_de_ade(motor.CUENTA)
        except Exception:
            registrar(traceback.format_exc())
        return
    iniciales = [a for a in sys.argv[1:] if a.lower().endswith(EXTENSIONES)]
    api = Api(iniciales)
    ventana = webview.create_window(NOMBRE, motor.recurso(os.path.join('ui', 'index.html')), js_api=api,
                                    width=392, height=744, resizable=False, frameless=True, easy_drag=False,
                                    background_color='#05060a')
    api._ventana = ventana
    webview.start(enlazar, (ventana, api), private_mode=True)


if __name__ == '__main__':
    main()
