import {STAGES, SIGNALS, PAGE_SIZE, filterCompanies, groupPoints, hasPoint, readCatalogue, readState, stateQuery} from './map-core.mjs';

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
let map, markers, loading = false, lastSelected = null;
const controls = {q: $('search'), stage: $('stage'), industry: $('industry'), location: $('location'), signal: $('signal')};
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

function setView(view) {
  document.querySelector('.explorer-body').dataset.view = view;
  $('list-view').setAttribute('aria-pressed', String(view === 'list'));
  $('map-view').setAttribute('aria-pressed', String(view === 'map'));
  if (view === 'map') requestAnimationFrame(() => map?.invalidateSize());
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
$('filters').addEventListener('submit', event => { event.preventDefault(); clearTimeout(searchTimer); applyFilters({fit: true}); });
let searchTimer;
controls.q.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => applyFilters({fit: true, replace: true}), 180); });
for (const key of ['stage', 'industry', 'location', 'signal']) controls[key].addEventListener('change', () => { clearTimeout(searchTimer); applyFilters({fit: true}); });
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
    tags.append(el('span', 'tag', STAGES[company.stage]), el('span', 'tag', company.industry));
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
  if (map && hasPoint(company)) map.setView([company.latitude, company.longitude], company.precision === 'city' ? 5 : 3, {animate: !reducedMotion});
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
  const locationAccuracy = company.precision === 'city' ? 'Approximate city centre, not an office address.' : company.precision === 'country' ? 'Country-centre estimate. City not resolved.' : 'Not pinned. No reliable location resolved.';
  for (const [label, value, note] of [
    ['Location', company.location || 'Unknown', locationAccuracy],
    ['Company stage', STAGES[company.stage], company.stageBasis || 'No supporting stage facts available.'],
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

function fitResults() {
  if (!map) return;
  map.invalidateSize();
  const points = filtered.filter(hasPoint);
  if (!points.length) { map.setView([25, 0], 2, {animate: false}); return; }
  map.fitBounds(points.map(c => [c.latitude, c.longitude]), {padding: [55, 85], maxZoom: 5, animate: !reducedMotion});
}
function renderPins() {
  if (!map || !markers) return;
  markers.clearLayers();
  const groups = groupPoints(filtered, (lat, lng) => map.project([lat, lng], map.getZoom()), $('group-pins').checked);
  for (const group of groups) {
    const multi = group.members.length > 1;
    const country = group.members.every(c => c.precision === 'country');
    const markerBody = el('div', `pin-dot${multi ? ' cluster' : ''}${country ? ' country' : ''}`, multi ? String(group.members.length) : initials(group.members[0].name));
    const size = multi ? 38 : 30;
    const label = multi ? `${group.members.length} companies near ${group.members[0].locationLabel || 'this region'}` : group.members[0].name;
    const marker = L.marker([group.latitude, group.longitude], {
      icon: L.divIcon({html: markerBody, className: 'company-pin', iconSize: [size, size], iconAnchor: [size / 2, size / 2]}),
      keyboard: true, title: label, alt: label,
    }).addTo(markers);
    const tooltip = el('span', '', label);
    marker.bindTooltip(tooltip, {permanent: $('show-names').checked, direction: 'top', className: 'company-tooltip', offset: [0, -12]});
    const markerEl = marker.getElement();
    if (markerEl) markerEl.setAttribute('aria-label', label);
    marker.on('click', () => {
      if (!multi) { selectCompany(group.members[0]); return; }
      groupIds = new Set(group.members.map(c => c.id)); state.company = ''; page = 0; updateURL();
      $('company-detail').hidden = true; $('list-panel').hidden = false; renderList();
      const positions = new Set(group.members.map(c => `${c.latitude}:${c.longitude}`));
      if (positions.size > 1) map.fitBounds(group.members.map(c => [c.latitude, c.longitude]), {padding: [60, 85], maxZoom: 5, animate: !reducedMotion});
      else map.setView([group.latitude, group.longitude], country ? 3 : 5, {animate: !reducedMotion});
      setView('list'); $('results-heading').focus({preventScroll: true});
    });
  }
}
async function initializeMap() {
  try {
    if (!globalThis.L) throw new Error('Map library unavailable');
    map = L.map('map', {zoomControl: false, minZoom: 1, maxZoom: 7, maxBounds: [[-85, -210], [85, 210]], maxBoundsViscosity: 1, scrollWheelZoom: false, zoomAnimation: !reducedMotion, fadeAnimation: !reducedMotion}).setView([25, 0], 2);
    L.control.zoom({position: 'topright'}).addTo(map);
    map.attributionControl.setPrefix('<a href="https://leafletjs.com" rel="noreferrer">Leaflet</a>');
    map.attributionControl.addAttribution('<a href="https://www.naturalearthdata.com/about/terms-of-use/" rel="noreferrer">Natural Earth</a> · approximate locations');
    markers = L.layerGroup().addTo(map);
    map.on('zoomend', renderPins);
    map.on('resize', renderPins);
    const response = await fetch('data/world.geojson', {credentials: 'omit'});
    if (!response.ok) throw new Error('Base map unavailable');
    const world = await response.json();
    L.geoJSON(world, {style: {color: '#d6cebd', weight: 0.7, fillColor: '#f5f1e9', fillOpacity: 1}, interactive: false}).addTo(map).bringToBack();
    renderPins();
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
    addOptions('industry', companies.map(c => c.industry)); addOptions('location', companies.map(c => c.locationLabel));
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
// The world outline and catalogue load independently; neither contacts a third party.
initializeMap();
loadCatalogue();
