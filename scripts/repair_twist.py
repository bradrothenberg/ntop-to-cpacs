"""Author a C3 root transition for additional tip twist through the live API.

The source's 2-degree geometry remains exact. Additional twist starts after the
existing center-body protection gate and reaches its linear law at the existing
straight-edge transition end. All design edits use the Notebook API.
"""
import json
import time
from pathlib import Path


def install_transition(notebook):
    """Install the verified transition in the retained GBI Rev38 graph."""
    added = []
    with notebook.paused_updates():
        section = notebook.add_section('15 CPACS smooth twist transition')['id']

        def literal(name, value, units=''):
            block = notebook.add_block('core.var<real>', section)['id']
            notebook.set_block_input(block, 'Input', value, units)
            notebook.rename_variable(block, name)
            added.append(name)
            return name

        def op(name, operation, args, scalar=False):
            typ = 'real' if scalar else 'real_field'
            ident = operation + '<' + ','.join([typ] * len(args)) + '>'
            block = notebook.add_block(ident, section)['id']
            inputs = [i['name'] for i in notebook.list_block_inputs(block) if not i['isReturnValue']]
            assert len(inputs) == len(args)
            for key, source in zip(inputs, args):
                notebook.connect_block_property(source, '', block, key)
            result = notebook.add_variable(name, block)['id']
            added.append(result)
            return result

        prefix = 'CPACS | '
        baseline = literal(prefix+'reference tip twist', 2.0, 'deg')
        # These positions come from the saved Rev38 construction, in metres.
        begin = literal(prefix+'twist transition start', .219456 + .086044, 'm')
        end = op(prefix+'twist transition end', 'add', ['Straight edge transition start','Straight edge transition width'], True)
        width = op(prefix+'twist transition width', 'subtract', [end,begin], True)
        zero = literal(prefix+'zero', 0)
        one = literal(prefix+'one', 1)
        c35 = literal(prefix+'C3 coefficient 35', 35)
        cn84 = literal(prefix+'C3 coefficient -84', -84)
        c70 = literal(prefix+'C3 coefficient 70', 70)
        cn20 = literal(prefix+'C3 coefficient -20', -20)
        fraction = op(prefix+'span fraction raw', 'divide', ['Absolute span','Wing half span'])
        fraction = op(prefix+'bounded span fraction', 'min', [fraction,one])
        delta = op(prefix+'additional tip twist', 'subtract', ['Tip twist',baseline], True)
        offset = op(prefix+'root span offset', 'subtract', ['Absolute span',begin])
        t = op(prefix+'root transition coordinate', 'divide', [offset,width])
        t = op(prefix+'root transition positive', 'max', [t,zero])
        t = op(prefix+'root transition bounded', 'min', [t,one])
        t2 = op(prefix+'root transition squared', 'multiply', [t,t])
        t4 = op(prefix+'root transition fourth power', 'multiply', [t2,t2])
        poly = op(prefix+'C3 polynomial term 1', 'multiply', [t,cn20])
        poly = op(prefix+'C3 polynomial term 2', 'add', [poly,c70])
        poly = op(prefix+'C3 polynomial term 3', 'multiply', [poly,t])
        poly = op(prefix+'C3 polynomial term 4', 'add', [poly,cn84])
        poly = op(prefix+'C3 polynomial term 5', 'multiply', [poly,t])
        poly = op(prefix+'C3 polynomial term 6', 'add', [poly,c35])
        gate = op(prefix+'C3 additional twist gate', 'multiply', [t4,poly])
        base_angle = op(prefix+'reference spanwise twist', 'multiply', [fraction,baseline])
        extra = op(prefix+'additional spanwise twist', 'multiply', [fraction,delta])
        extra = op(prefix+'root protected additional twist', 'multiply', [extra,gate])
        angle = op(prefix+'smooth spanwise twist', 'add', [base_angle,extra])
        # Keep the consumed variable in place. Connect its wrapped multiply
        # inputs, since this API build refuses clearing a consumed variable.
        notebook.connect_block_property(angle, '', 'Explicit source twist', 'Operand A')
        notebook.connect_block_property(one, '', 'Explicit source twist', 'Operand B')
        notebook.set_block_comment(angle, 'Retain the 2 deg source exactly. Blend additional tip twist with a C3 gate from Y=0.3055 m to the existing straight-edge transition end (1 m). Retain the linear twist law outside this interval.')
        notebook.collapse_section(section)
    return added


def prepare(notebook, folder):
    from api_runtime import FINAL, sha
    out = Path(folder)
    start = time.perf_counter()
    assert notebook.get_block_input_meta('Tip twist', 'Input') == {'type':'real','value':2.0,'units':'deg'}
    existing = {v['id'] for v in notebook.list_variables()}
    added = []
    if 'CPACS | smooth spanwise twist' not in existing:
        added = install_transition(notebook)
    state = notebook.block_state(FINAL)
    assert state['buildState'] == 'e_OK', state
    notebook.save_notebook_as(str(out / 'GBI-demo.ntop'))
    notebook.export_as_recipe(str(out / 'prepared.recipe.json'))
    (out / 'preparation-receipt.json').write_text(json.dumps(dict(
        added_variables=added, airframe_state=state,
        seconds=time.perf_counter()-start,
        recipe_sha256=sha(out/'prepared.recipe.json'),
        notebook_sha256=sha(out/'GBI-demo.ntop'),
        transition_start_m=.3055, transition_end_m=1.0,
        reference_tip_twist_deg=2.0), indent=2))
