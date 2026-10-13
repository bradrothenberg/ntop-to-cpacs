"""Measure native sections of API-saved GBI notebooks with nTop Automate.

Adapted from the verified Rev38 native section extraction.
Only measurement copies are instrumented. Design values come from the API save.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'source/GBI-V38.ntop'
ENGINE = Path(os.environ.get('NTOPCL_EXE',r'C:\Program Files\nTopology\nTopology\ntopcl.exe'))
sys.path.insert(0, str(ROOT / 'scripts'))
from ntop_container import read, write

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

class Builder:
    def __init__(self):
        self.head, self.chunks = read(SOURCE)
        assert write(self.head,self.chunks)==SOURCE.read_bytes()
        self.main=next(c for c in self.chunks if c.name=='main')
        self.fn=json.loads(self.main.find('fn').payload)
        self.index=json.loads(self.main.find('index').payload)
        self.nodes={n['id']:n for n in self.fn['code']}
        self.next=max(self.nodes)+10000
        self.template=copy.deepcopy(next(n for n in self.nodes.values() if n['type']=='real' and not n['inputs']))

    def edge(self,i,props=()):
        return dict(instanceId=i,modelInputIdx=-1,propchain=list(props),meta=dict(expression='',is_default=False,name=''))

    def add(self,func,typ,name,args=(),value=None,units=None):
        self.next+=1
        n=copy.deepcopy(self.template)
        n.update(id=self.next,func=func,type=typ,name=name,inputs=[a if isinstance(a,dict) else self.edge(a) for a in args],units=units or {},unitsKnown=True,autoc=True,paust=0,bldst=0)
        self.fn['code'].append(n);self.nodes[self.next]=n
        if value is not None:self.index.append(dict(id=str(self.next),type=typ,value=value))
        return self.next

    def real(self,v):return self.add('','real','Length',value=dict(isFinite=True,val=v,units={'length':1}),units={'length':1})
    def point(self,p):return self.add('','point','Origin',value=[dict(isFinite=True,val=v) for v in p],units={'length':1})
    def vector(self,p):return self.add('','vector','Axis',value=dict(value=[dict(isFinite=True,val=v) for v in p],units={}))

    def component(self,kind):
        if kind in ['fin','passage']:
            field=34039 if kind=='fin' else self.add('min<real_field,real_field>','real_field','Both original passage tools',[12010,23037])
            for x,y,z in [(32385,32412,115),(31040,110,115),(34123,110,34127),(51179,110,51181)]:
                field=self.add('remap<real_field,real_field,real_field,real_field>','real_field','Mapped fin',[field,x,y,z])
            return self.add('core.var<implicit>','implicit','Component for loft', [field])
        if kind in ['body','no_fin']:
            for union,base in [(35007,1774),(45053,45051)]:
                self.nodes[union].update(func='core.var<implicit>',inputs=[self.edge(base)])
        if kind=='body':
            for i in [35012,35013,45058,45059]:
                base=self.nodes[i]['inputs'][2]
                self.nodes[i].update(func='core.var<implicit>',inputs=[base])
        return 35023

    def save(self,path,exports):
        output=exports[-1];keep=set()
        def walk(i):
            if i in keep or i not in self.nodes:return
            keep.add(i)
            for a in self.nodes[i]['inputs']:walk(a['instanceId'])
        for i in exports:walk(i)
        keep.add(100);self.nodes[100]['inputs']=[self.edge(i) for i in exports]
        self.fn['code']=[n for n in self.fn['code'] if n['id'] in keep]
        self.fn['output']=output;self.fn['def']['inputs']=[]
        self.fn['def']['output']={'type':'cli_slice_data','default_type':'cli_slice_data'}
        self.fn['def']['outputBaseUnits']={}
        self.main.find('fn').payload=json.dumps(self.fn).encode()
        self.main.find('index').payload=json.dumps([v for v in self.index if int(v['id']) in keep]).encode()
        for c in self.chunks:
            if c.name in ['view','open']:c.payload=b'[]'
            elif c.name=='cache':c.find('index').payload=b'[]'
            elif c.name=='sections':c.payload=json.dumps(dict(decorations=[dict(name='SMLib source sections',description='',collapse=True)],poles=[0,len(exports)])).encode()
        path.write_bytes(write(self.head,self.chunks))
        h,ch=read(path);assert write(h,ch)==path.read_bytes()

def parse_cli(path,origin,u,v):
    loops=[];units=None;layer=None
    for line in path.read_text().splitlines():
        if line.startswith('$$UNITS/'):units=float(line.split('/')[1])*.001
        elif line.startswith('$$LAYER/'):layer=float(line.split('/')[1])*units
        elif line.startswith('$$POLYLINE/'):
            a=line.split('/')[1].split(',');part,direction,count=map(int,a[:3])
            p=np.array(list(map(float,a[3:]))).reshape(-1,2)*units
            assert len(p)==count and direction!=2 and np.array_equal(p[0],p[-1]) and abs(layer)<1e-12
            p=p[:-1];world=np.array(origin)+p[:,0,None]*u+p[:,1,None]*v
            loops.append(world)
    return loops

def run(tag,stations,feature=.002,component='final'):
    out=ROOT/'runs'/tag
    assert not out.exists(), 'Keep extraction attempts separate'
    out.mkdir(parents=True)
    digest=sha(SOURCE)
    b=Builder()
    field=b.component(component)
    if component=='passage':
        # Construction extent only: enclose the measured airframe's center
        # passage and extend above its 0.577 m upper skin. Do not sample the
        # remote continuation of the inlet cutting tool.
        boundary=b.add('box<point,real,real,real>','box','Local passage measurement boundary',[b.point([4.,0.,.5]),b.real(10.),b.real(1.5),b.real(2.)])
        clipped=b.add('max<real_field,real_field>','real_field','Bounded passage tool',[field,b.edge(boundary,['body'])])
        bounds=b.add('create_bounding_box<point,point>','bounding_box','Passage sampling bounds',[b.point([-1.,-.75,-.5]),b.point([9.,.75,1.5])])
        field=b.add('set_bounding_box<implicit,bounding_box>','implicit','Bounded passage for slicing',[clipped,bounds])
    else:
        boundary=b.add('box<point,real,real,real>','box','Slice boundary',[b.point([0.,0.,0.]),b.real(100.),b.real(100.),b.real(100.)])
        bounds=b.add('create_bounding_box<point,point>','bounding_box','Measured airframe sampling envelope',[b.point([-.1,-2.85,-.4]),b.point([7.6,2.85,1.2])])
        field=b.add('set_bounding_box<implicit,bounding_box>','implicit','Local airframe sampling bounds',[field,bounds])
    positive=b.add('','bool','Layers',value={'val':False})
    ascii_enum=b.add('','ascii_or_binary_enum','ASCII',value={'enum':0})
    exports=[];rows=[]
    for j,station in enumerate(stations):
        axis=station[0];s=float(station[1:])
        origin={'x':[s,0.,0.],'y':[0.,s,0.],'z':[0.,0.,s]}[axis]
        u,v={'x':([0.,1.,0.],[0.,0.,1.]),'y':([0.,0.,1.],[1.,0.,0.]),'z':([1.,0.,0.],[0.,1.,0.])}[axis]
        frame=b.add('frame<point,vector,vector>','frame','Section frame',[b.point(origin),b.vector(u),b.vector(v)])
        stack=b.add('slice_implicit<implicit,real,real,bool,frame,implicit>[3.1.0]','slice_stack','Source section',[field,b.real(100.),b.real(feature),positive,frame,b.edge(boundary,['body'])])
        cli=out/f'{j:03d}-{axis}-{s:.6f}.cli'
        path=b.add('','file_path','Contour output',value={'val':cli.as_posix()})
        exports.append(b.add('export_slices_to_cli<file_path,slice_stack,ascii_or_binary_enum>','cli_slice_data','Section export',[path,stack,ascii_enum]))
        rows.append(dict(axis=axis,station_m=s,origin=origin,u=u,v=v,path=str(cli)))
    dest=out/'extract.ntop';b.save(dest,exports)
    cmd=[str(ENGINE),'--trustnotebook','-o',str(out/'output.json'),str(dest),'-m','8','-v','2']
    t=time.perf_counter()
    with (out/'native.log').open('w') as log:
        proc=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        print(json.dumps({'pid':proc.pid,'sections':len(rows),'tag':tag}),flush=True)
        try:code=proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            proc.kill();proc.wait();raise
    text=(out/'native.log').read_text(errors='replace')
    assert code in [0,72] and 'nTop successfully built' in text and '[E]' not in text,text[-2500:]
    for row in rows:
        loops=parse_cli(Path(row['path']),row['origin'],np.array(row['u']),np.array(row['v']))
        npz=Path(row['path']).with_suffix('.npz')
        np.savez_compressed(npz,**{f'loop_{i}':p for i,p in enumerate(loops)})
        row['curves']=str(npz);row['loops']=[{'count':len(p),'bounds_m':[p.min(0).tolist(),p.max(0).tolist()], 'perimeter_m':float(np.linalg.norm(np.roll(p,-1,axis=0)-p,axis=1).sum())} for p in loops]
        row['curve_sha256']=sha(npz)
        print(json.dumps({k:row[k] for k in ['axis','station_m','loops']}),flush=True)
    assert sha(SOURCE)==digest
    result=dict(source=str(SOURCE),source_sha256=digest,engine=str(ENGINE),engine_sha256=sha(ENGINE),feature_m=feature,wall_seconds=time.perf_counter()-t,component=component,sections=rows)
    (out/'manifest.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'completed':tag,'wall_seconds':result['wall_seconds']}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('tag');p.add_argument('stations',nargs='+');p.add_argument('--feature',type=float,default=.002);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--component',choices=['final','body','no_fin','fin','passage'],default='final')
    a=p.parse_args();SOURCE=a.source.resolve();run(a.tag,a.stations,a.feature,a.component)
