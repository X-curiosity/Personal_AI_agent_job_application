import {PAGE_SIZE, buildCityCountries, buildCityRoutes, citySlug, continentForCountry, countryFlag, declutterDirectoryGroups, directoryGroups, filterJobs, matchCvText, readJobs, readState, stateQuery} from './jobs-core.mjs';
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
let knownCities = new Map(), knownCityCountries = new Map(), jobsByCompany = new Map(), peopleByCompany = new Map();
const PREFS_KEY = 'hired-prefs';
function loadPrefs() { try { const p = JSON.parse(localStorage.getItem(PREFS_KEY)); if (p && typeof p === 'object') return Object.assign({sectors:[],keywords:'',location:'',companyType:''}, p); } catch {} return {sectors:[],keywords:'',location:'',companyType:''}; }
let prefs = loadPrefs();
function savePrefs() { try { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); } catch {} }
function applyPrefs(list) {
  const kw = (prefs.keywords || '').toLocaleLowerCase('en'), loc = (prefs.location || '').toLocaleLowerCase('en');
  return list.filter(job => (!prefs.sectors.length || prefs.sectors.includes(job.sector)) && (!kw || [job.title, job.company, ...job.skills, ...job.locations.map(p => p.label)].join(' ').toLocaleLowerCase('en').includes(kw)) && (!prefs.companyType || job.companyType === prefs.companyType) && (!loc || job.locations.some(p => (p.label || '').toLocaleLowerCase('en').includes(loc))));
}
const pathCity = () => { try { return location.pathname.startsWith('/map/') ? citySlug(decodeURIComponent(location.pathname.split('/')[2] || '')) : ''; } catch { return ''; } };
const isMapPage = () => location.pathname === '/map' || location.pathname.startsWith('/map/');
const markers = [], controls = {q:$('search'), area:$('area'), type:$('type'), location:$('location'), hiring:$('hiring')};
function samePlace(value) { return state.cityRoute ? citySlug(value) === state.cityRoute : value === state.location; }
function sameCountry(value) { return !state.country || value === state.country; }
function updateURL(replace = false) {
  const map = state.view === 'map';
  let path;
  if (map) {
    const route = state.cityRoute || (knownCities.has(citySlug(state.location)) ? citySlug(state.location) : '');
    path = route ? `/map/${route}` : '/map';
  } else {
    path = '/';
  }
  const query = stateQuery({...state, view: '', location: map && state.cityRoute ? '' : state.location, country: map && state.cityRoute && (knownCityCountries.get(state.cityRoute) || []).length <= 1 ? '' : state.country});
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
function applyFilters(fit = false, replace = false) { readControls(); state.cityRoute = knownCities.has(citySlug(state.location)) ? citySlug(state.location) : ''; const countries = knownCityCountries.get(state.cityRoute) || []; if (!state.cityRoute) state.country = ''; else if (!countries.includes(state.country)) state.country = countries[0] || ''; state.job = ''; state.company = ''; page = 0; updateURL(replace); render(); if (fit) fitResults(); }
$('filters').addEventListener('submit', e => { e.preventDefault(); applyFilters(true); });
controls.q.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => applyFilters(true,true),180); });
for (const key of ['area','type','location','hiring']) controls[key].addEventListener('change', () => applyFilters(true));
$('filters').addEventListener('reset', e => { e.preventDefault(); state = {...readState(''),view:state.view}; state.cityRoute = ''; restoreControls(); page = 0; updateURL(); render(); fitResults(); });
window.addEventListener('popstate', () => { state = readState(location.search); state.view = isMapPage() ? 'map' : 'jobs'; applyPathCity(); restoreControls(); render(); const view = state.view; document.querySelector('.explorer-body').dataset.view = view; $('nav-jobs').setAttribute('aria-current',view === 'jobs' ? 'page' : 'false'); $('nav-map').setAttribute('aria-current',view === 'map' ? 'page' : 'false'); });
$('previous').addEventListener('click', () => { page--; renderList(); $('jobs-heading').focus(); });
$('next').addEventListener('click', () => { page++; renderList(); $('jobs-heading').focus(); });
$('fit-map').addEventListener('click', fitResults);
$('prefs-button').addEventListener('click', () => showOnboarding(true));
$('back-jobs').addEventListener('click', () => setView('jobs'));
function areaCitySelected() { return state.view === 'map' && knownCities.has(citySlug(state.location)); }
function indexJobs() { jobsByCompany = new Map(); for (const job of jobs) { const key = job.company.toLocaleLowerCase('en'); (jobsByCompany.get(key) || jobsByCompany.set(key, []).get(key)).push(job); } }
function openRolesFor(company) { return jobsByCompany.get(company.name.toLocaleLowerCase('en')) || []; }
function companyJobs(company) { return openRolesFor(company).filter(job => !state.location || job.locations.some(place => samePlace(place.city) && sameCountry(place.country))); }
function hiringStatus(company) {
  if (openRolesFor(company).length) return {key:'hiring', label:'Hiring now', tone:'hiring'};
  if (company.hiringSignal === 'directory_flag') return {key:'flag', label:'Lists hiring', tone:'flag'};
  return {key:'none', label:'No open roles', tone:'none'};
}
function hiringMatch(company) { return !state.hiring || hiringStatus(company).key === state.hiring; }
function filterDirectory() {
  if (state.view !== 'map') { filteredCompanies = []; return; }
  const query = state.q.toLocaleLowerCase('en');
  const inArea = areaCitySelected();
  filteredCompanies = companies.filter(company => {
    const locationMatch = inArea
      ? (samePlace(company.locationLabel) && sameCountry(company.country)) || company.country === state.location || companyJobs(company).length > 0
      : (!state.location || (samePlace(company.locationLabel) && sameCountry(company.country)) || company.country === state.location);
    const queryMatch = !query || [company.name,company.summary,company.industry,company.location].join(' ').toLocaleLowerCase('en').includes(query);
    const typeMatch = !state.type || (state.type === 'Startup' ? company.type === 'startup' : state.type === 'Public' ? company.type === 'public' : company.type === 'private');
    const roleMatch = !state.area || companyJobs(company).some(job => job.area === state.area);
    return locationMatch && queryMatch && typeMatch && roleMatch && hiringMatch(company);
  });
}
function applyPathCity() {
  const slug = pathCity();
  if (slug) { state.cityRoute = slug; const countries = knownCityCountries.get(slug) || []; if (!countries.includes(state.country)) state.country = countries[0] || ''; state.location = knownCities.get(slug)?.[0] || slug; if (!state.view) state.view = 'map'; }
}
function renderArea() {
  const area = $('area-context'), selected = state.location;
  const city = knownCities.has(citySlug(selected));
  const place = city ? filtered.flatMap(job => job.locations).find(item => item.city === selected) : null;
  const country = state.country || place?.country || filteredCompanies[0]?.country || (!city && selected ? selected : '');
  const continent = continentForCountry(country);
  area.hidden = !selected;
  area.replaceChildren();
  const showCompanies = state.view === 'map';
  $('jobs-heading').textContent = selected || (showCompanies ? 'Companies to explore' : 'Jobs for you to explore');
  document.querySelector('.list-note').textContent = city ? 'Browse public company records and their current roles in this area. Directory presence is not proof of hiring.' : showCompanies ? 'Browse the public company directory. Hiring status reflects open roles in the vacancy snapshot or a directory hiring flag.' : '“For you” means discovery, not a hiring prediction. Check the original advert before applying.';
  document.title = selected ? `${selected} jobs · Hired` : showCompanies ? 'Companies · Hired' : 'Hired · jobs, mapped to you';
  if (!selected) return;
  const crumbs = el('nav','area-breadcrumbs'); crumbs.setAttribute('aria-label','Area breadcrumb');
  const continentButton = el('button','area-crumb',continent); continentButton.type = 'button'; continentButton.addEventListener('click',() => { controls.location.value = ''; state.country = ''; applyFilters(true); }); crumbs.append(continentButton);
  if (city && country) {
    crumbs.append(el('span','area-separator','›'));
    const flag = countryFlag(country); const countryButton = el('button','area-crumb',(flag ? flag + ' ' : '') + country); countryButton.type = 'button'; countryButton.addEventListener('click',() => { controls.location.value = country; applyFilters(true); }); crumbs.append(countryButton);
  }
  if (city) crumbs.append(el('span','area-separator','›'),el('strong','',selected));
  area.append(crumbs,el('p','area-summary',city ? `${filteredCompanies.length} companies · ${filteredCompanies.filter(company => companyJobs(company).length > 0).length} with open roles` : `${new Set(filtered.map(job => job.company)).size} companies · ${filtered.length} open roles in this snapshot`));
}
function render() {
  filtered = applyPrefs(filterJobs(jobs,state)); filterDirectory(); renderArea(); $('clear-filters').hidden = !['q','area','type','location','hiring'].some(k => controls[k].value);
  const inArea = areaCitySelected();
  $('result-count').textContent = state.view === 'map' ? `${inArea ? `${filteredCompanies.length} companies in this area` : `${filteredCompanies.length} companies`} · ${filtered.length} open roles in snapshot` : `${filtered.length.toLocaleString()} ${filtered.length === 1 ? 'role' : 'roles'} · ${new Set(filtered.flatMap(j => j.locations.map(p => p.city))).size.toLocaleString()} mapped places`;
  $('empty-state').textContent = state.view === 'map' ? 'No companies match these filters.' : 'No roles match. Try a broader search or clear a filter.';
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
    const locationMatch = !state.location || (samePlace(company.locationLabel) && sameCountry(company.country)) || company.country === state.location;
    return queryMatch && typeMatch && roleMatch && locationMatch && hiringMatch(company);
  });
}
function renderCompanyList() {
  const pages = Math.max(1,Math.ceil(filteredCompanies.length / PAGE_SIZE)); page = Math.max(0,Math.min(page,pages-1));
  const fragment = document.createDocumentFragment();
  for (const company of filteredCompanies.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE)) {
    const roles = companyJobs(company), li = el('li','company-row'), button = el('button','job-button'); button.type = 'button';
    button.setAttribute('aria-label',`View ${company.name}, ${roles.length} open roles`);
    const flag = countryFlag(company.country); const content = el('span','job-summary'); content.append(el('span','job-title',company.name),el('span','job-company',`${flag ? flag + ' ' : ''}${company.location || company.locationLabel} · ${company.industry}`),el('span','job-location',company.summary || 'Public company directory record'));
    const status = hiringStatus(company), openCount = openRolesFor(company).length, tags = el('span','company-tags'); tags.append(el('span','tag',company.type === 'startup' ? (company.fundingStage || 'Startup') : company.type === 'public' ? 'Public company' : 'Private company'),el('span',`hiring-badge ${status.tone}`,status.key === 'hiring' ? `● ${status.label} · ${openCount} open role${openCount === 1 ? '' : 's'}` : `○ ${status.label}`)); content.append(tags);
    button.append(companyMark({company:company.name,logo:company.logo}),content,el('span','row-arrow','→')); button.addEventListener('click',() => selectCompany(company)); li.append(button); fragment.append(li);
  }
  $('job-list').replaceChildren(fragment); $('pagination').hidden = filteredCompanies.length <= PAGE_SIZE; $('page-label').textContent = `${page+1} / ${pages}`; $('previous').disabled = page === 0; $('next').disabled = page === pages-1;
  $('empty-state').hidden = filteredCompanies.length > 0;
}
function renderList() {
  if (state.view === 'map') { renderCompanyList(); return; }
  const pages = Math.max(1,Math.ceil(filtered.length / PAGE_SIZE)); page = Math.max(0,Math.min(page,pages-1));
  $('empty-state').hidden = filtered.length > 0 || loading || !$('load-error').hidden;
  const fragment = document.createDocumentFragment();
  for (const job of filtered.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE)) {
    const li = el('li','company-row'), button = el('button',`job-button${state.job === job.id ? ' is-selected' : ''}`);
    button.type = 'button'; button.setAttribute('aria-label',`View ${job.title} at ${job.company}`);
    const content = el('span','job-summary'); content.append(el('span','job-title',job.title),el('span','job-company',`${job.company} · ${job.companyType}`));
    const tags = el('span','company-tags'); tags.append(el('span','tag',job.area)); if (job.employment) tags.append(el('span','tag',job.employment)); content.append(tags,el('span','job-location',job.locations.map(p => `${countryFlag(p.country) ? countryFlag(p.country) + ' ' : ''}${p.label}`).join(' · ')));
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
  const status = hiringStatus(company);
  const flag = countryFlag(company.country); headingWrap.append(title,el('p','detail-subtitle',`${flag ? flag + ' ' : ''}${company.location || company.locationLabel} · ${company.industry}`),el('span',`hiring-badge ${status.tone}`,status.key === 'hiring' ? '● Hiring now' : status.key === 'flag' ? '○ Lists hiring (directory flag)' : '○ No open roles in snapshot')); top.append(companyMark({company:company.name,logo:company.logo}),headingWrap); detail.append(top);
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
  const match = el('section','detail-section'); match.append(el('h3','','Match your CV'));
  const drop = el('div','cv-dropzone',`Drop your CV here (.txt / .md) to match against ${job.skills.length} detected terms — or paste skills below`); drop.tabIndex = 0; drop.setAttribute('role','button');
  const input = el('textarea'); input.id = 'skill-profile'; input.maxLength = 1800; input.placeholder = 'Python, SQL, Docker';
  const result = el('div','match-result','Drop or paste skills to see exact overlap with terms found in this advert.');
  const runMatch = () => { const matched = matchCvText(job,input.value); result.textContent = matched.length ? `${matched.length} matched term${matched.length === 1 ? '' : 's'}: ${matched.join(', ')}. This is not a hiring probability; review the full context yourself.` : 'No matching terms found yet. Missing terms are not proof that you lack relevant experience.'; };
  input.addEventListener('input',runMatch);
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('drag'); }); drop.addEventListener('dragleave', () => drop.classList.remove('drag'));
  drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('drag'); const file = e.dataTransfer.files && e.dataTransfer.files[0]; if (!file) return; if (/\.(txt|md)$/i.test(file.name)) { file.text().then(text => { input.value = text.slice(0,1800); runMatch(); drop.textContent = `Matched against ${file.name} — runs only in this page.`; }); } else { drop.textContent = 'PDF/DOCX CV matching runs in the local app (Prepare privately) — nothing is uploaded here.'; } });
  match.append(drop,el('p','field-note','Runs only in this page. Nothing is saved or uploaded. For full PDF/DOCX CV analysis, use the private local app.'),input,result); detail.append(match);
  const contacts = el('section','detail-section'); contacts.append(el('h3','','People to contact'));
  const companyPeople = peopleByCompany.get(job.company.toLocaleLowerCase('en')) || [];
  if (companyPeople.length) { const peopleList = el('div','people-list'); for (const person of companyPeople) { const link = document.createElement('a'); link.className = 'person-card'; link.href = person.linkedin; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.setAttribute('aria-label', `Open the LinkedIn profile for ${person.name}`); link.append(el('span','person-avatar', initials(person.name))); const info = el('span','person-info'); info.append(el('strong','person-name',person.name), el('span','person-role', person.role + (person.location ? ' · ' + person.location : ''))); if (person.category) info.append(el('span',`person-badge ${person.category}`, person.category === 'recruiter' ? 'Recruiter' : person.category === 'executive' ? 'Leadership' : person.category)); link.append(info); peopleList.append(link); } contacts.append(peopleList,el('p','field-note','Publicly listed, surfaced via web search. Opens LinkedIn; verify before contacting.')); }
  else contacts.append(el('p','field-note','No publicly listed contacts for this company in the snapshot yet.')); detail.append(contacts);
  const about = el('section','detail-section'); about.append(el('h3','','About the role'),el('p','',job.description || 'Open the official advert for the complete description.')); if (job.skills.length) { const skills = el('div','company-tags'); for (const skill of job.skills) skills.append(el('span','tag',skill)); about.append(el('h3','','Terms detected in the advert'),skills); } detail.append(about,el('p','field-note',`Source: ${job.source} employer board. Verify the current advert and submit it yourself. Hired never applies on your behalf.`));
}
function clearMarkers() { for (const marker of markers.splice(0)) marker.remove(); }
function selectArea(city, country) {
  controls.location.value = city; state.country = country; state.cityRoute = citySlug(city); applyFilters();
}
function addAreaMarker(group, level) {
  const card = el('div','area-map-card');
  const thumb = el('span','area-map-thumb');
  const flag = countryFlag(level === 'country' ? group.key : group.country);
  if (flag) { thumb.textContent = flag; thumb.classList.add('flag'); }
  else if (group.companies.length === 1 && group.logo) { const image = el('img','company-logo'); image.src = '/' + group.logo; image.alt = ''; thumb.append(image); }
  else thumb.textContent = initials(group.key);
  const title = level === 'city' ? `${flag ? flag + ' ' : ''}${group.label || group.key}` : (group.label || group.key);
  card.append(thumb,el('span','area-map-title',title),el('span','area-map-count',`${group.companies.length} companies · ${group.jobs} roles`));
  card.tabIndex = 0; card.setAttribute('role','button'); card.setAttribute('aria-label',`${group.key}, ${group.companies.length} companies and ${group.jobs} roles`);
  const choose = () => {
    if (level === 'country') map.jumpTo({center:[group.longitude,group.latitude],zoom:5});
    else { selectArea(group.label || group.key,group.country); map.jumpTo({center:[group.longitude,group.latitude],zoom:11}); }
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
  const lngs = points.map(p => p.longitude), lats = points.map(p => p.latitude); const camera = map.cameraForBounds([[Math.min(...lngs),Math.min(...lats)],[Math.max(...lngs),Math.max(...lats)]],{padding:70,maxZoom:12}); if (camera) map.jumpTo({center:camera.center,zoom:Math.max(2.8,camera.zoom)});
}
async function initializeMap() {
  try {
    if (!globalThis.maplibregl) throw new Error('Map unavailable');
    let style = 'https://tiles.openfreemap.org/styles/positron';
    try { const response = await fetch(style,{credentials:'omit',signal:AbortSignal.timeout(8000)}); if (!response.ok) throw new Error('Style unavailable'); } catch { const response = await fetch('/data/world.geojson'); const world = await response.json(); style = {version:8,sources:{world:{type:'geojson',data:world}},layers:[{id:'bg',type:'background',paint:{'background-color':'#eee9df'}},{id:'land',type:'fill',source:'world',paint:{'fill-color':'#fff7e9','fill-outline-color':'#d7c7b2'}}]}; }
    map = new maplibregl.Map({container:'map',style,center:[12,51],zoom:2.5,minZoom:2,maxZoom:18,scrollZoom:false,attributionControl:{compact:true},fadeDuration:matchMedia('(prefers-reduced-motion:reduce)').matches ? 0 : 250}); globalThis.__hiredMap = map; map.addControl(new maplibregl.NavigationControl({showCompass:false}),'top-right'); map.on('load',() => { mapReady = true; renderPins(); if (pendingFit) fitResults(); }); map.on('moveend',renderPins); map.on('idle',() => { if (!$('job-list').children.length) renderPins(); }); map.on('error',() => { $('map-status').hidden = false; $('map-status').textContent = 'Some map tiles failed. The job list still works.'; });
  } catch { $('map-status').hidden = false; $('map-status').textContent = 'Map unavailable. All roles remain in Jobs.'; $('fit-map').disabled = true; }
}
let companiesLoading = false, companiesLoaded = false;
function registerCities(records) {
  knownCities = buildCityRoutes(records);
  knownCityCountries = buildCityCountries(records);
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
    const payload = await response.json(); jobs = readJobs(payload); indexJobs();
    if (isMapPage()) state.view = 'map';
    registerCities(jobs.flatMap(job => job.locations));
    addOptions('area',jobs.map(j => j.area)); addOptions('location',jobs.flatMap(j => j.locations.flatMap(p => [p.city,p.country])));
    applyPathCity(); restoreControls();
    $('job-total').textContent = `${jobs.length} roles from ${new Set(jobs.map(j => j.company)).size} companies`;
    $('snapshot-date').textContent = `Public-board snapshot exported ${dateLabel(payload.exportedAt)}`;
    loading = false; document.querySelector('.explorer-body').dataset.view = state.view === 'map' ? 'map' : 'jobs';
    render(); fitResults();
    if (state.view === 'map' || pathCity()) loadCompanies();
  } catch { loading = false; $('load-error').hidden = false; $('result-count').textContent = 'Vacancy snapshot unavailable'; }
}
async function loadPeople() {
  try {
    const response = await fetch('/data/people.json',{credentials:'omit',signal:AbortSignal.timeout(10000)});
    if (!response.ok) return;
    const payload = await response.json(); peopleByCompany = new Map();
    for (const person of (payload.people || [])) { const key = String(person.company || '').toLocaleLowerCase('en'); if (!peopleByCompany.has(key)) peopleByCompany.set(key, []); peopleByCompany.get(key).push(person); }
  } catch {}
}
function showOnboarding(force) {
  if (!force && localStorage.getItem(PREFS_KEY)) return;
  const overlay = el('div','onboard-overlay');
  const card = el('div','onboard-card');
  card.append(el('h2','','Tailor your search'), el('p','onboard-sub','Choose your sectors and preferences — roles will be ranked to match.'));
  const chips = el('div','chip-row');
  for (const sector of ['finance','business','engineering']) { const chip = el('button',`onboard-chip${prefs.sectors.includes(sector) ? ' active' : ''}`, sector[0].toUpperCase() + sector.slice(1)); chip.type = 'button'; chip.addEventListener('click', () => { chip.classList.toggle('active'); const i = prefs.sectors.indexOf(sector); if (i >= 0) prefs.sectors.splice(i, 1); else prefs.sectors.push(sector); }); chips.append(chip); }
  const kw = el('input','onboard-input'); kw.placeholder = 'Keywords (e.g. trading, mechanical, machine learning)'; kw.value = prefs.keywords || '';
  const loc = el('input','onboard-input'); loc.placeholder = 'Location (e.g. Paris or France)'; loc.value = prefs.location || '';
  const type = el('select','onboard-input'); type.append(new Option('Any company',''), new Option('Startups','Startup'), new Option('Public companies','Public'), new Option('Private companies','Private')); type.value = prefs.companyType || '';
  const save = el('button','button primary','Start exploring'); save.type = 'button'; save.addEventListener('click', () => { prefs.sectors = [...prefs.sectors]; prefs.keywords = kw.value.trim(); prefs.location = loc.value.trim(); prefs.companyType = type.value; savePrefs(); overlay.remove(); applyFilters(true); });
  const skip = el('button','button','Skip for now'); skip.type = 'button'; skip.addEventListener('click', () => { savePrefs(); overlay.remove(); });
  const actions = el('div','onboard-actions'); actions.append(save, skip);
  card.append(chips, el('label','onboard-label','Keywords'), kw, el('label','onboard-label','Location'), loc, el('label','onboard-label','Company type'), type, actions);
  overlay.append(card); document.body.append(overlay);
}
$('retry').addEventListener('click',loadJobs); initializeMap(); loadJobs(); loadPeople(); if (!isMapPage()) showOnboarding();
