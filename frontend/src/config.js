/**
 * src/config.js — Centralized runtime configuration
 *
 * VITE_API_URL is injected at build time via the .env / .env.production file.
 * During local dev it falls back to http://localhost:8000 so nothing breaks.
 * When building for production, set VITE_API_URL to your deployed backend domain
 * (e.g. https://api.kisanmitra.in) in the .env.production file or the CI
 * environment so the built PWA always reaches the real server.
 */
// Optional chaining keeps this module importable from plain `node --test`
// (api.js dependency), where import.meta.env does not exist; Vite replaces
// import.meta.env with a real object at build time either way.
export const API = import.meta.env?.VITE_API_URL ?? "http://localhost:8000";

/**
 * derive_current_season()
 *
 * Returns the active agronomic season for Karnataka — identical logic to
 * backend/core/dates.py so both layers always agree.
 *
 * Kharif : June – October   (returns "Kharif <year>")
 * Rabi   : November – March  (returns "Rabi <year>-<year+1>")
 * Zaid   : April – May       (returns "Summer <year>")
 */
export function derive_current_season() {
  const now = new Date();
  const month = now.getMonth() + 1; // 1-indexed
  const year = now.getFullYear();
  if (month >= 6 && month <= 10) return `Kharif ${year}`;
  if (month >= 11) return `Rabi ${year}-${year + 1}`;
  if (month <= 3) return `Rabi ${year - 1}-${year}`;
  return `Summer ${year}`; // April–May (Zaid)
}

/**
 * Generates the rolling list of season options for a dropdown, covering
 * the previous season, the current season, and the next two.
 */
export function get_season_options() {
  const now = new Date();
  const year = now.getFullYear();
  const options = [];
  // Emit: Rabi (prev), Kharif (this), Rabi (this), Kharif (next)
  options.push(`Rabi ${year - 1}-${year}`);
  options.push(`Summer ${year}`);
  options.push(`Kharif ${year}`);
  options.push(`Rabi ${year}-${year + 1}`);
  options.push(`Kharif ${year + 1}`);
  return [...new Set(options)]; // deduplicate
}
