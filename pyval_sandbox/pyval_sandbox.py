#!/usr/bin/env python3
# -*- coding: utf-8 -*-

""" pyval_sandbox.py
    Compile source sent in with stdin, returns output on stdout.
    This script alone is not safe. It is designed to be ran through 
    pypy-sandbox with input validated beforehand to block other areas of
    danger.

    You communicate with it using stdin and stdout/stderr.
    Python will print to stderr on errors,
    this script will print normal output, or expected errors, to stdout.

    Send something in by stdin and it will compile and run it.
    Warning: This script itself is unguarded, and is dangerous.
             It requires sandboxing and input validation!

    * pyval_exec._exec() is an example of raw unprotected use.
    * pyval_exec.execute() is an example of blacklisted input use.
"""

from code import InteractiveInterpreter
import sys


NAME = 'pyval_sandbox.py'
VERSION = '1.0.0'
VERSIONSTR = '{} v. {}'.format(NAME, VERSION)


# Provide user with a couple builtin modules.
whitelist_modules = ['math', 're']
# Function that returns white listed modules
modules = lambda: 'modules are: {}'.format(', '.join(whitelist_modules))
# Fixed globals()/locals() for Interpreter.
dumblocals = {'__builtins__': None,
              'modules': modules,
              }
for okmodule in whitelist_modules:
    dumblocals[okmodule] = __import__(okmodule)


class Compiler(InteractiveInterpreter):

    def runsource(self, source, filename="<input>", symbol="single"):
        """ Compile and run some source in the interpreter.
            Arguments are as for compile_command().
        """

        try:
            code = self.compile(source, filename, symbol)
        except (OverflowError, SyntaxError, ValueError) as ex:
            # Complete but buggy.
            self.send_error(ex)
            return False

        if code is None:
            # Incomplete Code.
            return True

        # Complete code, try to run it.
        try:
            self.runcode(code)
        except Exception as ex:
            self.send_error('bad code: {}'.format(ex))
        return False

    def send_error(self, exception):
        """ Send basic error msg to stdout. """
        sys.stdout.write('{}'.format(exception))


def main(args):
    """ Main entry point, expects args from sys. """
    # Read python source from stdin.
    source = sys.stdin.read()
    compiler = Compiler(locals=dumblocals)
    try:
        incomplete = compiler.runsource(source)
    except Exception as ex:
        # Send error signal.
        compiler.send_error(ex)
    else:
        # Compile was incomplete, send signal
        if incomplete:
            compiler.send_error('incomplete source.')


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
