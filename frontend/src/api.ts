// Python server (app/web.py) bilan aloqa. Cookie avtomatik yuboriladi.

export class AuthError extends Error {}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(path, {
    method: opts.method ?? (opts.body !== undefined ? "POST" : "GET"),
    credentials: "same-origin",
    headers: opts.body !== undefined && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {},
    body:
      opts.body === undefined ? undefined : opts.body instanceof FormData ? opts.body : JSON.stringify(opts.body),
  });
  if (res.status === 401) throw new AuthError("Kirish kerak");
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Xato: ${res.status}`);
  return data as T;
}

// ---------- turlar ----------
export type Role = "owner" | "manager" | "admin" | "teacher";

export interface Me {
  name: string;
  role: Role;
  role_uz: string;
  tools: string[];
  branches: { id: string; name: string; active: boolean }[];
  voice_input: boolean;
}

export interface Group {
  id: string;
  nom: string;
  fan: string;
  filial: string;
  oqituvchi: string | null;
  xona: string | null;
  jadval: string;
  oquvchilar: number;
}

// ---------- formatlash ----------
export const money = (x: number | string | null | undefined) =>
  x === null || x === undefined || x === "" ? "—" : `${Math.round(Number(x)).toLocaleString("ru-RU").replace(/,/g, " ")} so'm`;

/** KPI kartochkalari uchun qisqa: 1 300 000 -> "1,3 mln so'm" */
export const moneyShort = (x: number | string | null | undefined) => {
  if (x === null || x === undefined || x === "") return "—";
  const n = Number(x);
  if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(1).replace(".0", "").replace(".", ",")} mlrd so'm`;
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1).replace(".0", "").replace(".", ",")} mln so'm`;
  return money(n);
};

export const num = (x: number | null | undefined) => (x === null || x === undefined ? "—" : x.toLocaleString("ru-RU"));

export const pct = (x: number | null | undefined) => (x === null || x === undefined ? "—" : `${Math.round(x * 100)}%`);

export const fmtDate = (s: string | null | undefined) => {
  if (!s) return "—";
  const [y, m, d] = s.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
};

export const todayISO = () => {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};

export const PAY_STATE: Record<string, { text: string; tone: "ok" | "bad" | "warn" | "" }> = {
  paid: { text: "To'langan", tone: "ok" },
  window: { text: "To'lov oynasi", tone: "warn" },
  overdue: { text: "Qarz", tone: "bad" },
  not_yet: { text: "Hali erta", tone: "" },
};

export const LEAD_STATUS: Record<string, string> = {
  new: "Yangi",
  contacted: "Aloqa qilindi",
  trial: "Sinov darsi",
  enrolled: "O'quvchi bo'ldi",
  rejected: "Rad etdi",
};

export const STUDENT_STATUS: Record<string, string> = { active: "Faol", frozen: "Muzlatilgan", left: "Ketgan" };

export const DAYS = ["Du", "Se", "Chor", "Pay", "Juma", "Shan", "Yak"];
