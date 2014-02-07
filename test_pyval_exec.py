#!/usr/bin/env python2
# -*- coding: utf-8 -*-

""" test_pyval_exec.py
       Unit tests for pyval_exec
"""
import os.path
import sys
import unittest

from pyval_exec import ExecBox, PYPYSANDBOX_EXE

PYPYSANDBOX_EXISTS = os.path.exists(PYPYSANDBOX_EXE)
NOSANDBOX_MSG = ('ERROR: no pypy-sandbox executable found! '
                 'pyvalbot will not work.')


class TestExec(unittest.TestCase):
    
    def test_pypysandbox_exists(self):
        """ pypy-sandbox exists """
        self.assertEqual(PYPYSANDBOX_EXISTS, True,
                         msg=NOSANDBOX_MSG)

    @unittest.skipUnless(PYPYSANDBOX_EXISTS, NOSANDBOX_MSG)
    def test_execute_output(self):
        """ execute output and safe_output() works """
        
        # Test raw output on simple command.
        ebox = ExecBox('print("okay")')
        rawoutput = ebox.execute(raw_output=True)
        self.assertEqual(rawoutput, 'okay',
                         msg=('Incorrect raw output!\n'
                              'Expecting: \'okay\'\n'
                              '      Got: {}'.format(rawoutput)))

        # Test truncating lines in safe_output()
        longcode = 'print("\\\\n".join([str(i) for i in range(55)]))'
        ebox.maxlines = 30
        safeoutput = ebox.execute(evalstr=longcode)
        truncated = ('truncated' in safeoutput) and ('lines' in safeoutput)
        self.assertTrue(truncated, msg=('safe_output() did not truncate lines:'
                                        ' {}'.format(safeoutput)))

        # Test truncating each line in safe_output()
        ebox.maxlines = 0
        ebox.maxlength = 15
        longcode = 'print("\\\\n".join([str(i) * 16 for i in range(5)]))'
        safeoutput = ebox.execute(evalstr=longcode)
        truncated = ('truncated' in safeoutput)
        self.assertTrue(truncated, msg=('safe_output() did not truncate lines:'
                                        ' {}'.format(safeoutput)))


if __name__ == '__main__':
    sys.exit(unittest.main(argv=sys.argv))
