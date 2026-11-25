"""Video tahrirlash (ffmpeg): qirqish, vertikal 9:16 (Reels/Shorts/TikTok), sarlavha, avtomatik subtitr.

ffmpeg kompyuterda o'rnatilgan bo'lishi kerak (README: "Video agenti").
"""
import asyncio
import pathlib
import shutil
import tempfile

from . import voice
from .core import ToolError

FONTS = pathlib.Path(__file__).resolve().parent.parent / "assets" / "fonts"
MAX_SECONDS = 180


def available():
    return bool(shutil.which("ffmpeg"))


async def _run(args, cwd):
    proc = await asyncio.create_subprocess_exec("ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args, cwd=cwd,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise ToolError("Video ishlanmadi: " + err.decode(errors="ignore")[-300:])


async def duration(path, cwd):
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path), cwd=cwd,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, _ = await proc.communicate()
    try:
        return float(out.decode().strip())
    except ValueError:
        return 0.0


def _ts(sec):
    h, rem = divmod(max(sec, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02}:{int(m):02}:{int(s):02},{int(round((s - int(s)) * 1000)):03}"


def to_srt(lines):
    return "\n".join(f"{i}\n{_ts(a)} --> {_ts(b)}\n{t}\n" for i, (a, b, t) in enumerate(lines, 1))


def parse_time(v):
    """'1:05', '65', '00:01:05' -> soniya"""
    if v in (None, ""):
        return None
    parts = [float(p) for p in str(v).replace(",", ".").split(":")]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


async def edit(src: bytes, start=None, end=None, vertical=True, subtitles=False, title=None):
    """Qaytaradi: (mp4 bytes, ma'lumot dict)"""
    if not available():
        raise ToolError("ffmpeg o'rnatilmagan. README dagi 'Video agenti' bo'limiga qarang.")
    s, e = parse_time(start), parse_time(end)
    info = {}
    with tempfile.TemporaryDirectory() as tmp:
        cwd = pathlib.Path(tmp)
        (cwd / "in.mp4").write_bytes(src)
        total = await duration("in.mp4", cwd)
        s = s or 0.0
        e = min(e, total) if e and total else (e or total)
        if not e or e <= s:
            raise ToolError("Boshlanish/tugash vaqti noto'g'ri.")
        if e - s > MAX_SECONDS:
            e = s + MAX_SECONDS
            info["eslatma"] = f"Video {MAX_SECONDS} soniyaga qisqartirildi."
        cut = ["-ss", f"{s:.2f}", "-to", f"{e:.2f}", "-i", "in.mp4"]
        filters = []
        if vertical:
            # Asl kadr to'liq ko'rinadi, bo'sh joy xiralashtirilgan fon bilan to'ldiriladi
            filters.append("split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                           "boxblur=24:2[bg];[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")
        else:
            filters.append("scale='min(1080,iw)':-2,setsar=1")
        shutil.copy(FONTS / "DejaVuSans-Bold.ttf", cwd / "font.ttf")
        if title:
            (cwd / "title.txt").write_text(title.strip()[:60], encoding="utf-8")
            filters.append("drawtext=fontfile=font.ttf:textfile=title.txt:fontcolor=white:fontsize=58:"
                           "box=1:boxcolor=0x0b0451@0.75:boxborderw=24:x=(w-tw)/2:y=h*0.09")
        if subtitles:
            await _run(cut + ["-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", "audio.mp3"], cwd)
            lines = await voice.transcribe_timed((cwd / "audio.mp3").read_bytes())
            if lines:
                (cwd / "subs.srt").write_text(to_srt(lines), encoding="utf-8")
                (cwd / "fonts").mkdir()
                shutil.copy(FONTS / "DejaVuSans-Bold.ttf", cwd / "fonts" / "DejaVuSans-Bold.ttf")
                style = ("FontName=DejaVu Sans,Bold=1,FontSize=12,PrimaryColour=&H00FFFFFF,OutlineColour=&H00510B0B,"
                         "BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=" + ("70" if vertical else "25"))
                filters.append(f"subtitles=subs.srt:fontsdir=fonts:force_style='{style}'")
                info["subtitr_qatorlari"] = len(lines)
            else:
                info["subtitr"] = "Nutq topilmadi, subtitrsiz tayyorlandi."
        await _run(cut + ["-vf", ",".join(filters), "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                          "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "out.mp4"], cwd)
        out = (cwd / "out.mp4").read_bytes()
    info["davomiylik_soniya"] = round(e - s, 1)
    info["format"] = "9:16 vertikal" if vertical else "asl nisbat"
    return out, info
