#!/usr/bin/env python
# -*- coding: utf-8 -*-

""" PyVal - Tests - Commands

    These files are executable, so use `nosetests --exe`.
    `py.test` will work, as will `python -m unittest`.

    -Christopher Welborn 5-27-15
"""

import unittest
import random
from pyval_commands import AdminHandler, CommandHandler


# Only load admin help once, and save it here.
ADMINHELP = None


class NoCommand(object):

    """ Helper for get_usercmd_result, where returning None as a result from
        user/admin commands could mean several different things.
        Instead of returning None when no handler function is found,
        return NoCommand('your message')
        so the caller can recognize the difference.
    """

    def __init__(self, msg=None):
        self.msg = msg

    def __str__(self):
        return str(self.msg)

    def __repr__(self):
        return str(self.msg)


class TestCommandFuncs(unittest.TestCase):

    """ Test basic functionality of pyval_commands.
        This includes AdminHandler, CommandHandler, and CommandFuncs.
    """

    def cmd_str(self, cmd):
        """ Ensure a command starts with the command character. """
        if not cmd.startswith(self.cmdhandler.admin.cmdchar):
            return ''.join((
                self.cmdhandler.admin.cmdchar,
                cmd
            ))
        return cmd

    def fail_nocmd(self, nocmd):
        """ Fail due to NoCommand. Pass a NoCommand in. """

        self.fail('No cmd handler for: {}'.format(nocmd))

    def get_cmdfunc(self, cmdhandler, userinput, asadmin=False):
        """ Receives input like it came from chat, returns handler func. """
        if not cmdhandler:
            self.fail('No cmdhandler set in get_cmdfunc!')

        cmd, sep, args = userinput.partition(' ')
        usernick = 'testadmin' if asadmin else 'testuser'
        cmdfunc = cmdhandler.parse_data(usernick, '#channel', userinput)
        if cmdfunc:
            return cmdfunc

        return NoCommand(userinput)

    def get_usercmd_result(self, cmdhandler, userinput, asadmin=False):
        """ Receives input like it came from chat, returns cmd output. """
        if not cmdhandler:
            self.fail('No cmdhandler set in get_usercmd_result!')

        cmdfunc = self.get_cmdfunc(cmdhandler, userinput, asadmin=asadmin)
        if isinstance(cmdfunc, NoCommand):
            # No command was found for this input.
            return cmdfunc

        cmd, sep, args = userinput.partition(' ')
        usernick = 'testadmin' if asadmin else 'testuser'

        return cmdfunc(args, nick=usernick)

    def random_paste_str(self):
        """ Return a random string of characters that can be appended
            to paste data, so that the server doesn't return an
            error ('same as last paste').
        """
        return ''.join(chr(random.randint(97, 122)) for i in range(5))

    def setUp(self):
        """ Setup each test with an admin/command handler """
        global ADMINHELP
        if ADMINHELP:
            self.adminhandler = AdminHandler(help_info=ADMINHELP)
        else:
            self.adminhandler = AdminHandler()
            ADMINHELP = self.adminhandler.help_info
        self.adminhandler.nickname = 'testnick'
        self.adminhandler.admins.add('testadmin')
        self.cmdhandler = CommandHandler(adminhandler=self.adminhandler)

    def test_admin_getattr(self):
        """ admin command getattr works """

        self.cmdhandler.admin.blacklist = True

        cmdresult = self.get_usercmd_result(
            self.cmdhandler,
            self.cmd_str('getattr admin.blacklist'),
            asadmin=True)
        if isinstance(cmdresult, NoCommand):
            self.fail_nocmd(cmdresult)

        self.assertEqual(cmdresult, 'admin.blacklist = True',
                         msg='Failed to get attribute')

    def test_admin_setattr(self):
        """ admin command setattr works """

        self.cmdhandler.admin.blacklist = False
        cmd = self.cmd_str('setattr')
        args = 'admin.blacklist True'
        userinput = '{} {}'.format(cmd, args)
        setattrfunc = self.get_cmdfunc(
            self.cmdhandler,
            userinput,
            asadmin=True)

        if isinstance(setattrfunc, NoCommand):
            self.fail_nocmd(setattrfunc)

        setattrfunc(args, nick='testadmin')
        self.assertEqual(
            self.cmdhandler.admin.blacklist,
            True,
            msg='Failed to set attribute')

    def test_print_topastebin(self):
        """ test print_topastebin() """

        pastebin = self.cmdhandler.commands.print_topastebin

        noneresult = pastebin('', '')
        self.assertIsNone(noneresult, msg='empty arg should produce None')

        pastebinurl = pastebin(
            '<pyvaltest> query',
            '<pyvaltest> valid string ({})'.format(self.random_paste_str())
        )
        self.assertIsNotNone(
            pastebinurl,
            msg=('print_topastebin() failed to give url: \'{}\''.format(
                pastebinurl)
            )
        )
        print('test_print_topastebin - Url: {}'.format(pastebinurl))

if __name__ == '__main__':
    unittest.main()
