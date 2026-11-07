// Hired — global startup & job map. Static frontend over /data/startups.json + /data/jobs.json.

const $ = (id) => document.getElementById(id);

let startups = [];
let jobs = [];
let byCompany = new Map();      // startup_id -> startup
let jobsByCompany = new Map();  // startup_id -> jobs[]
let map = null;
let mapReady = false;
let mapMode = '';
let markers = [];

const state = { city: '', sector: '', type: '', stage: '', hiring: '', search: '' };

// --- data ----------------------------------------------------------------

async function load() {
  try {
    const [s, j] = await Promise.all([
      fetch('/data/startups.json', { signal: AbortSignal.timeout(15000) }).then(r => r.json()),
      fetch('/data/jobs.json', { signal: AbortSignal.timeout(15000) }).then(r => r.json()),
    ]);
    startups = Array.isArray(s) ? s : [];
    jobs = Array.isArray(j) ? j : [];
    byCompany = new Map(startups.map(c => [c.startup_id, c]));
    jobsByCompany = new Map();
    for (const job of jobs) {
      const id = job.startup_id;
      if (!jobsByCompany.has(id)) jobsByCompany.set(id, []);
      jobsByCompany.get(id).push(job);
    }
    populateFilters();
    render();
    initMap();
  } catch {
    $('load-error').hidden = false;
  }
}

// --- filters --------------------------------------------------------------

const STAGE_LABELS = { pre_seed: 'Pre-seed', seed: 'Seed', series_a: 'Series A', series_b: 'Series B', series_c: 'Series C', series_d: 'Series D', series_e: 'Series E', series_f: 'Series F', bootstrapped: 'Bootstrapped', growth: 'Growth' };
const FUNDING_STAGES = ['pre_seed', 'seed', 'series_a', 'series_b', 'series_c', 'series_d', 'series_e', 'series_f', 'bootstrapped', 'growth'];
function stageLabel(s) { return STAGE_LABELS[s] || (s ? s.replace(/_/g, ' ') : ''); }

function populateFilters() {
  const cities = [...new Set(startups.map(c => c.office_city).filter(Boolean))].sort();
  const sectors = [...new Set(startups.map(c => c.domain_primary).filter(Boolean))].sort();
  fill($('f-city'), cities);
  fill($('f-sector'), sectors);
  fill($('f-type'), ['public', 'private']);
  fill($('f-stage'), FUNDING_STAGES);
  fill($('f-hiring'), ['actively_hiring', 'open_to_talent']);
}
function fill(sel, values) {
  const first = { 'f-hiring': 'Any hiring', 'f-city': 'Any city', 'f-sector': 'Any sector', 'f-stage': 'Any stage', 'f-type': 'Any type' }[sel.id] || 'Any';
  sel.append(new Option(first, ''));
  for (const v of values) {
    let label = v;
    if (sel.id === 'f-hiring') label = v === 'actively_hiring' ? 'Actively hiring' : 'Open to talent';
    else if (sel.id === 'f-stage') label = stageLabel(v);
    else if (sel.id === 'f-type') label = v === 'public' ? 'Public' : 'Private';
    sel.add(new Option(label, v));
  }
}

function companyJobs(id) { return jobsByCompany.get(id) || []; }

function filteredCompanies() {
  const q = state.search.trim().toLowerCase();
  return startups.filter(c => {
    if (!companyJobs(c.startup_id).length) return false; // only companies with roles
    if (state.city && c.office_city !== state.city) return false;
    if (state.sector && c.domain_primary !== state.sector) return false;
    if (state.type && c.company_type !== state.type) return false;
    if (state.stage && c.stage !== state.stage) return false;
    if (state.hiring && c.hiring_status !== state.hiring) return false;
    if (q && !(c.name || '').toLowerCase().includes(q)) return false;
    return true;
  });
}

function filteredJobs(companyId) {
  const list = companyId ? companyJobs(companyId) : jobs;
  const q = state.search.trim().toLowerCase();
  return list.filter(job => {
    const c = byCompany.get(job.startup_id);
    if (state.city && !(job.location_display || '').includes(state.city)) return false;
    if (state.sector && c && c.domain_primary !== state.sector) return false;
    if (state.type && c && c.company_type !== state.type) return false;
    if (state.stage && c && c.stage !== state.stage) return false;
    if (state.hiring && c && c.hiring_status !== state.hiring) return false;
    if (q && !(`${job.job_title} ${job.startup_id} ${(job.type || []).join(' ')}`.toLowerCase().includes(q))) return false;
    return true;
  });
}

// --- rendering ------------------------------------------------------------

function render() {
  const hash = location.hash;
  if (hash.startsWith('#/job/')) return renderJob(hash.slice(6));
  if (hash.startsWith('#/company/')) return renderCompany(hash.slice(10));
  if (hash === '#/submit') return renderSubmit();
  if (hash === '#/dashboard') return renderDashboard();
  if (hash === '#/map') return renderMapView('map');
  return renderMapView('jobs');
}

function renderSubmit() {
  $('view-map').hidden = true;
  $('view-job').hidden = true;
  $('view-submit').hidden = false;
  $('view-dashboard').hidden = true;
  $('nav-jobs').setAttribute('aria-current', 'false');
  $('nav-map').setAttribute('aria-current', 'false');
  $('submit-status').hidden = true;
}

function renderMapView(mode = 'jobs') {
  $('view-job').hidden = true;
  $('view-submit').hidden = true;
  $('view-dashboard').hidden = true;
  $('view-map').hidden = false;
  $('view-map').dataset.mode = mode;
  $('nav-jobs').setAttribute('aria-current', mode === 'jobs' ? 'page' : 'false');
  $('nav-map').setAttribute('aria-current', mode === 'map' ? 'page' : 'false');
  const cos = filteredCompanies();
  const totalJobs = cos.reduce((n, c) => n + companyJobs(c.startup_id).length, 0);
  $('panel-title').textContent = 'Companies hiring now';
  $('panel-sub').textContent = `${cos.length} companies · ${totalJobs} open roles`;
  const list = $('list');
  list.textContent = '';
  for (const c of cos.slice(0, 200)) list.append(companyCard(c));
  $('empty').hidden = cos.length > 0;
  renderMarkers();
  if (map && mapReady && mode === 'map') { map.resize(); fitMap(); }
}

function companyCard(c) {
  const el = document.createElement('div');
  el.className = 'company-card';
  const n = companyJobs(c.startup_id).length;
  el.innerHTML = `
    ${logoHTML(c)}
    <div class="co-info">
      <div class="co-name">${esc(c.name)}</div>
      <div class="co-meta">${esc(c.office_city || c.country || '')}${c.stage ? ` · <span class="stage-badge">${esc(stageLabel(c.stage))}</span>` : ''}${c.company_type ? ` · <span class="stage-badge">${esc(c.company_type)}</span>` : ''}</div>
    </div>
    <span class="co-count">${n} roles</span>`;
  el.addEventListener('click', () => { location.hash = `#/company/${c.startup_id}`; });
  return el;
}

function renderCompany(id) {
  const c = byCompany.get(id);
  if (!c) { location.hash = '#/'; return; }
  $('view-map').hidden = true;
  $('view-submit').hidden = true;
  $('view-dashboard').hidden = true;
  $('view-job').hidden = false;
  const list = filteredJobs(id);
  const d = $('job-detail');
  d.textContent = '';
  d.innerHTML = `<button class="back" id="back-company">← All companies</button>
    <div class="job-head">${logoHTML(c)}
      <div><h1 class="job-title">${esc(c.name)}</h1>
      <div class="job-co">${esc(c.address || c.office_city || '')}</div></div></div>
    <div class="job-meta">${c.company_type ? `<span class="tag">${esc(c.company_type)}</span>` : ''}${c.stage ? `<span class="tag">${esc(stageLabel(c.stage))}</span>` : ''}<span class="tag">${esc(c.domain_primary || '')}</span><span class="tag">${list.length} open roles</span></div>`;
  $('back-company').addEventListener('click', () => { location.hash = '#/'; });
  const wrap = document.createElement('div');
  wrap.className = 'list';
  for (const job of list) wrap.append(jobCard(job));
  d.append(wrap);
}

function jobCard(job) {
  const el = document.createElement('div');
  el.className = 'company-card';
  el.innerHTML = `
    <div class="co-info">
      <div class="co-name">${esc(job.job_title)}</div>
      <div class="co-meta">${esc(job.location_display || '')}${(job.type || []).map(t => `<span class="stage-badge">${esc(t)}</span>`).join('')}</div>
    </div>`;
  el.addEventListener('click', () => { location.hash = `#/job/${job.jobs_id}`; });
  return el;
}

function renderJob(id) {
  const job = jobs.find(j => j.jobs_id === id);
  if (!job) { location.hash = '#/'; return; }
  const c = byCompany.get(job.startup_id);
  $('view-map').hidden = true;
  $('view-submit').hidden = true;
  $('view-dashboard').hidden = true;
  $('view-job').hidden = false;
  const d = $('job-detail');
  d.textContent = '';
  const req = job.requirements || {};
  const reqHTML = (req.skills?.length || req.experience || req.degrees?.length)
    ? `<h3 class="section-title">Requirements</h3>
       <div class="req-block">
         ${req.experience ? `<div class="req-item"><strong>Experience</strong> ${esc(req.experience)}</div>` : ''}
         ${req.degrees?.length ? `<div class="req-item"><strong>Degree</strong> ${req.degrees.map(d => esc(d)).join(', ')}</div>` : ''}
         ${req.skills?.length ? `<div class="req-skills">${req.skills.map(s => `<span class="tag">${esc(s)}</span>`).join('')}</div>` : ''}
       </div>` : '';
  d.innerHTML = `<button class="back" id="back-job">← All jobs</button>
    <div class="job-head">${logoHTML(c)}
      <div><h1 class="job-title">${esc(job.job_title)}</h1>
      <div class="job-co"><a href="#/company/${job.startup_id}">${esc(c?.name || job.startup_id)}</a>${job.location_display ? ' · ' + esc(job.location_display) : ''}</div></div></div>
    <div class="job-meta">${(job.type || []).map(t => `<span class="tag">${esc(t)}</span>`).join('')}${job.scrape_method ? `<span class="tag">${esc(job.scrape_method)}</span>` : ''}</div>
    <a class="apply-btn" href="${esc(job.apply_url)}" target="_blank" rel="noopener">Apply on company site ↗</a>
    ${reqHTML}
    <h3 class="section-title">About the role</h3>
    <div class="job-desc">${job.description ? esc(job.description) : '<span class="muted">No description in the public feed.</span>'}</div>`;
  $('back-job').addEventListener('click', () => { location.hash = '#/'; });
  const tracked = getApplications().some(a => a.job_id === job.jobs_id);
  const track = document.createElement('button');
  track.type = 'button';
  track.className = 'track-btn' + (tracked ? ' tracked' : '');
  track.textContent = tracked ? '✓ Tracked' : 'Track this role';
  track.addEventListener('click', () => { trackApplication(job); track.textContent = '✓ Tracked'; track.classList.add('tracked'); });
  d.querySelector('.apply-btn').after(track);
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}
function logoHTML(c) {
  const letter = esc((c?.name?.[0] || '?').toUpperCase());
  if (c?.logo_url) {
    return `<span class="logo-wrap"><span class="logo-fallback">${letter}</span><img class="logo" src="${esc(c.logo_url)}" alt="" loading="lazy" onerror="this.remove()"></span>`;
  }
  return `<span class="logo-fallback">${letter}</span>`;
}

// --- applications dashboard -------------------------------------------------

const APPS_KEY = 'hired-applications';
const APP_STATUSES = ['Saved', 'Applied', 'Interview', 'Offer', 'Rejected'];

function getApplications() {
  try { return JSON.parse(localStorage.getItem(APPS_KEY)) || []; } catch { return []; }
}
function saveApplications(apps) { localStorage.setItem(APPS_KEY, JSON.stringify(apps)); }
function trackApplication(job) {
  const apps = getApplications();
  if (!apps.some(a => a.job_id === job.jobs_id)) {
    apps.unshift({
      job_id: job.jobs_id, title: job.job_title,
      company_name: byCompany.get(job.startup_id)?.name || job.startup_id,
      url: job.apply_url, status: 'Saved', applied_at: new Date().toISOString(),
    });
    saveApplications(apps);
  }
}
function updateApplicationStatus(job_id, status) {
  saveApplications(getApplications().map(a => a.job_id === job_id ? { ...a, status } : a));
}
function removeApplication(job_id) {
  saveApplications(getApplications().filter(a => a.job_id !== job_id));
}

function renderDashboard() {
  $('view-map').hidden = true;
  $('view-job').hidden = true;
  $('view-submit').hidden = true;
  $('view-dashboard').hidden = false;
  $('nav-jobs').setAttribute('aria-current', 'false');
  $('nav-map').setAttribute('aria-current', 'false');
  const apps = getApplications();
  const list = $('dash-list');
  list.textContent = '';
  if (!apps.length) {
    list.innerHTML = '<p class="muted">No tracked applications yet. Open a role and click “Track this role”.</p>';
    return;
  }
  for (const a of apps) {
    const el = document.createElement('div');
    el.className = 'app-card';
    const status = document.createElement('select');
    status.className = 'app-status';
    for (const s of APP_STATUSES) status.add(new Option(s, s));
    status.value = a.status;
    status.addEventListener('change', () => updateApplicationStatus(a.job_id, status.value));
    const rm = document.createElement('button');
    rm.type = 'button'; rm.className = 'app-remove'; rm.textContent = '✕'; rm.title = 'Remove';
    rm.addEventListener('click', () => { removeApplication(a.job_id); renderDashboard(); });
    el.innerHTML = `<div class="app-info">
        <a class="app-title" href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a>
        <div class="app-co">${esc(a.company_name)}</div>
      </div>`;
    el.append(status, rm);
    list.append(el);
  }
}

// --- map ------------------------------------------------------------------

function initMap() {
  if (!window.maplibregl) return;
  try {
    map = new maplibregl.Map({
      container: 'map', style: 'https://tiles.openfreemap.org/styles/positron',
      center: [12, 51], zoom: 1.3, minZoom: 0.5, maxZoom: 18, scrollZoom: false,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    map.on('load', () => { mapReady = true; syncMode(); renderMarkers(); fitMap(); });
    map.on('zoom', syncMode);
    map.on('moveend', renderMarkers);
    map.on('error', () => { $('map-status').hidden = false; $('map-status').textContent = 'Some map tiles failed. The list still works.'; });
  } catch { $('map-status').hidden = false; $('map-status').textContent = 'Map unavailable.'; }
}

function syncMode() {
  if (!map || !mapReady) return;
  const globe = map.getZoom() < 4;
  const mode = globe ? 'globe' : 'flat';
  if (mapMode === mode) return;
  mapMode = mode;
  try { map.setProjection({ type: globe ? 'globe' : 'mercator' }); } catch {}
  // Same paper-toned atmosphere as the positron basemap, so the globe reads as
  // the same map colours at every zoom (no satellite imagery). Sky is only
  // set in globe mode; it doesn't apply to the flat mercator view.
  if (globe) {
    try { map.setSky({ 'sky-color': '#e9e2d4', 'horizon-color': '#ddd3c2', 'fog-color': '#fffaf3', 'fog-ground-blend': 0.12, 'horizon-fog-blend': 0.15, 'sky-horizon-blend': 0.35, 'atmosphere-blend': 0.08 }); } catch {}
  }
}

const COUNTRY_ISO = {
  'United States':'US','United Kingdom':'GB','Germany':'DE','France':'FR','Netherlands':'NL',
  'Sweden':'SE','Belgium':'BE','Switzerland':'CH','Spain':'ES','Italy':'IT','Denmark':'DK',
  'Norway':'NO','Finland':'FI','Ireland':'IE','Austria':'AT','Portugal':'PT','Poland':'PL',
  'Estonia':'EE','Lithuania':'LT','Czechia':'CZ','Czech Republic':'CZ',
  'Australia':'AU','Canada':'CA','Singapore':'SG','India':'IN','Israel':'IL','Japan':'JP',
  'Luxembourg':'LU','Iceland':'IS','Romania':'RO','Greece':'GR','Hungary':'HU','Bulgaria':'BG',
  'Croatia':'HR','Slovenia':'SI','Slovakia':'SK','Ukraine':'UA','Turkey':'TR',
  'United Arab Emirates':'AE','Albania':'AL','Argentina':'AR','Brazil':'BR','Chile':'CL',
  'Colombia':'CO','Cyprus':'CY','Mexico':'MX','New Zealand':'NZ','Pakistan':'PK','Philippines':'PH',
  'England':'GB','Scotland':'GB','Wales':'GB',
};

function countryFlag(country) {
  const iso = COUNTRY_ISO[country];
  if (!iso) return '';
  return String.fromCodePoint(...[...iso].map(c => 0x1F1E6 + c.charCodeAt(0) - 65));
}

function renderMarkers() {
  if (!map || !mapReady) return;
  markers.forEach(m => m.remove());
  markers = [];
  const cos = filteredCompanies().filter(c => c.latitude != null && c.longitude != null);
  if (!cos.length) return;
  if (map.getZoom() < 5) {
    renderCountryFlags(cos);
    return;
  }
  for (const c of cos.slice(0, 500)) {
    const el = document.createElement('div');
    el.className = 'pin';
    el.innerHTML = `<span>${companyJobs(c.startup_id).length}</span>`;
    el.title = c.name;
    el.addEventListener('click', () => { location.hash = `#/company/${c.startup_id}`; });
    markers.push(new maplibregl.Marker({ element: el, anchor: 'bottom' })
      .setLngLat([c.longitude, c.latitude]).addTo(map));
  }
}

function renderCountryFlags(cos) {
  const byCountry = new Map();
  for (const c of cos) {
    const key = c.country || 'Remote';
    if (!countryFlag(key)) continue;
    if (!byCountry.has(key)) byCountry.set(key, []);
    byCountry.get(key).push(c);
  }
  for (const [country, comps] of byCountry) {
    const lat = comps.reduce((a, c) => a + c.latitude, 0) / comps.length;
    const lng = comps.reduce((a, c) => a + c.longitude, 0) / comps.length;
    const jobs = comps.reduce((a, c) => a + companyJobs(c.startup_id).length, 0);
    const el = document.createElement('div');
    el.className = 'flag-marker';
    el.innerHTML = `<span class="flag">${countryFlag(country)}</span><span class="flag-count">${jobs}</span>`;
    el.title = `${country} — ${comps.length} companies · ${jobs} roles`;
    el.addEventListener('click', () => fitCountry(comps));
    markers.push(new maplibregl.Marker({ element: el, anchor: 'center' })
      .setLngLat([lng, lat]).addTo(map));
  }
}

function fitCountry(comps) {
  const lngs = comps.map(c => c.longitude), lats = comps.map(c => c.latitude);
  const cam = map.cameraForBounds(
    [[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]],
    { padding: 90, maxZoom: 7 });
  if (cam) map.flyTo({ center: cam.center, zoom: Math.max(6, cam.zoom) });
}

function fitMap() {
  const cos = filteredCompanies().filter(c => c.latitude != null && c.longitude != null);
  if (!cos.length) return;
  const lngs = cos.map(c => c.longitude), lats = cos.map(c => c.latitude);
  const cam = map.cameraForBounds(
    [[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]],
    { padding: 60, maxZoom: 12 });
  if (cam) map.jumpTo({ center: cam.center, zoom: Math.max(1.3, cam.zoom) });
}

// --- events ---------------------------------------------------------------

for (const key of ['city', 'sector', 'type', 'stage', 'hiring']) {
  $(`f-${key}`).addEventListener('change', e => { state[key] = e.target.value; render(); });
}
$('f-search').addEventListener('input', e => { state.search = e.target.value; render(); });
$('nav-map').addEventListener('click', () => { location.hash = '#/map'; });
$('nav-jobs').addEventListener('click', () => { location.hash = '#/jobs'; });
window.addEventListener('hashchange', render);

$('submit-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const status = $('submit-status');
  const payload = {
    company: $('s-company').value, website: $('s-website').value, title: $('s-title').value,
    location: $('s-location').value, apply_url: $('s-url').value,
    employment_type: $('s-employment').value, description: $('s-description').value,
    contact_email: $('s-email').value,
  };
  status.hidden = false;
  status.textContent = 'Submitting…';
  try {
    const r = await fetch('/api/submit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await r.json().catch(() => ({}));
    status.textContent = r.ok ? (data.message || 'Thanks — your role is pending review.') : (data.error || 'Something went wrong.');
    if (r.ok) e.target.reset();
  } catch {
    status.textContent = 'Could not reach the submission service. Please try again.';
  }
});

load();
