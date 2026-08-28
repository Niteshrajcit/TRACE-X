/**
 * The backend issues no `GET /v1/users` endpoint, so there is no directory
 * to resolve "who am I" against. The JWT the investigator already holds
 * carries their own `sub` (user_id) - decoding it client-side (never
 * trusted for authorization, only for UI convenience like "assign to me")
 * is the only honest way to know it without inventing a user directory.
 */
export interface DecodedTraceXToken {
  sub: string;
  role: string;
  jurisdiction_id: string | null;
  bank_id: string | null;
  exp: number;
}

export function decodeToken(token: string): DecodedTraceXToken | null {
  try {
    const payload = token.split(".")[1];
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");
    const json = decodeURIComponent(
      atob(padded)
        .split("")
        .map((c) => "%" + c.charCodeAt(0).toString(16).padStart(2, "0"))
        .join("")
    );
    return JSON.parse(json) as DecodedTraceXToken;
  } catch {
    return null;
  }
}
