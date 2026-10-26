import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {buildCityCountries, buildCityRoutes, citySlug, continentForCountry, declutterDirectoryGroups, directoryGroups, filterJobs, matchSkills, readJobs, readState, stateQuery, safeURL} from '../vercel-site/jobs-core.mjs';
import {readCatalogue} from '../vercel-site/map-core.mjs';
const fixture = {id:'job_0123456789abcdef0123',title:'ML Engineer',company:'Example AI',companyType:'Startup',url:'https://jobs.example.com/1',boardUrl:'https://jobs.example.com',source:'Ashby',area:'Data & AI',skills:['Python','SQL'],description:'Build useful systems.',locations:[{label:'Paris, France',city:'Paris',country:'France',latitude:48.85,longitude:2.35,precision:'city'}],sourceTimestamp:'2026-10-25T00:00:00Z',sourceTimestampKind:'published'};
const read = rows => readJobs({schemaVersion:1,jobs:rows});
test('vacancy validation, safe links and location precision',()=>{
 const [job]=read([fixture]); assert.equal(job.title,'ML Engineer'); assert.equal(job.locations[0].city,'Paris');
 assert.throws(()=>read([{...fixture,url:'javascript:alert(1)',id:'job_1123456789abcdef0123'}]));
 assert.throws(()=>read([{...fixture,locations:[{...fixture.locations[0],precision:'hq'}]}]));
 for(const url of ['http://example.com','https://a:b@example.com','https://localhost']) assert.equal(safeURL(url),null);
});
test('AND filters search listing locations and job skills',()=>{
 const rows=read([fixture,{...fixture,id:'job_2123456789abcdef0123',title:'Backend Engineer',company:'Global Co',companyType:'Public',area:'Engineering',locations:[{label:'Berlin, Germany',city:'Berlin',country:'Germany',latitude:52.5,longitude:13.4,precision:'city'}]}]);
 assert.equal(filterJobs(rows,{q:'python',type:'Startup',location:'Paris'}).length,1);
 assert.equal(filterJobs(rows,{area:'Engineering',location:'Germany'}).length,1);
 assert.equal(filterJobs(rows,{q:'not present'}).length,0);
});
test('skill match is exact, bounded and user supplied',()=>{
 const [job]=read([fixture]); assert.deepEqual(matchSkills(job,'Python, python, Rust'),['Python']);
 assert.deepEqual(matchSkills(job,'Py'),[]); assert.deepEqual(matchSkills(job,''),[]);
});
test('URL state retains only bounded explorer fields',()=>{
 const state=readState('?q=ML&view=map&job=job_0123456789abcdef0123&token=secret'); assert.equal(state.token,undefined); assert.deepEqual(readState(stateQuery(state)),state);
});
test('city slugs and directory groups are generic and count real roles',()=>{
 assert.equal(citySlug('Bessé-sur-Braye'),'besse-sur-braye');
 const company={id:'c1',name:'Example AI',locationLabel:'Brussels',country:'Belgium',latitude:50.85,longitude:4.35,logo:'data/logos/company_0123456789abcdef0123.ico'};
 const groups=directoryGroups([company],[{company:'Example AI',locations:[{city:'Brussels',country:'Belgium'}]}],'city');
 assert.equal(groups[0].label,'Brussels'); assert.equal(groups[0].companies.length,1); assert.equal(groups[0].jobs,1); assert.ok(groups[0].logo);
 const cards=[{latitude:1,longitude:1,companies:[1]},{latitude:1.01,longitude:1.01,companies:[1,2]}];
 assert.equal(declutterDirectoryGroups(cards,()=>({x:10,y:10})).length,1);
 assert.equal(declutterDirectoryGroups(cards,()=>({x:10,y:10}))[0].companies.length,2);
 const paris=directoryGroups([company],[{company:'Example AI',locations:[{city:'Paris',country:'France'}]}],'city');
 assert.equal(paris.find(group=>group.label==='Paris').jobs,1);
 assert.equal(directoryGroups([company],[],'city')[0].jobs,0);
 const remote={...company,name:'Remote Co',locationLabel:'San Francisco',country:'United States',latitude:37.77,longitude:-122.41};
 const lisbon=directoryGroups([remote],[{company:'Remote Co',locations:[{city:'Lisbon',country:'Portugal',latitude:38.72,longitude:-9.14}]}],'city');
 const lisbonGroup=lisbon.find(group=>group.label==='Lisbon');
 assert.equal(lisbonGroup.latitude,38.72); assert.equal(lisbonGroup.longitude,-9.14);
});

test('same-name cities in different countries remain separate area groups',()=>{
 const rows=[{id:'uk',name:'UK Co',locationLabel:'Cambridge',country:'United Kingdom',latitude:52.2,longitude:0.12,logo:null},{id:'us',name:'US Co',locationLabel:'Cambridge',country:'United States',latitude:42.37,longitude:-71.1,logo:null}];
 const groups=directoryGroups(rows,[],'city');
 assert.equal(groups.length,2);
 assert.deepEqual(new Set(groups.map(group=>group.country)),new Set(['United Kingdom','United States']));
});

test('every mapped city has a stable route and finite area groups',()=>{
 const catalogue=readCatalogue(JSON.parse(readFileSync(new URL('../vercel-site/data/companies.json',import.meta.url))));
 const jobs=readJobs(JSON.parse(readFileSync(new URL('../vercel-site/data/jobs.json',import.meta.url))));
 const routes=buildCityRoutes([...catalogue,...jobs.flatMap(job=>job.locations)]);
 assert.ok(routes.size>100);
 for(const company of catalogue){
  if(!['city','hq'].includes(company.precision)||company.locationLabel===company.country)continue;
  const labels=routes.get(citySlug(company.locationLabel));
  assert.ok(labels?.includes(company.locationLabel),`missing city route: ${company.locationLabel}`);
 }
 for(const group of directoryGroups(catalogue,jobs,'city')){
  assert.ok(Number.isFinite(group.latitude)&&Number.isFinite(group.longitude),group.key);
  assert.ok(group.companies.length>0);
 }
 for(const slug of routes.keys()) assert.equal(citySlug(slug),slug);
 const countries=buildCityCountries(catalogue);
 assert.ok([...countries.values()].flat().includes('United States'));
 assert.equal(continentForCountry('France'),'Europe'); assert.equal(continentForCountry('United States'),'North America');
 assert.equal(continentForCountry('Nigeria'),'Africa'); assert.equal(continentForCountry('India'),'Asia');
});

test('published European snapshot conforms to browser contract',()=>{
 const payload=JSON.parse(readFileSync(new URL('../vercel-site/data/jobs.json',import.meta.url))); const jobs=readJobs(payload);
 assert.ok(jobs.length>50); assert.equal(payload.live,false);
 for(const job of jobs){assert.ok(job.url);assert.ok(job.locations.length);assert.ok(job.description.length>0);}
});
