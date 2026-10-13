"""Measure the root-placement cause and verify the repaired C3 twist law."""
import argparse
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scalar_graph import Graph


def audit(baseline, old, candidate, out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    y=np.linspace(0,2.75,11001)
    points=np.column_stack((np.full_like(y,6.8),y,np.zeros_like(y)))
    fields=['Explicit source twist','V37 | rigid section Z translation']
    a,b,c=[Graph(p) for p in [baseline,old,candidate]]
    va,vb,vc=[np.array(g.eval(fields,points)) for g in [a,b,c]]
    normalized=np.minimum(y/2.7432,1)
    t=np.clip((y-.3055)/(1-.3055),0,1)
    gate=t**4*(35+t*(-84+t*(70-20*t)))
    expected=np.deg2rad(2)*normalized+np.deg2rad(2)*normalized*gate
    angle_error=float(np.max(abs(vc[0]-expected)))
    assert angle_error<1e-12,angle_error
    protected=y<=.3055
    outer=y>=1
    protected_error=float(np.max(abs(vc[:,protected]-va[:,protected])))
    outer_error=float(np.max(abs(vc[:,outer]-vb[:,outer])))
    reverted=np.array(c.eval(fields,points,{c.names['Tip twist']:np.deg2rad(2)}))
    baseline_error=float(np.max(abs(reverted-va)))
    assert max(protected_error,outer_error,baseline_error)<1e-12
    h=float(y[1]-y[0]);mask=(y>=.219456)&(y<=.3055)
    old_extra=vb[1]-va[1];new_extra=vc[1]-va[1]
    result=dict(sample_count=len(y),step_m=h,angle_formula_error_rad=angle_error,
                protected_zone_max_scalar_error=protected_error,
                outer_zone_max_scalar_error=outer_error,
                baseline_reversion_max_scalar_error=baseline_error,
                protected_zone_end_m=.3055,transition_end_m=1.0,
                old_root_peak_additional_placement_slope=float(np.max(abs(np.gradient(old_extra,h)[mask]))),
                repaired_root_peak_additional_placement_slope=float(np.max(abs(np.gradient(new_extra,h)[mask]))),
                root_added_displacement_at_gate_end_mm=float(np.interp(.3055,y,old_extra)*1000),
                continuity='The C3 polynomial and its first three derivatives match the constant branches at both endpoints.',
                scope='Independent scalar construction check. Native surface validation is separate.',passed=True)
    (out/'twist-law-audit.json').write_text(json.dumps(result,indent=2))
    np.savez_compressed(out/'twist-law.npz',y_m=y,baseline=va,old=vb,repaired=vc)
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.facecolor':'#F7F8FA','axes.edgecolor':'#CBD0D8','text.color':'#262626','grid.color':'#E4E7EC'})
    fig,axes=plt.subplots(1,2,figsize=(12,4),layout='constrained')
    for values,color,label in [(vb,'#6D6C6A','Previous 4 deg'),(vc,'#16489D','Repaired 4 deg')]:
        axes[0].plot(y,values[0]*180/np.pi,color=color,label=label)
        axes[1].plot(y,1000*(values[1]-va[1]),color=color,label=label)
    axes[0].set(xlim=(0,2.75),xlabel='Absolute span Y (m)',ylabel='Local twist (deg)',title='Twist distribution')
    axes[1].set(xlim=(.18,1.1),xlabel='Absolute span Y (m)',ylabel='Added vertical placement (mm)',title='Additional placement relative to 2 deg')
    for ax in axes:ax.grid();ax.legend(frameon=False,fontsize=9)
    fig.savefig(out/'twist-transition.png',dpi=160,facecolor='#F7F8FA');plt.close(fig)
    print(json.dumps(result,indent=2))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('baseline');p.add_argument('old');p.add_argument('candidate');p.add_argument('out')
    a=p.parse_args();audit(a.baseline,a.old,a.candidate,a.out)
