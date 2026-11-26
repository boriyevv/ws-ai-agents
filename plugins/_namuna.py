"""Yangi vosita (ko'nikma) qo'shish namunasi.

Bu fayl nomi '_' bilan boshlangani uchun yuklanmaydi. Ishlatish uchun nusxa oling va nomini '_' siz yozing,
masalan plugins/higgsfield.py. Bot qayta ishga tushganda vosita agentlarga ko'rinadi.
Agent qaysi vositani ko'rishini agents/*.md dagi `tools:` qatori belgilaydi (yoki `all`).
"""
from app.tools import S, tool


@tool("salom_namuna", "Namuna vosita: ismga salom qaytaradi.", {"ism": S("Ism")}, ["ism"])
async def salom_namuna(ctx, ism):
    return {"javob": f"Salom, {ism}!"}


# Amal bajaradigan (yozuvchi) vosita uchun: perm="..." (role_permissions dagi nom), write=True, confirm=True
# qo'shing. Shunda ruxsat, egasi tasdig'i va "ha" tasdig'i avtomatik ishlaydi.
