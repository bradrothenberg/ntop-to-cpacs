"""Independent evaluator for the scalar subset used by the GBI placement law.

Unsupported native geometry functions fail explicitly. Use native_probe for
the actual final airframe and surface measurements.
"""
import json
import numpy as np
from scipy.interpolate import BSpline
from ntop_container import read, write
from pathlib import Path


def literal(value):
    if isinstance(value,list):return np.array([literal(v) for v in value])
    if 'val' in value:return value['val']
    if 'enum' in value:return value['enum']
    if 'value' in value:return literal(value['value'])
    raise ValueError(value)


class Graph:
    def __init__(self,path):
        h,c=read(path);assert write(h,c)==Path(path).read_bytes()
        main=next(v for v in c if v.name=='main')
        self.nodes={n['id']:n for n in json.loads(main.find('fn').payload)['code']}
        self.values={int(v['id']):v['value'] for v in json.loads(main.find('index').payload)}
        self.names={n['name']:n['id'] for n in self.nodes.values() if n['func'].startswith('core.var')}
        self.splines={}

    def eval(self,ids,points,overrides=None):
        xyz=np.asarray(points,float);cache={105:xyz[...,0],110:xyz[...,1],115:xyz[...,2]}
        overrides=overrides or {}
        def get(i):
            if isinstance(i,str):i=self.names[i]
            if i in cache:return cache[i]
            if i in overrides:return overrides[i]
            n=self.nodes[i];fn=n['func'].split('<')[0];args=n['inputs']
            if not fn:r=literal(self.values[i])
            elif fn=='remap':
                p=np.stack(np.broadcast_arrays(*[get(a['instanceId']) for a in args[1:]]),axis=-1)
                r=self.eval(args[0]['instanceId'],p,overrides)
            elif fn=='set_bounding_box':r=get(args[0]['instanceId'])
            elif fn=='core.if':r=get(args[1 if get(args[0]['instanceId']) else 2]['instanceId'])
            elif fn=='curve_axis_distance':
                curve=get(args[0]['instanceId']);r=curve(np.clip(xyz[...,0]/curve.domain,0,1))[...,1]
            elif fn=='spline_by_control_points':
                if i not in self.splines:
                    c=np.array(get(args[0]['instanceId']));d=int(get(args[1]['instanceId']))
                    knots=np.r_[np.zeros(d),np.linspace(0,1,len(c)-d+1),np.ones(d)]
                    spline=BSpline(knots,c,d);spline.domain=c[-1,0]
                    t=np.linspace(0,1,21);assert np.max(abs(spline(t)[:,0]-t*spline.domain))<1e-12
                    self.splines[i]=spline
                r=self.splines[i]
            else:
                aa=[]
                for a in args:
                    assert not a['propchain'],(i,a)
                    aa.append(get(a['instanceId']))
                if fn=='core.var':r=aa[0]
                elif fn=='core.list':r=aa
                elif fn=='add':r=aa[0]+aa[1]
                elif fn=='subtract':r=aa[0]-aa[1]
                elif fn=='multiply':r=aa[0]*aa[1]
                elif fn=='divide':r=aa[0]/aa[1]
                elif fn=='min':r=np.minimum(aa[0],aa[1])
                elif fn=='max':
                    r=aa[0] if len(aa)==2 else aa[0][0]
                    for a in (aa[1:] if len(aa)==2 else aa[0][1:]):r=np.maximum(r,a)
                elif fn in ['sqrt','abs','exp','log','sin','cos']:r=getattr(np,fn)(aa[0])
                elif fn=='third_power':r=aa[0]**3
                elif fn=='equals':r=aa[0]==aa[1]
                elif fn=='ramp':
                    t=np.clip((aa[0]-aa[1])/(aa[2]-aa[1]),0,1);assert aa[5]==2
                    r=aa[3]+(aa[4]-aa[3])*t**3*(10+t*(-15+6*t))
                else:raise NotImplementedError((i,fn))
            cache[i]=r;return r
        return [get(i) for i in ids] if isinstance(ids,(list,tuple)) else get(ids)
