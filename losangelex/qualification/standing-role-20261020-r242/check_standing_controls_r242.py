"""Score the scorer against reference and nontrivial wrong programs before models."""
import json,runpy,tempfile,time
from pathlib import Path
from lax_connector.journal import saved
root=Path('/var/lib/lax-standing-responsibility-20261020-r242');p=root/'protocol';q=Path('/aosp/development/lax-three-context-20261018-r01/qualification')
m=runpy.run_path(str(q/'standing_outcome_r242.py'));cs=m['cases'](p)
oracle=(q/'standing_outcome_r242.py').read_text().split('def probe(')[0]
reference=oracle+'\ntry:\n print(json.dumps(expected(json.load(open(sys.argv[1])))))\nexcept Exception:\n print("Invalid catalog",file=sys.stderr);sys.exit(2)\n'
with tempfile.TemporaryDirectory(prefix='controls-',dir=root) as d:
 program=Path(d)/'control.py';program.write_text(reference)
 positive=m['probe'](program,cs);assert all(x['passed'] for x in positive)
 wrong={};initial=repr(m['expected'](json.loads((p/'initial-catalog.json').read_text())));released=repr(m['expected'](json.loads((p/'RELEASE-REQUIREMENTS.json').read_text())))
 variants={
 'constant-initial':'print(json.dumps('+initial+'))',
 'sample-aware':"c=json.load(open(sys.argv[1]));expected(c);print(json.dumps("+released+" if any(f['id']=='team-review' and f['state']=='released' for f in c['features']) else "+initial+"))",
 'wrong-sort':"c=json.load(open(sys.argv[1]));r=expected(c);r['features'].reverse();print(json.dumps(r))",
 'bool-as-integer':"c=json.load(open(sys.argv[1]));\nfor f in c['features']:\n if f['version'] is True:f['version']=1\nprint(json.dumps(expected(c)))"}
 for name,body in variants.items():
  program.write_text(oracle+'\ntry:\n '+body.replace('\n','\n ')+'\nexcept Exception:\n print("Invalid catalog",file=sys.stderr);sys.exit(2)\n')
  rows=m['probe'](program,cs);wrong[name]=rows;assert not all(x['passed'] for x in rows),name
 saved(root/'oracle-controls.json',{'at':time.time(),'reference':positive,'brokenControls':wrong,'claim':'Mechanical checker qualification, not model trials'})
print(json.dumps({'referencePassed':len(positive),'brokenVariantsRejected':list(wrong),'modelsStarted':0}))
