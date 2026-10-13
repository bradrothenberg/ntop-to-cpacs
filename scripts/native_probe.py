"""Measure saved native scalar fields at supplied metre coordinates."""
import copy
import json
from pathlib import Path
import subprocess
import time
import numpy as np
from ntop_container import read, write
from native_sampling import ENGINE, sha


def probe(source, points, fields, out, timeout=120):
    source, out = Path(source).resolve(), Path(out).resolve()
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    points = np.asarray(points, dtype=float)
    assert points.ndim == 2 and points.shape[1] == 3 and np.isfinite(points).all()
    csv = out / 'points-m.csv'
    np.savetxt(csv, points, delimiter=',', fmt='%.17g')
    assert np.array_equal(np.loadtxt(csv, delimiter=',').reshape(-1,3), points)
    h, chunks = read(source)
    assert write(h,chunks) == source.read_bytes()
    main = next(c for c in chunks if c.name == 'main')
    fn = json.loads(main.find('fn').payload)
    index = json.loads(main.find('index').payload)
    nodes = {n['id']:n for n in fn['code']}
    template = copy.deepcopy(next(n for n in nodes.values() if n['type']=='real' and not n['inputs']))
    next_id = max(nodes)+1000
    def edge(i):
        return dict(instanceId=i,modelInputIdx=-1,propchain=[],meta=dict(expression='',is_default=False,name=''))
    def node(func, typ, args, value=None):
        nonlocal next_id
        next_id += 1
        n = copy.deepcopy(template)
        n.update(id=next_id,name='Native continuity measurement',func=func,type=typ,inputs=[edge(i) for i in args],autoc=True)
        fn['code'].append(n)
        if value is not None:index.append(dict(id=str(next_id),type=typ,value=value))
        return next_id
    path=node('','file_path',[],dict(val=csv.as_posix()))
    units=node('','unit_length_enum',[],dict(id='m'))
    point_list=node('import_points<file_path,unit_length_enum>','list<point>',[path,units])
    output=None
    for field in fields.values():
        if isinstance(field,str):field=next(n['id'] for n in nodes.values() if n['name']==field)
        v=node('evaluate_field<real_field,point>','list<real>',[field,point_list])
        output=v if output is None else node('core.concatenate_lists<list_interface,list_interface>','list<real>',[output,v])
    nodes={n['id']:n for n in fn['code']};keep=set()
    def visit(i):
        if i in keep or i not in nodes:return
        keep.add(i)
        for a in nodes[i]['inputs']:visit(a['instanceId'])
    visit(output);keep.add(100)
    nodes[100]['inputs']=[edge(output)]
    fn['code']=[n for n in fn['code'] if n['id'] in keep]
    fn['output']=output
    fn['def']['output']=dict(default_type='list<real>',type='list<real>')
    main.find('fn').payload=json.dumps(fn).encode()
    main.find('index').payload=json.dumps([n for n in index if int(n['id']) in keep]).encode()
    for chunk in chunks:
        if chunk.name=='view':chunk.payload=b'[]'
        if chunk.name=='open':chunk.payload=b'{}'
        if chunk.name=='sections':chunk.payload=json.dumps(dict(decorations=[dict(name='Native continuity measurement',description='',collapse=True)],poles=[0,1])).encode()
    notebook=out/'probe.ntop';notebook.write_bytes(write(h,chunks))
    digest=sha(source);start=time.perf_counter()
    command=[str(ENGINE),'--trustnotebook','-o',str(out/'output.json'),str(notebook),'-m','8','-v','2']
    with (out/'native.log').open('w') as log:
        proc=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        print(json.dumps(dict(probe=str(out),pid=proc.pid,points=len(points))),flush=True)
        try:code=proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill();proc.wait();raise
    text=(out/'native.log').read_text(errors='replace')
    assert code in [0,72] and 'nTop successfully built' in text and '[E]' not in text,text[-2000:]
    data=json.loads((out/'output.json').read_text())[0]['components']
    assert len(data)==len(points)*len(fields)
    values=np.array([v['value']['val'] if v['value'].get('isFinite',True) else np.nan for v in data]).reshape(len(fields),len(points))
    np.savez_compressed(out/'measurements.npz',points=points,values=values,fields=list(fields))
    assert sha(source)==digest
    (out/'receipt.json').write_text(json.dumps(dict(source=source.name,source_sha256=digest,engine_sha256=sha(ENGINE),points=len(points),fields=list(fields),seconds=time.perf_counter()-start,finite=bool(np.isfinite(values).all())),indent=2))
    return values
