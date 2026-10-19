// Demo-mode nursery updates (a pretend Tapestry account, already connected). Photos are painted on a canvas at runtime
// so the single-file preview stays small. Kept in memory only.
import { Api, ApiError, NurseryConfig, NurseryUpdate, Topic } from "./types";
import { addDays, today } from "../dates";

type Extras = Pick<Api, "nursery" | "saveNursery" | "disconnectNursery" | "syncNursery" | "nurseryUpdates">;
type Scene = "blocks" | "rainbow" | "puddles" | "baking" | "garden" | "music";

function paint(scene: Scene, seed: number): string {
  const w = 1200, h = 900;
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  const g = c.getContext("2d")!;
  let s = seed;
  const r = () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
  const bright = ["#F0679A", "#4F7CEC", "#FFB938", "#2FB58A", "#9B6BE0", "#FF7A45"];
  const floor = (top: string, bottom: string) => { const gr = g.createLinearGradient(0, 0, 0, h); gr.addColorStop(0, top); gr.addColorStop(1, bottom); g.fillStyle = gr; g.fillRect(0, 0, w, h); };
  if (scene === "blocks") {
    floor("#F6E9D8", "#E2C9A6");
    g.fillStyle = "#C9A57C"; g.fillRect(0, h * 0.72, w, h * 0.28);
    for (let i = 0; i < 10; i++) {
      const bw = 150 - i * 4, x = w / 2 - bw / 2 + (r() - 0.5) * 24, y = h * 0.72 - (i + 1) * 58;
      g.fillStyle = bright[i % bright.length]; g.fillRect(x, y, bw, 56);
      g.fillStyle = "rgba(255,255,255,0.25)"; g.fillRect(x + 8, y + 8, bw - 16, 10);
    }
  } else if (scene === "rainbow") {
    floor("#FFFDF7", "#F3EEE2");
    ["#E0475B", "#FF7A45", "#FFB938", "#2FB58A", "#4F7CEC", "#9B6BE0"].forEach((col, i) => {
      g.strokeStyle = col; g.lineWidth = 46; g.lineCap = "round";
      g.beginPath(); g.arc(w / 2, h * 0.86, 420 - i * 50 + (r() - 0.5) * 10, Math.PI * 1.04, Math.PI * 1.96); g.stroke();
    });
    g.fillStyle = "#FFFFFF"; [[260, 700], [940, 700]].forEach(([x, y]) => { for (let k = 0; k < 4; k++) { g.beginPath(); g.arc(x + k * 46 - 70, y - (k % 2) * 30, 60, 0, Math.PI * 2); g.fill(); } });
  } else if (scene === "puddles" || scene === "garden") {
    floor("#BFE0F7", "#EAF5FB");
    g.fillStyle = scene === "garden" ? "#6FB35A" : "#5C8F4A"; g.fillRect(0, h * 0.58, w, h * 0.42);
    for (let i = 0; i < 6; i++) {
      const x = 80 + i * 200 + r() * 60;
      g.fillStyle = "#7A5236"; g.fillRect(x, h * 0.3, 26, h * 0.3);
      g.fillStyle = scene === "garden" ? "#3E8E41" : "#C4713F"; g.beginPath(); g.arc(x + 13, h * 0.28, 90, 0, Math.PI * 2); g.fill();
    }
    if (scene === "puddles") {
      g.fillStyle = "#6FA8D8"; g.beginPath(); g.ellipse(w * 0.5, h * 0.8, 300, 70, 0, 0, Math.PI * 2); g.fill();
      g.fillStyle = "#FFD23F"; g.fillRect(w * 0.47, h * 0.55, 70, 140); // a yellow welly
    } else {
      for (let i = 0; i < 18; i++) { g.fillStyle = bright[i % bright.length]; g.beginPath(); g.arc(60 + r() * (w - 120), h * 0.65 + r() * h * 0.3, 18, 0, Math.PI * 2); g.fill(); }
    }
  } else if (scene === "baking") {
    floor("#FCEFE3", "#F4D9C0");
    g.fillStyle = "#B0B6C3"; g.fillRect(w * 0.12, h * 0.25, w * 0.76, h * 0.55);
    for (let i = 0; i < 12; i++) {
      const x = w * 0.2 + (i % 4) * w * 0.2, y = h * 0.35 + Math.floor(i / 4) * h * 0.16;
      g.fillStyle = "#E3A857"; g.beginPath(); g.arc(x, y, 58, 0, Math.PI * 2); g.fill();
      g.fillStyle = bright[i % bright.length]; for (let k = 0; k < 5; k++) g.fillRect(x - 30 + r() * 50, y - 30 + r() * 50, 10, 10);
    }
  } else {
    floor("#E8E4F8", "#D5CDF2");
    g.fillStyle = "#FFB938"; g.beginPath(); g.ellipse(w * 0.35, h * 0.6, 160, 110, 0, 0, Math.PI * 2); g.fill();
    g.fillStyle = "#7A5236"; g.fillRect(w * 0.35 + 120, h * 0.2, 30, h * 0.4);
    g.fillStyle = "#4F7CEC"; g.fillRect(w * 0.6, h * 0.45, 260, 160);
    g.fillStyle = "#FFFFFF"; for (let k = 0; k < 6; k++) g.fillRect(w * 0.6 + 14 + k * 40, h * 0.45 + 20, 26, 120);
  }
  return c.toDataURL("image/jpeg", 0.82);
}

interface Seed { days: number; time: string; title: string; notes: string; author: string; scenes: Scene[]; video?: number; comment?: string }
const SEEDS: Seed[] = [
  { days: 0, time: "11:20:00", title: "Tallest tower yet!", author: "Miss Patel", scenes: ["blocks"],
    notes: "Leo built a tower of ten blocks today, choosing the biggest ones for the bottom so it wouldn't wobble. He counted every block out loud and asked his friends to count with him.\n\nNext steps: we'll try sorting the blocks by colour and size." },
  { days: 0, time: "09:05:00", title: "Morning music circle", author: "Mr Okafor", scenes: ["music", "music"], video: 1,
    notes: "Leo joined in with the shakers and kept a steady beat during \"The wheels on the bus\". He chose the drum for the last song." },
  { days: 1, time: "14:40:00", title: "Puddle jumping at forest school", author: "Miss Patel", scenes: ["puddles", "garden", "puddles"],
    notes: "Wellies on! Leo found the biggest puddle and measured how deep it was with a stick. He described the splash as \"a giant wave\".",
    comment: "He hasn't stopped talking about it! Thank you." },
  { days: 3, time: "10:15:00", title: "Rainbow painting", author: "Mrs Hughes", scenes: ["rainbow"],
    notes: "Leo mixed his own orange from red and yellow and painted a rainbow with all six colours in the right order." },
  { days: 6, time: "13:30:00", title: "Baking biscuits", author: "Mr Okafor", scenes: ["baking", "baking"],
    notes: "We weighed flour and butter together. Leo cut out stars and circles and decorated them with sprinkles, then shared them at snack time." },
];

export function demoNursery(checkPin: (pin: string) => void, emit: (...t: Topic[]) => void,
  people: () => { id: string; name: string; color: string }[]): Extras {
  let connected = true;
  let email = "parents@example.com";
  let photos: string[][] | null = null;
  let lastSync = new Date().toISOString();
  const pics = () => (photos ??= SEEDS.map((sd, i) => sd.scenes.map((sc, k) => paint(sc, 7 + i * 101 + k * 13))));
  const config = (): NurseryConfig => connected
    ? { configured: true, email, school: "", school_name: "Little Acorns Nursery", status: "ok", last_error: null, last_sync: lastSync, count: SEEDS.length }
    : { configured: false, email: "", school: "", school_name: null, status: "unconfigured", last_error: null, last_sync: null, count: 0 };
  return {
    nursery: async () => config(),
    async saveNursery(c) {
      checkPin(c.pin);
      await new Promise((ok) => setTimeout(ok, 700)); // "signing in to Tapestry"
      if (!c.email?.includes("@")) throw new ApiError(400, "Enter the email address you sign in to Tapestry with");
      if (!connected && !c.password) throw new ApiError(400, "Enter your Tapestry password");
      connected = true; email = c.email; lastSync = new Date().toISOString();
      emit("nursery");
      return config();
    },
    async disconnectNursery(pin) { checkPin(pin); connected = false; emit("nursery"); },
    async syncNursery() { lastSync = new Date().toISOString(); emit("nursery"); return config(); },
    async nurseryUpdates(): Promise<NurseryUpdate[]> {
      if (!connected) return [];
      const kid = people().find((p) => p.name === "Leo");
      const p = pics();
      return SEEDS.map((sd, i) => ({
        id: `obs_${i + 1}`, title: sd.title, notes: sd.notes, author: sd.author, date: `${addDays(today(), -sd.days)}T${sd.time}`,
        children: [{ name: "Leo", person_id: kid?.id ?? null, color: kid?.color ?? null }],
        photos: p[i].map((url, k) => ({ url, video: sd.video === k })),
        comments: sd.comment ? [{ author: "Alex", date: null, text: sd.comment }] : [],
        added_at: lastSync,
      }));
    },
  };
}
