/**
 * frontend/src/identity.js — farmer identity labelling for the registry.
 *
 * A declaration row carries one of three identity shapes:
 *   - phone-based  (web/WhatsApp, and ALL legacy rows incl. old telegram ids):
 *     display the (masked) phone exactly as before — historical representation
 *     is preserved.
 *   - platform identity (channel='telegram' with sender_id, phone NULL):
 *     render as `Telegram #<id>` — never as a phone number, no PII reveal
 *     machinery (a platform id is not a dialled number).
 * The helper is a plain module so `node --test` can cover it without JSX.
 */

export function isPlatformIdentity(row) {
  return !!row && row.channel === 'telegram' && !!row.sender_id;
}

export function identityLabel(row) {
  if (!row) return '—';
  if (isPlatformIdentity(row)) return `Telegram #${row.sender_id}`;
  return row.phone || '—';
}

/** Stable per-person grouping key: legacy rows keep the historic
 *  name+phone key; platform rows group by name+sender_id. */
export function identityKey(row) {
  return `${row.farmer_name}_${row.sender_id || row.phone || ''}`;
}
