import {PAGE_SIZE, filterJobs, matchSkills, readJobs, readState, stateQuery} from './jobs-core.mjs';
const $ = id => document.getElementById(id);
const el = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text != null) node.textContent = text; return node; };
const initials = name => name.split(/\s+/).slice(0, 2).map(word => word[0]).join('').toUpperCase();
const dateLabel = value => { const date = new Date(value); return Number.isNaN(date.valueOf()) ? 'Date unavailable' : date.toLocaleDateString('en', {year:'numeric',month:'short',day:'numeric',timeZone:'UTC'}); };
let jobs = [], filtered = [], state = readState(location.search), page = 0, loading = false, map, mapReady = false, pendingFit = false;
const markers = [], controls = {q:$('search'), area:$('area'), type:$('type'), location:$('location')};
function updateURL(replace = false) { const query = stateQuery(state); const url = `${location.pathname}${query ? '?' + query : ''}`; if (url !== location.pathname + location.search) history[replace ? 'replaceState' : 'pushState'](null, '', url); }
function readControls() { for (const [key, control] of Object.entries(controls)) state[key] = control.value; }
function restoreControls() { for (const [key, control] of Object.entries(controls)) { if (control.tagName === 'SELECT' && ![...control.options].some(o => o.value === state[key])) state[key] = ''; control.value = state[key] || ''; } }
function addOptions(id, values) { const select = $(id); for (const value of [...new Set(values.filter(Boolean))].sort((a,b) => a.localeCompare(b))) select.add(new Option(value,value)); }
function setView(view) { state.view = view; document.querySelector('.explorer-body').dataset.view = view; $('nav-jobs').setAttribute('aria-current', view === 'jobs' ? 'page' : 'false'); $('nav-map').setAttribute('aria-current', view === 'map' ? 'page' : 'false'); updateURL(); if (view === 'map') requestAnimationFrame(() => { map?.resize(); renderPins(); }); }
$('nav-jobs').addEventListener('click', () => setView('jobs'));
$('nav-map').addEventListener('click', () => setView('map'));
let searchTimer;
function applyFilters(fit = false, replace = false) { readControls(); state.job = ''; page = 0; updateURL(replace); render(); if (fit) fitResults(); }
$('filters').addEventListener('submit', e => { e.preventDefault(); applyFilters(true); });
controls.q.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => applyFilters(true,true),180); });
for (const key of ['area','type','location']) controls[key].addEventListener('change', () => applyFilters(true));
$('filters').addEventListener('reset', e => { e.preventDefault(); state = {...readState(''),view:state.view}; restoreControls(); page = 0; updateURL(); render(); fitResults(); });
window.addEventListener('popstate', () => { state = readState(location.search); restoreControls(); render(); const view = state.view === 'map' ? 'map' : 'jobs'; document.querySelector('.explorer-body').dataset.view = view; $('nav-jobs').setAttribute('aria-current',view === 'jobs' ? 'page' : 'false'); $('nav-map').setAttribute('aria-current',view === 'map' ? 'page' : 'false'); });
$('previous').addEventListener('click', () => { page--; renderList(); $('jobs-heading').focus(); });
$('next').addEventListener('click', () => { page++; renderList(); $('jobs-heading').focus(); });
$('fit-map').addEventListener('click', fitResults);
function render() {
  filtered = filterJobs(jobs,state); $('clear-filters').hidden = !['q','area','type','location'].some(k => controls[k].value);
  $('result-count').textContent = `${filtered.length.toLocaleString()} ${filtered.length === 1 ? 'role' : 'roles'} · ${new Set(filtered.flatMap(j => j.locations.map(p => p.city))).size.toLocaleString()} mapped places`;
  if (state.job && !filtered.some(j => j.id === state.job)) state.job = '';
  renderList(); renderPins(); renderDetail(filtered.find(j => j.id === state.job));
}
function renderList() {
  const pages = Math.max(1,Math.ceil(filtered.length / PAGE_SIZE)); page = Math.max(0,Math.min(page,pages-1));
  $('empty-state').hidden = filtered.length > 0 || loading || !$('load-error').hidden;
  const fragment = document.createDocumentFragment();
  for (const job of filtered.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE)) {
    const li = el('li','company-row'), button = el('button',`job-button${state.job === job.id ? ' is-selected' : ''}`);
    button.type = 'button'; button.setAttribute('aria-label',`View ${job.title} at ${job.company}`);
    const content = el('span','job-summary'); content.append(el('span','job-title',job.title),el('span','job-company',`${job.company} · ${job.companyType}`));
    const tags = el('span','company-tags'); tags.append(el('span','tag',job.area)); if (job.employment) tags.append(el('span','tag',job.employment)); content.append(tags,el('span','job-location',job.locations.map(p => p.label).join(' · ')));
    button.append(el('span','monogram',initials(job.company)),content,el('span','row-arrow','→')); button.addEventListener('click',() => selectJob(job)); li.append(button); fragment.append(li);
  }
  $('job-list').replaceChildren(fragment); $('pagination').hidden = filtered.length <= PAGE_SIZE; $('page-label').textContent = `${page+1} / ${pages}`; $('previous').disabled = page === 0; $('next').disabled = page === pages-1;
}
function externalLink(label,url,primary=false) { const a = el('a',`button${primary ? ' primary' : ''}`,label); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a; }
function selectJob(job) { state.job = job.id; setView('jobs'); renderList(); renderDetail(job); $('detail-title').focus({preventScroll:true}); }
function renderDetail(job) {
  document.querySelector('.explorer-body').classList.toggle('has-detail',Boolean(job));
  const detail = $('job-detail'); detail.replaceChildren(); if (!job) { const wrap = el('div','detail-placeholder'); wrap.append(el('span','','✳'),el('h2','','Choose a role. See the whole picture.'),el('p','','Review the job, its locations, skill overlap and contact-search options.')); detail.append(wrap); return; }
  const top = el('div','detail-top'), headingWrap = el('div'), title = el('h2','',job.title); title.id = 'detail-title'; title.tabIndex = -1; headingWrap.append(title,el('p','detail-subtitle',`${job.company} · ${job.companyType} · ${job.area}`)); top.append(el('span','monogram',initials(job.company)),headingWrap); detail.append(top);
  const actions = el('div','detail-actions'); actions.append(externalLink('View official role ↗',job.url,true)); if (matchMedia('(max-width:700px)').matches) { const back = el('button','button','← All jobs'); back.type = 'button'; back.addEventListener('click',() => { state.job=''; updateURL(); document.querySelector('.explorer-body').dataset.view='jobs'; renderDetail(); renderList(); }); actions.append(back); } detail.append(actions);
  const overview = el('section','detail-section'); overview.append(el('h3','','Role locations')); const facts = el('div','detail-facts'); for (const place of job.locations) facts.append(el('span','tag',`${place.label} (${place.precision === 'city' ? 'city centre' : 'country estimate'})`)); overview.append(facts); if (job.workplace) overview.append(el('p','field-note',`Workplace: ${job.workplace}`)); if (job.sourceTimestamp) overview.append(el('p','field-note',`Employer-board ${job.sourceTimestampKind || 'timestamp'}: ${dateLabel(job.sourceTimestamp)}. This may not be the original posting date.`)); detail.append(overview);
  const match = el('section','detail-section'); match.append(el('h3','','Skills from your CV, GitHub or portfolio')); const label = el('label','','Type skills to compare (for example: Python, SQL, Docker)'); label.htmlFor = 'skill-profile'; const input = el('textarea'); input.id = 'skill-profile'; input.maxLength = 1800; input.placeholder = 'Python, SQL, Docker'; const result = el('div','match-result','Add skills to see exact overlap with terms found in this advert. No score is calculated without your input.'); input.addEventListener('input',() => { const matched = matchSkills(job,input.value); result.textContent = matched.length ? `${matched.length} exact term${matched.length === 1 ? '' : 's'} overlap: ${matched.join(', ')}. This is not a hiring probability; review the full context yourself.` : 'No exact overlap with the extracted terms yet. Missing terms are not proof that you lack relevant experience.'; }); match.append(label,input,el('p','field-note','Runs only in this page. Nothing is saved or uploaded. For CV and evidence analysis, use the private local app.'),result); detail.append(match);
  const contacts = el('section','detail-section'); contacts.append(el('h3','','People to contact on LinkedIn')); const links = el('div','contact-links'); const query = encodeURIComponent(`${job.company} ${job.area} ${job.locations[0].city}`); links.append(externalLink(`Search ${job.company} people in ${job.locations[0].city} ↗`,`https://www.linkedin.com/search/results/people/?keywords=${query}`),externalLink(`Search recruiting contacts at ${job.company} ↗`,`https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(job.company + ' recruiter')}`)); contacts.append(links,el('p','field-note','Search suggestions only—not verified employee recommendations. LinkedIn may require sign-in. No profiles are retrieved or contacted.')); detail.append(contacts);
  const about = el('section','detail-section'); about.append(el('h3','','About the role'),el('p','',job.description || 'Open the official advert for the complete description.')); if (job.skills.length) { const skills = el('div','company-tags'); for (const skill of job.skills) skills.append(el('span','tag',skill)); about.append(el('h3','','Terms detected in the advert'),skills); } detail.append(about,el('p','field-note',`Source: ${job.source} employer board. Verify the current advert and submit it yourself. Hired never applies on your behalf.`));
}
function clearMarkers() { for (const marker of markers.splice(0)) marker.remove(); }
function renderPins() {
  if (!map || !mapReady) return; clearMarkers();
  const points = filtered.flatMap(job => job.locations.map(location => ({job,location})));
  const groups = new Map(); for (const point of points) { const key = `${point.location.latitude}:${point.location.longitude}`; if (!groups.has(key)) groups.set(key,[]); groups.get(key).push(point); }
  for (const members of groups.values()) {
    const {location} = members[0], jobsHere = [...new Map(members.map(p => [p.job.id,p.job])).values()];
    const pin = el('div',`job-pin${jobsHere.length > 1 ? ' group' : ''}`); pin.append(el('span','',String(jobsHere.length))); pin.tabIndex = 0; pin.setAttribute('role','button'); pin.setAttribute('aria-label',`${jobsHere.length} roles near ${location.label}`);
    const choose = () => { if (jobsHere.length === 1) selectJob(jobsHere[0]); else { controls.location.value = location.city; applyFilters(); } };
    pin.addEventListener('click',choose); pin.addEventListener('keydown',e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose(); } });
    markers.push(new maplibregl.Marker({element:pin}).setLngLat([location.longitude,location.latitude]).addTo(map));
  }
}
function fitResults() {
  if (!map || !mapReady) { pendingFit = true; return; } pendingFit = false; map.resize(); const points = filtered.flatMap(j => j.locations); if (!points.length) return;
  const lngs = points.map(p => p.longitude), lats = points.map(p => p.latitude); const camera = map.cameraForBounds([[Math.min(...lngs),Math.min(...lats)],[Math.max(...lngs),Math.max(...lats)]],{padding:70,maxZoom:7}); if (camera) map.jumpTo({center:camera.center,zoom:Math.max(2.8,camera.zoom)});
}
async function initializeMap() {
  try {
    if (!globalThis.maplibregl) throw new Error('Map unavailable');
    let style = 'https://tiles.openfreemap.org/styles/positron';
    try { const response = await fetch(style,{credentials:'omit',signal:AbortSignal.timeout(8000)}); if (!response.ok) throw new Error('Style unavailable'); } catch { const response = await fetch('data/world.geojson'); const world = await response.json(); style = {version:8,sources:{world:{type:'geojson',data:world}},layers:[{id:'bg',type:'background',paint:{'background-color':'#eee9df'}},{id:'land',type:'fill',source:'world',paint:{'fill-color':'#fff7e9','fill-outline-color':'#d7c7b2'}}]}; }
    map = new maplibregl.Map({container:'map',style,center:[12,51],zoom:3.4,minZoom:2,maxZoom:10,scrollZoom:false,attributionControl:{compact:true},fadeDuration:matchMedia('(prefers-reduced-motion:reduce)').matches ? 0 : 250}); map.addControl(new maplibregl.NavigationControl({showCompass:false}),'top-right'); map.on('load',() => { mapReady = true; renderPins(); if (pendingFit) fitResults(); }); map.on('idle',() => { if (!$('job-list').children.length) renderPins(); }); map.on('error',() => { $('map-status').hidden = false; $('map-status').textContent = 'Some map tiles failed. The job list still works.'; });
  } catch { $('map-status').hidden = false; $('map-status').textContent = 'Map unavailable. All roles remain in Jobs.'; $('fit-map').disabled = true; }
}
async function loadJobs() {
  if (loading) return; loading = true; $('load-error').hidden = true;
  try { const response = await fetch('data/jobs.json',{credentials:'omit',signal:AbortSignal.timeout(15000)}); if (!response.ok) throw new Error('Snapshot unavailable'); const payload = await response.json(); jobs = readJobs(payload); addOptions('area',jobs.map(j => j.area)); addOptions('location',jobs.flatMap(j => j.locations.flatMap(p => [p.city,p.country]))); restoreControls(); $('job-total').textContent = `${jobs.length} European roles from ${new Set(jobs.map(j => j.company)).size} companies`; $('snapshot-date').textContent = `Public-board snapshot exported ${dateLabel(payload.exportedAt)}`; loading = false; document.querySelector('.explorer-body').dataset.view = state.view === 'map' ? 'map' : 'jobs'; render(); fitResults(); } catch { loading = false; $('load-error').hidden = false; $('result-count').textContent = 'Vacancy snapshot unavailable'; } }
$('retry').addEventListener('click',loadJobs); initializeMap(); loadJobs();
