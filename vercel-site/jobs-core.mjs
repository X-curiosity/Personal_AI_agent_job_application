export const PAGE_SIZE = 30;
const clean = (value, max = 300) => typeof value === 'string' ? value.trim().slice(0, max) : '';
export function safeURL(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || url.port || !/^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/.test(url.hostname) || /\.(local|internal|test|invalid)$/.test(url.hostname)) return null;
    return url.href;
  } catch { return null; }
}
export function readJobs(payload) {
  if (payload?.schemaVersion !== 1 || !Array.isArray(payload.jobs) || payload.jobs.length > 500) throw new Error('Unsupported vacancy snapshot');
  const ids = new Set();
  return payload.jobs.map(raw => {
    if (!raw || !/^job_[a-f0-9]{20}$/.test(raw.id || '') || ids.has(raw.id) || !clean(raw.title) || !clean(raw.company) || !safeURL(raw.url)) throw new Error('Invalid vacancy');
    ids.add(raw.id);
    const locations = Array.isArray(raw.locations) ? raw.locations.slice(0, 20).filter(p => clean(p.label) && Number.isFinite(p.latitude) && Number.isFinite(p.longitude) && Math.abs(p.latitude) <= 85 && Math.abs(p.longitude) <= 180 && ['city', 'country'].includes(p.precision)).map(p => ({label: clean(p.label), city: clean(p.city, 100), country: clean(p.country, 100), latitude: p.latitude, longitude: p.longitude, precision: p.precision})) : [];
    if (!locations.length) throw new Error('Vacancy has no disclosed job location');
    return {id: raw.id, title: clean(raw.title), company: clean(raw.company), companyType: clean(raw.companyType, 60), url: safeURL(raw.url), boardUrl: safeURL(raw.boardUrl), source: clean(raw.source, 50), area: clean(raw.area, 80) || 'Other', skills: Array.isArray(raw.skills) ? raw.skills.slice(0, 20).map(s => clean(s, 60)).filter(Boolean) : [], description: clean(raw.description, 4000), locations, workplace: clean(raw.workplace, 60), employment: clean(raw.employment, 60), sourceTimestamp: clean(raw.sourceTimestamp, 60), sourceTimestampKind: ['published', 'created', 'updated'].includes(raw.sourceTimestampKind) ? raw.sourceTimestampKind : null};
  });
}
export function filterJobs(jobs, filters) {
  const q = clean(filters.q, 200).toLocaleLowerCase('en');
  return jobs.filter(j => (!q || [j.title, j.company, j.area, ...j.skills, ...j.locations.map(p => p.label)].join(' ').toLocaleLowerCase('en').includes(q)) && (!filters.area || j.area === filters.area) && (!filters.type || j.companyType === filters.type) && (!filters.location || j.locations.some(p => p.city === filters.location || p.country === filters.location)));
}
export function readState(search) {
  const p = new URLSearchParams(search);
  return Object.fromEntries(['q', 'area', 'type', 'location', 'job', 'view'].map(k => [k, clean(p.get(k), 200)]));
}
export function stateQuery(state) {
  const p = new URLSearchParams();
  for (const k of ['q', 'area', 'type', 'location', 'job', 'view']) if (state[k]) p.set(k, state[k]);
  return p.toString();
}
export function matchSkills(job, profile) {
  const seen = new Set();
  const wanted = String(profile || '').split(/[,;\n]/).map(s => s.trim()).filter(s => {
    const key = s.toLocaleLowerCase('en');
    if (s.length < 2 || s.length > 60 || seen.has(key)) return false;
    seen.add(key); return true;
  }).slice(0, 30);
  const required = new Set(job.skills.map(s => s.toLocaleLowerCase('en')));
  return wanted.filter(skill => required.has(skill.toLocaleLowerCase('en')));
}
