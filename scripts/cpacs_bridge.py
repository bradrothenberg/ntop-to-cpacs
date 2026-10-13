"""CPACS 3.5.1 geometry export and strict GBI tip-twist round-trip contract."""
import argparse
import copy
import hashlib
import json
import math
from datetime import datetime,timezone
from pathlib import Path
from lxml import etree as E
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
NS='urn:ntop:gbi:cpacs:1'
SOURCE_SHA='44acc807b70ef83ad130c73cbe5957843fe9ff194b3391dc7fa8f805cfaae7a5'
TIP_PATH=f'./toolspecific/tool/{{{NS}}}bridge/{{{NS}}}tipTwistDeg'
SCOPE='Sampled outer blended wing/body envelope and separate fin. Inlet/exhaust passages, fin-root blending and inter-section exactness are not represented. Source native geometry remains authoritative.'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load_manifest(path):
    path=Path(path).resolve()
    data=json.loads(path.read_text())
    for row in data['sections']:
        curve=Path(row['curves'])
        if not curve.is_absolute():row['curves']=str(path.parent/curve)
    return data
def parse(path):return E.parse(str(path),E.XMLParser(resolve_entities=False,no_network=True))
def child(parent,name,value=None,**attrs):
    n=E.SubElement(parent,name,**{k:str(v) for k,v in attrs.items()})
    if value is not None:n.text=str(value)
    return n
def xyz(parent,name,values,**attrs):
    p=child(parent,name,**attrs)
    for k,v in zip('xyz',values):child(p,k,format(float(v),'.16g'))
def transform(parent,translation=(0,0,0),rotation=(0,0,0),scaling=(1,1,1)):
    t=child(parent,'transformation');xyz(t,'scaling',scaling);xyz(t,'rotation',rotation);xyz(t,'translation',translation)
    return t

def validate(path):
    tree=parse(path)
    E.XMLSchema(E.parse(str(ROOT/'schema/demo-schema.xsd'))).assertValid(tree)
    ids=tree.xpath('//@uID');assert len(ids)==len(set(ids)),'Duplicate UID'
    for tag in ['airfoilUID','fromElementUID','toElementUID']:
        for el in tree.findall('.//'+tag):
            if el.text not in ids:raise ValueError(f'Unresolved {tag}: {el.text}')
    for pl in tree.findall('.//wingAirfoil/pointList'):
        p=np.array([np.fromstring(pl.findtext(k),sep=';') for k in 'xyz']).T
        if len(p)<4 or not np.isfinite(p).all() or not np.allclose(p[0],p[-1],atol=1e-12):raise ValueError('Invalid closed airfoil')
        if not np.allclose(p[:,1],0,atol=1e-12):raise ValueError('Airfoil not in local XZ plane')
    return tree

def section_loop(row):
    data=np.load(row['curves'])
    loops=[data[k] for k in data.files]
    p=max(loops,key=lambda p:np.linalg.norm(np.roll(p,-1,axis=0)-p,axis=1).sum())
    if not np.isfinite(p).all():raise ValueError('Nonfinite native points')
    # Start at the upper trailing-edge point. Preserve every native sample.
    thickness=2 if row['axis']=='y' else 1
    candidates=np.where(p[:,0]>=p[:,0].max()-1e-9)[0]
    start=candidates[np.argmax(p[candidates,thickness])]
    p=np.roll(p,-start,axis=0)
    # CPACS profile order: lower trailing edge -> leading edge -> upper edge.
    # Choose the lower-going branch for the start. Fin local thickness is -Y.
    zz=p[:,2] if row['axis']=='y' else -p[:,1]
    area=np.sum(p[:,0]*np.roll(zz,-1)-np.roll(p[:,0],-1)*zz)
    if area>0:p=np.concatenate([p[:1],p[:0:-1]])
    return np.vstack([p,p[0]])

def export(manifest,out,tip,recipe):
    manifest=Path(manifest);m=load_manifest(manifest);out=Path(out)
    if out.exists():raise FileExistsError(out)
    if not math.isfinite(tip):raise ValueError('Nonfinite tip twist')
    root=E.Element('cpacs',nsmap={'xsi':'http://www.w3.org/2001/XMLSchema-instance','ntop':NS})
    root.set('{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation','https://www.cpacs.de/schema/v3_5_1/cpacs_schema.xsd')
    h=child(root,'header');child(h,'name','GBI Rev38 CPACS Notebook API demo');child(h,'description',SCOPE);child(h,'version','1.0.0');child(h,'cpacsVersion','3.5.1')
    info=child(child(h,'versionInfos'),'versionInfo',version='1.0.0')
    child(info,'cpacsVersion','3.5.1');child(info,'description','Native measured sections and supported GBI parameter mapping.');child(info,'timestamp',datetime.now(timezone.utc).isoformat());child(info,'creator','nTop Notebook API demo')
    vehicles=child(root,'vehicles');model=child(child(vehicles,'aircraft'),'model',uID='GBI_V38');child(model,'name','GBI Rev38');child(model,'description',SCOPE)
    wings=child(model,'wings');profiles=child(child(vehicles,'profiles'),'wingAirfoils')
    recovered=[]
    for axis,uid,label in [('y','GBI_BWB','Blended wing and body envelope'),('z','GBI_FIN','Vertical stabilizer')]:
        rows=sorted([r for r in m['sections'] if r['axis']==axis],key=lambda r:r['station_m'])
        if len(rows)<2:raise ValueError('At least two sections per component are required')
        wing=child(wings,'wing',uID=uid,**({'symmetry':'x-z-plane'} if axis=='y' else {}));child(wing,'name',label);child(wing,'description',SCOPE);transform(wing,rotation=(0,0,0) if axis=='y' else (90,0,0))
        secs=child(wing,'sections');segs=child(wing,'segments');elements=[]
        for j,row in enumerate(rows):
            p=section_loop(row);xmin=p[:,0].min();chord=np.ptp(p[:,0])
            if chord<=0:raise ValueError('Degenerate chord')
            # After a +90 degree X rotation: (x,span,thickness)->(x,-thickness,span).
            local=np.column_stack(((p[:,0]-xmin)/chord,np.zeros(len(p)),(p[:,2] if axis=='y' else -p[:,1])/chord))
            suid=f'{uid}_S{j:03d}';euid=suid+'_E';auid=suid+'_PROFILE'
            section=child(secs,'section',uID=suid);child(section,'name',f'{label} station {row["station_m"]:.6g} m');transform(section,translation=(xmin,row['station_m'],0))
            element=child(child(section,'elements'),'element',uID=euid);child(element,'name',euid);child(element,'airfoilUID',auid);transform(element,scaling=(chord,chord,chord));elements.append(euid)
            air=child(profiles,'wingAirfoil',uID=auid);child(air,'name',auid);child(air,'description','Native section samples in local normalized chord coordinates.');pl=child(air,'pointList')
            for k,values in zip('xyz',local.T):child(pl,k,';'.join(format(float(v),'.16g') for v in values))
            q=local*chord;q[:,0]+=xmin
            if axis=='y':q[:,1]=row['station_m']
            else:q=np.column_stack((q[:,0],-q[:,2],np.full(len(q),row['station_m'])))
            recovered.append(float(np.max(abs(q-p))))
        for j,(a,b) in enumerate(zip(elements,elements[1:])):
            seg=child(segs,'segment',uID=f'{uid}_SEG{j:03d}');child(seg,'name',f'{label} segment {j}');child(seg,'fromElementUID',a);child(seg,'toElementUID',b)
    tool=child(child(root,'toolspecific'),'tool');child(tool,'name','nTop GBI Notebook API');child(tool,'version','1.0.0');bridge=child(tool,f'{{{NS}}}bridge',version='1',nativeVariable='Tip twist')
    for k,v in [('sourceSha256',SOURCE_SHA),('nativeRecipeSha256',sha(recipe)),('geometryTipTwistDeg',format(tip,'.16g')),('tipTwistDeg',format(tip,'.16g')),('samplingFeatureM',m['feature_m']),('geometryScope',SCOPE)]:child(bridge,f'{{{NS}}}{k}',v)
    out.parent.mkdir(parents=True,exist_ok=True);E.ElementTree(root).write(str(out),encoding='UTF-8',xml_declaration=True,pretty_print=True)
    validate(out)
    result={'file':str(out.resolve()),'sha256':sha(out),'schema':'CPACS 3.5.1 plus typed nTop toolspecific namespace','profiles':len(recovered),'native_sample_reconstruction_max_error_m':max(recovered),'tip_twist_deg':tip,'sampling_manifest_sha256':sha(manifest),'geometry_scope':SCOPE}
    out.with_suffix('.validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

def permitted_change(base,request):
    a=validate(base);b=validate(request)
    ea=a.find(TIP_PATH);eb=b.find(TIP_PATH)
    if ea is None or eb is None:raise ValueError('Missing supported nTop bridge')
    target=float(eb.text)
    if not math.isfinite(target) or target not in [2.0,4.0]:raise ValueError('This verified demo supports 2 or 4 degrees only')
    old=ea.text;eb.text=old
    if E.tostring(a,method='c14n')!=E.tostring(b,method='c14n'):raise ValueError('Unsupported CPACS edit. Only ntop:tipTwistDeg may change.')
    bridge=a.find(f'./toolspecific/tool/{{{NS}}}bridge')
    if bridge.findtext(f'{{{NS}}}sourceSha256')!=SOURCE_SHA:raise ValueError('Wrong GBI baseline')
    return {'baseline_tip_twist_deg':float(old),'tip_twist_deg':target,'source_sha256':SOURCE_SHA,'baseline_xml_sha256':sha(base),'request_xml_sha256':sha(request)}

def edit(base,out,tip):
    tree=validate(base)
    if Path(out).exists():raise FileExistsError(out)
    tree.find(TIP_PATH).text=format(tip,'.16g')
    tree.write(str(out),encoding='UTF-8',xml_declaration=True,pretty_print=True)
    print(json.dumps(permitted_change(base,out)))

if __name__=='__main__':
    p=argparse.ArgumentParser();sp=p.add_subparsers(dest='cmd',required=True)
    a=sp.add_parser('export');a.add_argument('manifest');a.add_argument('out');a.add_argument('--tip',type=float,required=True);a.add_argument('--recipe',required=True)
    a=sp.add_parser('validate');a.add_argument('file')
    a=sp.add_parser('edit');a.add_argument('baseline');a.add_argument('out');a.add_argument('--tip',type=float,required=True)
    a=sp.add_parser('check');a.add_argument('baseline');a.add_argument('request')
    a=p.parse_args()
    if a.cmd=='export':export(a.manifest,a.out,a.tip,a.recipe)
    elif a.cmd=='validate':validate(a.file);print('Valid CPACS 3.5.1 and nTop extension; UID references resolve.')
    elif a.cmd=='edit':edit(a.baseline,a.out,a.tip)
    else:print(json.dumps(permitted_change(a.baseline,a.request),indent=2))
