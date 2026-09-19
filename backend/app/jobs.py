"""Run one song pipeline job at a time without blocking the web request."""

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_ROOT = REPO_ROOT / "data" / "pipeline"
LIBRARY_ROOTS = [REPO_ROOT / "data" / "songs", PIPELINE_ROOT]
EXECUTION_MODE = os.getenv("BYPP_EXECUTION_MODE", "remote")
SCRIPT = REPO_ROOT / "scripts" / ("process_song.py" if EXECUTION_MODE == "pod" else "process_url_runpod.py")
RUNNER_PYTHON = Path(os.getenv("BYPP_PIPELINE_PYTHON", str(
    Path(sys.executable) if EXECUTION_MODE == "pod" else REPO_ROOT / ".venv-align" / "Scripts" / "python.exe")))
SONG_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,60}$")

# The remote mode is retained for local development; the deployed app runs on the Pod.
RUNPOD_HOST = os.getenv("BYPP_RUNPOD_HOST", "213.173.104.69")
RUNPOD_PORT = int(os.getenv("BYPP_RUNPOD_PORT", "10226"))
ALLOW_URL = os.getenv("BYPP_ALLOW_URL", "0") == "1"

_lock = threading.Lock()
_running: dict[str, threading.Thread] = {}

VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})")


def extract_video_id(url: str) -> str | None:
    m = VIDEO_ID_RE.search(url)
    return m.group(1) if m else None


def _title_of(song_dir: Path) -> str:
    assets_path = song_dir / "assets.json"
    if assets_path.is_file():
        try:
            return json.loads(assets_path.read_text(encoding="utf-8")).get("title") or song_dir.name
        except (OSError, ValueError):
            pass
    return song_dir.name


def find_existing_song(*, url: str | None = None, audio_path: Path | None = None) -> dict | None:
    """A song already processed from the same source (YouTube video or the
    exact same audio file), if any -- checked before starting a job so a
    re-submission never re-downloads or re-runs the GPU pipeline.
    Personal-use scale: a full directory scan per submission is cheap and
    needs no separate index file to keep in sync."""
    video_id = extract_video_id(url) if url else None
    file_hash = None
    if audio_path is not None:
        with audio_path.open("rb") as f:
            file_hash = hashlib.file_digest(f, "sha256").hexdigest()
    if not video_id and not file_hash:
        return None
    for root in LIBRARY_ROOTS:
        if not root.is_dir():
            continue
        for d in root.iterdir():
            if not (d / "assets.json").is_file() or not (d / "karaoke.json").is_file():
                continue
            sid = d / "source_id.txt"
            if not sid.is_file():
                continue
            existing = sid.read_text(encoding="utf-8").strip()
            match = (video_id and extract_video_id(existing) == video_id) or \
                    (file_hash and existing == f"sha256:{file_hash}")
            if match:
                return {"songId": d.name, "title": _title_of(d)}
    return None


def status_path(song_id: str) -> Path:
    return PIPELINE_ROOT / song_id / "job_status.json"


def log_path(song_id: str) -> Path:
    return PIPELINE_ROOT / song_id / "job_log.txt"


def get_status(song_id: str) -> dict | None:
    p = status_path(song_id)
    if not p.is_file():
        return None
    status = json.loads(p.read_text(encoding="utf-8"))
    if status.get("state") == "running" and song_id not in _running:
        status["state"] = "error"
        status["error"] = "서버가 재시작되어 작업이 중단되었습니다. 다시 등록해 주세요."
        _write_status(song_id, **status)
    lp = log_path(song_id)
    if lp.is_file():
        text = lp.read_text(encoding="utf-8", errors="replace")
        status["log"] = text[-4000:]
    return status


def _write_status(song_id: str, **fields) -> None:
    p = status_path(song_id)
    current = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    current.update(fields)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(current, ensure_ascii=False, indent=1), encoding="utf-8")


def _run(song_id: str, source: dict, lyrics_text: str, title: str, full_key_range: bool, language: str) -> None:
    try:
        out_dir = PIPELINE_ROOT / song_id
        out_dir.mkdir(parents=True, exist_ok=True)
        lyrics_path = out_dir / "submitted_lyrics.txt"
        lyrics_path.write_text(lyrics_text, encoding="utf-8")
        _write_status(song_id, state="running", startedAt=time.time(), title=title)
        cmd = [str(RUNNER_PYTHON), str(SCRIPT)]
        cmd += ["--url", source["url"]] if source.get("url") else ["--audio", source["uploadedFile"]]
        cmd += ["--lyrics", str(lyrics_path), "--out", str(out_dir), "--title", title, "--language", language]
        cmd += ["--device", "cuda"] if EXECUTION_MODE == "pod" else ["--host", RUNPOD_HOST, "--port", str(RUNPOD_PORT)]
        if full_key_range:
            cmd.append("--full-key-range")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        with log_path(song_id).open("w", encoding="utf-8") as log:
            proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, text=True, env=env)
        if proc.returncode != 0:
            raise RuntimeError(f"파이프라인 종료 코드: {proc.returncode}")
        if source.get("uploadedFile"):
            with Path(source["uploadedFile"]).open("rb") as input_file:
                identity = "sha256:" + hashlib.file_digest(input_file, "sha256").hexdigest()
        else:
            identity = "url:" + source["url"]
        (out_dir / "source_id.txt").write_text(identity + "\n", encoding="utf-8")
        _write_status(song_id, state="done", finishedAt=time.time())
    except Exception as error:
        with log_path(song_id).open("a", encoding="utf-8") as log:
            log.write(f"\n[backend] {error}\n")
        _write_status(song_id, state="error", error=str(error), finishedAt=time.time())
    finally:
        if source.get("uploadedFile"):
            Path(source["uploadedFile"]).unlink(missing_ok=True)
        with _lock:
            _running.pop(song_id, None)


def submit_job(song_id: str, lyrics_text: str, title: str, *, url: str = "",
              uploaded_audio: Path | None = None, full_key_range: bool = False,
              language: str = "auto") -> dict | None:
    """Start a job from either a YouTube URL or an uploaded audio file
    (exactly one of `url` / `uploaded_audio`). Returns {"error": msg} or
    {"error": msg, "existingSongId": id} if the job could not be started (or
    was skipped because it already exists), else None."""
    if not SONG_ID_RE.match(song_id):
        return {"error": "곡 ID는 영문/숫자/-/_ 만 쓸 수 있습니다."}
    if language not in ("auto", "ja", "ko"):
        return {"error": "지원하지 않는 가사 언어입니다."}
    if bool(url.strip()) == bool(uploaded_audio):
        return {"error": "음원 파일을 올려 주세요."}
    if url and not ALLOW_URL:
        return {"error": "현재는 음원 파일 업로드만 지원합니다."}
    if url and not url.strip().startswith(("http://", "https://")):
        return {"error": "유튜브 링크 형식이 아닙니다."}
    if uploaded_audio and uploaded_audio.suffix.lower() not in (".wav", ".mp4", ".mp3"):
        return {"error": "지원하는 오디오 형식이 아닙니다 (wav/mp4/mp3)."}
    if not lyrics_text.strip():
        return {"error": "가사를 붙여넣어 주세요."}
    if not RUNNER_PYTHON.is_file():
        return {"error": f"실행 환경을 찾을 수 없습니다: {RUNNER_PYTHON}"}
    if any((root / song_id / "assets.json").is_file() for root in LIBRARY_ROOTS):
        return {"error": "이미 사용 중인 곡 ID입니다. 다른 ID를 입력해 주세요.", "existingSongId": song_id}
    existing = find_existing_song(url=url or None, audio_path=uploaded_audio)
    if existing and existing["songId"] != song_id:
        return {"error": f"이 곡은 이미 '{existing['title']}'(으)로 처리되어 있습니다. "
                          "다시 처리하지 않고 그 곡으로 이동하세요.", "existingSongId": existing["songId"]}
    with _lock:
        if any(thread.is_alive() for thread in _running.values()):
            return {"error": "다른 곡을 처리 중입니다. 완료 후 다시 시도해 주세요."}
        if song_id in _running:
            return {"error": "이 ID로 이미 처리 중인 작업이 있습니다."}
        status = get_status(song_id)
        if status and status.get("state") == "running":
            return {"error": "이 ID로 이미 처리 중인 작업이 있습니다."}
        source = {"url": url} if url else {"uploadedFile": str(uploaded_audio)}
        thread = threading.Thread(target=_run, args=(song_id, source, lyrics_text, title, full_key_range, language), daemon=True)
        _running[song_id] = thread
        thread.start()
    return None
