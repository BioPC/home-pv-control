// Audit scanner/export safety; no flow execution, network or installation.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {inspect}=require('../audit_tools/inspect_legacy.cjs');
const bridge=require('../migration/legacy-bridge-v1.6.cjs');
const nodes=require('../node-red/hpvc_flow.json');let passed=0;
function test(name,fn){fn();passed++;console.log('PASS '+name);}
test('local flow inspection retains exact source identity and does not mutate flows',()=>{const before=JSON.stringify(nodes);const r=inspect(nodes,{},true);assert.equal(r.fingerprint,'23e70cb864ae386b2ffe202a86bd7683be49402679b6cf94cda12c6dc6af479d');assert.equal(r.version,'1.6.0');assert.equal(JSON.stringify(nodes),before);assert.equal(r.bridge.complete,false);});
test('unknown context nulls do not fabricate a drained runtime',()=>{const raw=Object.fromEntries(bridge.KEYS.map(k=>[k,null]));raw.homePvControlAdapterRuntimeOwner='owner';const r=inspect(nodes,{global_context:raw,runtime:{runtime_owner:'owner'},observed_at_utc:1},true);assert.equal(r.bridge.complete,false);});
test('raw credentials and Function bodies never appear in scanner output',()=>{const edited=structuredClone(nodes);edited.find(n=>n.type==='server').password='never-export-this-secret';const r=inspect(edited,{},true);const s=JSON.stringify(r);assert(!s.includes('never-export-this-secret'));assert(!s.includes('global.set('));assert.equal(r.version,null);});
test('flow source is inspected as data and never evaluated',()=>{const edited=structuredClone(nodes);edited.find(n=>n.type==='function').func='throw Error(\'must not execute\')';assert.doesNotThrow(()=>inspect(edited,{},true));});
test('browser helper contains only allowlisted HA read commands and compiles',()=>{const source=fs.readFileSync('audit_tools/browser_read_export.js','utf8');new vm.Script(source);const allowed=new Set(['get_states','get_config','config/entity_registry/list','config/entity_registry/get_entries','config/device_registry/list','config_entries/get']);for(const match of source.matchAll(/type:'([^']+)'/g))assert(allowed.has(match[1]));assert(!source.includes('call_service'));});
console.log(`${passed} site audit export/scanner checks passed`);
