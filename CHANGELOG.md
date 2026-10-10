# Registro de cambios · Changelog

## 1.2.0 · 2026-10-11 · Primera versión pública · First public release

**Español**
- Ya no hace falta Adobe Digital Editions en ningún momento: si el ordenador no tiene una autorización de Adobe que copiar, la app crea una anónima al convertir el primer libro y la guarda en la carpeta `datos`.
- Si el ordenador tiene Adobe Digital Editions autorizado, la app copia esa autorización para poder abrir también los libros ya descargados con ADE.
- Mensajes claros cuando un ticket ya se canjeó con otra autorización, ha caducado o no hay conexión.
- Aviso en Ajustes para hacer copia de seguridad de la carpeta `datos`.
- Se corrige desde fuera un fallo de DeACSM 0.0.16 que impedía crear autorizaciones con número de serie aleatorio.

**English**
- Adobe Digital Editions is no longer needed at all: if the computer has no Adobe authorization to copy, the app creates an anonymous one when converting the first book and stores it in the `datos` folder.
- If the computer has an authorized Adobe Digital Editions, the app copies that authorization so it can also open books already downloaded with ADE.
- Clear messages when a ticket was already redeemed with another authorization, has expired, or there is no connection.
- Settings now remind you to back up the `datos` folder.
- Works around a DeACSM 0.0.16 bug that prevented creating authorizations with a random serial number.

## 1.1.0 · 2026-10-11 · Portátil · Portable

**Español**
- Portátil: se descomprime y funciona sin instalar Adobe Digital Editions, Calibre ni DeDRM.
- El fondo y el confeti toman los colores de la portada del libro.
- Canje propio del `.acsm` (DeACSM), desprotección propia (DeDRM) y Calibre 9.16 incluido.

**English**
- Portable: unzip and run, without installing Adobe Digital Editions, Calibre or DeDRM.
- The background and confetti take on the colours of the book cover.
- Built-in `.acsm` fulfilment (DeACSM), built-in DRM removal (DeDRM) and bundled Calibre 9.16.

## 1.0.0 · 2026-10-11 · No publicada · Not released

- Primera versión: interfaz estilo iPhone en modo noche y conversión de `.acsm` a PDF usando Adobe Digital Editions, Calibre y DeDRM instalados.
- First version: iPhone-style night-mode interface and `.acsm` to PDF conversion using installed Adobe Digital Editions, Calibre and DeDRM.
