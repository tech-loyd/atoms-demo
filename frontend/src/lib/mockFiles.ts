import type { ProjectFile } from "./types";

/**
 * 代码视图的占位数据(Alex 未产出 files 时使用)。
 * 文件树示例(supabase.ts / Auth.tsx / HabitCard.tsx / Heatmap.tsx / App.tsx),
 * 代码为自写真实可读示例。Alex 产出 files 后 CodeView 自动切到真实代码。
 */
export const mockFiles: ProjectFile[] = [
  {
    path: "src/lib/supabase.ts",
    language: "ts",
    status: "done",
    content: `import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

// 内存存储兜底(iframe/Sandpack 里 localStorage 受限时用)
const memoryStore: Record<string, string> = {};

export const supabase = createClient(url, anonKey, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    storage: typeof window !== "undefined" ? window.localStorage : memoryStore,
  },
});
`,
  },
  {
    path: "src/components/Auth.tsx",
    language: "tsx",
    status: "done",
    content: `import { useState } from "react";
import { supabase } from "@/lib/supabase";

export function Auth() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) alert(error.message);
    setLoading(false);
  }

  return (
    <form onSubmit={handleSubmit} className="auth-form">
      <h2>登录 HabitFlow</h2>
      <input
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="邮箱"
        required
      />
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="密码"
        required
      />
      <button type="submit" disabled={loading}>
        {loading ? "登录中…" : "登录"}
      </button>
    </form>
  );
}
`,
  },
  {
    path: "src/components/HabitCard.tsx",
    language: "tsx",
    status: "done",
    content: `import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";

interface Habit {
  id: string;
  name: string;
  color: string;
}

export function HabitCard({ habit }: { habit: Habit }) {
  const [done, setDone] = useState(false);
  const today = new Date().toISOString().slice(0, 10);

  useEffect(() => {
    supabase
      .from("checkins")
      .select("date")
      .eq("habit_id", habit.id)
      .eq("date", today)
      .maybeSingle()
      .then(({ data }) => setDone(!!data));
  }, [habit.id, today]);

  async function toggle() {
    if (done) {
      await supabase.from("checkins").delete().eq("habit_id", habit.id).eq("date", today);
    } else {
      await supabase.from("checkins").insert({ habit_id: habit.id, date: today });
    }
    setDone(!done);
  }

  return (
    <div className="habit-card" style={{ borderLeftColor: habit.color }}>
      <span className="habit-name">{habit.name}</span>
      <button className="check-btn" onClick={toggle} aria-label="打卡">
        {done ? "✓" : "○"}
      </button>
    </div>
  );
}
`,
  },
  {
    path: "src/components/Heatmap.tsx",
    language: "tsx",
    status: "done",
    content: `const DAYS = 365;

interface Props {
  // key=日期(YYYY-MM-DD), value=当天打卡习惯数
  checkins: Record<string, number>;
}

export function Heatmap({ checkins }: Props) {
  const days = Array.from({ length: DAYS }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - (DAYS - 1 - i));
    const key = d.toISOString().slice(0, 10);
    return { key, count: checkins[key] ?? 0 };
  });

  return (
    <div className="heatmap">
      {days.map((d) => (
        <div
          key={d.key}
          className="cell"
          title={d.key + ": " + d.count + " 个习惯"}
          style={{ opacity: 0.15 + Math.min(d.count, 4) * 0.21 }}
        />
      ))}
    </div>
  );
}
`,
  },
  {
    path: "src/App.tsx",
    language: "tsx",
    status: "done",
    content: `import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { Auth } from "@/components/Auth";
import { HabitCard } from "@/components/HabitCard";
import { Heatmap } from "@/components/Heatmap";

const SEED_HABITS = [
  { id: "1", name: "晨跑 5 公里", color: "#4267ff" },
  { id: "2", name: "阅读 30 分钟", color: "#7c3aed" },
  { id: "3", name: "冥想 10 分钟", color: "#0d9488" },
];

export default function App() {
  const [userId, setUserId] = useState<string | null>(null);

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => setUserId(data.user?.id ?? null));
    const { data: sub } = supabase.auth.onAuthStateChange((_e, session) => {
      setUserId(session?.user?.id ?? null);
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  if (!userId) return <Auth />;

  return (
    <main className="app">
      <header>
        <h1>HabitFlow</h1>
        <button onClick={() => supabase.auth.signOut()}>退出</button>
      </header>
      <section className="habits">
        {SEED_HABITS.map((h) => (
          <HabitCard key={h.id} habit={h} />
        ))}
      </section>
      <section className="heatmap-section">
        <h2>年度热力图</h2>
        <Heatmap checkins={{}} />
      </section>
    </main>
  );
}
`,
  },
];
