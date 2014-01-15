#!/usr/bin/env python2
# -*- coding: utf-8 -*-

""" pyval_exec.py
    A safer exec/eval container for pyval bot or anything else that
    might require.
    Supports a limited subset of python, mostly hiding the nasty parts
    that aren't really needed for basic teaching purposes anyway.

    Designed for python2, python3 may work but has not been tested.
    Designed mainly for use with twisted-based pyvalbot which is not
    fully python3 compatible.

    This module is designed to be testable/runnable from the cmdline.
    Run `pyval_exec.py -h` for options.
    -Christopher Welborn 2013

    Killer Strings (known to crash python or cause problems):
    (lambda fc=(lambda n: [c for c in ().__class__.__bases__[0].__subclasses__() if c.__name__ == n][0]):fc("function")(fc("code")(0,0,0,0,"KABOOM",(),(),(),"","",0,""),{})())() # noqa
"""

from tempfile import SpooledTemporaryFile
import multiprocessing
import os
import subprocess
import sys

from pyval_util import __file__ as PYVAL_FILE
from pyval_util import VERSION

NAME = 'PyValExec'
SCRIPTNAME = os.path.split(sys.argv[0])[-1]
# Location for pypy-sandbox,
# TODO: needs to look for it in other locations as well.
PYPYSANDBOX_EXE = os.path.join('/usr', 'bin', 'pypy-sandbox')


class ExecBox(object):

    """ Handles python code execution using pypy-sandbox/pyval_sandbox.
        Uses safe_output() by default for irc-friendly short output.
        Uses timed_call() for a timeout on long running code.

    """

    def __init__(self, evalstr=None):
        self.debug = False
        self.output = ''
        self.inputstr = evalstr
        # Trimmed during execute()
        self.inputtrim = None
        # Set during execute()
        self.parsed = None
        # Maximum number of seconds to run.
        self.timeout = 5
        # Maximum lines/length for safe_output()
        # Disabled if < 1.
        self.maxlines = 0
        self.maxlength = 0
        
    def __str__(self):
        return self.output

    def __repr__(self):
        return self.output
    
    def _dir(self, *args):
        """ Fake attributes for dir() NO LONGER USED """
        return [aname for aname in self._globals().keys()]

    def _globals(self, *args, **kwargs):
        """ Fake globals() NO LONGER USED """
        def fake_meth(*args, **kwargs):
            return None
        return {'fake_attribute': 1,
                'fake_method': fake_meth,
                'fake_object': object(),
                }

    def _locals(self, *args, **kwargs):
        """ Fake locals()... NO LONGER USED """
        return self._globals()

    def blacklist(self):
        """ Return a dict of black-listed strings.
            Format is: {string: message}
        """
        badstrings = {
            '__bases__': 'too complicated for this bot.',
            '__import__': 'no __import__ allowed.',
            '__subclasses__': 'too complicated for this bot.',
            'builtin': 'no builtins allowed.',
            'eval(': 'no eval() allowed.',
            'exec(': 'no exec() allowed.',
            'exit': 'no exit allowed.',
            'help(': 'no help() allowed.',
            'import': 'no imports allowed.',
            'KABOOM': 'no way.',
            'kaboom': 'no way.',
            'open': 'no open() allowed.',
            'os.': 'no os module allowed.',
            'self': 'no self allowed.',
            'super': 'no super() allowed.',
            'sys': 'no sys allowed.',
            'SystemExit': 'no SystemExit allowed.',
        }
        return badstrings

    def check_blacklist(self):
        """ Checks current inputstr for blacklisted strings. """
        badstrings = self.blacklist()
        if self.inputtrim:
            for badstr, msg in badstrings.items():
                if badstr in self.inputtrim:
                    return msg
        return None

    def check_nesting(self, inputstr):
        """ Checks a single line for ( max. """
        bad_nesting = lambda s: s.count('(') > self.nestedmax
        for line in inputstr.split('\n'):
            if bad_nesting(line):
                return True
        return False

    def _exec(self, pipesend=None):
        """ Execute actual code using pypy-sandbox/pyval_sandbox combo.
            This method does not blacklist anything. 
            It runs whatever self.inputstr is set to.
        """
        if not self.inputstr:
            self.error_return('No source.')
        # let the user use '\n' (\\n) as newlines, and '\\n' ('\\\\n') as
        # escaped newline characters.
        self.inputstr = self.inputstr.replace('\\\\n', '//n')
        self.inputstr = self.inputstr.replace('\\n', '\n')
        self.inputstr = self.inputstr.replace('//n', '\\n')
        # Add shortcut for print, ?(value)
        self.inputstr = self.inputstr.replace('?(', 'print(')
        if ('\n' in self.inputstr) and (not self.inputstr.endswith('\n')):
                # Make sure code ends with \n.
                self.inputstr = '{}\n'.format(self.inputstr)

        # Get locations for pypy-sandbox, sandbox dir, pyval_sandbox.

        parentdir = os.path.split(PYVAL_FILE)[0]
        sandboxdir = os.path.join(parentdir, 'pyval_sandbox')
        targetfile = '/tmp/pyval_sandbox.py'
        # Setup command args for Popen.
        cmdargs = [PYPYSANDBOX_EXE,
                   '--timeout={}'.format(self.timeout),
                   '--tmp={}'.format(sandboxdir),
                   targetfile]

        self.printdebug('running sandbox: {}'.format(' '.join(cmdargs)))

        # Fill temp file with user input, send it to pyval_sandbox.
        self.printdebug('_exec({})'.format(self.inputstr))
        with TempInput(self.inputstr) as stdinput:
            proc = subprocess.Popen(cmdargs,
                                    stdin=stdinput,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)

        output = self.proc_output(proc)
        if pipesend is not None:
            pipesend.send(output)
        return output

    def error_return(self, s):
        """ Set output as error str and return it. """
        self.output = self.lasterror = str(s)
        return self.output

    def execute(self, evalstr=None, raw_output=False, use_blacklist=False):
        """ Execute code inside the pypy sandbox/pyval_sandbox. """

        # Reset last error.
        self.lasterror = None

        if evalstr:
            # Option to set inputstr during execute().
            self.inputstr = evalstr

        if self.inputstr:
            # Trim input to catch bad strings.
            self.inputtrim = self.inputstr.replace(' ', '').replace('\t', '')
        else:
            # No input, no execute().
            return self.error_return('no input.')

        # Check blacklisted strings.
        if use_blacklist:
            badinputmsg = self.check_blacklist()
            if badinputmsg:
                return self.error_return(badinputmsg)

        # Actually execute it with fingers crossed.
        try:
            result = self.timed_call(self._exec, timeout=self.timeout)
            self.output = str(result)
        except TimedOut:
            self.output = 'Error: Operation timed out.'
        except Exception as ex:
            self.output = 'Error: {}'.format(ex)

        # Return the safe output version of self.output unless forced.
        if raw_output:
            return self.output
        else:
            return self.safe_output()

    def pprint(self, s):
        """ No longer used. DELETE ME. """
        s = str(s)
        if self.output:
            self.output += '\n{}'.format(s)
        else:
            self.output = s

    def printdebug(self, s):
        """ Print only if self.debug == True. """
        if self.debug:
            print('debug: {}'.format(s))

    def proc_output(self, proc):
        """ Get process output, whether its on stdout or stderr.
            Used with _exec/timed_call.
            Arguments:
                proc  : a POpen() process to get output from.
        """
        # Get stdout
        outlines = []
        for line in iter(proc.stdout.readline, ''):
            if line:
                outlines.append(line.strip('\n'))
            else:
                break
        self.printdebug('out lines:\n    {}'.format('\n    '.join(outlines)))

        # Get stderr
        errlines = []
        for line in iter(proc.stderr.readline, ''):
            if line:
                errlines.append(line.strip('\n'))
            else:
                break
        self.printdebug('err lines:\n    {}'.format('\n    '.join(errlines)))

        # Pick stdout or stderr.
        if outlines:
            output = '\n'.join(outlines)
        else:
            remove_items(errlines, ['', '\'import site\' failed'])
            if errlines:
                output = errlines[-1].strip('\n')
                if output == 'RuntimeError':
                    output = 'operation not permitted in the sandbox.'
                elif output == '[Subprocess killed by SIGIOT]':
                    output = 'crash! the interpreter choked.'
            else:
                output = 'No output.'

        if self.debug:
            debugout = '\n    '.join(output.split('\n'))
            self.printdebug('final output:\n    {}'.format(debugout))
        return output.strip('\n')

    def safe_output(self, maxlines=None, maxlength=None):
        """ Retrieves output safe for irc. """
        
        maxlines = maxlines if maxlines is not None else self.maxlines
        maxlength = maxlength if maxlength is not None else self.maxlength
        if self.lasterror:
            lines = self.lasterror.split('\n')
            msg = 'error'
        elif self.output:
            lines = self.output.split('\n')
            msg = None
        else:
            return 'No output.'

        # truncate by line count first.
        if (maxlines > 0) and (len(lines) > maxlines):
            lines = lines[:maxlines]
            lines.append('(...truncated at {} lines.)'.format(maxlines))
            # Truncate each line if maxlength is set.
            if maxlength > 0:
                trimmedlines = []
                for line in lines:
                    if len(line) > maxlength:
                        newline = '{} (..truncated)'.format(line[:maxlength])
                        trimmedlines.append(newline)
                    else:
                        trimmedlines.append(line)
                lines = trimmedlines

            # Save edited lines as a one-line string.
            oneliner = '\\n'.join(lines)
        # truncate whole output length
        elif (maxlength > 0) and (len(self.output) > maxlength):
            # Save original output as a one-line string.
            oneliner = '\\n'.join(lines)
            # Truncate at maxlength.
            oneliner = '{} (...truncated)'.format(oneliner[:maxlength])
        else:
            oneliner = '\\n'.join(lines)
        # Append error tag if any.
        if msg:
            oneliner = '{}: {}'.format(msg, oneliner)

        return oneliner

    def timed_call(self, func, args=None, kwargs=None, timeout=4):
        """ Calls a function in a separate process, joins that process
            after 'timeout' seconds. If the process timed out, then
            TimedOut is raised.

            func needs a 'pipesend' kwarg to send its result.
            timed_call() will receive the result and return it.
            example:
                def myfunc(x, pipesend=None):
                    x = x * 5
                    pipesend.send(x)

                result = timed_call(myfunc, args=[25])
                # result is now: 25
            Arguments:
                func     : Function to call in a timed thread.
            Keyword Arguments:
                args     : List of args for the function.
                kwargs   : Dict of keyword args for the function.
                timeout  : Seconds to wait before the function times out.
                           Default: 4
        """

        args = args or []
        kwargs = kwargs or {}
        piperecv, pipesend = multiprocessing.Pipe()
        kwargs.update({'pipesend': pipesend})
        execproc = multiprocessing.Process(target=func,
                                           name='ExecutionProc',
                                           args=args,
                                           kwargs=kwargs)
        execproc.start()
        execproc.join(timeout=timeout)
        if execproc.is_alive():
            execproc.terminate()
            # This is an ugly way to shutdown pypy-c-sandbox,
            # but I can't seem to make anything else work.
            # the --timeout option on pypy-sandbox isn't doing anything.
            os.system('killall pypy-c-sandbox')
            raise TimedOut('Operation timed out.')
        # Return good result.
        output = piperecv.recv()
        return output


class TempInput(object):

    def __init__(self, inputstr):
        self.inputstr = inputstr

    def __enter__(self):
        self.tempfile = SpooledTemporaryFile()
        self.tempfile.write(self.inputstr)
        self.tempfile.seek(0)
        return self.tempfile
    
    def __exit__(self, type_, value, traceback):
        self.tempfile.close()
        return False


class TimedOut(Exception):

    """ Raised on timed_call() timeout. """
    pass


def parse_args(args, argset):
    """ Returns a dict of arg flags and True/False if they are there.
        Returns a 'cleaned' version of args also.
        Example:
            args, argdict = parse_args(sys.argv[1:], (('-o', '--option')))
            # When sys.argv == '-o test -a'
            # Returns:
            # args == 'test -a' (-a was not sent to parse_args)
            # argdict == {'--option': True} (-o was sent to parse_args)

    """

    # Set default False values
    argdict = {o[1]: False for o in argset}
    argcopy = args[:]
    # Set True for found args.
    for shortopt, longopt in argset:
        if (shortopt in args) or (longopt in args):
            argdict[longopt] = True
            while shortopt in argcopy:
                argcopy.remove(shortopt)
            while longopt in argcopy:
                argcopy.remove(longopt)

    return argcopy, argdict


def print_blacklist():
    """ Prints the current black list for ExecBox """

    badstrings = ExecBox().blacklist()
    print('Blacklisted items: ({})'.format(len(badstrings)))
    for badstring, msg in badstrings.items():
        print('    {} : {}'.format(badstring.rjust(25), msg))


def print_help(reason=None, show_options=True):
    """ Prints a little help message for cmdline options. """

    usage_str = ('{name} v. {ver}\n\n'
                 '    Usage:\n'
                 '        {script} -h | -b\n'
                 '        {script} evalstring\n').format(name=NAME,
                                                         ver=VERSION,
                                                         script=SCRIPTNAME)
    optionstr = ('    Options:\n'
                 '        evalstring          : String to evaluate/execute.\n'
                 '        -b,--blacklist      : Use blacklist (testing).\n'
                 '        -d,--debug          : Prints extra info before,\n'
                 '                              during, and after execution.\n'
                 '        -h,--help           : Show this message.\n'
                 '        -p,--printblacklist : Print blacklisted strings.\n'
                 '        -r,--raw            : Show unsafe, raw output.\n')
    if reason:
        print('\n{}\n'.format(reason))
    print(usage_str)
    if show_options:
        print(optionstr)


def remove_items(lst, items):
    """ Given a list of strings, rmeoves all occurrence from a list.
    """
    for s in items:
        while s in lst:
            lst.remove(s)


def main(args):
    """ Main entry point, expects args from sys. """
    # Parse args to return an arg dict like docopt.
    args, argd = parse_args(args, (('-b', '--blacklist'),
                                   ('-h', '--help'),
                                   ('-d', '--debug'),
                                   ('-p', '--printblacklist'),
                                   ('-r', '--raw'),
                                   ('-v', '--version'),
                                   ))
    if argd['--help']:
        # Catch help arg.
        print_help()
        return 0

    elif argd['--version']:
        # Catch version arg.
        print('{} v. {}'.format(NAME, VERSION))
        return 0

    elif argd['--printblacklist']:
        # Catch blacklist printer.
        print_blacklist()
        return 0

    if args:
        # Set eval string.
        evalstr = ' '.join(args)
    else:
        print_help('No string to evaluate!', show_options=False)
        return 1

    # Get pyval_exec.debug setting from cmdline.
    debug = argd['--debug']

    print('Content: {}\n'.format(evalstr))
    e = ExecBox(evalstr)
    e.debug = debug
    try:
        output = e.execute(raw_output=argd['--raw'],
                           use_blacklist=argd['--blacklist'])
    except TimedOut:
        print('\nOperation timed out. ({}s)'.format(e.timeout))
    except Exception as ex:
        print('\nExecution Error:\n{}'.format(ex))
    else:
        # Success
        outmethod = 'raw output' if argd['--raw'] else 'safe_output()'
        print('Results ({}):\n{}'.format(outmethod, output))
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
