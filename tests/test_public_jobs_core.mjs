import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {citySlug, declutterDirectoryGroups, directoryGroups, filterJobs, matchSkills, readJobs, readState, stateQuery, safeURL} from '../vercel-site/jobs-core.mjs';
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
 assert.equal(groups[0].key,'Brussels'); assert.equal(groups[0].companies.length,1); assert.equal(groups[0].jobs,1); assert.ok(groups[0].logo);
 const cards=[{latitude:1,longitude:1,companies:[1]},{latitude:1.01,longitude:1.01,companies:[1,2]}];
 assert.equal(declutterDirectoryGroups(cards,()=>({x:10,y:10})).length,1);
 assert.equal(declutterDirectoryGroups(cards,()=>({x:10,y:10}))[0].companies.length,2);
 const paris=directoryGroups([company],[{company:'Example AI',locations:[{city:'Paris',country:'France'}]}],'city');
 assert.equal(paris.find(group=>group.key==='Paris').jobs,1);
 assert.equal(directoryGroups([company],[],'city')[0].jobs,0);
 const remote={...company,name:'Remote Co',locationLabel:'San Francisco',country:'United States',latitude:37.77,longitude:-122.41};
 const lisbon=directoryGroups([remote],[{company:'Remote Co',locations:[{city:'Lisbon',country:'Portugal',latitude:38.72,longitude:-9.14}]}],'city');
 const lisbonGroup=lisbon.find(group=>group.key==='Lisbon');
 assert.equal(lisbonGroup.latitude,38.72); assert.equal(lisbonGroup.longitude,-9.14);
});

test('published European snapshot conforms to browser contract',()=>{
 const payload=JSON.parse(readFileSync(new URL('../vercel-site/data/jobs.json',import.meta.url))); const jobs=readJobs(payload);
 assert.ok(jobs.length>50); assert.equal(payload.live,false);
 for(const job of jobs){assert.ok(job.url);assert.ok(job.locations.length);assert.ok(job.description.length>0);}
});
