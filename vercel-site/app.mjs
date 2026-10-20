import {STAGES, SIGNALS, PAGE_SIZE, filterCompanies, groupPoints, hasPoint, readCatalogue, readState, stateQuery, zoomLayer, countryCards, regionCards, cityCards, flagEmoji, declutterCards} from './map-core.mjs';

const $ = id => document.getElementById(id);
const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
};
const initials = name => name.split(/\s+/).slice(0, 2).map(word => word[0]).join('').toUpperCase();
const dateLabel = value => {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? 'Date unavailable' : date.toLocaleDateString('en', {year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC'});
};
let companies = [], filtered = [], state = readState(location.search), groupIds = null, page = 0;
let map, mapReady = false, loading = false, lastSelected = null;
const mapMarkers = [];
const controls = {q: $('search'), role: $('role'), industry: $('industry'), type: $('type'), location: $('location')};
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

function setView(view) {
  document.querySelector('.explorer-body').dataset.view = view;
  $('list-view').setAttribute('aria-pressed', String(view === 'list'));
  $('map-view').setAttribute('aria-pressed', String(view === 'map'));
  if (view === 'map') requestAnimationFrame(() => map?.resize());
}
$('list-view').addEventListener('click', () => setView('list'));
$('map-view').addEventListener('click', () => setView('map'));

function updateURL(replace = false) {
  const query = stateQuery(state);
  const url = `${location.pathname}${query ? '?' + query : ''}${location.hash}`;
  if (url !== location.pathname + location.search + location.hash) history[replace ? 'replaceState' : 'pushState'](null, '', url);
}
function readControls() {
  for (const [key, control] of Object.entries(controls)) state[key] = control.value;
}
function restoreControls() {
  for (const [key, control] of Object.entries(controls)) {
    if (control.tagName === 'SELECT' && ![...control.options].some(option => option.value === state[key])) state[key] = '';
    control.value = state[key] || '';
  }
}
function addOptions(id, values) {
  const select = $(id);
  while (select.options.length > 1) select.remove(1);
  for (const value of [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b))) select.add(new Option(value, value));
}
function applyFilters({fit = false, replace = false} = {}) {
  readControls(); state.company = ''; groupIds = null; page = 0;
  updateURL(replace); render();
  if (fit) fitResults();
}
function refreshChipState() {
  const active = ['role', 'industry', 'type', 'location'].some(k => controls[k].value) || controls.q.value;
  $('clear-filters').hidden = !active;
  for (const [key, control] of Object.entries(controls)) control.classList.toggle('is-active', Boolean(control.value));
}
$('filters').addEventListener('submit', event => { event.preventDefault(); clearTimeout(searchTimer); applyFilters({fit: true}); });
let searchTimer;
controls.q.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => applyFilters({fit: true, replace: true}), 180); });
for (const key of ['role', 'industry', 'type', 'location']) controls[key].addEventListener('change', () => { clearTimeout(searchTimer); applyFilters({fit: true}); });
$('filters').addEventListener('reset', event => {
  event.preventDefault(); clearTimeout(searchTimer);
  state = readState(''); restoreControls(); groupIds = null; page = 0;
  updateURL(); render(); fitResults();
});
window.addEventListener('popstate', () => {
  clearTimeout(searchTimer); state = readState(location.search); restoreControls(); groupIds = null; page = 0;
  render(); fitResults();
});
$('previous').addEventListener('click', () => { page--; renderList(); $('results-heading').focus(); });
$('next').addEventListener('click', () => { page++; renderList(); $('results-heading').focus(); });
$('clear-group').addEventListener('click', () => { groupIds = null; page = 0; renderList(); });
$('group-pins').addEventListener('change', renderPins);
$('show-names').addEventListener('change', renderPins);
$('fit-map').addEventListener('click', () => { groupIds = null; page = 0; renderList(); fitResults(); });

function render() {
  refreshChipState();
  filtered = filterCompanies(companies, state);
  const mapped = filtered.filter(hasPoint).length;
  const noun = filtered.length === 1 ? 'company' : 'companies';
  $('result-count').textContent = `${filtered.length.toLocaleString()} ${noun} · ${mapped.toLocaleString()} mapped · ${(filtered.length - mapped).toLocaleString()} without a resolved location`;
  if (state.company && !filtered.some(c => c.id === state.company)) state.company = '';
  renderList(); renderPins();
  if (state.company) renderDetail(filtered.find(c => c.id === state.company));
  else { $('company-detail').hidden = true; $('list-panel').hidden = false; }
}
function renderList() {
  const rows = groupIds ? filtered.filter(c => groupIds.has(c.id)) : filtered;
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  page = Math.max(0, Math.min(page, pages - 1));
  $('clear-group').hidden = !groupIds;
  $('group-note').hidden = !groupIds;
  if (groupIds) $('group-note').textContent = `${rows.length} companies in this pin group. Their locations are approximate.`;
  $('empty-state').hidden = rows.length > 0 || loading || !$('load-error').hidden;
  const fragment = document.createDocumentFragment();
  for (const company of rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)) {
    const li = el('li', 'company-row');
    const button = el('button', 'company-button'); button.type = 'button'; button.dataset.company = company.id;
    button.setAttribute('aria-label', `View ${company.name}, ${company.location || 'Location unknown'}`);
    const monogram = el('span', 'monogram', initials(company.name)); monogram.setAttribute('aria-hidden', 'true');
    const content = el('span', 'company-summary');
    content.append(el('span', 'company-name', company.name), el('span', 'company-location', company.location || 'Location unknown'));
    const tags = el('span', 'company-tags');
    const typeLabel = company.type === 'startup' ? 'Startup' : company.type === 'public' ? 'Public company' : 'Private company';
    tags.append(el('span', 'tag', typeLabel));
    if (company.type === 'startup' && company.fundingStage) tags.append(el('span', 'tag', company.fundingStage));
    tags.append(el('span', 'tag', company.industry));
    content.append(tags);
    const arrow = el('span', 'row-arrow', '↗'); arrow.setAttribute('aria-hidden', 'true');
    button.append(monogram, content, arrow); button.addEventListener('click', () => selectCompany(company));
    li.append(button); fragment.append(li);
  }
  $('company-list').replaceChildren(fragment);
  $('pagination').hidden = rows.length <= PAGE_SIZE;
  $('page-label').textContent = `${page + 1} / ${pages}`;
  $('previous').disabled = page === 0; $('next').disabled = page === pages - 1;
}
function selectCompany(company) {
  state.company = company.id; lastSelected = company.id; updateURL(); renderDetail(company);
  if (map && hasPoint(company)) map.jumpTo({center: [company.longitude, company.latitude], zoom: company.precision === 'city' ? 8 : 5});
}
function closeDetail() {
  state.company = ''; updateURL(); $('company-detail').hidden = true; $('list-panel').hidden = false;
  renderList();
  const button = [...document.querySelectorAll('[data-company]')].find(node => node.dataset.company === lastSelected);
  (button || $('results-heading')).focus();
}
function renderDetail(company) {
  if (!company) return;
  const detail = $('company-detail'); detail.replaceChildren();
  const back = el('button', 'button detail-back', '← Back to companies'); back.type = 'button'; back.addEventListener('click', closeDetail);
  const body = el('div', 'detail-content');
  const heading = el('h2', '', company.name); heading.id = 'detail-title'; heading.tabIndex = -1;
  body.append(el('div', 'monogram', initials(company.name)), heading, el('p', '', company.summary || 'No company description in this snapshot. Check the source for more information.'));
  const facts = el('dl', 'detail-facts');
  const locationAccuracy = company.precision === 'hq' ? 'Verified headquarters coordinate from Wikidata (CC0 public data).' : company.precision === 'city' ? 'Approximate city centre, not an office address.' : company.precision === 'country' ? 'Country-centre estimate. City not resolved.' : 'Not pinned. No reliable location resolved.';
  for (const [label, value, note] of [
    ['Location', company.location || 'Unknown', locationAccuracy],
    ['Type', company.type === 'startup' ? 'Startup' : company.type === 'public' ? 'Public company' : 'Private company',
     company.type === 'startup' ? (company.fundingStage ? `Funding stage: ${company.fundingStage}` : 'Funding stage not published.') : (company.stageBasis || '')],
    ['Industry', company.industry, ''],
    ['Hiring evidence', SIGNALS[company.hiringSignal], company.hiringSignal === 'directory_flag' ? 'Unverified directory flag; check current roles with the employer.' : company.hiringSignal === 'board_snapshot' ? 'Historical board observation, not a real-time vacancy guarantee.' : 'This source does not establish current vacancies.'],
    ['Source', company.source || 'Unspecified', `Facts imported ${dateLabel(company.observedAt)}. Not a job posting date.`],
  ]) {
    const row = el('div'); const dd = el('dd', '', value);
    if (note) dd.append(el('span', 'detail-subnote', note));
    row.append(el('dt', '', label), dd); facts.append(row);
  }
  body.append(facts);
  for (const [label, url, primary] of [['Visit company website ↗', company.website, true], ['Check public source ↗', company.sourceUrl, false]]) {
    if (!url) continue;
    const a = el('a', `button${primary ? ' primary' : ''}`, label); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; body.append(a);
  }
  body.append(el('p', 'detail-disclaimer', 'Opening an external link shares a request with that site. No application is submitted and no personal profile is shared by this explorer.'));
  detail.append(back, body); detail.hidden = false; $('list-panel').hidden = true;
  setView('list'); document.querySelector('.results-panel').scrollTop = 0; heading.focus({preventScroll: true});
}
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !$('company-detail').hidden) closeDetail(); });

let pendingFit = false;
function fitResults() {
  if (!map || !mapReady) { pendingFit = true; return; }
  map.resize();
  if (!map.getContainer().clientWidth || !map.getContainer().clientHeight) { pendingFit = true; return; }
  pendingFit = false;
  const points = filtered.filter(hasPoint);
  if (!points.length) { map.jumpTo({center: [0, 25], zoom: 2}); return; }
  zoomToBounds(points, worldSpreadMaxZoom(points));
}


function worldSpreadMaxZoom(points) {
  const lngs = points.map(c => c.longitude);
  return Math.max(...lngs) - Math.min(...lngs) > 60 ? 2.8 : 5;
}
const ENTRY_MIN_ZOOM = 1.6;

// cameraForBounds + jumpTo: deterministic and honors maxZoom. fitBounds and
// easeTo both misbehaved under animation-less environments in verification.
function zoomToBounds(points, maxZoom) {
  if (!map) return;
  const lngs = points.map(c => c.longitude), lats = points.map(c => c.latitude);
  const camera = map.cameraForBounds(
    [[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]],
    {padding: {top: 60, bottom: 60, left: 85, right: 85}, maxZoom},
  );
  if (camera) map.jumpTo({center: camera.center, zoom: Math.max(camera.zoom, Math.min(maxZoom, ENTRY_MIN_ZOOM))});
}

function clearMarkers() {
  for (const marker of mapMarkers.splice(0)) marker.remove();
}

function addMapMarker(group, content, label, onClick) {
  const element = el('div', 'map-marker');
  element.append(content);
  element.tabIndex = 0; element.setAttribute('role', 'button');
  element.setAttribute('aria-label', label);
  element.addEventListener('click', onClick);
  element.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onClick(); } });
  const marker = new maplibregl.Marker({element, anchor: 'center'}).setLngLat([group.longitude, group.latitude]).addTo(map);
  mapMarkers.push(marker);
}
function cardIcon(text1, text2, extraClass = '') {
  const card = el('div', `map-card${extraClass ? ' ' + extraClass : ''}`);
  card.append(el('span', 'map-card-title', text1), el('span', 'map-card-count', text2));
  return card;
}

function addCard(group, title, countLabel, extraClass = '', nextLayerZoom = 0) {
  addMapMarker(group, cardIcon(title, countLabel, extraClass), `${title}, ${countLabel}`, () => {
    // Fit the group, but always advance at least into the next hierarchy
    // layer so a card click can never loop on the same view.
    const lngs = group.members.map(c => c.longitude), lats = group.members.map(c => c.latitude);
    const camera = map.cameraForBounds(
      [[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]],
      {padding: {top: 60, bottom: 60, left: 85, right: 85}, maxZoom: 12},
    );
    const sameSpot = new Set(group.members.map(c => `${c.latitude}:${c.longitude}`)).size === 1;
    if (camera) map.jumpTo({center: camera.center, zoom: Math.min(sameSpot ? 10 : 12, Math.max(camera.zoom, nextLayerZoom))});
  });
}

function companyPinIcon(company, multi) {
  const wrap = el('div', 'pin-wrap');
  const body = el('div', 'pin-body');
  if (company.logo) {
    const img = el('img', 'pin-logo');
    img.src = company.logo; img.alt = ''; img.loading = 'lazy';
    img.addEventListener('error', () => { img.replaceWith(el('span', 'pin-monogram', initials(company.name))); }, {once: true});
    body.append(img);
  } else {
    body.append(el('span', 'pin-monogram', initials(company.name)));
  }
  if (company.hiringSignal === 'directory_flag') {
    const dot = el('span', 'hiring-dot'); dot.title = 'Directory hiring flag (unverified)'; body.append(dot);
  }
  if (multi) body.append(el('span', 'pin-count', String(multi)));
  wrap.append(body, el('span', 'pin-name', multi ? `${multi} companies` : company.name));
  return wrap;
}

function renderPins() {
  if (!map || !mapReady) return;
  clearMarkers();
  const layer = zoomLayer(map.getZoom());
  const project = (lat, lng) => map.project([lng, lat]);
  if (layer === 'country') {
    for (const group of declutterCards(countryCards(filtered), project)) {
      const code = group.members.find(c => c.countryCode)?.countryCode;
      addCard(group, `${flagEmoji(code)} ${group.key}`.trim(), `${group.members.length.toLocaleString()} ${group.members.length === 1 ? 'company' : 'companies'}`, 'country-card', 4);

    }
    return;
  }
  if (layer === 'region') {
    for (const group of declutterCards(regionCards(filtered), project)) {
      const [, region, city] = group.key.includes('::') ? group.key.split('::') : [null, group.key, null];
      const label = group.key.startsWith('city::') ? city : region;
      addCard(group, label, `${group.members.length.toLocaleString()} ${group.members.length === 1 ? 'company' : 'companies'}`, '', 6);
    }
    return;
  }
  if (layer === 'city') {
    for (const group of declutterCards(cityCards(filtered), project)) {
      addCard(group, group.key, `${group.members.length.toLocaleString()} ${group.members.length === 1 ? 'company' : 'companies'}`, '', 8);
    }
    return;
  }
  // Street level. Companies share city-centre coordinates, so co-located
  // pins fan out on a deterministic spiral around their centre (like the
  // reference map) with an honest disclosure; beyond FANOUT_CAP per spot the
  // centroid keeps a count pin whose click filters the complete list.
  const bounds = map.getBounds();
  const inView = [], outView = [];
  for (const company of filtered.filter(hasPoint)) {
    (bounds.contains([company.longitude, company.latitude]) ? inView : outView).push(company);
  }
  const bySpot = new Map();
  for (const company of inView) {
    const key = `${company.latitude}:${company.longitude}`;
    if (!bySpot.has(key)) bySpot.set(key, []);
    bySpot.get(key).push(company);
  }
  let fanned = 0;
  for (const members of bySpot.values()) {
    const base = members[0];
    if (members.length === 1) { addCompanyPin(base, base, 0); continue; }
    const sorted = [...members].sort((a, b) => a.name.localeCompare(b.name, 'en'));
    const shown = sorted.slice(0, FANOUT_CAP);
    // Screen-space spiral (markercluster-style): a constant visual spread at
    // every zoom, converted back to coordinates for placement.
    const zoom = map.getZoom();
    const centre = map.project([base.longitude, base.latitude], zoom);
    shown.forEach((company, i) => {
      const angle = i * 2.399963, radius = 20 * Math.sqrt(i + 1); // pixels
      const point = map.unproject([centre.x + radius * Math.cos(angle), centre.y + radius * Math.sin(angle)], zoom);
      fanned++;
      addCompanyPin(company, {latitude: point.lat, longitude: point.lng}, 0);
    });
    if (members.length > FANOUT_CAP) {
      const extra = members.length - FANOUT_CAP;
      addCompanyPin(base, base, extra, members);
    }
  }
  $('map-spread-note').hidden = fanned === 0;
  // Out-of-viewport companies stay decluttered grid clusters.
  for (const group of groupPoints(outView, (lat, lng) => map.project([lng, lat]), true)) {
    if (group.members.length < 3) continue; // single/double distant pins are noise at street zoom
    const company = group.members[0];
    addCompanyPin(company, group, group.members.length, group.members);
  }
}

const FANOUT_CAP = 300;

function addCompanyPin(company, position, extraCount, groupMembers = null) {
  const multi = groupMembers ? groupMembers.length : 0;
  const label = multi ? `${multi} companies near ${company.locationLabel || 'this spot'}` : company.name;
  const pin = companyPinIcon(company, multi > 1 ? multi : 0);
  if (!$('show-names').checked) pin.querySelector('.pin-name').hidden = true;
  addMapMarker(position, pin, label, () => {
    if (!multi) { selectCompany(company); return; }
    groupIds = new Set(groupMembers.map(c => c.id)); state.company = ''; page = 0; updateURL();
    $('company-detail').hidden = true; $('list-panel').hidden = false; renderList();
    setView('list'); $('results-heading').focus({preventScroll: true});
  });
}
async function initializeMap() {
  try {
    if (!globalThis.maplibregl) throw new Error('Map library unavailable');
    // Street basemap: OpenFreeMap Positron (keyless, OpenStreetMap data). If
    // the style cannot be fetched, fall back to the self-hosted Natural Earth
    // outline so the map never renders a third-party error watermark.
    let style = 'https://tiles.openfreemap.org/styles/positron';
    try {
      const probe = await fetch(style, {credentials: 'omit', signal: AbortSignal.timeout(8000)});
      if (!probe.ok) throw new Error('style unavailable');
    } catch {
      const worldResponse = await fetch('data/world.geojson', {credentials: 'omit'});
      const world = worldResponse.ok ? await worldResponse.json() : {type: 'FeatureCollection', features: []};
      style = {version: 8, sources: {world: {type: 'geojson', data: world}}, layers: [
        {id: 'bg', type: 'background', paint: {'background-color': '#e7e6df'}},
        {id: 'land', type: 'fill', source: 'world', paint: {'fill-color': '#f5f1e9', 'fill-outline-color': '#d6cebd'}},
      ]};
    }
    map = new maplibregl.Map({
      container: 'map', style, center: [0, 25], zoom: 2, minZoom: 1, maxZoom: 12,
      maxBounds: [[-179.9, -85], [179.9, 85]], scrollZoom: false, attributionControl: {compact: true},
      fadeDuration: reducedMotion ? 0 : 300,
    });
    map.addControl(new maplibregl.NavigationControl({showCompass: false}), 'top-right');
    globalThis.__companyMap = map; // debug/test handle
    map.on('zoomend', renderPins);
    map.on('moveend', renderPins);
    map.on('resize', renderPins);
    map.on('load', () => { mapReady = true; renderPins(); });
    map.on('idle', () => { renderPins(); if (pendingFit) requestAnimationFrame(fitResults); });
    map.on('error', () => {
      $('map-status').hidden = false;
      $('map-status').textContent = 'Some map tiles failed to load. Company pins and the list still work.';
    });
  } catch {
    $('map-status').hidden = false;
    $('map-status').textContent = 'Map background unavailable. You can still explore all companies in the list.';
    if (!map) { setView('list'); $('fit-map').disabled = true; $('group-pins').disabled = true; $('show-names').disabled = true; }
  }
}
async function loadCatalogue() {
  if (loading) return;
  loading = true; $('load-error').hidden = true; $('empty-state').hidden = true;
  $('result-count').textContent = 'Loading companies…';
  for (const control of Object.values(controls)) control.disabled = true;
  $('retry').disabled = true;
  try {
    const response = await fetch('data/companies.json', {credentials: 'omit', signal: AbortSignal.timeout(15000)});
    if (!response.ok) throw new Error('Catalogue unavailable');
    const payload = await response.json(); companies = readCatalogue(payload);
    const {ROLE_AREAS} = await import('./map-core.mjs');
    addOptions('role', Object.keys(ROLE_AREAS).filter(a => ROLE_AREAS[a].length));
    addOptions('industry', companies.map(c => c.industry));
    addOptions('location', companies.flatMap(c => [c.country, c.region]));
    restoreControls();
    $('catalogue-total').textContent = `${companies.length.toLocaleString()} public companies`;
    $('snapshot-date').textContent = `Snapshot exported ${dateLabel(payload.exportedAt)}`;
    loading = false; render(); fitResults();
    for (const control of Object.values(controls)) control.disabled = false;
  } catch {
    loading = false; $('load-error').hidden = false; $('result-count').textContent = 'Catalogue unavailable';
    $('snapshot-date').textContent = 'Unable to load the snapshot'; setView('list');
  } finally { $('retry').disabled = false; }
}
$('retry').addEventListener('click', loadCatalogue);
// The basemap style and catalogue load independently; only map tiles contact
// a third party (OpenFreeMap), company data and logos stay self-hosted.
initializeMap();
loadCatalogue();
