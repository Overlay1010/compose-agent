"""음원 변환: 브라우저가 렌더한 WAV를 ffmpeg로 MP3 · FLAC · OGG · M4A · MP4로 바꾼다.

렌더링(악기 샘플 · 드럼 킷 · 효과)은 재생과 똑같은 소리를 내려고 브라우저(Tone.js Offline)에서 하고,
브라우저가 못 만드는 형식만 서버가 바꾼다. ffmpeg가 없으면 503 (WAV는 브라우저에서 바로 받을 수 있다).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

router = APIRouter(prefix="/audio", tags=["audio"])

MAX_WAV_BYTES = 300 * 1024 * 1024  # 44.1kHz 스테레오 16비트로 약 28분
FFMPEG_TIMEOUT = 180

# 형식 → (ffmpeg 인자, MIME)
FORMATS: dict[str, tuple[list[str], str]] = {
    "mp3": (["-codec:a", "libmp3lame", "-b:a", "320k"], "audio/mpeg"),
    "flac": (["-codec:a", "flac"], "audio/flac"),
    "ogg": (["-codec:a", "libvorbis", "-q:a", "7"], "audio/ogg"),
    "m4a": (["-codec:a", "aac", "-b:a", "256k", "-movflags", "+faststart"], "audio/mp4"),
    "mp4": (["-codec:a", "aac", "-b:a", "256k", "-movflags", "+faststart"], "video/mp4"),  # 영상 없이 소리만
}


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


@router.get("/formats")
def formats() -> dict[str, list[str]]:
    """서버에서 바꿀 수 있는 형식 (ffmpeg가 없으면 빈 목록 → 화면은 WAV만 보여 준다)."""
    return {"formats": list(FORMATS) if ffmpeg_path() else []}


@router.post("/convert")
async def convert(request: Request, format: str, name: str = "song") -> Response:
    if format not in FORMATS:
        raise _error(400, "unknown_format", f"지원하는 형식: {', '.join(FORMATS)}")
    ffmpeg = ffmpeg_path()
    if ffmpeg is None:
        raise _error(503, "ffmpeg_missing", "서버에 ffmpeg가 없어 WAV로만 내보낼 수 있어요.")
    data = await request.body()
    if len(data) > MAX_WAV_BYTES:
        raise _error(413, "too_large", "음원이 너무 길어요 (최대 약 28분).")
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise _error(400, "not_wav", "WAV 파일이 아니에요.")

    args, media_type = FORMATS[format]
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.wav", Path(tmp) / f"out.{format}"
        src.write_bytes(data)
        try:
            done = subprocess.run(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), *args, str(dst)],
                capture_output=True, timeout=FFMPEG_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            raise _error(504, "convert_timeout", "변환이 너무 오래 걸려 멈췄어요.")
        if done.returncode != 0 or not dst.exists():
            raise _error(500, "convert_failed", f"변환하지 못했어요: {done.stderr.decode(errors='replace')[-300:]}")
        out = dst.read_bytes()

    filename = f"{Path(name).name or 'song'}.{format}"
    return Response(
        content=out,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
