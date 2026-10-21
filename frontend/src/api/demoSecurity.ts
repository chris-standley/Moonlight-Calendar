// Demo-mode security: a pretend alarm with door, window and motion sensors and three cameras. The camera pictures
// are drawn as SVG (a "live" one moves a little) so the demo needs no real camera.
import {
  AlarmState, Api, ApiError, PopupTarget, SecurityAlert, SecurityCamera, SecurityOptions, SecurityOverview, SecuritySensor, SecuritySettings, Topic,
} from "./types";

type Extras = Pick<Api, "security" | "securityAlerts" | "securityOptions" | "testSecurityAlert" | "setAlarm">;
const ALARM_LABEL: Record<string, string> = {
  disarmed: "Disarmed", arming: "Arming", armed_away: "Armed away", armed_home: "Armed home", armed_night: "Armed night",
  armed_vacation: "Armed vacation",
};

interface Cam { entity_id: string; name: string; person: string; sky: string; ground: string; scene: "drive" | "door" | "garden" }
const CAMS: Cam[] = [
  { entity_id: "camera.front_doorbell", name: "Front door", person: "binary_sensor.front_door_person_detected", sky: "#9cc2e6", ground: "#8a7f72", scene: "door" },
  { entity_id: "camera.driveway", name: "Driveway", person: "binary_sensor.driveway_person_detected", sky: "#a9cbe9", ground: "#6f747c", scene: "drive" },
  { entity_id: "camera.back_garden", name: "Back garden", person: "binary_sensor.back_garden_person_detected", sky: "#b7d3ea", ground: "#5f9a5a", scene: "garden" },
];
const PANEL = { entity_id: "alarm_control_panel.alarm", name: "Alarm", alarmo: true, state: "disarmed" };

const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();
const SENSORS: Omit<SecuritySensor, "armed" | "last_changed">[] = [
  { entity_id: "binary_sensor.front_door", name: "Front door", group: "doors", state: "off", label: "Closed", active: false, available: true },
  { entity_id: "binary_sensor.back_door", name: "Back door", group: "doors", state: "on", label: "Open", active: true, available: true },
  { entity_id: "binary_sensor.garage_door", name: "Garage door", group: "doors", state: "off", label: "Closed", active: false, available: true },
  { entity_id: "binary_sensor.kitchen_window", name: "Kitchen window", group: "windows", state: "off", label: "Closed", active: false, available: true },
  { entity_id: "binary_sensor.lounge_window", name: "Lounge window", group: "windows", state: "off", label: "Closed", active: false, available: true },
  { entity_id: "binary_sensor.hallway_motion", name: "Hallway", group: "motion", state: "on", label: "Motion", active: true, available: true },
  { entity_id: "binary_sensor.lounge_motion", name: "Lounge", group: "motion", state: "off", label: "Clear", active: false, available: true },
  { entity_id: "binary_sensor.landing_motion", name: "Landing", group: "motion", state: "off", label: "Clear", active: false, available: true },
  { entity_id: "binary_sensor.kitchen_smoke", name: "Kitchen smoke", group: "environment", state: "off", label: "Clear", active: false, available: true },
];
const CHANGED = [180, 4, 600, 1440, 2900, 1, 35, 90, 9000];

function scene(c: Cam, live: boolean): string {
  const now = new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const extras = {
    drive: `<rect x="90" y="250" width="190" height="70" rx="18" fill="#3c5a8a"/><rect x="120" y="215" width="120" height="50" rx="14" fill="#4d6fa6"/><circle cx="135" cy="322" r="18" fill="#222"/><circle cx="245" cy="322" r="18" fill="#222"/><path d="M0 360 L640 300 L640 360 Z" fill="#5d6168"/>`,
    door: `<rect x="250" y="90" width="150" height="250" fill="#c9b8a0"/><rect x="285" y="130" width="80" height="210" rx="6" fill="#2f4858"/><circle cx="352" cy="240" r="5" fill="#e3c46b"/><rect x="420" y="150" width="90" height="70" fill="#dfe9f2" stroke="#9aa" stroke-width="5"/>`,
    garden: `<circle cx="150" cy="230" r="70" fill="#3f7d45"/><rect x="142" y="260" width="16" height="70" fill="#6b4b2e"/><rect x="380" y="250" width="140" height="10" fill="#8b6a46"/><rect x="390" y="200" width="10" height="60" fill="#8b6a46"/><rect x="500" y="200" width="10" height="60" fill="#8b6a46"/>`,
  }[c.scene];
  const walker = live
    ? `<g fill="#1f2430"><circle cx="0" cy="228" r="13"/><rect x="-12" y="243" width="24" height="52" rx="10"/><rect x="-10" y="290" width="8" height="40" rx="4"/><rect x="2" y="290" width="8" height="40" rx="4"/><animateTransform attributeName="transform" type="translate" values="470 0; 330 0; 470 0" dur="9s" repeatCount="indefinite"/></g>
       <circle cx="606" cy="26" r="8" fill="#e0475b"><animate attributeName="opacity" values="1;0.2;1" dur="1.2s" repeatCount="indefinite"/></circle>`
    : "";
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360" width="640" height="360">
    <rect width="640" height="360" fill="${c.sky}"/><rect y="230" width="640" height="130" fill="${c.ground}"/>${extras}${walker}
    <rect x="0" y="0" width="640" height="360" fill="#000" opacity="0.06"/>
    <text x="14" y="30" font-family="monospace" font-size="18" fill="#fff" opacity="0.9">${c.name.toUpperCase()}  ${now}</text></svg>`;
  return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
}

export function demoSecurity(emit: (...t: Topic[]) => void, settings: () => SecuritySettings | undefined, checkPin: (pin: string) => void): Extras {
  const tests = new Map<string, number>();
  // The demo alarm's code is the demo PIN.
  const panel = { state: "disarmed", by: "Mum", at: ago(95) };
  const cams = () => {
    const conf = settings()?.cameras ?? {};
    return CAMS.map((c) => ({ ...c, show: conf[c.entity_id]?.show ?? true, personSensor: conf[c.entity_id]?.person ?? c.person }));
  };
  const shown = (): SecurityCamera[] => cams().filter((c) => c.show).map((c) => ({
    entity_id: c.entity_id, name: c.name, available: true, person: !!c.personSensor,
    snapshot_url: scene(c, false), live_url: scene(c, true), video_url: null, video_hd_url: null,
  }));
  const alerts = (): SecurityAlert[] => cams().filter((c) => c.show && (tests.get(c.entity_id) ?? 0) > Date.now()).map((c) => ({
    camera: c.entity_id, name: c.name, since: new Date().toISOString(), test: true, live_url: scene(c, true), snapshot_url: scene(c, false), video_url: null, video_hd_url: null,
  }));
  const alarmEntity = () => settings()?.alarm_entity ?? PANEL.entity_id;
  return {
    async security(): Promise<SecurityOverview> {
      const alarm: AlarmState | null = alarmEntity() ? {
        entity_id: PANEL.entity_id, name: PANEL.name, state: panel.state, label: ALARM_LABEL[panel.state] ?? panel.state,
        armed: panel.state.startsWith("armed_"), alarmo: true, available: true,
        changed_by: panel.by, last_changed: panel.at, next_state: null, delay: null, open_sensors: [],
        modes: ["away", "home", "night"], code_arm_required: false,
      } : null;
      const sensors = SENSORS.map((s, i) => ({ ...s, armed: false, last_changed: ago(CHANGED[i]) }));
      return { configured: true, reachable: true, error: null, sensors_source: "alarmo", alarm, sensors, cameras: shown(), alerts: alerts() };
    },
    securityAlerts: async () => alerts(),
    async securityOptions(): Promise<SecurityOptions> {
      return {
        alarm_entity: alarmEntity(), panels: [PANEL],
        cameras: cams().map((c) => ({ entity_id: c.entity_id, name: c.name, show: c.show, person: c.personSensor, auto_person: settings()?.cameras?.[c.entity_id]?.person == null, default_person: c.person, available: true })),
        person_sensors: CAMS.map((c) => ({ entity_id: c.person, name: `${c.name} Person detected` })),
        sensors_source: "alarmo", sensor_count: SENSORS.length,
        popup: { large: true, compact: true, phone: false, tv: false, ...settings()?.popup } as Record<PopupTarget, boolean>,
      };
    },
    async setAlarm(action, code) {
      if (action === "disarm") {
        if (code !== "1234") throw new ApiError(403, "That code wasn't accepted");
        Object.assign(panel, { state: "disarmed", by: "Demo", at: new Date().toISOString() });
      } else {
        Object.assign(panel, { state: "arming", by: "Demo", at: new Date().toISOString() });
        setTimeout(() => { if (panel.state === "arming") { panel.state = `armed_${action}`; emit("security"); } }, 5_000);
      }
      emit("security");
      return { ok: true, state: panel.state };
    },
    async testSecurityAlert(camera, pin) {
      checkPin(pin);
      if (!cams().some((c) => c.entity_id === camera && c.show)) throw new ApiError(404, "No such camera");
      tests.set(camera, Date.now() + 20_000);
      emit("security_alert");
      setTimeout(() => emit("security_alert"), 20_200);
    },
  };
}
