from galaxy.util import XML
from galaxy.util.bunch import Bunch
from galaxy.app_unittest_utils.galaxy_mock import MockTrans
from galaxy.app_unittest_utils.tools_support import UsesTools
from galaxy.tools.parameters import populate_state
from galaxy.tools.parameters.basic import (
    BooleanToolParameter,
    TextToolParameter,
)
from galaxy.tools.parameters.grouping import (
    Conditional,
    Repeat,
)
from galaxy.tool_util.unittest_utils import functional_test_tool_path
from galaxy.util.unittest import TestCase


trans = Bunch(workflow_building_mode=False)


def test_populate_state():
    
    a = TextToolParameter(None, XML('<param name="a"/>'))
    b = Repeat('b')
    b.min = 0
    b.max = 1
    c = TextToolParameter(None, XML('<param name="c"/>'))
    d = Repeat('d')
    d.min = 0
    d.max = 1
    e = TextToolParameter(None, XML('<param name="e"/>'))
    f = Conditional('f')
    g = BooleanToolParameter(None, XML('<param name="g"/>'))
    h = TextToolParameter(None, XML('<param name="h"/>'))
    i = TextToolParameter(None, XML('<param name="i"/>'))
    b.inputs = dict([('c', c), ('d', d)])
    d.inputs = dict([('e', e), ('f', f)])
    f.test_param = g
    f.cases = [Bunch(value='true', inputs= { 'h': h }), Bunch(value='false', inputs= { 'i': i })]
    inputs = dict([('a',a),('b',b)])
    flat = dict([('a', 1), ('b_0|c', 2), ('b_0|d_0|e', 3), ('b_0|d_0|f|h', 4), ('b_0|d_0|f|g', True)])
    state = {}
    populate_state(trans, inputs, flat, state, check=False)
    assert state['a'] == 1
    assert state['b'][0]['c'] == 2
    assert state['b'][0]['d'][0]['e'] == 3
    assert state['b'][0]['d'][0]['f']['h'] == 4
    # now test with input_format='21.01'
    nested = {'a': 1, 'b': [{'c': 2, 'd': [{'e': 3, 'f': {'h': 4, 'g': True}}]}]}
    state_new = {}
    populate_state(trans, inputs, nested, state_new, check=False, input_format='21.01')
    assert state_new['a'] == 1
    assert state_new['b'][0]['c'] == 2
    assert state_new['b'][0]['d'][0]['e'] == 3
    assert state_new['b'][0]['d'][0]['f']['h'] == 4
