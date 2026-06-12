import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote

from flask import Flask, Response, jsonify, request, send_file, send_from_directory


ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
DOWNLOAD_DIR = ROOT / "downloads"
SOURCE_DIR = ROOT / "source"
JOBS_DIR = ROOT / "jobs"

for directory in (DOWNLOAD_DIR, SOURCE_DIR, JOBS_DIR):
    directory.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder=str(PUBLIC_DIR), static_url_path="")
jobs_lock = threading.Lock()
jobs = {}


@app.before_request
def require_password():
    password = os.environ.get("APP_PASSWORD", "").strip()
    if not password:
        return None

    auth = request.authorization
    if auth and auth.username == "admin" and auth.password == password:
        return None

    return Response(
        "Autenticacion requerida",
        401,
        {"WWW-Authenticate": 'Basic realm="Instagram downloader"'},
    )


def clean_url(url):
    return str(url or "").strip()


def is_instagram_url(url):
    return re.match(r"^https?://([a-z0-9-]+\.)*instagram\.com(/|$)", clean_url(url), re.I) is not None


def safe_filename(name):
    safe = re.sub(r'[\\/:*?"<>|]', "_", name)
    safe = re.sub(r"\s+", " ", safe).strip()
    return (safe[:90].strip() or "instagram-video")


def job_path(job_id):
    return JOBS_DIR / f"{job_id}.json"


def save_job(job):
    jobs[job["id"]] = job
    path = job_path(job["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_job(job_id):
    if job_id in jobs:
        return jobs[job_id]

    path = job_path(job_id)
    if not path.exists():
        return None
    job = json.loads(path.read_text(encoding="utf-8"))
    jobs[job_id] = job
    return job


def update_job(job):
    with jobs_lock:
        save_job(job)


def run_command(args, stdout_path, stderr_path):
    with open(stdout_path, "w", encoding="utf-8", errors="replace") as stdout, open(
        stderr_path, "w", encoding="utf-8", errors="replace"
    ) as stderr:
        process = subprocess.run(args, stdout=stdout, stderr=stderr, text=True)
    return process.returncode


def download_source_video(url, cookie_mode):
    yt_dlp = shutil.which("yt-dlp")
    if not yt_dlp:
        raise RuntimeError("No encontre yt-dlp en el servidor.")

    before = {path.resolve() for path in SOURCE_DIR.glob("*") if path.is_file()}
    output_template = str(SOURCE_DIR / "%(id)s.%(ext)s")
    args = [
        yt_dlp,
        "--no-playlist",
        "--force-overwrites",
        "--restrict-filenames",
        "--windows-filenames",
        "-f",
        "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "--merge-output-format",
        "mp4",
        "-o",
        output_template,
        url,
    ]

    if cookie_mode == "cookies-file":
        cookies_path = ROOT / "cookies.txt"
        if cookies_path.exists():
            args[1:1] = ["--cookies", str(cookies_path)]
        else:
            raise RuntimeError("No encontre cookies.txt en el servidor.")
    elif cookie_mode and cookie_mode != "none":
        raise RuntimeError(
            "En la version web no se pueden leer cookies del navegador del visitante. "
            "Usa reels publicos o cookies.txt en el servidor."
        )

    code = run_command(args, ROOT / "last-output.log", ROOT / "last-error.log")
    after = sorted((path for path in SOURCE_DIR.glob("*") if path.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    new_files = [path for path in after if path.resolve() not in before]
    new_file = new_files[0] if new_files else (after[0] if after else None)

    if code != 0:
        stderr = (ROOT / "last-error.log").read_text(encoding="utf-8", errors="replace")
        raise RuntimeError(stderr.strip() or "No se pudo descargar.")

    if not new_file:
        raise RuntimeError("La descarga termino, pero no encontre el archivo.")

    return new_file


def convert_to_whatsapp(input_path, output_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("No encontre ffmpeg en el servidor.")

    copy_args = [
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    copy_code = run_command(copy_args, ROOT / "last-ffmpeg-output.log", ROOT / "last-ffmpeg-error.log")
    if copy_code == 0 and output_path.exists() and output_path.stat().st_size > 0:
        return

    args = [
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        "scale='min(720,iw)':-2,format=yuv420p",
        "-threads",
        "1",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "23",
        "-profile:v",
        "high",
        "-level",
        "4.0",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    code = run_command(args, ROOT / "last-ffmpeg-output.log", ROOT / "last-ffmpeg-error.log")
    if code != 0:
        error = (ROOT / "last-ffmpeg-error.log").read_text(encoding="utf-8", errors="replace")
        raise RuntimeError(f"No se pudo convertir para WhatsApp. {error.strip()}")


def process_job(job_id, urls, cookie_mode):
    try:
        job = load_job(job_id)
        if not job:
            return

        job["status"] = "running"
        update_job(job)

        yt_dlp = shutil.which("yt-dlp")
        if not yt_dlp:
            for item in job["items"]:
                item["status"] = "error"
                item["message"] = "No encontre yt-dlp en el servidor."
                item["exitCode"] = 1
            job["status"] = "finished_with_errors"
            job["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            update_job(job)
            return

        for index, url in enumerate(urls):
            job = load_job(job_id)
            item = job["items"][index]
            item["status"] = "running"
            item["message"] = "Descargando"
            update_job(job)

            job = load_job(job_id)
            item = job["items"][index]

            try:
                new_file = download_source_video(url, cookie_mode)
                item["message"] = "Convirtiendo para WhatsApp"
                update_job(job)
                ready_name = f"{safe_filename(new_file.stem)} - WhatsApp.mp4"
                ready_path = DOWNLOAD_DIR / ready_name
                convert_to_whatsapp(new_file, ready_path)
                item["status"] = "done"
                item["message"] = "Listo para WhatsApp"
                item["file"] = str(ready_path)
                item["downloadUrl"] = f"/files/{quote(ready_name)}"
            except Exception as exc:
                item["status"] = "error"
                item["message"] = str(exc)
                item["exitCode"] = 1
            update_job(job)

        job = load_job(job_id)
        for item in job["items"]:
            if item["status"] in ("queued", "running"):
                item["status"] = "error"
                item["message"] = "No se proceso este enlace."
                item["exitCode"] = 1
        job["status"] = "finished_with_errors" if any(item["status"] == "error" for item in job["items"]) else "done"
        job["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        update_job(job)
    except Exception as exc:
        job = load_job(job_id)
        if job:
            for item in job["items"]:
                if item["status"] in ("queued", "running"):
                    item["status"] = "error"
                    item["message"] = f"Error interno del servidor: {exc}"
                    item["exitCode"] = 1
            job["status"] = "finished_with_errors"
            job["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            update_job(job)


@app.get("/")
def index():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.post("/api/download")
def start_download():
    payload = request.get_json(silent=True) or {}
    urls = [clean_url(url) for url in payload.get("urls", [])]
    urls = [url for url in urls if url and is_instagram_url(url)]
    if not urls:
        return jsonify({"error": "Pega al menos un enlace valido de Instagram."}), 400

    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "status": "queued",
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "finishedAt": None,
        "downloadDir": str(DOWNLOAD_DIR),
        "items": [
            {"url": url, "status": "queued", "message": "Esperando", "file": None, "downloadUrl": None, "exitCode": None}
            for url in urls
        ],
    }
    update_job(job)
    thread = threading.Thread(target=process_job, args=(job_id, urls, clean_url(payload.get("browser", "none"))), daemon=True)
    thread.start()
    return jsonify(job), 202


@app.post("/download-now")
def download_now():
    raw_urls = request.form.get("urls", "")
    cookie_mode = clean_url(request.form.get("browser", "none"))
    urls = [clean_url(url) for url in raw_urls.splitlines()]
    urls = [url for url in urls if url and is_instagram_url(url)]

    if not urls:
        return Response("Pega al menos un enlace valido de Instagram.", 400, mimetype="text/plain")

    ready_files = []
    errors = []
    for url in urls:
        try:
            source_file = download_source_video(url, cookie_mode)
            ready_name = f"{safe_filename(source_file.stem)} - WhatsApp.mp4"
            ready_path = DOWNLOAD_DIR / ready_name
            convert_to_whatsapp(source_file, ready_path)
            ready_files.append(ready_path)
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    if not ready_files:
        return Response("\n".join(errors) or "No se pudo descargar.", 500, mimetype="text/plain")

    if len(ready_files) == 1:
        response = send_file(
            ready_files[0],
            as_attachment=True,
            download_name=ready_files[0].name,
            mimetype="video/mp4",
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    zip_name = f"instagram-whatsapp-{int(time.time())}.zip"
    zip_path = DOWNLOAD_DIR / zip_name
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for ready_file in ready_files:
            archive.write(ready_file, arcname=ready_file.name)
        if errors:
            archive.writestr("errores.txt", "\n".join(errors))

    return send_file(zip_path, as_attachment=True, download_name=zip_name)


@app.get("/api/jobs/<job_id>")
def get_job(job_id):
    job = load_job(job_id)
    if not job:
        return jsonify({"error": "Trabajo no encontrado."}), 404
    return jsonify(job)


@app.get("/api/downloads")
def downloads():
    files = []
    for path in sorted(DOWNLOAD_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.is_file():
            files.append(
                {
                    "Name": path.name,
                    "FullName": str(path),
                    "Length": path.stat().st_size,
                    "LastWriteTime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(path.stat().st_mtime)),
                    "Url": f"/files/{quote(path.name)}",
                }
            )
    return jsonify({"downloadDir": str(DOWNLOAD_DIR), "files": files})


@app.get("/files/<path:name>")
def download_file(name):
    if name.lower().endswith(".mp4"):
        response = send_from_directory(DOWNLOAD_DIR, name, as_attachment=True, mimetype="video/mp4")
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    return send_from_directory(DOWNLOAD_DIR, name, as_attachment=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8787"))
    app.run(host="0.0.0.0", port=port)
