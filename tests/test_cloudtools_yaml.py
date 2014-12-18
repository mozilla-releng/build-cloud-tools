import textwrap
from cStringIO import StringIO
import yaml

from cloudtools.yaml import process_includes


def test_no_change():
    assert process_includes({}) == {}
    assert process_includes([]) == []
    assert process_includes("x") == "x"
    complex = {
        'a': [
            {'a': 'b'},
            {'c': 'd'},
        ],
        'b': 123,
    }
    assert process_includes(complex) == complex


def test_includes():
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
    assert process_includes(input) == exp


def test_recursion():
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
    assert process_includes(input) == exp
