// Pure functions shared by the public explorer and its Node tests.
export const STAGES = Object.freeze({early: 'Early stage', growth: 'Growth', scaleup: 'Scale-up', big: 'Big company', unknown: 'Stage unknown'});
export const SIGNALS = Object.freeze({directory_flag: 'Directory hiring flag', board_snapshot: 'Board snapshot', unknown: 'Hiring unknown'});
export const TYPES = Object.freeze({startup: 'Startup', public: 'Public company', private: 'Private company'});

// Role areas match a company's own industry/tags, not invented job data.
export const ROLE_AREAS = Object.freeze({
  'Engineering': ['software', 'developer', 'devtools', 'infrastructure', 'cloud', 'saas', 'hardware', 'robotics', 'semiconductor', 'electronics', 'embedded', 'platform', 'api'],
  'Data & AI': ['ai', 'artificial intelligence', 'machine learning', 'ml', 'data', 'analytics', 'llm', 'generative', 'computer vision', 'nlp'],
  'Product': ['product', 'collaboration', 'productivity'],
  'Design': ['design', 'creative', 'media', 'video', 'gaming', 'content'],
  'Sales': ['sales', 'crm', 'revenue', 'marketing', 'advertising', 'adtech'],
  'Marketing': ['marketing', 'advertising', 'brand', 'social media', 'seo', 'content'],
  'Customer Success': ['customer', 'support', 'success'],
  'Operations': ['operations', 'logistics', 'supply chain', 'manufacturing', 'procurement', 'shipping', 'delivery'],
  'Finance': ['fintech', 'finance', 'financial', 'payments', 'banking', 'insurance', 'accounting', 'crypto', 'investment', 'lending'],
  'People & HR': ['hr', 'recruiting', 'hiring', 'people', 'talent', 'payroll', 'workforce'],
  'Legal': ['legal', 'compliance', 'privacy', 'regulation', 'govtech'],
  'Research': ['biotech', 'research', 'science', 'pharma', 'clinical', 'lab', 'health', 'medical', 'quantum', 'space', 'energy', 'climate'],
  'Founding / Generalist': [],
  'Internship': [],
});

export function companyRoles(company) {
  const text = normalize([company.industry, ...(company.tags || [])].join(' '));
  if (!text) return [];
  return Object.entries(ROLE_AREAS).filter(([, keywords]) => keywords.some(k => k && text.includes(k))).map(([area]) => area);
}
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
    && ['city', 'country', 'hq'].includes(company.precision);
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
      country: text('country', 100) || null, countryCode: /^[A-Z]{2}$/.test(raw.countryCode || '') ? raw.countryCode : null,
      region: text('region', 100) || null,
      logo: /^data\/logos\/company_[0-9a-f]{20}\.(png|jpg|webp|gif|ico)$/.test(raw.logo || '') ? raw.logo : null,
      type: Object.hasOwn(TYPES, raw.type) ? raw.type : 'private',
      fundingStage: text('fundingStage', 100) || null,
      tags: Array.isArray(raw.tags) ? raw.tags.slice(0, 10).map(t => String(t).slice(0, 60)) : [],
    };
    if (!hasPoint(company)) Object.assign(company, {latitude: null, longitude: null, precision: 'unmapped'});
    return company;
  });
  return companies.sort((a, b) => a.name.localeCompare(b.name, 'en') || a.id.localeCompare(b.id));
}

export function filterCompanies(companies, filters) {
  const query = normalize(filters.q).slice(0, 200);
  return companies.filter(c => (!query || normalize([c.name, c.summary, c.industry, c.location, ...(c.tags || [])].join(' ')).includes(query))
    && (!filters.stage || c.stage === filters.stage)
    && (!filters.industry || c.industry === filters.industry)
    && (!filters.location || c.locationLabel === filters.location || c.country === filters.location || c.region === filters.location)
    && (!filters.signal || c.hiringSignal === filters.signal)
    && (!filters.type || c.type === filters.type)
    && (!filters.role || companyRoles(c).includes(filters.role)));
}

export function readState(search) {
  const p = new URLSearchParams(search);
  return Object.fromEntries(['q', 'stage', 'industry', 'location', 'signal', 'type', 'role', 'company'].map(key => [key, (p.get(key) || '').slice(0, 200)]));
}

export function stateQuery(state) {
  const p = new URLSearchParams();
  for (const key of ['q', 'stage', 'industry', 'location', 'signal', 'type', 'role', 'company']) if (state[key]) p.set(key, state[key]);
  return p.toString();
}

// Zoom hierarchy, following the observed startupmap pattern: country cards
// far out, region cards (US states and named regions) next, city cards closer,
// and one pin per company once the map is street-level.
export const ZOOM = Object.freeze({countryMax: 3, regionMax: 5, cityMax: 7});
export function zoomLayer(zoom) {
  if (zoom <= ZOOM.countryMax) return 'country';
  if (zoom <= ZOOM.regionMax) return 'region';
  if (zoom <= ZOOM.cityMax) return 'city';
  return 'pins';
}

export function cardGroups(companies, keyFn) {
  const groups = new Map();
  for (const company of companies.filter(hasPoint)) {
    const key = keyFn(company);
    if (!key) continue;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(company);
  }
  return [...groups.entries()].map(([key, members]) => ({
    key,
    members,
    latitude: members.reduce((v, c) => v + c.latitude, 0) / members.length,
    longitude: members.reduce((v, c) => v + c.longitude, 0) / members.length,
  })).sort((a, b) => b.members.length - a.members.length);
}

export function countryCards(companies) {
  return cardGroups(companies, c => c.country);
}
export function regionCards(companies) {
  // Region cards where a region is known; companies without one join their
  // city groups so the zoom level never hides them.
  const regions = cardGroups(companies.filter(c => c.region), c => `${c.country}::${c.region}`);
  const cities = cardGroups(companies.filter(c => !c.region), c => `city::${c.locationLabel}`);
  return [...regions, ...cities];
}
export function cityCards(companies) {
  return cardGroups(companies, c => c.locationLabel);
}

// Card layers declutter like the reference map: one card per screen cell,
// keeping the largest group, so dense regions (Europe) stay readable.
export function declutterCards(groups, project, cellPx = 150) {
  const cells = new Map();
  for (const group of groups) {
    const p = project(group.latitude, group.longitude);
    const key = `${Math.floor(p.x / cellPx)}:${Math.floor(p.y / cellPx)}`;
    if (!cells.has(key) || cells.get(key).members.length < group.members.length) cells.set(key, group);
  }
  return [...cells.values()];
}

export function flagEmoji(iso) {
  if (!/^[A-Z]{2}$/.test(iso || '')) return '';
  return String.fromCodePoint(...[...iso].map(ch => 0x1F1E6 + ch.charCodeAt(0) - 65));
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
