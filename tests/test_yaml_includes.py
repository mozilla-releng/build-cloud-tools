import textwrap
import unittest
import sys
import os
from cStringIO import StringIO
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../scripts'))
from yaml_includes import process_includes

class TestFreshInstances(unittest.TestCase):

    def test_no_change(self):
        self.assertEqual(process_includes({}), {})
        self.assertEqual(process_includes([]), [])
        self.assertEqual(process_includes('x'), 'x')
        complex = {
            'a': [
                {'a': 'b'},
                {'c': 'd'},
            ],
            'b': 123,
        }
        self.assertEqual(process_includes(complex), complex)

    def test_includes(self):
        input = yaml.load(StringIO(textwrap.dedent("""\
            includes:
                test-incl:
                    - a
                    - b
                test-dict:
                    a: 1
                    b: 2
            info:
                - a: b
                  c: d
                - include: test-incl
            x:
              include: test-dict
            """)))
        exp = yaml.load(StringIO(textwrap.dedent("""\
            info:
                - a: b
                  c: d
                - - a
                  - b
            x:
              a: 1
              b: 2
            """)))
        self.assertEqual(process_includes(input), exp)


    def test_recursion(self):
        input = yaml.load(StringIO(textwrap.dedent("""\
            includes:
                inc:
                  a: b
                meta-inc:
                  - include: inc
                  - include: inc
            wow:
                include: meta-inc
            """)))
        exp = yaml.load(StringIO(textwrap.dedent("""\
            wow:
              - a: b
              - a: b
            """)))
        self.assertEqual(process_includes(input), exp)
