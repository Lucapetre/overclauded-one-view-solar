import { seed } from "./domain";
const KEY = "solarlenes-demo-v1";
export function readDB() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || seed();
  } catch {
    return seed();
  }
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
export function audit(db, user, action, subject) {
  db.audit.unshift({
    id: crypto.randomUUID(),
    actor: user.name,
    action,
    subject,
    time: new Date().toISOString(),
  });
}
const mediaDB = () =>
  new Promise((resolve, reject) => {
    const r = indexedDB.open("solarlenes-media", 1);
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
