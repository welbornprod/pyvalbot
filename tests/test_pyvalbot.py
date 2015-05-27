#!/usr/bin/env python2
# -*- coding: utf-8 -*-

""" PyVal - Tests - PyValBot

    These files are executable, so use `nosetests --exe`.
    `py.test` will work, as will `python -m unittest`.

    -Christopher Welborn 5-27-15
"""

import unittest

# Versions that are required (tested and work-well) with PyVal..
VERSIONS = {
    'docopt': '0.6.1',
    'easysettings': '1.9.1',
    'twisted': '13.2.0',
}


def check_versions(v1, v2):
    """ Compare two version strings.
        Returns:
             -1 : if v1 < v2
              0 : if v1 == v2
              1 : if v1 > v2

        Raises ValueError on invalid version strings.
    """
    if not (v1 and v2):
        raise ValueError('Expecting 2 valid version-strings to compare.')
    elif v1 == v2:
        return 0

    return 1 if (v1 > v2) else -1


def import_failmsg(pkg, subpkgs=None, curver=None, exc=None):
    """ Return an error string for a missing package.
        List the sub-packages we were looking for.
        Report current version and required version if they differ.
    """
    reqver = VERSIONS.get(pkg, None)
    if reqver is None:
        errmsg = ['{} is not installed!'.format(pkg)]
    else:
        errmsg = ['{} >= {} is not installed!'.format(pkg, reqver)]
    if curver:
        errmsg.append('currently installed version: {}'.format(curver))

    if subpkgs:
        errmsg.extend(['    {}.{}'.format(pkg, p) for p in subpkgs])

    if exc is not None:
        errmsg.extend(['', 'Error msg: {}'.format(exc)])

    return '\n'.join(errmsg)


class TestImports(unittest.TestCase):

    """ Test imports to be sure that all third-party requirements are met. """

    def setUp(self):
        self.longMessage = True

    def test_docopt(self):
        """ docopt is avaiable """
        try:
            # Arg-parsing lib.
            import docopt
            from docopt import docopt as notused_docopt_func  # noqa
        except ImportError as ex:
            errmsg = import_failmsg('docopt', subpkgs=['docopt'], exc=ex)
            self.fail(errmsg)
        else:
            # docopt installed check version.
            curver = docopt.__version__
            reqver = VERSIONS['docopt']
            if check_versions(curver, reqver) < 0:
                errmsg = import_failmsg('docopt',
                                        subpkgs=['docopt'],
                                        curver=curver)
                self.fail(errmsg)

    def test_easysettings(self):
        """ easysettings is available """
        try:
            # Configuration lib.
            from easysettings import EasySettings  # noqa
        except ImportError as ex:
            errmsg = import_failmsg('easysettings',
                                    subpkgs=['EasySettings'],
                                    exc=ex)
            self.fail(errmsg)
        else:
            # easysettings installed, check version.
            if hasattr(EasySettings, '__version__'):
                curver = getattr(EasySettings, '__version__')
            elif hasattr(EasySettings, 'es_version'):
                es = EasySettings()
                curver = getattr(es, 'es_version')()
            else:
                self.fail('Unable to determine EasySettings version!')

            reqver = VERSIONS['easysettings']
            if check_versions(curver, reqver) < 0:

                errmsg = import_failmsg('easysettings',
                                        subpkgs=['EasySettings'],
                                        curver=curver)
                self.fail(errmsg)

    def test_twisted(self):
        """ twisted and twisted-apps are available """

        ver = VERSIONS['twisted']

        try:
            # Twisted-core installed?
            import twisted
        except ImportError as ex:
            errmsg = '\n'.join((
                'twisted >= {version} is not installed!',
                '\nError msg: {message}'
            )).format(version=ver, message=ex)
            self.fail(errmsg)

        try:
            from twisted.python import failure, log  # noqa
        except ImportError as ex:
            errmsg = '\n'.join((
                'twisted.python >= {version} is not installed!',
                'looking for:',
                '    twisted.python.failure'
                '    twisted.python.log',
                '\nError msg: {message}'
            )).format(version=ver, message=ex)
            self.fail(errmsg)

        try:
            # Net/Async stuff
            from twisted.internet import (  # noqa
                defer,
                endpoints,
                protocol,
                reactor,
                task)
        except ImportError as ex:
            errmsg = '\n'.join((
                'twisted.internet >= {version} is not installed!',
                'looking for:',
                '    twisted.internet.defer',
                '    twisted.internet.endpoints',
                '    twisted.internet.protocol',
                '    twisted.internet.reactor',
                '    twisted.internet.task',
                '\nError msg: {message}'
            )).format(version=ver, message=ex)
            self.fail(errmsg)

        try:
            # Irc stuff.
            from twisted.words.protocols import irc  # noqa
        except ImportError as ex:
            errmsg = '\n'.join((
                'twisted.words.protocols >= {version} is not installed!',
                'looking for:',
                '    twisted.words.protocols.irc',
                '\nError msg: {message}'
            )).format(version=ver, message=ex)
            self.fail(errmsg)

        # All required modules are installed, check twisted version.
        curver = twisted.__version__
        reqver = VERSIONS['twisted']
        if check_versions(curver, reqver) < 0:
            subpkgs = (
                'internet.defer',
                'internet.endpoints',
                'internet.protocol',
                'internet.reactor',
                'internet.task',
                'python.log',
                'python.failure',
                'words.protocols.irc',
            )
            errmsg = import_failmsg('twisted',
                                    subpkgs=subpkgs,
                                    curver=curver)
            self.fail(errmsg)

if __name__ == '__main__':
    unittest.main()
