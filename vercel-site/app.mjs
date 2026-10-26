import {PAGE_SIZE, citySlug, declutterDirectoryGroups, directoryGroups, filterJobs, matchSkills, readJobs, readState, stateQuery} from './jobs-core.mjs';
import {readCatalogue} from './map-core.mjs';
const $ = id => document.getElementById(id);
const el = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text != null) node.textContent = text; return node; };
const initials = name => name.split(/\s+/).slice(0, 2).map(word => word[0]).join('').toUpperCase();
function companyMark(job) {
  const mark = el('span','monogram');
  if (job.logo) {
    const image = el('img','company-logo'); image.src = '/' + job.logo; image.alt = ''; image.loading = 'lazy';
    image.addEventListener('error',() => { image.remove(); mark.textContent = initials(job.company); },{once:true}); mark.append(image);
  } else mark.textContent = initials(job.company);
  return mark;
}
const dateLabel = value => { const date = new Date(value); return Number.isNaN(date.valueOf()) ? 'Date unavailable' : date.toLocaleDateString('en', {year:'numeric',month:'short',day:'numeric',timeZone:'UTC'}); };
let jobs = [], filtered = [], companies = [], filteredCompanies = [], state = readState(location.search), page = 0, loading = false, map, mapReady = false, pendingFit = false;
let knownCities = new Map();
const pathCity = () => { try { return location.pathname.startsWith('/map/') ? citySlug(decodeURIComponent(location.pathname.split('/')[2] || '')) : ''; } catch { return ''; } };
const markers = [], controls = {q:$('search'), area:$('area'), type:$('type'), location:$('location')};
function samePlace(value) { return state.cityRoute ? citySlug(value) === state.cityRoute : value === state.location; }
function updateURL(replace = false) {
  const route = state.cityRoute || citySlug(state.location);
  const slug = knownCities.has(route) ? route : '';
  const path = slug ? `/map/${slug}` : (location.pathname.startsWith('/map/') ? '/' : location.pathname);
  const query = stateQuery({...state, location: slug ? '' : state.location});
  const url = `${path}${query ? '?' + query : ''}`;
  if (url !== location.pathname + location.search) history[replace ? 'replaceState' : 'pushState'](null, '', url);
}
function readControls() { for (const [key, control] of Object.entries(controls)) state[key] = control.value; }
function restoreControls() { for (const [key, control] of Object.entries(controls)) { if (control.tagName === 'SELECT' && ![...control.options].some(o => o.value === state[key])) state[key] = ''; control.value = state[key] || ''; } }
function addOptions(id, values) { const select = $(id); for (const value of [...new Set(values.filter(Boolean))].sort((a,b) => a.localeCompare(b))) select.add(new Option(value,value)); }
function setView(view) { state.view = view; document.querySelector('.explorer-body').dataset.view = view; $('nav-jobs').setAttribute('aria-current', view === 'jobs' ? 'page' : 'false'); $('nav-map').setAttribute('aria-current', view === 'map' ? 'page' : 'false'); updateURL(); render(); if (view === 'map') { loadCompanies(); requestAnimationFrame(() => { map?.resize(); renderPins(); }); } }
$('nav-jobs').addEventListener('click', () => setView('jobs'));
$('nav-map').addEventListener('click', () => setView('map'));
let searchTimer;
function applyFilters(fit = false, replace = false) { readControls(); state.cityRoute = knownCities.has(citySlug(state.location)) ? citySlug(state.location) : ''; state.job = ''; state.company = ''; page = 0; updateURL(replace); render(); if (fit) fitResults(); }
$('filters').addEventListener('submit', e => { e.preventDefault(); applyFilters(true); });
controls.q.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => applyFilters(true,true),180); });
for (const key of ['area','type','location']) controls[key].addEventListener('change', () => applyFilters(true));
$('filters').addEventListener('reset', e => { e.preventDefault(); state = {...readState(''),view:state.view}; state.cityRoute = ''; restoreControls(); page = 0; updateURL(); render(); fitResults(); });
window.addEventListener('popstate', () => { state = readState(location.search); applyPathCity(); restoreControls(); render(); const view = state.view === 'map' ? 'map' : 'jobs'; document.querySelector('.explorer-body').dataset.view = view; $('nav-jobs').setAttribute('aria-current',view === 'jobs' ? 'page' : 'false'); $('nav-map').setAttribute('aria-current',view === 'map' ? 'page' : 'false'); });
$('previous').addEventListener('click', () => { page--; renderList(); $('jobs-heading').focus(); });
$('next').addEventListener('click', () => { page++; renderList(); $('jobs-heading').focus(); });
$('fit-map').addEventListener('click', fitResults);
function areaCitySelected() { return state.view === 'map' && knownCities.has(citySlug(state.location)); }
function companyJobs(company) { return filtered.filter(job => job.company.toLocaleLowerCase('en') === company.name.toLocaleLowerCase('en') && (!state.location || job.locations.some(place => samePlace(place.city) || place.country === state.location))); }
function filterDirectory() {
  if (!areaCitySelected()) { filteredCompanies = []; return; }
  const query = state.q.toLocaleLowerCase('en');
  filteredCompanies = companies.filter(company => {
    const cityMatch = samePlace(company.locationLabel) || company.country === state.location || companyJobs(company).length > 0;
    const queryMatch = !query || [company.name,company.summary,company.industry,company.location].join(' ').toLocaleLowerCase('en').includes(query);
    const typeMatch = !state.type || (state.type === 'Startup' ? company.type === 'startup' : state.type === 'Public' ? company.type === 'public' : company.type === 'private');
    const roleMatch = !state.area || companyJobs(company).some(job => job.area === state.area);
    return cityMatch && queryMatch && typeMatch && roleMatch;
  });
}
function applyPathCity() {
  const slug = pathCity();
  if (slug) { state.cityRoute = slug; state.location = knownCities.get(slug)?.[0] || slug; if (!state.view) state.view = 'map'; }
}
function renderArea() {
  const area = $('area-context'), selected = state.location;
  const city = knownCities.has(citySlug(selected));
  const place = city ? filtered.flatMap(job => job.locations).find(item => item.city === selected) : null;
  const country = place?.country || filteredCompanies[0]?.country || (!city && selected ? selected : '');
  area.hidden = !selected;
  area.replaceChildren();
  $('jobs-heading').textContent = selected || 'Jobs for you to explore';
  document.querySelector('.list-note').textContent = city ? 'Browse public company records and their current roles in this area. Directory presence is not proof of hiring.' : '“For you” means discovery, not a hiring prediction. Check the original advert before applying.';
  document.title = selected ? `${selected} jobs · Hired` : 'Hired · European jobs, mapped to you';
  if (!selected) return;
  const crumbs = el('nav','area-breadcrumbs'); crumbs.setAttribute('aria-label','Area breadcrumb');
  const europe = el('button','area-crumb','Europe'); europe.type = 'button'; europe.addEventListener('click',() => { controls.location.value = ''; applyFilters(true); }); crumbs.append(europe);
  if (city && country) {
    crumbs.append(el('span','area-separator','›'));
    const countryButton = el('button','area-crumb',country); countryButton.type = 'button'; countryButton.addEventListener('click',() => { controls.location.value = country; applyFilters(true); }); crumbs.append(countryButton);
  }
  if (city) crumbs.append(el('span','area-separator','›'),el('strong','',selected));
  area.append(crumbs,el('p','area-summary',city ? `${filteredCompanies.length} companies · ${filteredCompanies.filter(company => companyJobs(company).length > 0).length} with open roles` : `${new Set(filtered.map(job => job.company)).size} companies · ${filtered.length} open roles in this snapshot`));
}
function render() {
  filtered = filterJobs(jobs,state); filterDirectory(); renderArea(); $('clear-filters').hidden = !['q','area','type','location'].some(k => controls[k].value);
  $('result-count').textContent = areaCitySelected() ? `${filteredCompanies.length} companies in this area · ${filtered.length} open roles` : `${filtered.length.toLocaleString()} ${filtered.length === 1 ? 'role' : 'roles'} · ${new Set(filtered.flatMap(j => j.locations.map(p => p.city))).size.toLocaleString()} mapped places`;
  $('empty-state').textContent = areaCitySelected() ? 'No companies match this area and these filters.' : 'No roles match. Try a broader search or clear a filter.';
  if (state.job && !filtered.some(j => j.id === state.job)) state.job = '';
  if (state.company && !companies.some(company => company.id === state.company)) state.company = '';
  renderList(); renderPins();
  if (state.company) renderCompanyDetail(companies.find(company => company.id === state.company));
  else renderDetail(filtered.find(j => j.id === state.job));
}
function directoryForMap() {
  const query = state.q.toLocaleLowerCase('en');
  return companies.filter(company => {
    const queryMatch = !query || [company.name,company.summary,company.industry,company.location].join(' ').toLocaleLowerCase('en').includes(query);
    const typeMatch = !state.type || (state.type === 'Startup' ? company.type === 'startup' : state.type === 'Public' ? company.type === 'public' : company.type === 'private');
    const roleMatch = !state.area || companyJobs(company).some(job => job.area === state.area);
    const locationMatch = !state.location || samePlace(company.locationLabel) || company.country === state.location;
    return queryMatch && typeMatch && roleMatch && locationMatch;
  });
}
function renderCompanyList() {
  const pages = Math.max(1,Math.ceil(filteredCompanies.length / PAGE_SIZE)); page = Math.max(0,Math.min(page,pages-1));
  const fragment = document.createDocumentFragment();
  for (const company of filteredCompanies.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE)) {
    const roles = companyJobs(company), li = el('li','company-row'), button = el('button','job-button'); button.type = 'button';
    button.setAttribute('aria-label',`View ${company.name}, ${roles.length} open roles`);
    const content = el('span','job-summary'); content.append(el('span','job-title',company.name),el('span','job-company',`${company.location || company.locationLabel} · ${company.industry}`),el('span','job-location',company.summary || 'Public company directory record'));
    const tags = el('span','company-tags'); tags.append(el('span','tag',company.type === 'startup' ? (company.fundingStage || 'Startup') : company.type === 'public' ? 'Public company' : 'Private company'),el('span','tag',`${roles.length} open roles`)); content.append(tags);
    button.append(companyMark({company:company.name,logo:company.logo}),content,el('span','row-arrow','→')); button.addEventListener('click',() => selectCompany(company)); li.append(button); fragment.append(li);
  }
  $('job-list').replaceChildren(fragment); $('pagination').hidden = filteredCompanies.length <= PAGE_SIZE; $('page-label').textContent = `${page+1} / ${pages}`; $('previous').disabled = page === 0; $('next').disabled = page === pages-1;
  $('empty-state').hidden = filteredCompanies.length > 0;
}
function renderList() {
  if (areaCitySelected()) { renderCompanyList(); return; }
  const pages = Math.max(1,Math.ceil(filtered.length / PAGE_SIZE)); page = Math.max(0,Math.min(page,pages-1));
  $('empty-state').hidden = filtered.length > 0 || loading || !$('load-error').hidden;
  const fragment = document.createDocumentFragment();
  for (const job of filtered.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE)) {
    const li = el('li','company-row'), button = el('button',`job-button${state.job === job.id ? ' is-selected' : ''}`);
    button.type = 'button'; button.setAttribute('aria-label',`View ${job.title} at ${job.company}`);
    const content = el('span','job-summary'); content.append(el('span','job-title',job.title),el('span','job-company',`${job.company} · ${job.companyType}`));
    const tags = el('span','company-tags'); tags.append(el('span','tag',job.area)); if (job.employment) tags.append(el('span','tag',job.employment)); content.append(tags,el('span','job-location',job.locations.map(p => p.label).join(' · ')));
    button.append(companyMark(job),content,el('span','row-arrow','→')); button.addEventListener('click',() => selectJob(job)); li.append(button); fragment.append(li);
  }
  $('job-list').replaceChildren(fragment); $('pagination').hidden = filtered.length <= PAGE_SIZE; $('page-label').textContent = `${page+1} / ${pages}`; $('previous').disabled = page === 0; $('next').disabled = page === pages-1;
}
function externalLink(label,url,primary=false) { const a = el('a',`button${primary ? ' primary' : ''}`,label); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a; }
function selectCompany(company) { state.company = company.id; state.job = ''; setView('jobs'); renderCompanyDetail(company); $('detail-title').focus({preventScroll:true}); }
function renderCompanyDetail(company) {
  document.querySelector('.explorer-body').classList.add('has-detail');
  const detail = $('job-detail'); detail.replaceChildren();
  const top = el('div','detail-top'), headingWrap = el('div'), title = el('h2','',company.name); title.id = 'detail-title'; title.tabIndex = -1;
  headingWrap.append(title,el('p','detail-subtitle',`${company.location || company.locationLabel} · ${company.industry}`)); top.append(companyMark({company:company.name,logo:company.logo}),headingWrap); detail.append(top);
  const actions = el('div','detail-actions');
  const back = el('button','button','← Back to area'); back.type = 'button'; back.addEventListener('click',() => { state.company=''; setView('map'); render(); }); actions.append(back);
  if (company.website) actions.append(externalLink('Visit company website ↗',company.website,true)); if (company.sourceUrl) actions.append(externalLink('Check public source ↗',company.sourceUrl)); detail.append(actions);
  const about = el('section','detail-section'); about.append(el('h3','','About the company'),el('p','',company.summary || 'No public description is available in this snapshot.')); detail.append(about);
  const roles = companyJobs(company), roleSection = el('section','detail-section'); roleSection.append(el('h3','',`${roles.length} open roles in this snapshot`));
  if (!roles.length) roleSection.append(el('p','','No current role from this company appears in our employer-board snapshot. Check the company website for other openings.'));
  for (const job of roles) { const button = el('button','button',`${job.title} →`); button.type = 'button'; button.addEventListener('click',() => selectJob(job)); roleSection.append(button); }
  detail.append(roleSection,el('p','field-note',`Directory facts imported ${dateLabel(company.observedAt)}. Company presence is not proof of a current vacancy.`));
}
function selectJob(job) { state.job = job.id; state.company = ''; setView('jobs'); renderList(); renderDetail(job); $('detail-title').focus({preventScroll:true}); }
function renderDetail(job) {
  document.querySelector('.explorer-body').classList.toggle('has-detail',Boolean(job));
  const detail = $('job-detail'); detail.replaceChildren(); if (!job) { const wrap = el('div','detail-placeholder'); wrap.append(el('span','','✳'),el('h2','','Choose a role. See the whole picture.'),el('p','','Review the job, its locations, skill overlap and contact-search options.')); detail.append(wrap); return; }
  const top = el('div','detail-top'), headingWrap = el('div'), title = el('h2','',job.title); title.id = 'detail-title'; title.tabIndex = -1; headingWrap.append(title,el('p','detail-subtitle',`${job.company} · ${job.companyType} · ${job.area}`)); top.append(companyMark(job),headingWrap); detail.append(top);
  const actions = el('div','detail-actions'); actions.append(externalLink('View official role ↗',job.url,true)); if (matchMedia('(max-width:700px)').matches) { const back = el('button','button','← All jobs'); back.type = 'button'; back.addEventListener('click',() => { state.job=''; state.company=''; updateURL(); document.querySelector('.explorer-body').dataset.view='jobs'; renderDetail(); renderList(); }); actions.append(back); } detail.append(actions);
  const overview = el('section','detail-section'); overview.append(el('h3','','Role locations')); const facts = el('div','detail-facts'); for (const place of job.locations) facts.append(el('span','tag',`${place.label} (${place.precision === 'city' ? 'city centre' : 'country estimate'})`)); overview.append(facts); if (job.workplace) overview.append(el('p','field-note',`Workplace: ${job.workplace}`)); if (job.sourceTimestamp) overview.append(el('p','field-note',`Employer-board ${job.sourceTimestampKind || 'timestamp'}: ${dateLabel(job.sourceTimestamp)}. This may not be the original posting date.`)); detail.append(overview);
  const match = el('section','detail-section'); match.append(el('h3','','Skills from your CV, GitHub or portfolio')); const label = el('label','','Type skills to compare (for example: Python, SQL, Docker)'); label.htmlFor = 'skill-profile'; const input = el('textarea'); input.id = 'skill-profile'; input.maxLength = 1800; input.placeholder = 'Python, SQL, Docker'; const result = el('div','match-result','Add skills to see exact overlap with terms found in this advert. No score is calculated without your input.'); input.addEventListener('input',() => { const matched = matchSkills(job,input.value); result.textContent = matched.length ? `${matched.length} exact term${matched.length === 1 ? '' : 's'} overlap: ${matched.join(', ')}. This is not a hiring probability; review the full context yourself.` : 'No exact overlap with the extracted terms yet. Missing terms are not proof that you lack relevant experience.'; }); match.append(label,input,el('p','field-note','Runs only in this page. Nothing is saved or uploaded. For CV and evidence analysis, use the private local app.'),result); detail.append(match);
  const contacts = el('section','detail-section'); contacts.append(el('h3','','People to contact on LinkedIn')); const links = el('div','contact-links'); const query = encodeURIComponent(`${job.company} ${job.area} ${job.locations[0].city}`); links.append(externalLink(`Search ${job.company} people in ${job.locations[0].city} ↗`,`https://www.linkedin.com/search/results/people/?keywords=${query}`),externalLink(`Search recruiting contacts at ${job.company} ↗`,`https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(job.company + ' recruiter')}`)); contacts.append(links,el('p','field-note','Search suggestions only—not verified employee recommendations. LinkedIn may require sign-in. No profiles are retrieved or contacted.')); detail.append(contacts);
  const about = el('section','detail-section'); about.append(el('h3','','About the role'),el('p','',job.description || 'Open the official advert for the complete description.')); if (job.skills.length) { const skills = el('div','company-tags'); for (const skill of job.skills) skills.append(el('span','tag',skill)); about.append(el('h3','','Terms detected in the advert'),skills); } detail.append(about,el('p','field-note',`Source: ${job.source} employer board. Verify the current advert and submit it yourself. Hired never applies on your behalf.`));
}
function clearMarkers() { for (const marker of markers.splice(0)) marker.remove(); }
function addAreaMarker(group, level) {
  const card = el('div','area-map-card');
  const thumb = el('span','area-map-thumb');
  if (group.logo) { const image = el('img','company-logo'); image.src = '/' + group.logo; image.alt = ''; thumb.append(image); } else thumb.textContent = initials(group.key);
  card.append(thumb,el('span','area-map-title',group.key),el('span','area-map-count',`${group.companies.length} companies · ${group.jobs} roles`));
  card.tabIndex = 0; card.setAttribute('role','button'); card.setAttribute('aria-label',`${group.key}, ${group.companies.length} companies and ${group.jobs} roles`);
  const choose = () => {
    if (level === 'country') map.jumpTo({center:[group.longitude,group.latitude],zoom:5});
    else { controls.location.value = group.key; applyFilters(); map.jumpTo({center:[group.longitude,group.latitude],zoom:8}); }
  };
  card.addEventListener('click',choose);
  card.addEventListener('keydown',event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); choose(); } });
  markers.push(new maplibregl.Marker({element:card,anchor:'center'}).setLngLat([group.longitude,group.latitude]).addTo(map));
}
function currentMapPoints(directory) {
  const directoryPoints = directory.filter(company => !filtered.some(job => job.company.toLocaleLowerCase('en') === company.name.toLocaleLowerCase('en'))).map(company => ({kind:'directory',record:company,location:{latitude:company.latitude,longitude:company.longitude,city:company.locationLabel,label:company.location || company.locationLabel}}));
  const jobPoints = filtered.flatMap(job => job.locations.map(location => ({kind:'job',record:job,location})));
  return [...directoryPoints,...jobPoints];
}
function renderPins() {
  if (!map || !mapReady) return; clearMarkers();
  const zoom = map.getZoom();
  const directory = directoryForMap();
  const project = (lat,lng) => map.project([lng,lat]);
  if (zoom <= 3) { for (const group of declutterDirectoryGroups(directoryGroups(directory,filtered,'country'),project)) addAreaMarker(group,'country'); return; }
  if (zoom <= 7) { for (const group of declutterDirectoryGroups(directoryGroups(directory,filtered,'city'),project)) addAreaMarker(group,'city'); return; }
  const bounds = map.getBounds();
  const points = currentMapPoints(directory).filter(point => bounds.contains([point.location.longitude,point.location.latitude]));
  const groups = new Map(); for (const point of points) { const key = `${point.kind}:${point.location.latitude}:${point.location.longitude}`; if (!groups.has(key)) groups.set(key,[]); groups.get(key).push(point); }
  for (const members of groups.values()) {
    const {location,kind} = members[0], records = [...new Map(members.map(point => [point.record.id,point.record])).values()];
    const pin = el('div',`job-pin${records.length > 1 ? ' group' : ''}${kind === 'directory' ? ' directory-pin' : ''}`);
    if (records.length === 1 && records[0].logo) { const image = el('img','job-pin-logo'); image.src = '/' + records[0].logo; image.alt = ''; pin.append(image); }
    else pin.append(el('span','',String(records.length)));
    pin.tabIndex = 0; pin.setAttribute('role','button'); pin.setAttribute('aria-label',kind === 'job' ? `${records.length} roles near ${location.label}` : `${records.length} directory companies near ${location.label}`);
    const choose = () => { if (records.length === 1) { if (kind === 'job') selectJob(records[0]); else selectCompany(records[0]); } else { controls.location.value = location.city; applyFilters(); } };
    pin.addEventListener('click',choose); pin.addEventListener('keydown',e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose(); } });
    markers.push(new maplibregl.Marker({element:pin}).setLngLat([location.longitude,location.latitude]).addTo(map));
  }
}
function fitResults() {
  if (!map || !mapReady) { pendingFit = true; return; } pendingFit = false; map.resize(); const points = currentMapPoints(directoryForMap()).map(point => point.location); if (!points.length) return;
  const lngs = points.map(p => p.longitude), lats = points.map(p => p.latitude); const camera = map.cameraForBounds([[Math.min(...lngs),Math.min(...lats)],[Math.max(...lngs),Math.max(...lats)]],{padding:70,maxZoom:7}); if (camera) map.jumpTo({center:camera.center,zoom:Math.max(2.8,camera.zoom)});
}
async function initializeMap() {
  try {
    if (!globalThis.maplibregl) throw new Error('Map unavailable');
    let style = 'https://tiles.openfreemap.org/styles/positron';
    try { const response = await fetch(style,{credentials:'omit',signal:AbortSignal.timeout(8000)}); if (!response.ok) throw new Error('Style unavailable'); } catch { const response = await fetch('/data/world.geojson'); const world = await response.json(); style = {version:8,sources:{world:{type:'geojson',data:world}},layers:[{id:'bg',type:'background',paint:{'background-color':'#eee9df'}},{id:'land',type:'fill',source:'world',paint:{'fill-color':'#fff7e9','fill-outline-color':'#d7c7b2'}}]}; }
    map = new maplibregl.Map({container:'map',style,center:[12,51],zoom:3.4,minZoom:2,maxZoom:10,scrollZoom:false,attributionControl:{compact:true},fadeDuration:matchMedia('(prefers-reduced-motion:reduce)').matches ? 0 : 250}); globalThis.__hiredMap = map; map.addControl(new maplibregl.NavigationControl({showCompass:false}),'top-right'); map.on('load',() => { mapReady = true; renderPins(); if (pendingFit) fitResults(); }); map.on('moveend',renderPins); map.on('idle',() => { if (!$('job-list').children.length) renderPins(); }); map.on('error',() => { $('map-status').hidden = false; $('map-status').textContent = 'Some map tiles failed. The job list still works.'; });
  } catch { $('map-status').hidden = false; $('map-status').textContent = 'Map unavailable. All roles remain in Jobs.'; $('fit-map').disabled = true; }
}
let companiesLoading = false, companiesLoaded = false;
function registerCities(records) {
  const routes = new Map();
  for (const record of records) {
    const city = record.locationLabel || record.city;
    if (!city || city === record.country || !['city','hq'].includes(record.precision)) continue;
    const slug = citySlug(city), labels = routes.get(slug) || [];
    if (!labels.includes(city)) labels.push(city);
    routes.set(slug, labels);
  }
  knownCities = routes;
}
async function loadCompanies() {
  if (companiesLoaded || companiesLoading) return;
  companiesLoading = true;
  try {
    const response = await fetch('/data/companies.json',{credentials:'omit',signal:AbortSignal.timeout(20000)});
    if (!response.ok) throw new Error('Company catalogue unavailable');
    companies = readCatalogue(await response.json());
    registerCities([...companies,...jobs.flatMap(job => job.locations)]);
    addOptions('location',[...companies.flatMap(company => [company.locationLabel,company.country]),...jobs.flatMap(job => job.locations.flatMap(place => [place.city,place.country]))]);
    applyPathCity(); restoreControls(); companiesLoaded = true;
    $('map-status').hidden = true; render(); fitResults();
  } catch {
    $('map-status').hidden = false;
    $('map-status').textContent = 'Company catalogue unavailable. Job search and official role links still work.';
  } finally { companiesLoading = false; }
}
async function loadJobs() {
  if (loading) return; loading = true; $('load-error').hidden = true;
  try {
    const response = await fetch('/data/jobs.json',{credentials:'omit',signal:AbortSignal.timeout(15000)});
    if (!response.ok) throw new Error('Snapshot unavailable');
    const payload = await response.json(); jobs = readJobs(payload);
    registerCities(jobs.flatMap(job => job.locations));
    addOptions('area',jobs.map(j => j.area)); addOptions('location',jobs.flatMap(j => j.locations.flatMap(p => [p.city,p.country])));
    applyPathCity(); restoreControls();
    $('job-total').textContent = `${jobs.length} European roles from ${new Set(jobs.map(j => j.company)).size} companies`;
    $('snapshot-date').textContent = `Public-board snapshot exported ${dateLabel(payload.exportedAt)}`;
    loading = false; document.querySelector('.explorer-body').dataset.view = state.view === 'map' ? 'map' : 'jobs';
    render(); fitResults();
    if (state.view === 'map' || pathCity()) loadCompanies();
  } catch { loading = false; $('load-error').hidden = false; $('result-count').textContent = 'Vacancy snapshot unavailable'; }
}
$('retry').addEventListener('click',loadJobs); initializeMap(); loadJobs();
