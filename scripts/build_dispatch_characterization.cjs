// Characterize the exact bundled v1.6 dispatcher Function nodes without services.
const fs=require('fs'),path=require('path'),vm=require('vm'),crypto=require('crypto'),zlib=require('zlib');
const root=path.resolve(__dirname,'..');
let source=fs.readFileSync(path.join(__dirname,'test_dispatch_lifecycle.cjs'),'utf8');
source=source.replace("require('./control_test_runtime.cjs')","require('../tests/policy_oracle_runtime.cjs')");
const output=[];
const sandbox={require:(id)=>id==='../tests/policy_oracle_runtime.cjs'?require('../tests/policy_oracle_runtime.cjs'):require(id),process:{argv:['node','characterize']},console:{log:(...args)=>output.push(args.join(' '))}};
vm.runInNewContext(source,sandbox,{timeout:120000,filename:'original-dispatch-tests.cjs'});
const raw=zlib.gunzipSync(fs.readFileSync(path.join(root,'tests/fixtures/policy-v1.6-runtime.json.gz')));
const result={source_flow_sha256:crypto.createHash('sha256').update(raw).digest('hex'),source_tests:output.filter(x=>x.startsWith('PASS ')).map(x=>x.slice(5)),notes:'Original Function nodes with fake callbacks. Native tests characterize corresponding invariants; native accepted timing, restart, preflight evidence and maintenance provenance intentionally strengthen source behavior.'};
fs.writeFileSync(path.join(root,'tests/fixtures/dispatch-v1.6-characterization.json'),JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify(result));
