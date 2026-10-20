// Pure functions shared by the public explorer and its Node tests.
export const STAGES = Object.freeze({early: 'Early stage', growth: 'Growth', scaleup: 'Scale-up', big: 'Big company', unknown: 'Stage unknown'});
export const SIGNALS = Object.freeze({directory_flag: 'Directory hiring flag', board_snapshot: 'Board snapshot', unknown: 'Hiring unknown'});
export const PAGE_SIZE = 30;
const normalize = value => String(value ?? '').trim().toLocaleLowerCase('en');

export function safeURL(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || url.port || !url.hostname.includes('.') || /[\u0000-\u0020\u007f]/.test(value)) return null;
    // Reject all IP literals (including alternate numeric forms normalized by
    // URL), single-label hosts and reserved local/testing domains.
    if (!/^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/.test(url.hostname) || /\.(local|internal|localhost|test|invalid)$/.test(url.hostname)) return null;
    return url.href;
  } catch { return null; }
}

export function hasPoint(company) {
  return Number.isFinite(company.latitude) && Number.isFinite(company.longitude)
    && Math.abs(company.latitude) <= 85 && Math.abs(company.longitude) <= 180
    && ['city', 'country'].includes(company.precision);
}

export function readCatalogue(payload) {
  if (payload?.schemaVersion !== 1 || !Array.isArray(payload.companies) || payload.companies.length > 10000) throw new Error('Unsupported company catalogue.');
  const ids = new Set();
  const companies = payload.companies.map(raw => {
    if (!raw || typeof raw.id !== 'string' || !/^[a-zA-Z0-9_-]{1,100}$/.test(raw.id) || ids.has(raw.id) || typeof raw.name !== 'string' || !raw.name.trim()) throw new Error('Invalid company record.');
    ids.add(raw.id);
    const text = (key, max = 500) => typeof raw[key] === 'string' ? raw[key].slice(0, max) : '';
    const company = {
      id: raw.id, name: text('name', 200), summary: text('summary'), industry: text('industry', 200) || 'Unspecified',
      stage: Object.hasOwn(STAGES, raw.stage) ? raw.stage : 'unknown', stageBasis: text('stageBasis'),
      location: text('location'), locationLabel: text('locationLabel', 200),
      latitude: raw.latitude, longitude: raw.longitude, precision: raw.precision,
      source: text('source', 200), sourceUrl: safeURL(raw.sourceUrl), website: safeURL(raw.website),
      hiringSignal: Object.hasOwn(SIGNALS, raw.hiringSignal) ? raw.hiringSignal : 'unknown', observedAt: text('observedAt', 80),
    };
    if (!hasPoint(company)) Object.assign(company, {latitude: null, longitude: null, precision: 'unmapped'});
    return company;
  });
  return companies.sort((a, b) => a.name.localeCompare(b.name, 'en') || a.id.localeCompare(b.id));
}

export function filterCompanies(companies, filters) {
  const query = normalize(filters.q).slice(0, 200);
  return companies.filter(c => (!query || normalize([c.name, c.summary, c.industry, c.location].join(' ')).includes(query))
    && (!filters.stage || c.stage === filters.stage)
    && (!filters.industry || c.industry === filters.industry)
    && (!filters.location || c.locationLabel === filters.location)
    && (!filters.signal || c.hiringSignal === filters.signal));
}

export function readState(search) {
  const p = new URLSearchParams(search);
  return Object.fromEntries(['q', 'stage', 'industry', 'location', 'signal', 'company'].map(key => [key, (p.get(key) || '').slice(0, 200)]));
}

export function stateQuery(state) {
  const p = new URLSearchParams();
  for (const key of ['q', 'stage', 'industry', 'location', 'signal', 'company']) if (state[key]) p.set(key, state[key]);
  return p.toString();
}

// Grid grouping is a visual decluttering operation, not geographic precision.
// Even with grouping off, identical city-centre points share one count pin.
export function groupPoints(companies, project, grouped = true) {
  const cells = new Map();
  for (const company of companies.filter(hasPoint)) {
    const p = project(company.latitude, company.longitude);
    const key = grouped ? `${Math.floor(p.x / 64)}:${Math.floor(p.y / 64)}` : `${company.latitude}:${company.longitude}`;
    if (!cells.has(key)) cells.set(key, []);
    cells.get(key).push(company);
  }
  return [...cells.values()].map(members => ({
    latitude: members.reduce((v, c) => v + c.latitude, 0) / members.length,
    longitude: members.reduce((v, c) => v + c.longitude, 0) / members.length,
    members,
  }));
}
