"""Independent CPACS transform readback, native checks, and demo artifact."""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from cpacs_bridge import validate,permitted_change,sha,SOURCE_SHA,NS,load_manifest
from ntop_container import read,write
from scalar_graph import Graph

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL=Path(os.environ['NTOP_ORIGINAL_SOURCE']) if os.environ.get('NTOP_ORIGINAL_SOURCE') else None

def native_twist(path):
    header,chunks=read(path);assert write(header,chunks)==Path(path).read_bytes()
    main=next(c for c in chunks if c.name=='main')
    fn=json.loads(main.find('fn').payload);nodes={n['id']:n for n in fn['code']}
    values={int(v['id']):v for v in json.loads(main.find('index').payload)}
    node=next(n for n in nodes.values() if n['name']=='Tip twist')
    while node['func'].startswith('core.var'):node=nodes[node['inputs'][0]['instanceId']]
    value=values[node['id']]['value'];assert value['units']=={'angle':1}
    return math.degrees(value['val'])

def collapse(source,dest):
    h,chunks=read(source);assert write(h,chunks)==Path(source).read_bytes()
    before={c.name:c.serialize() for c in chunks}
    opened=next(c for c in chunks if c.name=='open');records=json.loads(opened.payload)
    count=0
    for rec in records:
        if rec.get('relativePath')!='100_':rec['collapsed']=True;count+=1
    opened.payload=json.dumps(records).encode()
    sections=next(c for c in chunks if c.name=='sections');sc=json.loads(sections.payload)
    for s in sc['decorations']:s['collapse']=True
    sections.payload=json.dumps(sc).encode()
    assert all(c.serialize()==before[c.name] for c in chunks if c.name not in ['open','sections'])
    raw=write(h,chunks)
    if dest.exists() and dest.read_bytes()!=raw:raise FileExistsError(dest)
    dest.write_bytes(raw);hh,cc=read(dest);assert write(hh,cc)==raw
    return {'blocks_collapsed':count,'sections_collapsed':len(sc['decorations']),'non_ui_chunks_unchanged':True,'sha256':sha(dest)}

def matrix(t):
    def v(tag,default):
        el=t.find(tag) if t is not None else None
        return np.array([float(el.findtext(k,str(d))) if el is not None else d for k,d in zip('xyz',default)])
    x,y,z=np.deg2rad(v('rotation',[0,0,0]));sx,cx=np.sin(x),np.cos(x);sy,cy=np.sin(y),np.cos(y);sz,cz=np.sin(z),np.cos(z)
    rx=np.array([[1,0,0],[0,cx,-sx],[0,sx,cx]])
    ry=np.array([[cy,0,sy],[0,1,0],[-sy,0,cy]])
    rz=np.array([[cz,-sz,0],[sz,cz,0],[0,0,1]])
    m=np.eye(4);m[:3,:3]=rz@ry@rx@np.diag(v('scaling',[1,1,1]));m[:3,3]=v('translation',[0,0,0]);return m

def loops(row):
    d=np.load(row['curves']);ls=[d[k] for k in d.files]
    return max(ls,key=lambda p:np.linalg.norm(np.roll(p,-1,axis=0)-p,axis=1).sum())

def decode_check(xml,manifest):
    tree=validate(xml);m=load_manifest(manifest);profiles={p.get('uID'):p for p in tree.findall('.//wingAirfoil')};errors=[]
    for axis,uid in [('y','GBI_BWB'),('z','GBI_FIN')]:
        wing=tree.find(f'.//wing[@uID="{uid}"]');rows=sorted([r for r in m['sections'] if r['axis']==axis],key=lambda r:r['station_m'])
        sections=wing.findall('sections/section');assert len(sections)==len(rows)
        for sec,row in zip(sections,rows):
            el=sec.find('elements/element');pl=profiles[el.findtext('airfoilUID')].find('pointList')
            p=np.array([np.fromstring(pl.findtext(k),sep=';') for k in 'xyz']).T
            transform=matrix(wing.find('transformation'))@matrix(sec.find('transformation'))@matrix(el.find('transformation'))
            world=(transform@np.column_stack((p,np.ones(len(p)))).T).T[:,:3][:-1]
            native=loops(row);assert world.shape==native.shape
            # Sort by quantized full point tuples, then compare unrounded values.
            def sort(q):
                r=np.round(q,10);return q[np.lexsort((r[:,2],r[:,1],r[:,0]))]
            error=float(np.max(np.linalg.norm(sort(world)-sort(native),axis=1)))
            assert error<1e-9,error
            errors.append(error)
    return {'profiles':len(errors),'max_decoded_point_error_m':max(errors),'uids_resolved':True}

def contract_checks(run):
    base=run/'baseline.xml';request=run/'request.xml';cfg=permitted_change(base,request)
    testdir=run/'contract-checks';testdir.mkdir(exist_ok=True)
    invalid=[]
    for label,mutate in [
        ('geometry',lambda t:setattr(t.find('.//wing/sections/section/transformation/translation/x'),'text','100')),
        ('nan',lambda t:setattr(t.find(f'./toolspecific/tool/{{{NS}}}bridge/{{{NS}}}tipTwistDeg'),'text','NaN')),
        ('unsupported_value',lambda t:setattr(t.find(f'./toolspecific/tool/{{{NS}}}bridge/{{{NS}}}tipTwistDeg'),'text','20'))]:
        tree=validate(request);mutate(tree);dest=testdir/(label+'.xml');tree.write(str(dest),encoding='UTF-8',xml_declaration=True,pretty_print=True)
        try:permitted_change(base,dest)
        except (ValueError,AssertionError):invalid.append(label)
        else:raise AssertionError('Importer accepted '+label)
    return {'valid_request':cfg,'rejected_edits':invalid}

def compare_plot(run):
    a=load_manifest(run/'baseline-sections.json')['sections'];b=load_manifest(run/'changed-sections.json')['sections']
    assert [(r['axis'],r['station_m'])for r in a]==[(r['axis'],r['station_m'])for r in b]
    rows=[]
    for ra,rb in zip(a,b):
        pa,pb=loops(ra),loops(rb)
        ea=np.array([pa.min(0),pa.max(0)]);eb=np.array([pb.min(0),pb.max(0)])
        rows.append({'axis':ra['axis'],'station_m':ra['station_m'],'baseline_bounds_m':ea.tolist(),'changed_bounds_m':eb.tolist(),'max_bounds_coordinate_change_mm':float(np.max(abs(eb-ea))*1000)})
    assert max(r['max_bounds_coordinate_change_mm']for r in rows)>1
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'text.color':'#262626','axes.labelcolor':'#262626','xtick.color':'#6D6C6A','ytick.color':'#6D6C6A','axes.edgecolor':'#CBD0D8','axes.spines.top':False,'axes.spines.right':False,'axes.facecolor':'#F7F8FA','grid.color':'#CBD0D8'})
    fig,axs=plt.subplots(2,2,figsize=(12,6),layout='constrained')
    for ax,y in zip(axs.flat,[.5,1.1,1.9,2.56]):
        for data,color,label in [(a,'#6D6C6A','Baseline 2 deg'),(b,'#16489D','CPACS update 4 deg')]:
            row=min((r for r in data if r['axis']=='y'),key=lambda r:abs(r['station_m']-y));p=loops(row);p=np.vstack((p,p[0]));ax.plot(p[:,0],p[:,2],color=color,label=label,lw=1.6)
        ax.set_title(f'Wing section at Y = {row["station_m"]:.2f} m',loc='left',weight='bold');ax.set_xlabel('X (m)');ax.set_ylabel('Z (m)');ax.grid(alpha=.18);ax.set_aspect('equal',adjustable='datalim')
    axs[0,0].legend(frameon=False,fontsize=9)
    fig.savefig(run/'section-comparison.png',dpi=160,facecolor='#F7F8FA');plt.close(fig)
    return rows

def verify(run):
    assert sha(ROOT/'source/GBI-V38.ntop')==SOURCE_SHA
    source_check={'retained_copy_sha256':sha(ROOT/'source/GBI-V38.ntop'),'original_path':str(ORIGINAL) if ORIGINAL else None,'original_checked':bool(ORIGINAL and ORIGINAL.is_file())}
    if ORIGINAL and ORIGINAL.is_file():
        source_check['original_sha256']=sha(ORIGINAL)
        assert source_check['original_sha256']==SOURCE_SHA
    receipt=json.loads((run/'apply-receipt.json').read_text())
    assert receipt['before']['value']==2 and receipt['after']['value']==4
    assert receipt['field_before']['value']!=receipt['field_after']['value']
    recipes=[]
    for label in ['baseline','changed']:
        r=json.loads((run/f'{label}.recipe.json').read_text())
        control=next(n for n in r['body'] if n.get('name')=='Tip twist')
        assert control['contents']['type']=='real'
        assert control['contents']['value']['units']=={'angle':1}
        control['contents']['value']['val']=0
        recipes.append(r)
    assert recipes[0]==recipes[1],'Unexpected graph changes outside the supported control'
    result={'source_unchanged':True,'api_apply':receipt,'cpacs':{},'notebooks':{},'contract_checks':contract_checks(run)}
    result['source_preservation']=source_check
    result['only_tip_twist_changed_in_recipe']=True
    y=np.linspace(0,2.75,11001)
    points=np.column_stack((np.full_like(y,6.8),y,np.zeros_like(y)))
    fraction=np.minimum(y/2.7432,1)
    t=np.clip((y-.3055)/(1.-.3055),0,1)
    gate=t**4*(35+t*(-84+t*(70-20*t)))
    twist_errors={}
    for label,angle in [('baseline',2),('changed',4)]:
        graph=Graph(run/f'{label}-working.ntop')
        actual=graph.eval('Explicit source twist',points)
        expected=np.deg2rad(2)*fraction+np.deg2rad(angle-2)*fraction*gate
        twist_errors[label]=float(np.max(abs(actual-expected)))
        assert twist_errors[label]<1e-12
    result['twist_transition']={'reference_tip_deg':2,'construction_start_m':.3055,
        'construction_end_m':1.,'samples':len(y),'formula_error_rad':twist_errors,
        'continuity':'The added-twist gate and its first three derivatives match at both endpoints.',
        'scope':'Scalar construction check; no global surface-fairness claim.'}
    for label,angle in [('baseline',2),('changed',4)]:
        assert abs(native_twist(run/f'{label}-working.ntop')-angle)<1e-12
        result['cpacs'][label]=decode_check(run/f'{label}.xml',run/f'{label}-sections.json')
        result['notebooks'][label]=collapse(run/f'{label}-working.ntop',run/f'GBI-{label}.ntop')
    result['section_bounds_comparison']=compare_plot(run)
    result['passed']=True
    (run/'verification.json').write_text(json.dumps(result,indent=2))
    (ROOT/'latest-run.txt').write_text(str(run)+'\n')
    summary={k:v for k,v in result.items() if k not in ['section_bounds_comparison','api_apply','contract_checks']}
    print(json.dumps(summary,indent=2))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);a=p.parse_args();verify(a.run.resolve())
