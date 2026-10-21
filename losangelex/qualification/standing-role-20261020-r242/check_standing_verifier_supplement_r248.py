"""Supplementary verifier audit. Does not replace any frozen model-run score."""
import json,runpy,tempfile,subprocess,time
from pathlib import Path
Q=Path('/aosp/development/lax-three-context-20261018-r01/qualification')
R=Path('/var/lib/lax-standing-responsibility-20261020-r242')
m=runpy.run_path(str(Q/'standing_outcome_r242.py'))
oracle=(Q/'standing_outcome_r242.py').read_text().split('def probe(')[0]
program=oracle+"""
try:
 c=json.load(open(sys.argv[1]));r=expected(c)
 for f in r['features']:
  if f['version']==1:f['version']=True
 print(json.dumps(r))
except Exception:
 print('Invalid catalog',file=sys.stderr);sys.exit(2)
"""
with tempfile.TemporaryDirectory(prefix='supplementary-control-',dir=R) as d:
 p=Path(d)/'wrong.py';p.write_text(program)
 released=json.loads((R/'protocol/RELEASE-REQUIREMENTS.json').read_text())
 rows=m['probe'](p,[released]+m['cases'](R/'protocol'))
 assert all(x['passed'] for x in rows)
 got=rows[0]['actual'];want=rows[0]['expected']
 canonical=lambda x:json.dumps(x,sort_keys=True,separators=(',',':'))
 strict_rejects=canonical(got)!=canonical(want);assert strict_rejects
 proof={'at':time.time(),'scope':'Post-trial supplementary evaluator audit; frozen r242 scorer/results unchanged','blindSpot':'Python object equality conflates boolean True and integer1. Frozen unseen cases reject other wrong programs but omit a released version1 valid case. A wrong-output-primitive program passes the frozen checks.','originalScorerAdmitsBooleanOutputControl':all(x['passed'] for x in rows),'strictJsonPrimitiveComparisonRejectsControl':strict_rejects,'rows':rows,'policy':'Apply strict JSON comparison as explicitly supplementary evidence to actual outputs. Future tests freeze strict primitive checks and this control before models. No model/source/output repair or score rewrite.'}
 (Q/'standing-verifier-supplement-r248.json').write_text(json.dumps(proof,indent=2)+'\n')
 print(json.dumps({k:v for k,v in proof.items() if k!='rows'}))
