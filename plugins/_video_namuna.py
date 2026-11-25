"""AI video generatsiya xizmatini (masalan Higgsfield) ulash uchun namuna.

Hozircha ULANMAGAN: xizmatning API hujjatlari, kaliti va narxi aniq bo'lganda shu fayl asosida ulanadi.
Ishlatish: nusxa oling (masalan plugins/video_ai.py), API chaqiruvini yozing, .env ga kalit qo'shing,
agents/content.md dagi tools: qatoriga "generate_video" ni qo'shing.

Ishlash tartibi (deyarli hamma video-AI xizmatlarida bir xil):
  1) prompt (va ixtiyoriy rasm) bilan vazifa yaratiladi -> job id
  2) bir necha soniyada bir holat so'raladi, tayyor bo'lsa video havolasi olinadi
  3) video social.upload_public bilan Supabase'ga yuklanadi va publish_post ga media_url sifatida beriladi
Video pullik (kredit) bo'lgani uchun confirm=True: Jimi har safar narx va promptni aytib "ha" kutadi.
"""
import os

from app import social
from app.core import ToolError
from app.tools import S, tool


@tool("generate_video", "AI bilan qisqa video yaratadi (prompt bo'yicha) va ochiq havolasini qaytaradi.",
      {"prompt": S("Video tavsifi (ingliz tilida aniqroq ishlaydi)"), "aspect": S("9:16 | 16:9 | 1:1")},
      ["prompt"], perm="publish_post", write=True, confirm=True)
async def generate_video(ctx, prompt, aspect="9:16"):
    key = os.getenv("VIDEO_AI_KEY")
    if not key:
        raise ToolError("Video AI xizmati ulanmagan (.env da VIDEO_AI_KEY yo'q).")
    # 1) job = await create_job(key, prompt, aspect)
    # 2) url = await wait_result(key, job)
    # 3) data = ...yuklab olish...; public = await social.upload_public(data, "mp4", "video/mp4")
    raise ToolError("generate_video hali yozilmagan: plugins/_video_namuna.py ga qarang.")
