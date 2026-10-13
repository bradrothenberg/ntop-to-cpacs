"""Small live Notebook API adapter. Uses the dedicated demo session only."""
import hashlib
import json
import math
import time
from pathlib import Path

FINAL='GBI airframe | simplified section placement v38'

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def snapshot(notebook,folder,witness_path):
    out=Path(folder);start=time.perf_counter()
    assert notebook.get_block_input_meta('Tip twist','Input')=={'type':'real','value':2.0,'units':'deg'}
    witness=json.loads(Path(witness_path).read_text())['point_m']
    if 'CPACS witness field' not in {v['id'] for v in notebook.list_variables()}:
        sec=notebook.add_section('14 CPACS round-trip verification')['id']
        with notebook.paused_updates():
            node=notebook.add_block('evaluate_field<real_field,point>',sec)['id']
            inputs=notebook.list_block_inputs(node)
            point_name=next(v['name'] for v in inputs if v['type']=='point' and not v['isReturnValue'])
            field_name=next(v['name'] for v in inputs if v['type']=='real_field' and not v['isReturnValue'])
            notebook.set_block_input(node,point_name,witness,'m')
            notebook.connect_block_property(FINAL,'scalar field',node,field_name)
            var=notebook.add_variable('CPACS witness field',node)['id']
            notebook.set_block_comment(var,'Native field at a fixed baseline wing point. This is a field witness, not a surface-distance measurement.')
            notebook.set_block_comment('Tip twist','Mapped from CPACS toolspecific/tool/ntop:bridge/ntop:tipTwistDeg. Verified demo values: 2 and 4 deg.')
            notebook.collapse_section(sec)
    state=notebook.block_state(FINAL)
    assert state['buildState']=='e_OK',state
    result={'tip_twist':notebook.get_block_input_meta('Tip twist','Input'),'field':notebook.get_block_output_meta('CPACS witness field'),'point_m':witness,'airframe_state':state}
    notebook.save_notebook_as(str(out/'baseline-working.ntop'))
    notebook.export_as_recipe(str(out/'baseline.recipe.json'))
    result.update(seconds=time.perf_counter()-start,recipe_sha256=sha(out/'baseline.recipe.json'),notebook_sha256=sha(out/'baseline-working.ntop'))
    (out/'baseline-api.json').write_text(json.dumps(result,indent=2))

def apply(notebook,config_path):
    cfg=json.loads(Path(config_path).read_text());out=Path(cfg['run_dir']);start=time.perf_counter()
    for key in ['baseline','request']:
        if sha(cfg[key+'_xml'])!=cfg[key+'_xml_sha256']:raise ValueError('CPACS XML changed after validation')
    current=notebook.get_block_input_meta('Tip twist','Input')
    assert current['units']=='deg' and current['value']==cfg['baseline_tip_twist_deg'],current
    notebook.export_as_recipe(str(out/'pre-apply.recipe.json'))
    if sha(out/'pre-apply.recipe.json')!=cfg['baseline_recipe_sha256']:raise ValueError('Live notebook differs from exported CPACS baseline')
    before=notebook.get_block_output_meta('CPACS witness field')
    target=cfg['tip_twist_deg']
    if target not in [2.0,4.0] or not math.isfinite(target):raise ValueError('Unsupported target')
    if current['value']!=target:notebook.set_block_input('Tip twist','Input',target,'deg')
    readback=notebook.get_block_input_meta('Tip twist','Input')
    assert readback['units']=='deg' and readback['value']==target,readback
    state=notebook.block_state(FINAL);assert state['buildState']=='e_OK',state
    after=notebook.get_block_output_meta('CPACS witness field')
    for section in notebook.list_sections():notebook.collapse_section(section['id'])
    notebook.save_notebook_as(str(out/'changed-working.ntop'))
    notebook.export_as_recipe(str(out/'changed.recipe.json'))
    receipt={'from_cpacs':cfg['request_xml'],'request_sha256':cfg['request_xml_sha256'],'parameter':'Tip twist','before':current,'after':readback,'field_before':before,'field_after':after,'airframe_state':state,'seconds':time.perf_counter()-start,'recipe_sha256':sha(out/'changed.recipe.json'),'notebook_sha256':sha(out/'changed-working.ntop')}
    (out/'apply-receipt.json').write_text(json.dumps(receipt,indent=2))


def reopen_verified(notebook,folder):
    """Open the verified presentation copy after guarding the live session."""
    out=Path(folder);start=time.perf_counter()
    receipt=json.loads((out/'apply-receipt.json').read_text())
    notebook.export_as_recipe(str(out/'pre-reopen.recipe.json'))
    if sha(out/'pre-reopen.recipe.json')!=receipt['recipe_sha256']:
        raise ValueError('Live notebook changed after the demo. Preserve it without reopening.')
    target=out/'GBI-changed.ntop';digest=sha(target)
    verification=json.loads((out/'verification.json').read_text())
    assert verification['passed'] and digest==verification['notebooks']['changed']['sha256']
    notebook.open_notebook(str(target))
    value=notebook.get_block_input_meta('Tip twist','Input')
    state=notebook.block_state(FINAL)
    assert value==receipt['after'] and state['buildState']=='e_OK'
    assert sha(target)==digest
    (out/'reopen-receipt.json').write_text(json.dumps({
        'path':str(target),'sha256':digest,'tip_twist':value,
        'airframe_state':state,'seconds':time.perf_counter()-start},indent=2))
