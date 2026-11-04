// Hired — global startup & job map. Static frontend over /data/startups.json + /data/jobs.json.

const $ = (id) => document.getElementById(id);
const SATELLITE_TILES = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';

let startups = [];
let jobs = [];
let byCompany = new Map();      // startup_id -> startup
let jobsByCompany = new Map();  // startup_id -> jobs[]
let map = null;
let mapReady = false;
let mapMode = '';
let markers = [];

const state = { city: '', sector: '', stage: '', hiring: '', search: '' };

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

function populateFilters() {
  const cities = [...new Set(startups.map(c => c.office_city).filter(Boolean))].sort();
  const sectors = [...new Set(startups.map(c => c.domain_primary).filter(Boolean))].sort();
  const stages = [...new Set(startups.map(c => c.stage).filter(Boolean))].sort();
  fill($('f-city'), cities);
  fill($('f-sector'), sectors);
  fill($('f-stage'), stages);
  fill($('f-hiring'), ['actively_hiring', 'open_to_talent']);
}
function fill(sel, values) {
  sel.append(new Option(sel.id === 'f-hiring' ? 'Any hiring' : (sel.id === 'f-city' ? 'Any city' : sel.id === 'f-sector' ? 'Any sector' : 'Any stage'), ''));
  for (const v of values) {
    const label = sel.id === 'f-hiring' ? (v === 'actively_hiring' ? 'Actively hiring' : 'Open to talent') : v;
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
  return renderMapView();
}

function renderMapView() {
  $('view-job').hidden = true;
  $('view-map').hidden = false;
  $('nav-jobs').setAttribute('aria-current', 'page');
  $('nav-map').setAttribute('aria-current', 'false');
  const cos = filteredCompanies();
  const totalJobs = cos.reduce((n, c) => n + companyJobs(c.startup_id).length, 0);
  $('panel-title').textContent = 'Companies hiring now';
  $('panel-sub').textContent = `${cos.length} companies · ${totalJobs} open roles`;
  const list = $('list');
  list.textContent = '';
  for (const c of cos.slice(0, 200)) list.append(companyCard(c));
  $('empty').hidden = cos.length > 0;
  renderMarkers();
  if (map && mapReady) fitMap();
}

function companyCard(c) {
  const el = document.createElement('div');
  el.className = 'company-card';
  const n = companyJobs(c.startup_id).length;
  el.innerHTML = `
    <span class="logo-fallback">${(c.name[0] || '?').toUpperCase()}</span>
    <div class="co-info">
      <div class="co-name">${esc(c.name)}</div>
      <div class="co-meta">${esc(c.office_city || c.country || '')}${c.stage ? ` · <span class="stage-badge">${esc(c.stage)}</span>` : ''}</div>
    </div>
    <span class="co-count">${n} roles</span>`;
  el.addEventListener('click', () => { location.hash = `#/company/${c.startup_id}`; });
  return el;
}

function renderCompany(id) {
  const c = byCompany.get(id);
  if (!c) { location.hash = '#/'; return; }
  $('view-map').hidden = true;
  $('view-job').hidden = false;
  const list = filteredJobs(id);
  const d = $('job-detail');
  d.textContent = '';
  d.innerHTML = `<button class="back" id="back-company">← All companies</button>
    <div class="job-head"><span class="logo-fallback">${(c.name[0] || '?').toUpperCase()}</span>
      <div><h1 class="job-title">${esc(c.name)}</h1>
      <div class="job-co">${esc(c.office_city || '')}${c.country ? ', ' + esc(c.country) : ''}</div></div></div>
    <div class="job-meta">${c.stage ? `<span class="tag">${esc(c.stage)}</span>` : ''}<span class="tag">${esc(c.domain_primary || '')}</span><span class="tag">${list.length} open roles</span></div>`;
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
  $('view-job').hidden = false;
  const d = $('job-detail');
  d.textContent = '';
  d.innerHTML = `<button class="back" id="back-job">← All jobs</button>
    <div class="job-head"><span class="logo-fallback">${(c?.name?.[0] || '?').toUpperCase()}</span>
      <div><h1 class="job-title">${esc(job.job_title)}</h1>
      <div class="job-co"><a href="#/company/${job.startup_id}">${esc(c?.name || job.startup_id)}</a>${job.location_display ? ' · ' + esc(job.location_display) : ''}</div></div></div>
    <div class="job-meta">${(job.type || []).map(t => `<span class="tag">${esc(t)}</span>`).join('')}${job.scrape_method ? `<span class="tag">${esc(job.scrape_method)}</span>` : ''}</div>
    <a class="apply-btn" href="${esc(job.apply_url)}" target="_blank" rel="noopener">Apply on company site ↗</a>
    <h3 class="section-title">About the role</h3>
    <div class="job-desc">${job.description ? esc(job.description) : '<span class="muted">No description in the public feed.</span>'}</div>`;
  $('back-job').addEventListener('click', () => { location.hash = '#/'; });
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
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
  try { map.setSky(globe ? { 'sky-color': '#8ec3e0', 'horizon-color': '#cfe3f5', 'fog-color': '#dbe9f5', 'fog-ground-blend': 0.15, 'horizon-fog-blend': 0.15, 'sky-horizon-blend': 0.5, 'atmosphere-blend': 0.12 } : null); } catch {}
  if (!map.getSource('satellite')) {
    map.addSource('satellite', { type: 'raster', tiles: [SATELLITE_TILES], tileSize: 256, maxzoom: 18, attribution: 'Imagery © Esri, Maxar, Earthstar Geographics' });
    map.addLayer({ id: 'satellite', type: 'raster', source: 'satellite' });
  }
  map.setLayoutProperty('satellite', 'visibility', globe ? 'visible' : 'none');
}

function renderMarkers() {
  if (!map || !mapReady) return;
  markers.forEach(m => m.remove());
  markers = [];
  const cos = filteredCompanies().filter(c => c.latitude != null && c.longitude != null);
  for (const c of cos.slice(0, 400)) {
    const el = document.createElement('div');
    el.className = 'pin';
    el.innerHTML = `<span>${companyJobs(c.startup_id).length}</span>`;
    el.title = c.name;
    el.addEventListener('click', () => { location.hash = `#/company/${c.startup_id}`; });
    markers.push(new maplibregl.Marker({ element: el, anchor: 'bottom' })
      .setLngLat([c.longitude, c.latitude]).addTo(map));
  }
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

for (const key of ['city', 'sector', 'stage', 'hiring']) {
  $(`f-${key}`).addEventListener('change', e => { state[key] = e.target.value; render(); });
}
$('f-search').addEventListener('input', e => { state.search = e.target.value; render(); });
$('nav-map').addEventListener('click', () => { location.hash = '#/'; if (map && mapReady) setTimeout(() => map.resize(), 50); });
$('nav-jobs').addEventListener('click', () => { location.hash = '#/'; });
window.addEventListener('hashchange', render);

load();
