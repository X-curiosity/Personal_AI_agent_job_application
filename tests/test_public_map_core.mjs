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
test('published snapshot conforms to browser contract', () => {
 const payload=JSON.parse(readFileSync(new URL('../vercel-site/data/companies.json',import.meta.url)));
 const rows=readCatalogue(payload);
 assert.ok(rows.length>0); assert.equal(rows.length,payload.companies.length);
 for(const row of rows) assert.ok(row.precision==='unmapped'||hasPoint(row));
});
