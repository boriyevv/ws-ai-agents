import { useEffect, useRef, useState } from "react";
import { api, AuthError } from "../api";
import { PageHead, useApp } from "../ui";

interface Msg { role: "user" | "assistant"; content: string; pending?: boolean }

const SUGGESTIONS: Record<string, string[]> = {
  owner: ["Jimi, bugun nimalarga e'tibor beraylik?", "Jimi, qarzdorlar kimlar?", "Jimi, shu oy moliyaviy xulosa", "Jimi, qaysi manba lidlari o'quvchiga ko'proq aylanyapti?", "Jimi, bu hafta uchun post g'oyalari ber"],
  manager: ["Jimi, qarzdorlar kimlar?", "Jimi, javobsiz lidlar bormi?", "Jimi, davomat kiritilmagan guruhlar"],
  admin: ["Jimi, bugungi darslar", "Jimi, to'lov oynasi ochiq o'quvchilar", "Jimi, yangi lid qo'sh"],
  teacher: ["Jimi, mening guruhlarim natijalari", "Jimi, bugungi davomat"],
};

export default function Chat() {
  const { me, toast, onAuthError } = useApp();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [speak, setSpeak] = useState(() => localStorageGet("jimi_speak") === "1");
  const [rec, setRec] = useState<MediaRecorder | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api<{ xabarlar: Msg[] }>("/api/chat").then((d) => setMsgs(d.xabarlar)).catch((e) => e instanceof AuthError && onAuthError());
  }, [onAuthError]);
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [msgs]);
  useEffect(() => localStorageSet("jimi_speak", speak ? "1" : "0"), [speak]);

  const play = (b64: string | null) => {
    if (b64) new Audio(`data:audio/mpeg;base64,${b64}`).play().catch(() => {});
  };

  const fail = (e: unknown) => {
    if (e instanceof AuthError) return onAuthError();
    toast((e as Error).message, true);
    setMsgs((m) => m.filter((x) => !x.pending));
  };

  const send = async (t = text) => {
    const q = t.trim();
    if (!q || busy) return;
    setText("");
    setBusy(true);
    setMsgs((m) => [...m, { role: "user", content: q }, { role: "assistant", content: "Jimi o'ylayapti…", pending: true }]);
    try {
      const r = await api<{ javob: string; audio: string | null }>("/api/chat", { body: { text: q, speak } });
      setMsgs((m) => [...m.filter((x) => !x.pending), { role: "assistant", content: r.javob }]);
      play(r.audio);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const toggleMic = async () => {
    if (rec) return rec.stop();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      mr.ondataavailable = (e) => chunks.push(e.data);
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setRec(null);
        const blob = new Blob(chunks, { type: mr.mimeType || "audio/webm" });
        if (blob.size < 2000) return toast("Ovoz juda qisqa", true);
        const fd = new FormData();
        fd.append("audio", blob, mr.mimeType.includes("mp4") ? "voice.mp4" : "voice.webm");
        setBusy(true);
        setMsgs((m) => [...m, { role: "assistant", content: "Eshityapman…", pending: true }]);
        try {
          const r = await api<{ eshitildi: string; javob: string; audio: string | null }>("/api/voice", { body: fd });
          setMsgs((m) => [...m.filter((x) => !x.pending), { role: "user", content: `🎤 ${r.eshitildi}` }, { role: "assistant", content: r.javob }]);
          play(r.audio);
        } catch (e) {
          fail(e);
        } finally {
          setBusy(false);
        }
      };
      mr.start();
      setRec(mr);
    } catch {
      toast("Mikrofonga ruxsat berilmadi", true);
    }
  };

  return (
    <div className="stack">
      <PageHead title="Jimi">
        <label className="row small" style={{ gap: 6 }}>
          <input type="checkbox" checked={speak} onChange={(e) => setSpeak(e.target.checked)} style={{ width: "auto", minHeight: 0 }} />
          Javobni ovozda o'qish
        </label>
      </PageHead>
      <div className="card chat">
        <div className="chat-log" ref={logRef}>
          {msgs.length === 0 && (
            <div className="msg assistant">
              Salom, {me.name.split(" ")[0]}! Men Jimi. Telegramdagi bilan bir xil ishlarni shu yerda ham bajaraman:
              davomat, to'lov, lidlar, hisobot, maslahat. Yozing yoki 🎤 tugmasini bosib gapiring.
            </div>
          )}
          {msgs.map((m, i) => (
            <div key={i} className={`msg ${m.role} ${m.pending ? "thinking" : ""}`}>{m.content}</div>
          ))}
        </div>
        <div className="chips">
          {(SUGGESTIONS[me.role] ?? []).map((s) => (
            <button key={s} disabled={busy} onClick={() => send(s)}>{s}</button>
          ))}
        </div>
        <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <textarea
            rows={1}
            value={text}
            placeholder="Jimiga yozing: «Jimi, …» (Enter — yuborish, Shift+Enter — yangi qator)"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          {me.voice_input && (
            <button type="button" className={`mic ${rec ? "rec" : ""}`} onClick={toggleMic} disabled={busy && !rec}
              aria-label={rec ? "Yozishni to'xtatish" : "Ovozli buyruq"}>
              {rec ? "■ To'xtatish" : "🎤"}
            </button>
          )}
          <button className="primary" disabled={busy || !text.trim()}>Yuborish</button>
        </form>
      </div>
    </div>
  );
}

function localStorageGet(k: string) {
  try { return localStorage.getItem(k); } catch { return null; }
}
function localStorageSet(k: string, v: string) {
  try { localStorage.setItem(k, v); } catch { /* shaxsiy rejim */ }
}
