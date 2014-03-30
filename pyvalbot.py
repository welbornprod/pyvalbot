#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pyvalbot.py
    Python Evaluation Bot (PyVal)
    IRC Bot that accepts commands, mostly to evaluate and return the result
    of python code.

    Class descriptions:
        PyValIRCFactory: Creates a Protocol instance and starts things off.

        PyValIRCProtocol: Handles all IRC communications. All data comes
        |                 through here first.
        |
        |____ AdminHandler: Stores admin info needed by the protocol, the
        |                   command-handler, and the command-functions.
        |
        |__ CommandHandler: After privmsg's are decided to be bot commands,
            |               the content is passed to CommandHandler for
            |               parsing. Command names are validated, and admin
            |               commands are validated. The proper function is
            |               retrieved and returned to the protocol.
            |
            |
            |__ CommandFuncs: Both admin, and user commands are stored as
                              functions in CommandFuncs. Admin commands start
                              with 'admin_', and user commands start with
                              'cmd_'. The function is retrieved by the
                              CommandHandler, and returned to the Protocol
                              which executes it. If the return value is a
                              string, the string is sent as a privmsg to
                              wherever the original command came from.
                              Either a channel, or a user. Functions may return
                              None if no response is needed.

    Original Twisted basic bot code borrowed from github.com/habnabit.
    Sandboxing is done by pypy-sandbox (pypy.org)

    -Christopher Welborn 2013-2014
"""


# System/General stuff
from datetime import datetime
from hashlib import md5
from os import getpid
import os.path
import sys

# Arg parsing
from docopt import docopt

# Irc stuff
from twisted.internet import defer, endpoints, protocol, reactor, task
from twisted.python import failure, log  # noqa
from twisted.words.protocols import irc

 
# Local stuff (Command Handler)
from pyval_commands import AdminHandler, CommandHandler
from pyval_util import NAME, VERSION, VERSIONSTR

SCRIPT = os.path.split(sys.argv[0])[1]

BANFILE = '{}_banned.lst'.format(NAME.lower().replace(' ', '-'))

USAGESTR = """{versionstr}

    Usage:
        {script} -h | -v
        {script} [options]
        
    Options:
        -b,--noheartbeat           : Don't log the heartbeat pongs.
        -c chans,--channels chans  : Comma-separated list of channels to join.
        -C chr,--commandchar chr   : Character that marks a msg as a command.
                                     Messages that start with this character
                                     are considered commands by {name}.
                                     Defaults to: !
        -d,--data                  : Log all sent/received data.
        -h,--help                  : Show this message.
        -i,--ips                   : Print all messages to log, 
                                     include ip addresses.
        -l,--logfile               : Use log file instead of stderr/stdout.
        -m,--monitor               : Print all messages to log.
        -n <nick>,--nick <nick>    : Choose what NICK to use for this bot.
        -P pw,--password pw        : Specify a password for the IDENTIFY
                                     command. The bot will identify with
                                     NickServ on connection.
        -p port,--port port        : Port number for the irc server.
                                     Defaults to: 6667
        -s server,--server server  : Name/Domain for the irc server.
                                     Defaults to: irc.freenode.net
        -v,--version               : Show {name} version.
        
""".format(name=NAME, versionstr=VERSIONSTR, script=SCRIPT)


class PyValIRCProtocol(irc.IRCClient):
 
    def __init__(self):
        self.argd = main_argd
        # Main deferred, fired on fatal error or final disconnect.
        self.deferred = defer.Deferred()

        # Class to handle admin stuff. Needs to be accessed here and in
        # CommandHandler.
        self.admin = AdminHandler()
        self.admin.monitor = self.get_argd('--monitor', False)
        self.admin.monitordata = self.get_argd('--data', False)
        self.admin.monitorips = self.get_argd('--ips', False)
        self.admin.nickname = self.get_argd('--nick', 'pyval')
        self.admin.cmdchar = self.get_argd('--commandchar', '!')
        self.admin.noheartbeatlog = self.get_argd('--noheartbeat', False)
        # Give admin access to certain functions.
        self.admin.quit = self.quit
        self.admin.sendLine = self.sendLine
        self.admin.ctcpMakeQuery = self.ctcpMakeQuery
        self.admin.do_action = self.me
        self.admin.handlinglock = defer.DeferredLock()
        # IRCClient must hold the nickname attribute.
        self.nickname = self.admin.nickname
        self.erroneousNickFallback = '{}_'.format(self.nickname)
        # Settings for client/version replies.
        self.versionName = NAME
        self.versionNum = VERSION
        # parse cmdline args to set attributes.
        # self.channels depends on self.nickname for the default channel.
        self.channels = self.parse_join_channels(self.get_argd('--channels'))
        self.nickservpw = self.get_argd('--password', default=None)

        # Class to handle messages and commands.
        self.commandhandler = CommandHandler(defer_=defer,
                                             reactor_=reactor,
                                             task_=task,
                                             adminhandler=self.admin)

    def connectionMade(self):
        """ Initial connection was made, no 'welcome' message yet. """
        # Take care of some internal stuff.
        irc.IRCClient.connectionMade(self)
        try:
            self.transport.setTcpKeepAlive(1)
        except Exception as ex:
            log.msg('Unable to setTcpKeepAlive:\n{}'.format(ex))

        # Log the settings for this session.
        log.msg('     Version: {}'.format(VERSIONSTR))
        log.msg('      Python: {}'.format(sys.version.replace('\n', '- ')))
        log.msg('Connected to: {} - Port: {}'.format(self.hostname,
                                                     self.portnum))
        log.msg('        Nick: {}'.format(self.admin.nickname))
        log.msg('    Channels: {}'.format(', '.join(self.channels)))
        log.msg('Command Char: {}'.format(self.admin.cmdchar))

        # Reset the delay counts on the global factory.
        factory.resetDelay()

    def connectionLost(self, reason):
        """ Connection to the server was lost.
            Log it, and fire the main deferred with an errback().
        """
        logmsgs = ['Connection Lost']
        if reason:
            # Log with reason.
            logmsgs.append(': {}'.format(reason))
        else:
            logmsgs.append('.')
        log.msg(''.join(logmsgs))

        # Fire the main deferred with an error (the disconnect reason).
        self.deferred.errback(reason)

    def get_argd(self, argname, default=None):
        """ Safely retrieves a command-line arg from self.argd. """
        if not self.argd:
            log.msg('Something went wrong, self.argd was None!\n'
                    '    Setting to main_argd.')
            self.argd = main_argd

        if self.argd:
            argval = self.argd.get(argname, None)
            if argval:
                return argval
        return default

    def irc_PING(self, prefix, params):
        """ Called when someone has pinged the bot,
            the bot needs to reply to pings.
        """
        self.sendLine('PONG {}'.format(params[-1]))
        if not self.admin.monitordata:
            log.msg('Sent PONG reply: {}'.format(params[-1]))

    def is_command(self, s):
        """ Return true if this string/message is considered a command.
            (returns True even if it's an unknown command name.)
        """
        return s.startswith(self.admin.cmdchar)

    def joined(self, channel):
        """ Called when the bot successfully joins a channel.
            This is used to keep track of self.admin.channels
        """

        log.msg('Joined: {}'.format(channel))
        self.admin.channels.append(channel)

        if channel.strip('#') == self.nickname:
            # Set topic to our own channel if possible.
            topic = [
                'Python Evaluation Bot (pyval) | ',
                'Type {cc}py <code> or {cc}help [cmd] if {nick} is around. | ',
                'Use \\n for actual newlines (Enter), or \\\\n for '
                'escaped newlines.'
            ]
            topic = ''.join(topic).format(cc=self.admin.cmdchar,
                                          nick=self.admin.nickname)
            self.topic(channel, topic)

    def kickedFrom(self, channel, kicker, message):
        """ Call when the bot is kicked from a channel. """

        log.msg('Kicked from {} by {}: {}'.format(channel, kicker, message))
        while channel in self.admin.channels:
            self.admin.channels.remove(channel)

    def left(self, channel):
        """ Called when the bot leaves a channel.
            This is used to keep track of self.admin.channels.
        """
        log.msg('Left: {}'.format(channel))
        while channel in self.admin.channels:
            self.admin.channels.remove(channel)

    def lineReceived(self, line):
        """ Receive line, catch what is being received for logs. """
        irc.IRCClient.lineReceived(self, line)
        if self.admin.monitordata:
            log.msg('Recv: {}'.format(line))

        if 'PONG' in line:
            try:
                pongdatalines = line.split('PONG')[1].strip().split()
                # Don't know where this pong came from.
                self.pong(pongdatalines[-1].strip(':'), None)
            except Exception as ex:
                log.msg('Failed to parse pong msg: {}'.format(ex))

    def logPrefix(self):
        """ Retrieve the name used for logging.
            Usually self.__class__.__name__, but a shorter name is used
            instead for PyVal.
        """
        return self.versionName

    def md5(self, s):
        """ md5 some bytes, strings are encoded in utf-8 if passed. """
        if isinstance(s, bytes):
            hashobj = md5(s)
        else:
            hashobj = md5(s.encode('utf-8'))
        return hashobj.hexdigest()

    def me(self, channel, action):
        """ Perform an action, (/ME action) """
        if channel and (not channel.startswith('#')):
            channel = '#{}'.format(channel)
        self.ctcpMakeQuery(channel, [('ACTION', action)])

    def modeChanged(self, user, channel, enabled, modes, args):
        """ Called when a mode has changed for a user/channel.
            Any mode that affects the bot is logged, 
            whether it's from the server or another user.
        """

        usermode = (args and (self.nickname in args))
        if usermode or (channel == self.nickname):
            # This mode affects the bot.
            if user == self.nickname:
                username = 'server'
            else:
                # another user has set a mode on the bot.
                username = self.parse_user(user)
            # Use +/- notation for enabled/disabled.
            modestr = '+{}' if enabled else '-{}'
            modestr = modestr.format(modes)
            if (args > (None,)) and (args != (self.nickname,)):
                # Mode has args.
                # If the bots nick is the only argument, don't log the args.
                argstr = ', args: {!r}'.format(args)
            else:
                # No args for this mode.
                argstr = ''

            if channel == self.nickname:
                # server mode, no channel.
                log.msg('Mode changed by {}: {}{}'.format(username,
                                                          modestr,
                                                          argstr))
            else:
                log.msg('Mode changed by {} in {}: {}{}'.format(username,
                                                                channel,
                                                                modestr,
                                                                argstr))

    def nickChanged(self, nick):
        """ Called when the bots nick changes. """
        self.admin.nickname = nick

    def notice(self, user, message):
        """ Send a "notice" to a channel or user. """
        self.sendLine('NOTICE {} :{}'.format(user, message))
        # Notice sends are always logged, either here or in sendLine when
        # monitordata is set.
        if not self.admin.monitordata:
            log.msg('NOTICE to {}: {}'.format(user, message))

    def noticed(self, user, channel, message):
        """ Called when a NOTICE is sent to the bot or channel. """
        # If data is already monitored, printing again will only cause clutter.
        # So skip this part if monitordata is set.
        if not self.admin.monitordata:
            if channel == self.admin.nickname:
                # Private notice.
                # Check for ZNC autoop challenge.
                if '!ZNCAO CHALLENGE' in message:
                    self.respond_znc_challenge(user, message)
                noticefmt = 'NOTICE from {}: {}'
                log.msg(noticefmt.format(user, message))
            else:
                # Channel/server notice.
                noticefmt = 'NOTICE from {} in {}: {}'
                log.msg(noticefmt.format(user, channel, message))

    def parse_comma_args(self, s):
        """ Parses comma-separated strings, returns a list.
            empty args like 'arg1,,arg2' are skipped.
        """

        args = []
        for a in s.split(','):
            trimmed = a.strip()
            if trimmed:
                args.append(trimmed)
        return args

    def parse_join_channels(self, chanargstr):
        """ Parse any channels that were sent by cmdline.
            for automatic joins on connection.
        """
        if chanargstr:
            # Comma-separated list of channels to join from cmd-line args.
            chans = self.parse_comma_args(chanargstr)
        else:
            if self.nickname == 'irc':
                log.msg('Default nick is being used!: '
                        '{}'.format(self.nickname))
                log.msg('This will affect the default channel!')

            # Default channel to join when none are supplied
            chans = ['#{}'.format(self.nickname)]

        return chans

    def parse_user(self, userstring):
        """ Parses irc format for user names, returns only the user name.
            No host.
        """
        if userstring and ('!' in userstring):
            return userstring.split('!')[0]
        # not an irc format
        return userstring

    def pong(self, user, secs):
        """ Called when pong results are received. """
        # Only print a pong reply if secs is given, or monitordata is False.
        if secs:
            # seconds is known, print it whether monitordata is set or not.
            log.msg('PONG from: {} ({}s)'.format(user, secs))
        elif not self.admin.monitordata:
            # no data monitoring, but seconds is unknown.
            # log it if --noheartbeat isn't being used.
            if not self.admin.noheartbeatlog:
                log.msg('PONG from: {} (heartbeat response)'.format(user))

    def privmsg(self, user, channel, message):
        """ Handles personal and channel messages.
            Most of the work is done here.
            Lines are checked for pyval commands, auto-bans are handled,
            responses are throttled based on a number of things.
        """
        nick, _, host = user.partition('!')
        message = message.strip()
        is_admin = (nick in self.admin.admins)

        if (nick.lower() == 'nickserv'):
            log.msg('NickServ: {}'.format(message))

        # Disallow banned nicks.
        if nick in self.admin.banned:
            return None

        # Handle auto-bans for command msgs.
        ban_msg = None
        if (self.admin.last_handle and
           self.admin.last_nick and self.is_command(message)):
            # save seconds since last response.
            respondtime = (datetime.now() - self.admin.last_handle)
            respondsecs = respondtime.total_seconds()
            # If this user has been ban warned, check their last response time.
            if nick in self.admin.banned_warned.keys():
                lasttime = self.admin.banned_warned[nick]['last']
                usersecs = (datetime.now() - lasttime).total_seconds()
                if usersecs < self.admin.msg_timelimit:
                    # User is sending too many msgs too fast.
                    ban_msg = self.admin.ban_add(nick)
                else:
                    # Time on last command is okay,
                    # update this warned-user's last msg time.
                    self.admin.banned_warned[nick]['last'] = datetime.now()

            elif (nick == self.admin.last_nick) and (respondsecs < 3):
                # first time offender
                ban_msg = self.admin.ban_add(nick)

        if ban_msg:
            # Send ban msg instead of usual command response if available.
            d = defer.maybeDeferred(lambda: ban_msg)
        else:
            # Process command.
            # Ignore cmd if we just processed the same command.
            if (message == self.admin.last_command) and (not is_admin):
                return None

            # Handle message parsing and commands.
            # If the message triggers a command, then a function is returned to
            # handle it. If there is no function returned, then just return.
            func = self.commandhandler.parse_data(user, channel, message)
            
            # Nothing returned from commandhandler, no response is needed.
            if not func:
                return None

            # Get '!cmd rest' to send to func args...
            cmd, sep, rest = message.lstrip(self.admin.cmdchar).partition(' ')

            # Save this message, and build deferred with these args.
            self.admin.last_command = message
            # If the function returns a deferred, it will be handled
            # the same as non-deferred-returning functions.
            d = defer.maybeDeferred(func, rest.strip(), nick=nick)

        if self.admin.limit_rate:
            # Disallow backup of requests. If handlingcount is too much
            # just ignore this one.
            if ((not is_admin) and
               (self.admin.handlingcount > self.admin.banwarn_limit)):
                log.msg('Too busy, ignoring command: {}'.format(message))
                return None
            # Keep track of how many requests are unanswered (handling).
            self.admin.handling_increase()

        # Add error callbackfor func, the _show_error callback will turn the
        # error into a terse message first:
        d.addErrback(self._showError)
        # Pick args for _sendMessage based on where the message came from.
        # This will fire off our send function
        if channel == self.admin.nickname:
            # Send private response.
            d.addCallback(self._sendMessage, nick)
        else:
            # Send channel response.
            d.addCallback(self._sendMessage, channel, nick)

        # Save the last command-handled time for next time.
        self.admin.last_handle = datetime.now()
        self.admin.last_nick = nick

    def respond_znc_challenge(self, user, msg):
        """ Respond to a ZNC auth challenge.
            This currently only works if no key is set.

            When an admin is using a ZNC bouncer, and has *autoop enabled,
            pyval can be added as an 'autoop' user.
            When pyval joins a channel setup for autoop ZNC will send a
            challenge (NOTICE !ZNCAO CHALLENGE <challenge_text>).
            This will automatically respond with:
                '!ZNCAO RESPONSE <md5(challenge_text)>'

            It will not handle keys. 
            Pyval will need to connect to a BNC bouncer so ZNC can handle the 
            keys itself.
        """

        if user and msg:
            challenge = msg.split()[-1]
            response = self.md5(challenge)
            self.notice(user, '!ZNCAO RESPONSE {}'.format(response))

        # No user/message was provided.
        return None

    def sendLine(self, line):
        """ Send line, catch what is being sent for logs. """
        # call the original sendline (handles default actions).
        irc.IRCClient.sendLine(self, line)
        # log everything sent if monitordata is set.
        if self.admin.monitordata:
            if ':IDENTIFY' in line:
                # don't log the users nick pw.
                idline = ' '.join(line.split()[:-1])
                log.msg('Sent: {} {}'.format(idline, '******'))
            elif ':PASS' in line:
                # password line. don't log the pw.
                pwline = ' '.join(line.split()[:-1])
                log.msg('Sent: {} {}'.format(pwline, '******'))
            else:
                # normal, probably safe line. log it.
                log.msg('Sent: {}'.format(line))

    def setArg(self, argname, argval):
        """ Function to call from other places, to set argd args. """
        
        if self.argd:
            self.argd[argname] = argval
            log.msg('Set arg: {} = {}'.format(argname, argval))

    def signedOn(self):
        """ This is called once the server has acknowledged that we sent
            both NICK and USER.
        """

        # identify with nickserv if the --password flag was given.
        if self.nickservpw:
            self.admin.identify(self.nickservpw)
            # no need to save the pw here.
            self.nickservpw = None
            self.argd['--password'] = None

        # Join channels.
        for channel in self.channels:
            log.msg('Joining :{}'.format(channel))
            self.join(channel)

    def _handleMessage(self, msg, target, nick=None):
        """ Actually send the message,
            decrease the handling count,
            increase the handled count.
        """
        if msg:
            if nick:
                msg = '{}, {}'.format(nick, msg)
            self.msg(target, msg)

        # admin cmds have no msg sometimes, but still count as 'handling'.
        self.admin.handling_decrease()

        # increase the 'handled' count.
        self.admin.handled += 1

    def _sendMessage(self, msg, target, nick=None):
        # Default handling delay for non-msg handling or low-load times.
        timeout = 0.25
        if self.admin.handlingcount > 1:
            # Calculate delay needed based on current handling count.
            # Ends up being around 2 seconds per response.
            # Schedule message handling for later.
            if msg:
                timeout = 2 * self.admin.handlingcount
                log.msg('Delaying msg response for later: {}'.format(timeout))

        # Call the handle message function later-ish.
        reactor.callLater(timeout,
                          self._handleMessage,
                          msg,
                          target,
                          nick)

    def _showError(self, failure):
        return failure.getErrorMessage()
    
    
class PyValIRCFactory(protocol.ReconnectingClientFactory):

    """ Reconnecting client factory,
        should reconnect all client instances on disconnect.
    """

    def __init__(self, argd=None, serverstr=None):
        self.protocol = PyValIRCProtocol
        # Set the hostname and portnum on the protocol for this connection.
        try:
            serverinfo = serverstr.split(':')[1:]
        except ValueError:
            serverinfo = 'Unknown', 'Unknown'
        self.protocol.hostname, self.protocol.portnum = serverinfo

    def logPrefix(self):
        """ Returns the label for logging msgs coming from the factory.
            Usually self.__class__.__name__, but not for PyVal.
        """
        return '{}-Factory'.format(NAME)


def write_pidfile():
    """ Writes the current pid to file, for pyval_restart. """

    try:
        pyvalpid = getpid()
        with open('pyval_pid', 'w') as fwrite:
            fwrite.write(str(pyvalpid))
        log.msg('Wrote pid to pyval_pid: {}'.format(pyvalpid))
        return True
    except (IOError, OSError) as ex:
        log.msg('Unable to write pid file, pyval_restart will be useless.\n'
                '{}'.format(ex))
        return False


def main(reactor, serverstr, argd):
    """ main-entry point for ircbot. """
    global factory

    try:
        endpoint = endpoints.clientFromString(reactor, serverstr)
        # Global factory for creating client instances, and reconnecting.
        factory = PyValIRCFactory(argd=argd, serverstr=serverstr)
        # Connect the factory to the specified host/port.
        d = endpoint.connect(factory)
        # Add the protocol's main deferred, which can be fired on fatal errors.
        d.addCallback(lambda protocol: protocol.deferred)
        return d
    except Exception as ex:
        log.msg('Error in main():\n{}'.format(ex))
        return None


if __name__ == '__main__':
    # Get docopt args
    main_argd = docopt(USAGESTR, version=VERSIONSTR)

    # Start logging as soon as possible.
    # Open log file if --logfile is passed, (fallback to stderr on error)
    if main_argd['--logfile']:
        logfilename = '{}.log'.format(NAME.lower().replace(' ', '-'))
        try:
            logfile = open(logfilename, 'w')
            log.startLogging(logfile)
        except (IOError, OSError) as exio:
            print('\nUnable to open logfile!: '
                  '{}\nstderr will be used instead.\n'.format(logfilename))
            log.startLogging(sys.stderr)
    else:
        # normal stderr logging
        log.startLogging(sys.stderr)
    # Fixup the main log prefix, should only affect msgs at the main level.
    log.logPrefix = lambda self: '{}-Main'.format(NAME)

    # Write pid file.
    write_pidfile()
    
    # Parse server/port settings from cmdline, or set defaults.
    servername = main_argd['--server'] or 'irc.freenode.net'
    portnum = main_argd['--port'] or '6667'

    try:
        # validate user's port number (redundant when no --port was given)
        int(portnum)
    except ValueError:
        log.msg('Invalid port number given!: {}'.format(main_argd['--port']))
        sys.exit(1)

    # Final server string for endpoints.clientFromString()
    serverstr = 'tcp:{}:{}'.format(servername, portnum)

    # Global factory instance, clients need to call 'resetDelay' on connect.
    # main() creates the instance.
    factory = None
    # Start irc client.
    task.react(main, [serverstr, main_argd])
