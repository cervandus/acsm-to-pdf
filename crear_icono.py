"""Genera icono.ico (y icono.png) con el estilo de la app: degradado aurora y un libro que se abre."""
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

T = 1024
AQUI = os.path.dirname(os.path.abspath(__file__))


def degradado(t):
    base = Image.new('RGB', (t, t))
    a, b, c = (94, 92, 230), (191, 90, 242), (10, 132, 255)
    px = base.load()
    for y in range(t):
        for x in range(t):
            u = (x + y) / (2 * t)
            if u < .5:
                k = u / .5
                col = tuple(int(c[i] + (a[i] - c[i]) * k) for i in range(3))
            else:
                k = (u - .5) / .5
                col = tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))
            px[x, y] = col
    return base


fondo = degradado(256).resize((T, T), Image.BICUBIC)
mascara = Image.new('L', (T, T), 0)
ImageDraw.Draw(mascara).rounded_rectangle((40, 40, T - 40, T - 40), radius=230, fill=255)
icono = Image.new('RGBA', (T, T), (0, 0, 0, 0))
icono.paste(fondo, (0, 0), mascara)

# brillo superior
brillo = Image.new('L', (T, T), 0)
ImageDraw.Draw(brillo).ellipse((-300, -800, T + 300, 460), fill=45)
brillo = brillo.filter(ImageFilter.GaussianBlur(140))
blanco = Image.new('RGBA', (T, T), (255, 255, 255, 0))
blanco.putalpha(Image.composite(brillo, Image.new('L', (T, T), 0), mascara))
icono = Image.alpha_composite(icono, blanco)

# sombra + hoja de papel
capa = Image.new('RGBA', (T, T), (0, 0, 0, 0))
d = ImageDraw.Draw(capa)
hoja = [(300, 210), (620, 210), (740, 330), (740, 814), (300, 814)]
sombra = Image.new('RGBA', (T, T), (0, 0, 0, 0))
ImageDraw.Draw(sombra).polygon([(x + 14, y + 26) for x, y in hoja], fill=(20, 10, 60, 120))
sombra = sombra.filter(ImageFilter.GaussianBlur(26))
icono = Image.alpha_composite(icono, sombra)
d.polygon(hoja, fill=(255, 255, 255, 255))
d.polygon([(620, 210), (620, 330), (740, 330)], fill=(214, 206, 255, 255))
# candado abierto
d.rounded_rectangle((420, 300, 620, 440), radius=26, fill=(94, 92, 230, 255))
d.arc((450, 205, 590, 345), start=180, end=320, fill=(94, 92, 230, 255), width=30)
d.rectangle((450, 272, 480, 305), fill=(94, 92, 230, 255))
d.ellipse((505, 352, 535, 382), fill=(255, 255, 255, 255))
# PDF
try:
    fuente = ImageFont.truetype(r'C:\Windows\Fonts\segoeuib.ttf', 150)
except OSError:
    fuente = ImageFont.load_default()
d.text((520, 640), 'PDF', font=fuente, fill=(255, 55, 95, 255), anchor='mm')
icono = Image.alpha_composite(icono, capa)

icono.save(os.path.join(AQUI, 'icono.png'))
icono.save(os.path.join(AQUI, 'icono.ico'), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print('icono creado')
