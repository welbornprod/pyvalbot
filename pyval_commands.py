#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""pyval_commands.py

    Handles commands for pyvalbot.py, separate from the rest of the other
    irc bot functionality to prevent mess.

    -Christopher Welborn

"""

from datetime import datetime
import json
import os
import re
from sys import version as sysversion
import urllib

from easysettings import EasySettings
from twisted.python import log

from pyval_exec import ExecBox, TimedOut
from pyval_util import (
    NAME,
    VERSION,
    get_args,
    humantime,
    timefromsecs)

ADMINFILE = '{}_admins.lst'.format(NAME.lower().replace(' ', '-'))
BANFILE = '{}_banned.lst'.format(NAME.lower().replace(' ', '-'))
HELPFILE = '{}_help.json'.format(NAME.lower().replace(' ', '-'))

# Parses common string for True/False values.
true_values = ('true', 'on', 'yes', '1')
false_values = ('false', 'off', 'no', '0')
bool_values = list(true_values)
bool_values.extend(false_values)
boolpat = re.compile('\[({})\]'.format('|'.join(bool_values)), re.IGNORECASE)
intpat = re.compile('\[(\d+)\]')
parse_true = lambda s: s.lower() in true_values
parse_false = lambda s: s.lower() in false_values
parse_bool = lambda s: parse_true(s[1:-1]) if boolpat.match(s) else None


def block_dict_val(data, blockedlst, value=None):
    """ Block certain dict/config values from being seen.
        Replaces a keys value if any strings in blockedlst are found.
        Strings are found if they start or end with any string in the
        blocked list.
        Values are replaces with the 'value' argument.

        This is meant to be used with string representations of dicts.
        The original data is unchanged, the changed version is returned.

        Arguments:
            data  : dict or EasySetting instance.
            blockedlst  : Tuple of strings, if found in a key it is blocked.
            value       : New value for blocked items. Defaults to: '********'

    """
    if isinstance(data, dict):
        d = data
    elif isinstance(data, EasySettings):
        d = data.settings
    else:
        # Not the correct type to be blocked.
        return data

    if value is None:
        # Default value for blocked vlaues.
        value = '********'

    # Block all 'password/pw' values from dict/settings...
    newdata = {}
    for k, v in d.items():
        keystr = str(k)
        if keystr.startswith(blockedlst) or keystr.endswith(blockedlst):
            newdata[k] = value
        else:
            newdata[k] = v

    return newdata


def load_json_object(filename):
    """ Loads an object from a json file,
        returns {} on failure.
    """
    try:
        with open(filename, 'r') as fjson:
            rawjson = fjson.read()
    except (OSError, IOError) as exio:
        log.msg('\nError loading json from: {}\n{}'.format(filename, exio))
        return {}

    try:
        jsonobj = json.loads(rawjson)
    except Exception as ex:
        log.msg('\nError parsing json from: {}\n{}'.format(filename, ex))
        return {}

    return jsonobj


def pasteit(data):
    """ Submit a paste to welbornprod.com/paste ...
        data should be a dict with at least:
        {'content': <paste content>}

        with optional settings:
        {'author': 'name',
         'title': 'paste title',
         'content': 'this is content',
         'private': True,
         'onhold': True,
         }
    """
    pasteurl = 'http://welbornprod.com/paste/api/submit'
    try:
        newdata = urllib.urlencode(data)
    except Exception as exenc:
        log.msg('Unable to encode paste data: {}\n{}'.format(data, exenc))
        return None
    try:
        con = urllib.urlopen(pasteurl, data=newdata)
    except Exception as exopen:
        log.msg('Unable to open paste url: {}\n{}'.format(pasteurl, exopen))
        return None
    try:
        resp = con.read()
    except Exception as exread:
        log.msg('Unable to read paste response from '
                '{}\n{}'.format(pasteurl, exread))
        return None
    try:
        respdata = json.loads(resp)
    except Exception as exjson:
        log.msg('Unable to decode JSON from {}\n{}'.format(pasteurl, exjson))
        return None

    status = respdata.get('status', 'error')
    if status == 'error':
        # Server responded with json error response.
        errmsg = respdata.get('message', '<no msg>')
        log.msg('Paste site responded with error: {}'.format(errmsg))
        # Little something for the unit tests..
        # The error is most likely 'too many pastes in a row',
        # just return the error msg so the test will pass and be printed.
        if data.get('author', '').startswith('<pyvaltest>'):
            return 'TESTERROR: {}'.format(errmsg)
        # Paste site errored, no url given to the chat user.
        return None

    # Good response.
    suburl = respdata.get('url', None)
    if suburl:
        finalurl = 'http://welbornprod.com{}'.format(suburl)
        return finalurl

    # No url found to respond with.
    return None


class AdminHandler(object):

    """ Handles admin functions like bans/admins/settings. """

    def __init__(self, help_info=None):
        # These are overwritten by the PyValIRCProtocol()
        self.quit = None
        self.sendLine = None
        self.ctcpMakeQuery = None
        self.do_action = None
        self.handlinglock = None

        # Set startup time.
        self.starttime = datetime.now()
        # Current channels the bot is in.
        self.channels = []

        # These are all set by PyValIRCProtocol after config is loaded.
        self.argd = {}
        self.cmdchar = '*'
        self.config = {}
        self.nickname = None
        self.topicfmt = ''
        self.topicmsg = ''
        self.noheartbeatlog = False

        # Whether or not to use PyVal.ExecBoxs blacklist.
        self.blacklist = False
        # Monitoring options. (privmsgs, all recvline, include ips)
        self.monitor = False
        self.monitordata = False
        self.monitorips = False
        # If this is true, privmsgs are forwarded to the admins.
        self.forwardmsgs = True
        # List of admins/banned
        self.admins = self.admins_load()
        self.banned = self.ban_load()
        self.banned_warned = {}
        # Time of last response sent (rate-limiting/bans)
        self.last_handle = None
        # The msg that was last sent.
        self.last_msg = None
        # Last nick responded to (rate-limiting/bans)
        self.last_nick = None
        # Last command handled (dupe-blocking/rate-limiting)
        self.last_command = None
        # Whether or not response rate-limiting is enabled.
        self.limit_rate = True
        # Time in between commands required for a user.
        # If the user sends multiple commands before this limit is reached,
        # their 'ban-warned' count increases.
        self.msg_timelimit = 3
        # Number of 'ban-warns' before perma-banning a nick.
        self.banwarn_limit = 3
        # Current load, and lock required to change its value.
        self.handlingcount = 0
        self.handlinglock = None
        # Number of handled requests
        self.handled = 0
        # Help dict {'user': {'cmd': {'args': null, {'desc': 'mycommand'}}},
        #            'admin': <same as 'user' key> }
        # Tests can pass a preloaded help_info in.
        self.help_info = help_info if help_info else self.load_help()
        if self.help_info:
            if (not help_info):
                # Print a message if help was loaded from file
                log.msg('Help info file loaded: {}'.format(HELPFILE))
        else:
            log.msg('No help commands will be available.')

    def admins_add(self, nick):
        """ Add an admin to the list and save it. """
        if nick in self.admins:
            return 'already an admin: {}'.format(nick)

        self.admins.add(nick)
        if self.admins_save():
            return 'added admin: {}'.format(nick)
        else:
            return 'unable to save admins, {} is not permanent.'.format(nick)

    def admins_list(self):
        """ List admins. """
        return 'admins: {}'.format(', '.join(self.admins))

    def admins_load(self):
        """ Load admins from list. """

        # admin is cj until the admins file says otherwise.
        admins = {'cjwelborn'}

        if not os.path.exists(ADMINFILE):
            log.msg('No admins list, defaults will be used.')
            return admins

        try:
            with open(ADMINFILE) as fread:
                admins = set(l.strip() for l in fread.readlines())
        except EnvironmentError as ex:
            log.msg('Unable to load admins list:\n{}'.format(ex))
            pass

        return admins

    def admins_remove(self, nick):
        """ Remove an admin from the list and save it. """
        if nick in self.admins:
            self.admins.remove(nick)
            if self.admins_save():
                msg = 'removed admin: {nick}'
            else:
                msg = 'unable to save admins, {nick} will persist on restart'
            return msg.format(nick=nick)

        return 'not an admin: {}'.format(nick)

    def admins_save(self):
        """ Save current admins list. """
        try:
            with open(ADMINFILE, 'w') as f:
                f.write('\n'.join(sorted(self.admins)))
                f.write('\n')
                return True
        except (IOError, OSError) as ex:
            log.msg('Error saving admin list:\n{}'.format(ex))
            return False

    def ban_add(self, nick, permaban=False):
        """ Add a warning to a nick, after 3 warnings ban them for good. """

        if nick in self.admins:
            # Admins wont be banned or counted.
            return ''

        if permaban:
            # Straight to permaban. (better to use ban_addperma now)
            self.ban_addperma(nick)
            return 'no more.'

        # Auto banner.
        if nick in self.banned_warned.keys():
            # Increment the warning count.
            self.banned_warned[nick]['last'] = datetime.now()
            self.banned_warned[nick]['count'] += 1
            newcount = self.banned_warned[nick]['count']
            if newcount == self.banwarn_limit:
                # No more warnigns, permaban.
                self.banned.append(nick)
                self.ban_save()
                return 'no more.'
            elif newcount == (self.banwarn_limit - 1):
                # last warning.
                return 'really, slow down with your commands.'

        else:
            # First warning.
            self.banned_warned[nick] = {'last': datetime.now(), 'count': 1}

        # Warning count increased, not last warning or permaban yet.
        return 'slow down with your commands.'

    def ban_addperma(self, nick):
        """ Add a permanently banned nick. """

        banned = []
        if isinstance(nick, (list, tuple)):
            for n in nick:
                if (n not in self.admins) and (n not in self.banned):
                    self.banned.append(n)
                    banned.append(n)
        else:
            if (nick not in self.admins) and (nick not in self.banned):
                self.banned.append(nick)
                banned.append(n)

        saved = self.ban_save() if banned else False
        if saved:
            return banned
        else:
            return []

    def ban_load(self):
        """ Load banned nicks if any are available. """

        banned = []
        if not os.path.isfile(BANFILE):
            return banned

        try:
            with open(BANFILE) as fread:
                banned = [l.strip('\n') for l in fread.readlines()]
        except (IOError, OSError) as exos:
            log.msg('Unable to load banned file: {}\n{}'.format(BANFILE, exos))
        return banned

    def ban_remove(self, nicklst):
        """ Remove nicks from the banned list. """
        if not nicklst:
            return []

        removed = []
        for nick in nicklst:
            if nick in self.banned:
                while nick in self.banned:
                    self.banned.remove(nick)
                # Reset ban warnings.
                if nick in self.banned_warned.keys():
                    self.banned_warned[nick] = {'last': datetime.now(),
                                                'count': 0}
                removed.append(nick)

        saved = self.ban_save()
        if saved:
            return removed
        else:
            return []

    def ban_save(self):
        """ Load perma-banned list. """
        try:
            with open(BANFILE, 'w') as f:
                f.write('\n'.join(self.banned))
                return True
        except (IOError, OSError) as exos:
            log.msg('Unable to save banned file: {}\n{}'.format(BANFILE, exos))
        return False

    def get_uptime(self):
        """ Return the current uptime in seconds for this instance.
            Further processing can be done with pyval_util.timefromsecs().
        """
        return int((datetime.now() - self.starttime).total_seconds())

    def handling_decrease(self):
        if self.handlingcount > 0:
            self.handlinglock.acquire()
            self.handlingcount -= 1
            self.handlinglock.release()

    def handling_increase(self):
        self.handlinglock.acquire()
        self.handlingcount += 1
        self.handlinglock.release()

    def identify(self, pw):
        """ Send an IDENTIFY msg to NickServ. """
        log.msg('Identifying with nickserv...')
        if not pw:
            return 'No password supplied for IDENTIFY.'

        self.sendLine('PRIVMSG NickServ :IDENTIFY '
                      '{} {}'.format(self.nickname, pw))
        return None

    def load_help(self):
        """ Load help from json file. """

        return load_json_object(HELPFILE)

    def op_request(self, channel=None, nick=None, reverse=False):
        """ op or deop a user through ChanServ.
            Arguments:
                channel  : Default channel is '##<self.nickname>'.
                nick     : Default user is the bot itself.
                reverse  : Use DEOP instead of OP.

        """
        chanservcmd = (
            'deop' if reverse else 'op',
            channel or '##{}'.format(self.nickname),
            nick or self.nickname
        )
        self.sendmsg('ChanServ', ' '.join(chanservcmd))

    def save_config(self):
        """ Save config settings to disk.
            Returns the number of items changed/saved.
            Returns None on failure.
        """
        if not hasattr(self, 'argd'):
            log.msg('Unable to save config, admin.argd not found!')
            return None
        if not hasattr(self, 'config'):
            log.msg('Unable to save config, admin.config not found!')
            return None

        changecnt = 0
        for argopt, argval in self.argd.items():
            configopt = argopt.strip('--')
            configval = self.config.get(configopt, default=None)
            if argval and (argval != configval):
                # New config option.
                self.config.set(configopt, argval)
                changecnt += 1

        if changecnt > 0:
            if self.config.save():
                # Save was a success.
                return changecnt
            # Bad save.
            return None
        else:
            # No items to save.
            return 0

    def sendmsg_tochans(self, msgtext):
        """ Send the same message to all channels pyvalbot is in. """
        for chan in self.channels:
            self.sendmsg(chan, msgtext)

    def sendmsg_toadmins(self, msgtext, fromnick=None):
        """ Sends a private message to all admins as pyvalbot.
            Can be disabled by settings self.forwardsmsgs = False
            If fromnick is set, it will be included in the message.
        """
        if fromnick:
            msg = '{}: {}'.format(fromnick, msgtext)
        else:
            msg = '{}'.format(msgtext)

        if self.forwardmsgs:
            for adminnick in self.admins:
                # Don't send the admin's own message to them.
                if fromnick != adminnick:
                    self.sendmsg(adminnick, msg)

    def sendmsg(self, target, msgtext):
        """ Send a private message as pyvalbot.
            This is a shortcut to: self.sendLine('PRIVMSG target: msgtext')
        """
        if (self.last_nick, self.last_msg) != (target, msgtext):
            self.sendLine('PRIVMSG {} :{}'.format(target, msgtext))
            self.last_nick = target
            self.last_msg = msgtext

    def set_topic(self, topic=None, channel=None):
        """ Try to set the bot's channel topic.
            If no topic is given, self.topicmsg is used.
        """
        self.sendLine('TOPIC {chan} :{msg}'.format(
            chan=channel or '##{}'.format(self.nickname),
            msg=topic or self.topicmsg))


class CommandHandler(object):

    """ Handles commands/messages sent from pyvalbot.py """

    def __init__(self, **kwargs):
        """ Keyword Arguments:
                ** These are required. **
                adminhandler  : Shared AdminHandler() for these functions.
                defer_        : Shared defer module.
                reactor_      : Shared reactor module.
                task_         : Shared task module.
        """
        self.admin = kwargs.get('adminhandler', None)
        self.defer = kwargs.get('defer_', None)
        self.reactor = kwargs.get('reactor_', None)
        self.task = kwargs.get('task_', None)
        self.commands = CommandFuncs(defer_=self.defer,
                                     reactor_=self.reactor,
                                     task_=self.task,
                                     adminhandler=self.admin)

    def parse_command(self, msg, username=None):
        """ Parse a message, return corresponding command function if found,
            otherwise, return None.
        """
        command, sep, rest = msg.lstrip(self.admin.cmdchar).partition(' ')
        # Retrieve function related to this command.
        func = getattr(self.commands, 'cmd_' + command, None)
        # Check admin command.
        if username and (username in self.admin.admins):
            adminfunc = getattr(self.commands, 'admin_' + command, None)
            if adminfunc:
                # return callable admin command.
                return adminfunc

        # Return callable function for command.
        return func

    def parse_data(self, user, channel, msg):
        """ Parse raw data from privmsg().
            Logs messages if 'monitor' or 'monitorips' is set.
            Returns parse_command(msg) if it is a command,
            otherwise it returns None.

            Arguments:
                user        : (str) - user string (full nick!host format).
                channel     : (str) - channel where the msg came from.
                msg         : (str) - content of the message.
        """

        # Parse irc name, ip address from user.
        username, ipstr = self.parse_username(user)
        # Monitor incoming messages?
        if self.admin.monitor:
            # Include ip address in print info?
            if self.admin.monitorips:
                userstr = '{} ({})'.format(username, ipstr)
            else:
                userstr = username
            log.msg('[{}]\t{}:\t{}'.format(channel, userstr, msg))
        elif (channel == self.admin.nickname):
            if not msg.startswith(self.admin.cmdchar):
                # normal private msg sent directly to pyval.
                log.msg('Message from {}: {}'.format(username, msg))
                self.admin.sendmsg_toadmins(msg, fromnick=username)

        # Handle message
        if msg.startswith(self.admin.cmdchar):
            return self.parse_command(msg, username=username)

        # Not a command.
        return None

    def parse_username(self, rawuser):
        """ Parse a raw username into (ircname, ipaddress),
            returns (rawuser, '') on failure.
        """
        if '!' in rawuser:
            splituser = rawuser.split('!')
            username = splituser[0].strip()
            rawip = splituser[1]
            if '@' in rawip:
                ipaddress = rawip.split('@')[1]
            else:
                ipaddress = rawip
        else:
            username = rawuser
            ipaddress = ''
        return (username, ipaddress)


class CommandFuncs(object):

    """ Holds only the command-handling functions themselves. """

    def __init__(self, **kwargs):
        """ Keyword Arguments:
                ** These are required. **
                adminhandler  : Shared AdminHandler() for these functions.
                defer_        : Shared defer module.
                reactor_      : Shared reactor module.
                task_         : Shared task module.
        """
        self.admin = kwargs.get('adminhandler', None)
        self.defer = kwargs.get('defer_', None)
        self.reactor = kwargs.get('reactor_', None)
        self.task = kwargs.get('task_', None)

    # Commands (must begin with cmd)
    def admin_adminadd(self, rest, nick=None):
        """ Add an admin to the list. """
        return self.admin.admins_add(rest)

    def admin_adminhelp(self, rest, nick=None):
        """ Build list of admin commands. """
        self.admin.sendmsg(
            nick,
            self.get_help(role='admin', cmdname=rest, usernick=None))

    def admin_adminlist(self, rest, nick=None):
        """ List current admins. """
        return self.admin.admins_list()

    def admin_adminmsg(self, rest, nick=None):
        """ Send a message to all pyvalbot admins. """
        if not rest:
            return 'Must give a message to send!'

        self.admin.sendmsg_toadmins(rest)
        return None

    def admin_adminreload(self, rest, nick=None):
        """ Reloads admin list for IRCClient. """
        # Really need to reorganize things, this is getting ridiculous.
        self.admin.admins_load()
        return 'admins loaded.'

    def admin_adminrem(self, rest, nick=None):
        """ Alias for admin_adminremove """
        return self.admin_adminremove(rest)

    def admin_adminremove(self, rest, nick=None):
        """ Remove an admin from the handlers list. """
        return self.admin.admins_remove(rest)

    def admin_ban(self, rest, nick=None):
        """ Ban a nick. """

        if not rest:
            return 'usage: {}ban <nick>'.format(self.admin.cmdchar)

        nicks = rest.split(' ')
        alreadybanned = [n for n in nicks if n in self.admin.banned]

        banned = self.admin.ban_addperma(nicks)
        notbanned = [n for n in nicks
                     if (n not in banned) and (n not in alreadybanned)]

        msg = []
        if banned:
            msg.append('banned: {}'.format(', '.join(banned)))

        if alreadybanned:
            msg.append('already banned: '
                       '{}'.format(', '.join(alreadybanned)))
        if notbanned:
            msg.append('unable to ban: {}'.format(', '.join(notbanned)))
        return ', '.join(msg)

    def admin_banned(self, rest, nick=None):
        """ list banned. """
        banned = ', '.join(sorted(self.admin.banned))
        if banned:
            return 'currently banned: {}'.format(banned)
        else:
            return 'nobody is banned.'

    def admin_banwarns(self, rest, nick=None):
        """ list ban warnings. """

        banwarns = []
        for warnednick in sorted(self.admin.banned_warned.keys()):
            count = self.admin.banned_warned[warnednick]['count']
            banwarns.append('{}: {}'.format(warnednick, count))

        if banwarns:
            return '[{}]'.format(']['.join(banwarns))
        else:
            return 'no ban warnings issued.'

    def admin_blacklist(self, rest, nick=None):
        """ Toggle the blacklist option """
        if rest == '?' or (not rest):
            # current status will be printed at the bottom of this func.
            pass
        elif rest == '-':
            # Toggle current value.
            self.admin.blacklist = False if self.admin.blacklist else True
        else:
            if parse_true(rest):
                self.admin.blacklist = True
            elif parse_false(rest):
                self.admin.blacklist = False
            else:
                return 'invalid value for blacklist option (true/false).'
        return 'blacklist enabled: {}'.format(self.admin.blacklist)

    def admin_channels(self, rest, nick=None):
        """ Return a list of current channels for the bot. """
        return 'current channels: {}'.format(', '.join(self.admin.channels))

    def admin_chanmsg(self, rest, nick=None):
        """ Send a msg to all channels pyvalbot is in. """
        if not rest:
            return 'Must give a message to send!'

        self.admin.sendmsg_tochans(rest)
        return None

    def admin_configget(self, rest, nick=None):
        """ Retrieve value for a config setting. """
        if not rest:
            return 'usage: {}configget <option>'.format(self.admin.cmdchar)

        val = self.admin.config.get(rest, '__NOTSET__')
        if val == '__NOTSET__':
            return '{}: <not set>'.format(rest)

        # Filter some config settings (dont want passwords sent to chat)
        blocked = ('pw', 'password')
        if rest.startswith(blocked) or rest.endswith(blocked):
            return '{}: ********'.format(rest)

        # Value is ok to send to chat.
        return '{}: {}'.format(rest, val)

    def admin_configlist(self, rest, nick=None):
        """ List current config. Filters certain items from chat. """

        return self.admin_getattr('admin.config')

    def admin_configsave(self, rest, nick=None):
        """ Save the current config (cmdline options) to disk. """
        saved = self.admin.save_config()
        if saved is None:
            return 'unable to save config.'

        return 'saved {} new config settings.'.format(saved)

    def admin_configset(self, rest, nick=None):
        """ Set value for a config setting. """

        usagestr = 'usage: {}configset <option> <value>'.format(
            self.admin.cmdchar
        )
        if not rest:
            return usagestr

        args = rest.split(' ')
        if len(args) < 2:
            # Not enough args.
            return usagestr

        opt, val = args[0], ' '.join(args[1:])

        if val == '-':
            # Have to pass - to blank-out config settings.
            val = None
        elif boolpat.match(val):
            # Have a valid bool config value, use it.
            val = parse_true(val[1:-1])
        elif intpat.match(val):
            try:
                val = int(val[1:-1])
            except (TypeError, ValueError):
                return 'bad int value: {}'.format(val[1:-1])

        if self.admin.config.setsave(opt, val):
            return 'saved {}: {}'.format(opt, val)

        # Failure.
        return 'unable to save: {}: {}'.format(opt, val)

    def admin_deop(self, rest, nick=None):
        """ Request deop from ChanServ on behalf of the bot. """
        if not rest:
            self.admin.op_request(reverse=True)
            return None

        chan, _, nick = rest.partition(' ')
        if not chan.startswith('#'):
            # No channel given, request ops for nick in ##<botnick>
            nick = chan
            chan = None

        self.admin.op_request(channel=chan, nick=nick, reverse=True)

    def admin_deopme(self, rest, nick=None):
        """ Request deop from the bot (if the bot is an op itself) """
        chan = rest if rest.startswith('#') else None
        self.admin.op_request(channel=chan, nick=nick, reverse=True)

    def admin_getattr(self, rest, nick=None):
        """ Return value for attribute. """
        if not rest:
            return 'usage: {}getattr <attribute>'.format(self.admin.cmdchar)

        parent, attrname, attrval = self.parse_attrstr(rest)
        if attrname is None:
            return 'no attribute named: {}'.format(rest)

        # Block certain config attributes from being printed.
        if ('password' in attrname) or attrname.endswith('pw'):
            attrval = '********'
        elif 'config' in rest:
            # Block password config from chat.
            attrval = block_dict_val(attrval, ('password', 'pw'))

        attrval = str(attrval)
        if len(attrval) > 250:
            attrval = '{} ...truncated'.format(attrval[:250])
        return '{} = {}'.format(rest, attrval)

    def admin_id(self, rest, nick=None):
        """ Shortcut for admin_identify """
        return self.admin.identify(rest)

    def admin_identify(self, rest, nick=None):
        """ Identify with nickserv, expects !identify password """

        return self.admin.identify(rest)

    def admin_join(self, rest, nick=None):
        """ Join a channel as pyval. """
        if ',' in rest:
            # multiple channel names.
            chans = [s.strip() for s in rest.split(',')]
        else:
            # single channel.
            chans = [rest]

        alreadyin = []
        for chan in chans:
            if not chan.startswith('#'):
                chan = '#{}'.format(chan)

            if chan in self.admin.channels:
                # already in that channel, send a msg in a moment.
                alreadyin.append(chan)
            else:
                log.msg('Joining: {}'.format(chan))
                self.admin.sendLine('JOIN {}'.format(chan))

            if alreadyin:
                chanstr = 'channel' if len(alreadyin) == 1 else 'channels'
                return 'Already in {}: {}'.format(chanstr,
                                                  ', '.join(alreadyin))
        # Joined channels, no response is sent
        # (you can look at the log/stdout)
        return None

    def admin_limitrate(self, rest, nick=None):
        """ Toggle limit_rate """
        if rest == '?' or (not rest):
            # current status will be printed at the bottom of this func.
            pass
        elif rest == '-':
            # Toggle current value.
            self.admin.limit_rate = False if self.admin.limit_rate else True
        else:
            if parse_true(rest):
                self.admin.limit_rate = True
            elif parse_false(rest):
                self.admin.limit_rate = False
            else:
                return 'invalid value for limitrate option (true/false).'
        return 'limitrate enabled: {}'.format(self.admin.limit_rate)

    def admin_me(self, rest, nick=None):
        """ Perform an irc action, /ME <channel> <text> """
        cmdargs = rest.split()
        if len(cmdargs) < 2:
            return 'usage: {}me <channel> <text>'.format(self.admin.cmdchar)
        channel, text = cmdargs[0], ' '.join(cmdargs[1:])
        if not channel.startswith('#'):
            channel = '#{}'.format(channel)
        if channel not in self.admin.channels:
            return 'not in that channel: {}'.format(channel)

        self.admin.do_action(channel, text)
        return None

    def admin_msg(self, rest, nick=None):
        """ Send a private msg, expects !msg nick/channel message """

        msgparts = rest.split()
        if len(msgparts) < 2:
            return 'need target and message.'
        target = msgparts[0]
        msgtext = ' '.join(msgparts[1:])
        self.admin.sendmsg(target, msgtext)
        return None

    def admin_op(self, rest, nick=None):
        """ Request ops from ChanServ on behalf of the bot. """
        if not rest:
            self.admin.op_request()
            return None

        chan, _, nick = rest.partition(' ')
        if not chan.startswith('#'):
            # No channel given, request ops for nick in ##<botnick>
            nick = chan
            chan = None

        self.admin.op_request(channel=chan, nick=nick)

    def admin_opme(self, rest, nick=None):
        """ Request ops from the bot (if the bot is an op itself) """
        chan = rest if rest.startswith('#') else None
        self.admin.op_request(channel=chan, nick=nick)

    def admin_part(self, rest, nick=None):
        """ Leave a channel as pyval. """
        if ',' in rest:
            # multichannel
            chans = [s.strip() for s in rest.split(',')]
        else:
            # single channel.
            chans = [rest]

        notinchans = []
        for chan in chans:
            if not chan.startswith('#'):
                chan = '#{}'.format(chan)

            if chan in self.admin.channels:
                log.msg('Parting from: {}'.format(chan))
                self.admin.sendLine('PART {}'.format(chan))
            else:
                # not in that channel, send a msg in a moment.
                notinchans.append(chan)

        if notinchans:
            chanstr = 'channel' if len(notinchans) == 1 else 'channel'
            return 'Not in {}: {}'.format(chanstr, ', '.join(notinchans))

        # parted channel(s) no response is sent.
        # (you can check the log/stdout)
        return None

    def admin_partall(self, rest, nick=None):
        """ Part all current channels.
            The only way to re-join is to send a private msg to pyval,
            or shutdown and restart.
        """

        return self.admin_part(','.join(self.admin.channels))

    def admin_say(self, rest, nick=None):
        """ Send chat message back to person. """
        if not rest:
            return None
        log.msg('Saying: {}'.format(rest))
        return rest

    def admin_sendline(self, rest, nick=None):
        """ Send raw line as pyval. """
        if rest:
            log.msg('Sending line: {}'.format(rest))
            self.admin.sendLine(rest)
        return None

    def admin_setattr(self, rest, nick=None):
        """ Set an attribute to self or children of self by string.
            Example:
                self.admin_setattr('admin.blacklist True')
            Automatically converts types from string so
            admin_setattr('attribute True')
            will set attribute to bool(True)
            ...special handling is needed for False and other values.

        """
        usagestr = 'usage: setattr <attribute> <val>'
        if not rest:
            return usagestr

        # Parse args
        attrstr, _, valstr = rest.partition(' ')
        if not valstr:
            return 'No arguments, {}'.format(usagestr)

        # Find old value, final attrname, and parent of old value.
        parent, oldname, oldval = self.parse_attrstr(attrstr)
        if oldname is None:
            return 'no attribute named: {}'.format(attrstr)

        # convret the new string value into the old type.
        try:
            newval = self.parse_typestr(oldval, valstr)
        except Exception as ex:
            # Unable to convert new value into old type.
            return ex

        # Actually set the new value.
        try:
            setattr(parent, oldname, newval)
        except Exception as ex:
            # Unable to set the attribute.
            return ex

        # Success. Show new value.
        newval = str(newval)
        if len(newval) > 250:
            newval = '{} ...truncated'.format(newval[:250])
        return '{} = {}'.format(attrstr, newval)

    def admin_shutdown(self, rest, nick=None):
        """ Shutdown the bot. """
        finalmsg = 'Shutting down: {}'.format(rest if rest else 'No reason.')
        log.msg(finalmsg)

        quitmsg = rest or 'Shutting down...'
        self.admin.quit(message=quitmsg)
        # Unreachable code.
        return finalmsg

    def admin_stats(self, rest, nick=None):
        """ Return simple stats info. """
        uptime = timefromsecs(self.admin.get_uptime())
        statslst = (
            'uptime: {}'.format(uptime),
            'handled: {}'.format(self.admin.handled),
            'banned: {}'.format(len(self.admin.banned)),
            'warned: {}'.format(len(self.admin.banned_warned)),
        )
        return ', '.join(statslst)

    def admin_topic(self, rest, nick=None):
        """ Set the topic for a channel.
            Defaults to bot channel and default topic.
        """
        if not rest:
            self.admin.set_topic()
            return None

        chan, _, msg = rest.partition(' ')
        if not chan.startswith('#'):
            # No channel specified
            chan = None
            msg = rest

        self.admin.set_topic(topic=msg, channel=chan)

    def admin_unban(self, rest, nick=None):
        """ Unban a nick. """
        if not rest.strip():
            return 'usage: {}unban <nick>'.format(self.admin.cmdchar)

        nicks = rest.split()
        unbanned = self.admin.ban_remove(nicks)
        notbanned = [n for n in nicks if n not in unbanned]

        msg = []
        if unbanned:
            msg.append('unbanned: {}'.format(', '.join(unbanned)))
            if notbanned:
                msg.append('not banned: {}'.format(', '.join(notbanned)))
            return ', '.join(msg)
        else:
            if notbanned:
                return 'not banned: {}'.format(', '.join(notbanned))
            else:
                return 'unable to unban: {}'.format(rest)

    def cmd_help(self, rest, nick=None):
        """ Returns a short help string. """
        self.admin.sendmsg(
            nick,
            self.get_help(role='user', cmdname=rest, usernick=nick))

    def cmd_py(self, rest, nick=None):
        """ Shortcut for cmd_python """
        return self.cmd_python(rest, nick=nick)

    def cmd_python(self, rest, nick=None):
        """ Evaluate python code and return the answer.
            Restrictions are set. No os module, no nested eval() or exec().
        """

        if not rest:
            # No input.
            return None

        # Parse command arguments and trim them from the command.
        argd, rest = get_args(rest, (('-p', '--paste'),))

        def pastebin_chatout(pastebinurl):
            """ Callback for deferred print_topastebin.
                Expects result from print_topastebin(content).
                Returns final chat output when finished.

                It uses the 'execbox' created in cmd_python() to get output.
                ...so it must be local to cmd_python() for now.

            """
            # Get chat safe output (partial eval output with pastebin url)
            if pastebinurl:
                # Build chat result
                # semi-full output was pasted, but still need acceptable chat
                # msg.
                chatout = execbox.safe_output(maxlines=30, maxlength=140)
                if len(chatout) > 100:
                    chatout = chatout[:100]
                return ('{} '.format(chatout) +
                        ' - goto: {}'.format(pastebinurl))
            else:
                # failed to pastebin.
                chatout = execbox.safe_output(maxlines=30, maxlength=140)
                if len(chatout) > 100:
                    chatout = chatout[:100]
                return '{} (...truncated)'.format(chatout)

        # User wants help.
        if rest.lower().startswith('help'):
            return self.cmd_help(rest)

        # Execute using pypy-sandbox/pyval_sandbox powered ExecBox.
        execbox = ExecBox(rest)
        try:
            # Get raw output from eval, this will have to be checked
            # and possibly trimmed later before returning a result.
            results = execbox.execute(use_blacklist=self.admin.blacklist,
                                      raw_output=True)
        except TimedOut:
            return 'result: timed out.'
        except Exception as ex:
            return 'error: {}'.format(ex)

        if argd['--paste'] or (len(results) > 160):
            # Parse output to replace 'fake' newlines with realones,
            # use it for pastebin output.
            parsed = execbox.parse_input(rest, stringmode=True)

            # Use pastebinit, with safe_pastebin() settings.
            pastebincontent = self.safe_pastebin(execbox.output)
            if self.admin.handlingcount > 1:
                # Delay this pastebin call based on the handling count.
                timeout = 3 * self.admin.handlingcount
                log.msg('Delaying pastebin call for '
                        '{} seconds.'.format(timeout))
                # Create a deferred that will be called at a later time.
                deferredurl = self.task.deferLater(self.reactor,
                                                   timeout,
                                                   self.print_topastebin,
                                                   parsed,
                                                   pastebincontent,
                                                   author=nick)
                # Create a callback that takes in the url and produces
                # the final chat response.
                # IRCClient.privmsg() looks for a deferred and will add
                # the _sendMessage callback to this when it is finished.
                # (after some further checking/processing ofcourse)
                deferredurl.addCallback(pastebin_chatout)
                return deferredurl

            else:
                # paste it right away
                pastebinout = self.print_topastebin(parsed,
                                                    pastebincontent,
                                                    author=nick)
                resultstr = pastebin_chatout(pastebinout)

        else:
            # No pastebin needed.
            resultstr = execbox.safe_output()

        return resultstr

    def cmd_pyval(self, rest, nick=None):
        """ Someone addressed 'pyval' directly. """
        if rest.replace(' ', '').replace('\t', ''):
            log.msg('Message from {}: {}'.format(nick, rest))
            # Don't reply to this valid msg.
            return None
        else:
            return ' '.join([
                'try {cc}help,'
                '{cc}py help,'
                'or {cc}help py']).format(cc=self.admin.cmdchar)

    def _cmd_saylater(self, rest, nick=None):
        """ Delayed response... DISABLED"""
        when, sep, msg = rest.partition(' ')
        try:
            when = int(when)
        except ValueError:
            return 'usage: {}saylater <seconds>'.format(self.admin.cmdchar)

        d = self.defer.Deferred()
        # A small example of how to defer the reply from a command. callLater
        # will callback the Deferred with the reply after so many seconds.
        self.reactor.callLater(when, d.callback, msg)
        # Returning the Deferred here means that it'll be returned from
        # maybeDeferred in pyvalbot.PyValIRCProtocol.privmsg.
        return d

    def cmd_time(self, rest, nick=None):
        """ Retrieve current date and time. """

        return humantime(datetime.now())

    def cmd_uptime(self, rest, nick=None):
        """ Return uptime, and starttime """
        uptime = timefromsecs(self.admin.get_uptime())
        s = 'start: {}, up: {}'.format(humantime(self.admin.starttime),
                                       uptime)
        return s

    def cmd_version(self, rest, nick=None):
        """ Return pyval version, and sys.version. """
        pyvalver = '{}: {}'.format(NAME, VERSION)
        pyver = 'Python: {}'.format(sysversion.split()[0])
        gccver = 'GCC: {}'.format(sysversion.split('\n')[-1])
        verstr = '{}, {}, {}'.format(pyvalver, pyver, gccver)
        return verstr

    def get_commands(self, role='user', usernick=None):
        """ Returns a list of available user commands. """
        if role == 'user':
            # Not dynamically generating list right now, maybe later when
            # commands are final and stable.
            # This is a list of 'acceptable' commands right now.
            if usernick and (usernick in self.admin.admins):
                # hint an admin user towards the adminhelp command.
                usercmds = ['adminhelp']
            else:
                usercmds = []
            usercmds.extend(['help', 'py', 'python',
                             'pyval', 'uptime', 'version'])
            return usercmds

        else:
            # Dynamically generate a list of admin commands.
            admincmds = [a for a in dir(self) if a.startswith('admin_')]
            admincmdnames = [s.split('_')[1] for s in admincmds]
            return sorted(admincmdnames)

    def get_help(self, role='user', cmdname=None, usernick=None):
        """ Retrieve help for a command. """

        if not self.admin.help_info:
            return 'help isn\'t available right now.'

        # Handle python style help (still only works for pyval cmds)
        if cmdname and '(' in cmdname:
            # Convert 'help(test)' into 'help test', or 'help()' into 'help '
            cmdname = cmdname.replace('(', ' ')
            cmdname = cmdname.strip(')')
            # Remove " and '
            if ("'" in cmdname) or ('"' in cmdname):
                cmdname = cmdname.replace('"', '').replace("'", '')
            # Convert 'help ' into 'help'
            cmdname = cmdname.strip()
            # Convert 'help ' into None so it can be interpreted as plain help.
            if cmdname == 'help':
                cmdname = None
            else:
                # Convert 'help blah' into 'blah'
                cmdname = ' '.join(cmdname.split()[1:])

        if cmdname:
            # Look for cmd name in help_info.
            cmdname = cmdname.lower()
            if cmdname in self.admin.help_info[role]:
                cmdhelp = self.admin.help_info[role][cmdname]
                if cmdhelp['args']:
                    return '{}{} {}: {}'.format(self.admin.cmdchar,
                                                cmdname,
                                                cmdhelp['args'],
                                                cmdhelp['desc'])
                else:
                    return '{}{}: {}'.format(self.admin.cmdchar,
                                             cmdname,
                                             cmdhelp['desc'])
            else:
                return 'no {} command named: {}'.format(role, cmdname)

        else:
            # All commands
            cmds = self.get_commands(role=role, usernick=usernick)
            return '{} commands: {}'.format(role, ', '.join(cmds))

    def parse_attrstr(self, attrstr):
        """ Return value and parent for attribute by string. """
        if '.' in attrstr:
            attrs = attrstr.split('.')
        else:
            attrs = [attrstr]

        # Find old value, and parent of old value.
        parent = None
        abase = self
        for aname in attrs:
            if hasattr(abase, aname):
                parent = abase
                abase = getattr(parent, aname)
            else:
                return None, None, None
        # Parent, and value.
        return parent, aname, abase

    def parse_typestr(self, oldval, newval):
        """ Returns correct type from string,
            when given the original value.
            Example:
                mybool = True
                newval = parse_typestr(mybool, 'False')
                #   newval == bool(False)
                myint = 23
                newval = parse_typestr(myint, '46')
                #   newval == int(46)

            Handles all builtin types, not datetime (yet).
            Does not suppress any ValueError/TypeError.
        """

        def make_bool(s):
            """ Return a bool by string value. """
            if s.lower() in ('false', '0'):
                return False
            return bool(s)

        # NoneType just returns none.
        if oldval is None:
            return None

        handlers = {bool: make_bool}

        if type(oldval) in handlers.keys():
            # Special cases need custom handlers. Like bool('False')...
            converted = handlers[type(oldval)](newval)
        else:
            # Normal case, or no custom handler.
            converted = type(oldval)(newval)
        return converted

    def print_topastebin(self, query, result, author=None, title=None):
        """ Uses welbornprod.com/paste to paste a response. """

        if (not query) or (not result):
            return None

        div = '-' * 80
        contentfmt = '{dv}\nQuery:\n{dv}\n\n{q}\n\n{dv}\nResult:\n{dv}\n\n{r}'
        content = contentfmt.format(dv=div, q=query, r=result)

        if author is None:
            author = 'PyVal'
        else:
            author = 'PyVal (for {})'.format(author)

        pastedata = {
            'author': author,
            'title': title or 'PyVal Evaluation Results',
            'language': 'Python',
            'content': content,
            'private': True,

        }

        # Add extra args for the unittests..
        if author.startswith('<pyvaltest>') or query.startswith('<pyvaltest>'):
            pastedata['disabled'] = True
            pastedata['author'] = '<pyvaltest> {}'.format(author)

        return pasteit(pastedata)

    def proc_output(self, proc):
        """ Get process output, whether its on stdout or stderr.
            Used with _exec/timed_call.
            Arguments:
                proc  : a POpen() process to get output from.
        """

        if not proc:
            return ''

        # Get stdout
        outlines = []
        for line in iter(proc.stdout.readline, ''):
            if line:
                outlines.append(line.strip('\n'))
            else:
                break

        # Get stderr
        errlines = []
        for line in iter(proc.stderr.readline, ''):
            if line:
                errlines.append(line.strip('\n'))
            else:
                break

        # Pick stdout or stderr.
        if outlines:
            output = '\n'.join(outlines)
        elif errlines:
            output = '\n'.join(outlines)
        else:
            # no output
            output = ''

        return output.strip('\n')

    def safe_pastebin(self, s, maxlines=300, maxlength=400):
        """ Format string for safe pastebin pasting.
            maxlines is the limit of lines allowed.
            maxlength is the limit allowed for each line.
        """

        if maxlines < 1:
            maxlines = 1
        if maxlength < 1:
            maxlength = 1

        if not s:
            return s

        if '\n' in s:
            lines = s.split('\n')
        elif '\\n' in s:
            lines = s.split('\\n')
        else:
            lines = [s]

        truncatedlines = False
        # truncate by line count first.
        if len(lines) > maxlines:
            lines = lines[:maxlines]
            truncatedlines = True

        # Truncate each line if maxlength is set.
        trimmedlines = []
        for line in lines:
            if len(line) > maxlength:
                newline = ('{} ..truncated'.format(line[:maxlength]) +
                           ' ({} chars)'.format(maxlength))
                trimmedlines.append(newline)
            else:
                trimmedlines.append(line)
        lines = trimmedlines

        if truncatedlines:
            lines.append('..truncated at {} lines.'.format(maxlines))

        return '\n'.join(lines)
