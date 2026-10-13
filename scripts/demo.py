"""Host-side stages used by run_demo.ps1."""
import argparse
import json
from pathlib import Path
import native_sampling as sampling
from cpacs_bridge import export,edit,permitted_change,sha,SOURCE_SHA,validate

ROOT=Path(__file__).resolve().parents[1]
YS=[0,.1,.2,.35,.5,.7,.9,1.1,1.3,1.5,1.7,1.9,2.1,2.3,2.45,2.56,2.65,2.7,2.73,2.742]
ZS=[0,.2,.4,.6,.8,.95,.992,1.04,1.09,1.13,1.151]

def measure(run,label):
    sampling.SOURCE=(run/f'{label}-working.ntop').resolve()
    tag=run.relative_to(ROOT/'runs').as_posix()
    m={'feature_m':.002,'source':str(sampling.SOURCE),'source_sha256':sha(sampling.SOURCE),'sections':[]}
    for component,axis,stations in [('body','y',YS),('fin','z',ZS)]:
        for start in range(0,len(stations),4):
            suffix=f'{label}-{component}-batch-{start:03d}'
            manifest=run/suffix/'manifest.json'
            if not manifest.exists():
                sampling.run(f'{tag}/{suffix}',[f'{axis}{s}' for s in stations[start:start+4]],component=component)
            data=json.loads(manifest.read_text())
            assert data['source_sha256']==m['source_sha256']
            for row in data['sections']:assert sha(row['curves'])==row['curve_sha256']
            m['sections']+=data['sections']
    (run/f'{label}-sections.json').write_text(json.dumps(m,indent=2))
    receipt=json.loads((run/('baseline-api.json' if label=='baseline' else 'apply-receipt.json')).read_text())
    tip=receipt['tip_twist']['value'] if label=='baseline' else receipt['after']['value']
    if not (run/f'{label}.xml').exists():export(run/f'{label}-sections.json',run/f'{label}.xml',tip,run/f'{label}.recipe.json')
    else:validate(run/f'{label}.xml')

def prepare(run,tip):
    if not (run/'request.xml').exists():edit(run/'baseline.xml',run/'request.xml',tip)
    cfg=permitted_change(run/'baseline.xml',run/'request.xml')
    cfg.update(run_dir=str(run),baseline_xml=str(run/'baseline.xml'),request_xml=str(run/'request.xml'),baseline_recipe_sha256=sha(run/'baseline.recipe.json'))
    (run/'apply-config.json').write_text(json.dumps(cfg,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['measure-baseline','prepare','measure-changed']);p.add_argument('run',type=Path);p.add_argument('--tip',type=float,default=4)
    a=p.parse_args();run=a.run.resolve()
    if a.stage=='prepare':prepare(run,a.tip)
    else:measure(run,a.stage.split('-')[1])
