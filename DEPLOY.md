# Publicar la app en una web

Esta version cloud usa Docker, Python, `yt-dlp` y `ffmpeg`.

## Donde subirla

No conviene Netlify para esta app: las funciones tienen limites de tiempo/payload y esto descarga/convierte videos. Usar un servicio que corra Docker como Render, Fly.io, Railway o un VPS.

## Opcion recomendada: Render

1. Crear una cuenta en Render.
2. Subir esta carpeta a un repositorio de GitHub.
3. En Render: **New +** -> **Web Service**.
4. Conectar el repositorio.
5. Elegir **Docker** como runtime.
6. En **Environment**, agregar `APP_PASSWORD` con una clave para proteger la web.
7. Deploy.
8. Abrir la URL publica que te da Render.

Cuando pida login, usar:

- Usuario: `admin`
- Contrasena: el valor de `APP_PASSWORD`

## Opcion Fly.io

Desde esta carpeta:

```powershell
fly launch
fly deploy
```

## Limitaciones de la version web

- Solo funciona bien con reels publicos.
- La version web no puede leer las cookies de Chrome/Edge del visitante.
- Los archivos quedan en el servidor. En planes sin disco persistente pueden borrarse cuando el servicio se reinicia.
- Usar solo con contenido propio o con permiso.
