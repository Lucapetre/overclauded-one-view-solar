import { seed } from "./domain";
// v3: Bucharest Sectors 1–6 and Ilfov (fixture site ids, one crew per area). v2 crews
// live in the db, assignments carry kind/area/assignedBy, no supplier-support role and
// no audit page. Older v1/v2 state is ignored so it cannot break the new screens.
const KEY = "solarlens-demo-v3";
const list = (value, fallback) => (Array.isArray(value) ? value : fallback);
export function readDB() {
  let stored;
  try {
    stored = JSON.parse(localStorage.getItem(KEY));
  } catch {
    return seed();
  }
  if (!stored || typeof stored !== "object") return seed();
  const defaults = seed();
  const previousUsers = stored.users || [];
  return {
    ...defaults,
    ...stored,
    users: defaults.users.map((user) => ({
      ...user,
      ...previousUsers.find((saved) => saved.id === user.id),
    })),
    inverters: list(stored.inverters, defaults.inverters),
    crews: list(stored.crews, defaults.crews),
    incidents: list(stored.incidents, defaults.incidents),
    assignments: list(stored.assignments, defaults.assignments),
    plans: list(stored.plans, defaults.plans),
    contracts: stored.contracts || {},
    preferences: stored.preferences || {},
    visits: list(stored.visits, []).map((visit) => ({
      requestType: "other",
      priority: "standard",
      routedTo: "PPC Triage",
      ...visit,
    })),
  };
}
export function saveDB(db) {
  localStorage.setItem(KEY, JSON.stringify(db));
  window.dispatchEvent(new Event("solar-db"));
}
export const resetDB = () => saveDB(seed());
// Replace this boundary with authenticated API calls. Frontend roles are demo UX, not security.
export function mutate(fn) {
  let db = readDB();
  fn(db);
  saveDB(db);
  return db;
}
const mediaDB = () =>
  new Promise((resolve, reject) => {
    const r = indexedDB.open("solarlens-media", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("files");
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
export async function putMedia(id, file) {
  const db = await mediaDB();
  return new Promise((resolve, reject) => {
    const t = db.transaction("files", "readwrite");
    t.objectStore("files").put(file, id);
    t.oncomplete = () => {
      db.close();
      resolve();
    };
    t.onerror = () => reject(t.error);
  });
}
export async function getMedia(id) {
  const db = await mediaDB();
  return new Promise((resolve) => {
    const r = db.transaction("files").objectStore("files").get(id);
    r.onsuccess = () => {
      db.close();
      resolve(r.result);
    };
  });
}
export async function clearMedia() {
  const db = await mediaDB();
  db.transaction("files", "readwrite").objectStore("files").clear();
}
