"""Botga yuborilgan fayllarni Jimi tushunadigan ko'rinishga keltirish: PDF, Word, Excel, matn, rasm."""
import base64
import io
import re
import zipfile

MAX_TEXT = 40000
IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _decode(data):
    for enc in ("utf-8", "utf-16", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="ignore")


def _docx(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _xlsx(data):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        out.append(f"### Varaq: {ws.title}")
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= 300:
                out.append("... (qolgan qatorlar qisqartirildi)")
                break
            if any(c is not None for c in row):
                out.append("\t".join("" if c is None else str(c) for c in row))
    return "\n".join(out)


def to_attachment(name, mime, data):
    """-> attachment dict yoki None (qo'llab-quvvatlanmaydigan fayl)."""
    name = name or "fayl"
    low = name.lower()
    mime = (mime or "").lower()
    if mime in IMAGE_TYPES or low.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        if len(data) > 5 * 1024 * 1024:
            return {"kind": "text_file", "name": name, "text": "(rasm 5 MB dan katta, Jimi uni ko'ra olmaydi)"}
        m = mime if mime in IMAGE_TYPES else "image/png" if low.endswith(".png") else "image/jpeg"
        return {"kind": "photo", "name": name, "mime": m, "b64": base64.b64encode(data).decode()}
    if mime == "application/pdf" or low.endswith(".pdf"):
        return {"kind": "pdf", "name": name, "b64": base64.b64encode(data).decode()}
    try:
        if low.endswith(".docx"):
            text = _docx(data)
        elif low.endswith((".xlsx", ".xlsm")):
            text = _xlsx(data)
        elif low.endswith((".txt", ".csv", ".md", ".json", ".tsv", ".log", ".html", ".xml")) or mime.startswith("text/"):
            text = _decode(data)
        else:
            return None
    except Exception as e:
        return {"kind": "text_file", "name": name, "text": f"(faylni o'qib bo'lmadi: {e})"}
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + "\n... (fayl qisqartirildi)"
    return {"kind": "text_file", "name": name, "text": text}
