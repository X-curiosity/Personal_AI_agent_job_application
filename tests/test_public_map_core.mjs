import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {filterCompanies, hasPoint, groupPoints, readCatalogue, readState, stateQuery, safeURL} from '../vercel-site/map-core.mjs';
const fixture = {id:'one',name:'Example',stage:'early',industry:'Software',hiringSignal:'directory_flag',location:'London, UK',locationLabel:'London',latitude:51.5,longitude:-0.12,precision:'city'};
const read = rows => readCatalogue({schemaVersion:1,companies:rows});
test('catalogue sanitizes URLs and retains unknowns', () => {
 const [c] = read([{...fixture,stage:'invented',website:'javascript:alert(1)',sourceUrl:'https://example.com',latitude:NaN}]);
 assert.equal(c.website,null); assert.equal(c.stage,'unknown'); assert.equal(c.precision,'unmapped');
 assert.equal(c.sourceUrl,'https://example.com/');
});
test('URLs reject dangerous or credentialed destinations', () => {
 for(const u of ['http://example.com','javascript:alert(1)','data:text/html,test','https://a:b@example.com','https://localhost','https://127.0.0.1','https://example.com:999','https://example.com/\nsecret']) assert.equal(safeURL(u),null,u);
 for (const host of ['172.16.0.1','172.31.255.255','[::1]','[fc00::1]','169.254.169.254','2130706433','0177.0.0.1','8.8.8.8','app.local','app.internal']) assert.equal(safeURL(`https://${host}/x`),null,host);
 assert.equal(safeURL('https://example.com/jobs'),'https://example.com/jobs');
});
test('empty and malformed catalogues', () => {
 assert.deepEqual(read([]),[]);
 for (const p of [null,{}, {schemaVersion:2,companies:[]}, {schemaVersion:1,companies:[fixture,fixture]}, {schemaVersion:1,companies:[{...fixture,id:'<script>'}]}]) assert.throws(()=>readCatalogue(p));
});
test('AND filters and search include unmapped companies', () => {
 const rows=read([fixture,{...fixture,id:'two',name:'Other',stage:'big',latitude:null,longitude:null,precision:'unmapped'}]);
 assert.equal(filterCompanies(rows,{q:'LONDON',stage:'early'}).length,1);
 assert.equal(filterCompanies(rows,{q:'Other'}).length,1);
 assert.equal(filterCompanies(rows,{stage:'big',signal:'directory_flag'}).length,1);
 assert.equal(filterCompanies(rows,{industry:'Finance'}).length,0);
 assert.equal(filterCompanies(rows,{location:'London'}).length,2);
});
test('coordinate bounds include zero and reject fake or out-of-range points', () => {
 assert.equal(hasPoint({...fixture,latitude:0,longitude:0}),true);
 for(const c of [{latitude:Infinity},{longitude:181},{latitude:'51.5'},{precision:'exact'},{latitude:null}]) assert.equal(hasPoint({...fixture,...c}),false);
});
test('grouping retains co-located companies and omits unmapped records', () => {
 const rows=read([fixture,{...fixture,id:'two'},{...fixture,id:'three',latitude:30,longitude:100},{...fixture,id:'four',latitude:null}]);
 const projection=(lat,lng)=>({x:lng*10,y:lat*10});
 const groups=groupPoints(rows,projection,false);
 assert.equal(groups.length,2); assert.equal(groups[0].members.length,2);
 assert.equal(groupPoints(rows,()=>({x:0,y:0}),true)[0].members.length,3);
});
test('URL state roundtrip is bounded and excludes unrelated parameters', () => {
 const state=readState('?q=AI+%26+Data&company=one&stage=big&token=secret');
 assert.equal(state.q,'AI & Data'); assert.equal(state.token,undefined);
 assert.deepEqual(readState(stateQuery(state)),state);
 assert.equal(readState('?q='+'a'.repeat(300)).q.length,200);
});
test('hq precision pins like a city coordinate', () => {
 const [c] = read([{...fixture, precision:'hq', latitude:37.67, longitude:-121.88}]);
 assert.equal(c.precision,'hq'); assert.equal(hasPoint(c),true);
});
test('published snapshot conforms to browser contract', () => {
 const payload=JSON.parse(readFileSync(new URL('../vercel-site/data/companies.json',import.meta.url)));
 const rows=readCatalogue(payload);
 assert.ok(rows.length>0); assert.equal(rows.length,payload.companies.length);
 for(const row of rows) assert.ok(row.precision==='unmapped'||hasPoint(row));
});
test('zoom hierarchy and grouping cards', async () => {
 const {zoomLayer, countryCards, regionCards, cityCards, flagEmoji} = await import('../vercel-site/map-core.mjs');
 assert.equal(zoomLayer(2),'country'); assert.equal(zoomLayer(3),'country');
 assert.equal(zoomLayer(4),'region'); assert.equal(zoomLayer(5),'region');
 assert.equal(zoomLayer(6),'city'); assert.equal(zoomLayer(7),'city');
 assert.equal(zoomLayer(8),'pins'); assert.equal(zoomLayer(12),'pins');
 const rows=read([
  {...fixture,country:'United States',countryCode:'US',region:'California',locationLabel:'San Francisco'},
  {...fixture,id:'two',country:'United States',countryCode:'US',region:'California',locationLabel:'San Francisco'},
  {...fixture,id:'three',country:'United States',countryCode:'US',region:'Texas',locationLabel:'Austin',latitude:30.26,longitude:-97.74},
  {...fixture,id:'four',country:'France',countryCode:'FR',region:null,locationLabel:'Paris',latitude:48.85,longitude:2.35},
 ]);
 const countries=countryCards(rows);
 assert.equal(countries[0].key,'United States'); assert.equal(countries[0].members.length,3);
 const regions=regionCards(rows);
 assert.equal(regions.filter(g=>!g.key.startsWith('city::')).length,2); // California + Texas
 assert.equal(regions.filter(g=>g.key.startsWith('city::')).length,1); // Paris joins as city
 const cities=cityCards(rows);
 assert.deepEqual(cities.map(g=>g.key).sort(),['Austin','Paris','San Francisco']);
 assert.equal(flagEmoji('US'),'🇺🇸'); assert.equal(flagEmoji('XX'),'🇽🇽'); assert.equal(flagEmoji('usa'),'');
});
test('logo paths are allowlisted', () => {
 const good={...fixture,logo:'data/logos/company_0123456789abcdef0123.png'};
 assert.equal(read([good])[0].logo,good.logo);
 for(const bad of ['https://evil.com/x.png','data/logos/../../secret','data/logos/company_x.png','data/logos/company_0123456789abcdef0123.svg'])
  assert.equal(read([{...fixture,logo:bad}])[0].logo,null,bad);
});
test('declutterCards keeps the largest group per screen cell', async () => {
 const {declutterCards} = await import('../vercel-site/map-core.mjs');
 const g=(lat,lng,n)=>({latitude:lat,longitude:lng,members:Array(n).fill(1)});
 const groups=[g(48.85,2.35,10),g(48.9,2.4,5),g(52.5,13.4,8),g(52.52,13.42,3)];
 // ~2km apart at this fake projection: same cell for each pair, cities far apart
 const project=(lat,lng)=>({x:lng*100,y:lat*100});
 const kept=declutterCards(groups,project,150);
 assert.equal(kept.length,2);
 assert.deepEqual(kept.map(x=>x.members.length).sort((a,b)=>a-b),[8,10]);
});
test('type, role and funding stage fields', async () => {
 const {companyRoles, TYPES} = await import('../vercel-site/map-core.mjs');
 const rows=read([
  {...fixture,type:'startup',fundingStage:'Series A',tags:['Fintech','Payments'],industry:'Financial Services'},
  {...fixture,id:'two',type:'public',fundingStage:null,tags:[],industry:'Semiconductors'},
  {...fixture,id:'three',type:'bogus',fundingStage:null,tags:[],industry:'Design'},
 ]);
 const byId=Object.fromEntries(rows.map(r=>[r.id,r]));
 assert.equal(byId.one.type,'startup'); assert.equal(byId.one.fundingStage,'Series A');
 assert.equal(byId.three.type,'private'); // unknown type falls back safely
 assert.deepEqual(companyRoles(byId.one),['Finance']);
 assert.ok(companyRoles(byId.three).includes('Design'));
 assert.equal(companyRoles({...byId.two,industry:''}).length,0);
 assert.equal(filterCompanies(rows,{type:'startup'}).length,1);
 assert.equal(filterCompanies(rows,{role:'Finance'}).length,1);
 assert.equal(filterCompanies(rows,{role:'Engineering'}).length,1); // semiconductors are engineering
 assert.equal(filterCompanies(rows,{role:'Legal'}).length,0);
 assert.equal(filterCompanies(rows,{location:'London'}).length,3);
});
