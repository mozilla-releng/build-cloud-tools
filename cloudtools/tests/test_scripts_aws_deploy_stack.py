# ugh, I hate this.  Why can't this repo be a regular Python dist?

import mock

from nose.tools import assert_raises
from cloudtools.scripts import aws_deploy_stack

STACKS_YML = '''\
stacks:
  MyStack:
    region: us-west-1
    template: my.py
'''


def test_deploy_not_found(tmpdir):
    config = tmpdir.join('stacks.yml')
    config.write(STACKS_YML)
    with mock.patch('argparse.ArgumentParser.error') as error:
        def side_effect(msg):
            raise RuntimeError
        error.side_effect = side_effect
        assert_raises(RuntimeError, lambda:
                      aws_deploy_stack.deploy(['--config', str(config), 'NoSuchStack']))
        error.assert_called_with("Stack 'NoSuchStack' not found in " + str(config))


def test_deploy_deploy(tmpdir):
    config = tmpdir.join('stacks.yml')
    config.write(STACKS_YML)
    with mock.patch('cloudtools.scripts.aws_deploy_stack.deploy_stack') as deploy_stack:
        assert aws_deploy_stack.deploy(['--config', str(config), 'MyStack'])
        deploy_stack.assert_called_with(
            mock.ANY,
            {'region': 'us-west-1', 'template': 'my.py'},
            'MyStack')


def test_deploy_delete(tmpdir):
    config = tmpdir.join('stacks.yml')
    config.write(STACKS_YML)
    with mock.patch('cloudtools.scripts.aws_deploy_stack.delete_stack') as delete_stack:
        assert aws_deploy_stack.deploy(['--config', str(config), '--delete', 'MyStack'])
        delete_stack.assert_called_with(
            mock.ANY,
            {'region': 'us-west-1', 'template': 'my.py'},
            'MyStack')
