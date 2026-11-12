/**
 * The extension token lives in chrome.storage.session (cleared when the browser closes)
 * unless the user ticked "Remember this browser", which uses chrome.storage.local.
 */

export interface Connection {
  token: string;
  organizationName: string;
  userEmail: string;
  expiresAt: string;
}

const KEY = "connection";
const PENDING = "pendingPairing";

export async function getConnection(): Promise<Connection | null> {
  const session = await chrome.storage.session.get(KEY);
  const local = await chrome.storage.local.get(KEY);
  return (session[KEY] as Connection | undefined) ?? (local[KEY] as Connection | undefined) ?? null;
}

export async function saveConnection(connection: Connection, remember: boolean): Promise<void> {
  await clearConnection();
  await (remember ? chrome.storage.local : chrome.storage.session).set({ [KEY]: connection });
}

export async function clearConnection(): Promise<void> {
  await chrome.storage.session.remove(KEY);
  await chrome.storage.local.remove(KEY);
}

export interface PendingPairing {
  verifier: string;
  remember: boolean;
  createdAt: number;
}

export async function savePending(pending: PendingPairing): Promise<void> {
  await chrome.storage.session.set({ [PENDING]: pending });
}

export async function getPending(): Promise<PendingPairing | null> {
  const value = (await chrome.storage.session.get(PENDING))[PENDING] as PendingPairing | undefined;
  return value && Date.now() - value.createdAt < 15 * 60_000 ? value : null;
}

export async function clearPending(): Promise<void> {
  await chrome.storage.session.remove(PENDING);
}
