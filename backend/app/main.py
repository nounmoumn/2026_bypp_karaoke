"""BYPP local API + player.

Serves every song scripts/process_song.py has produced (previously a set of
standalone karaoke.html files, each opened directly as a file:// page).
Audio is now streamed over HTTP (FileResponse, Range-aware) instead of read
as a local file -- some mobile browsers (notably iOS Safari) refuse to
seek/play large file:// media reliably, which is the likely cause of "video
doesn't play" on a phone with the old static-file version.

Run:
    backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000

--host 0.0.0.0 (not 127.0.0.1) so a phone on the same Wi-Fi can reach it at
http://<this PC's LAN IP>:8000/.
"""

import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from . import jobs, library

UPLOAD_TMP = Path(__file__).resolve().parents[2] / "data" / "pipeline" / "_uploads"

app = FastAPI(title="BYPP local API", version="0.2.0")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

AUDIO_MEDIA_TYPES = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".mp4": "video/mp4"}
MAX_UPLOAD_BYTES = 300 * 1024 * 1024


@app.get("/api/songs")
def api_list_songs():
    return library.list_songs()


@app.get("/api/songs/{song_id}")
def api_get_song(song_id: str):
    try:
        return library.load_song(song_id)
    except library.SongNotFound:
        raise HTTPException(404, "Song not found")


@app.get("/api/songs/{song_id}/audio/{filename}")
def api_get_audio(song_id: str, filename: str):
    try:
        path = library.audio_path(song_id, filename)
    except library.SongNotFound:
        raise HTTPException(404, "Audio not found")
    media_type = AUDIO_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    # Starlette's FileResponse handles Range/If-Range itself (206 Partial Content) --
    # that's the part a plain file:// open on a phone doesn't get.
    return FileResponse(path, media_type=media_type)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"songs": library.list_songs()})


@app.get("/song/{song_id}", response_class=HTMLResponse)
def song_page(request: Request, song_id: str):
    try:
        library.load_song(song_id)  # 404 early instead of shipping a broken player page
    except library.SongNotFound:
        raise HTTPException(404, "Song not found")
    return templates.TemplateResponse(request, "player.html", {"song_id": song_id})


# ---------------------------------------------------------------- add a song from a URL or uploaded audio
@app.get("/new", response_class=HTMLResponse)
def new_song_form(request: Request):
    return templates.TemplateResponse(request, "new_song.html", {})


@app.post("/api/jobs")
def submit_job(songId: str = Form(...), lyrics: str = Form(...), title: str = Form(""),
              url: str = Form(""), fullKeyRange: bool = Form(False),
              language: str = Form("auto"),
              audio: UploadFile | None = File(None)):
    uploaded_path = None
    if audio is not None and audio.filename:
        # a scratch copy; the background job copies it again into data/pipeline/<id>/ and
        # deletes this one after the background process exits (see jobs._run)
        UPLOAD_TMP.mkdir(parents=True, exist_ok=True)
        uploaded_path = UPLOAD_TMP / f"{uuid.uuid4().hex}_{Path(audio.filename).name}"
        received = 0
        try:
            with uploaded_path.open("wb") as f:
                while chunk := audio.file.read(1024 * 1024):
                    received += len(chunk)
                    if received > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, "음원 파일은 300MB 이하로 올려 주세요.")
                    f.write(chunk)
        except Exception:
            uploaded_path.unlink(missing_ok=True)
            raise
    result = jobs.submit_job(songId, lyrics, title or songId, url=url,
                             uploaded_audio=uploaded_path, full_key_range=fullKeyRange,
                             language=language)
    if result and uploaded_path and uploaded_path.exists():
        uploaded_path.unlink()  # job never started (validation failed / duplicate) -- nothing left to clean up later
    if result:
        raise HTTPException(400, detail=result)
    return {"songId": songId}


@app.get("/api/jobs/{song_id}/status")
def job_status(song_id: str):
    status = jobs.get_status(song_id)
    if status is None:
        raise HTTPException(404, "No job found for this song ID")
    return JSONResponse(status)


@app.get("/job/{song_id}", response_class=HTMLResponse)
def job_status_page(request: Request, song_id: str):
    return templates.TemplateResponse(request, "job_status.html", {"song_id": song_id})
