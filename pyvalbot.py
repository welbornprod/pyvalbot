#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pyvalbot.py
    Python Evaluation Bot (PyVal)
    IRC Bot that accepts commands, mostly to evaluate and return the result
    of python code.

    Original Twisted basic bot code borrowed from github.com/habnabit.

    -Christopher Welborn 2013-2014
"""


# System/General stuff
from datetime import datetime
from os import getpid
import os.path
import sys

# Arg parsing
from docopt import docopt

# Irc stuff
from twisted.internet import defer, endpoints, protocol, reactor, task
from twisted.python import log
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
        -c chans,--channels chans  : Comma-separated list of channels to join.
        -d,--data                  : Log all sent/received data.
        -h,--help                  : Show this message.
        -i,--ips                   : Print all messages to log, 
                                     include ip addresses.
        -l,--logfile               : Use log file instead of stderr/stdout.
        -m,--monitor               : Print all messages to log.
        -n <nick>,--nick <nick>    : Choose what NICK to use for this bot.
        -p port,--port port        : Port number for the irc server.
                                     Defaults to: 6667
        -s server,--server server  : Name/Domain for the irc server.
                                     Defaults to: irc.freenode.net
        -v,--version               : Show pyval version.
        
""".format(versionstr=VERSIONSTR, script=SCRIPT)


class PyValIRCProtocol(irc.IRCClient):
 
    def __init__(self):
        self.argd = main_argd
        self.deferred = defer.Deferred()
        nick = self.get_argd('--nick', 'pyval')
        # uses self.serverstr, which is set by the factory before init.
        self.set_serverinfo()

        # Class to handle admin stuff. Needs to be accessed here and in
        # CommandHandler.
        self.admin = AdminHandler(nick=nick)
        self.admin.monitor = self.get_argd('--monitor', False)
        self.admin.monitordata = self.get_argd('--data', False)
        self.admin.monitorips = self.get_argd('--ips', False)

        # Give admin access to certain functions.
        self.admin.quit = self.quit
        self.admin.sendLine = self.sendLine
        self.admin.ctcpMakeQuery = self.ctcpMakeQuery
        self.admin.do_action = self.me
        self.admin.handlinglock = defer.DeferredLock()
        # IRCClient must hold a nickname attribute.
        self.nickname = self.admin.nickname
        self.erroneousNickFallback = '{}_'.format(self.nickname)
        # Settings for client/version replies.
        self.versionName = NAME
        self.versionNum = VERSION
        # Class to handle messages and commands.
        self.commandhandler = CommandHandler(defer_=defer,
                                             reactor_=reactor,
                                             task_=task,
                                             adminhandler=self.admin)

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        print('\nConnected to: {}, Port: {}'.format(self.servername,
                                                    self.portstr))
        
    def connectionLost(self, reason):
        print('\nConnection Lost.\n')
        self.deferred.errback(reason)

    def get_argd(self, argname, defaultval=None):
        """ Safely retrieves a command-line arg from self.argd. """
        if not self.argd:
            print('\nSomething went wrong, self.argd was None!\n'
                  'Setting to main_argd.')
            self.argd = main_argd
        if self.argd:
            if argname in self.argd.keys():
                return self.argd[argname]
            else:
                print('Key not found in self.argd!: {}'.format(argname))
        return defaultval

    def irc_PING(self, prefix, params):
        """ Called when someone has pinged the bot,
            the bot needs to reply to pings.
        """
        self.sendLine('PONG {}'.format(params[-1]))
        if not self.admin.monitordata:
            print('Sent PONG reply: {}'.format(params[-1]))

    def joined(self, channel):
        """ Called when the bot successfully joins a channel.
            This is used to keep track of self.admin.channels
        """

        print('\nJoined: {}'.format(channel))
        self.admin.channels.append(channel)

        if channel.strip('#') == self.nickname:
            # Set topic to our own channel if possible.
            topic = ('Python Evaluation Bot (pyval) | '
                     'Type !py <code> or !help [cmd] if '
                     '{} '.format(self.nickname) +
                     'is around. | '
                     'Use \\n for actual newlines (Enter), or \\\\n '
                     'for escaped newlines.')
            self.topic(channel, topic)

    def kickedFrom(self, channel, kicker, message):
        """ Call when the bot is kicked from a channel. """

        print('\nKicked from: {} by {}, {}'.format(channel, kicker, message))
        while channel in self.admin.channels:
            self.admin.channels.remove(channel)

    def left(self, channel):
        """ Called when the bot leaves a channel.
            This is used to keep track of self.admin.channels.
        """
        print('\nLeft: {}'.format(channel))
        while channel in self.admin.channels:
            self.admin.channels.remove(channel)

    def lineReceived(self, line):
        """ Receive line, catch what is being received for logs. """
        irc.IRCClient.lineReceived(self, line)
        if self.admin.monitordata:
            print('\nRecv: {}'.format(line))

        if 'PONG' in line:
            try:
                pongdatalines = line.split('PONG')[1].strip().split()
                # Don't know where this pong came from.
                self.pong(pongdatalines[-1].strip(':'), None)
            except Exception as ex:
                print('Failed to parse pong msg: {}'.format(ex))

    def me(self, channel, action):
        """ Perform an action, (/ME action) """
        if channel and (not channel.startswith('#')):
            channel = '#{}'.format(channel)
        self.ctcpMakeQuery(channel, [('ACTION', action)])

    def modeChanged(self, user, channel, enabled, modes, args):
        """ Called when a mode has changed for a user/channel. """

        if channel == self.nickname:
            if user == self.nickname:
                user = 'server'
            # Our mode has changed.
            enabledstr = '+' if enabled else '-'
            argstr = repr(args) if args else ''
            print('Mode changed by {} to: {}{}, args: {}'.format(user,
                                                                 enabledstr,
                                                                 modes,
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
            print('NOTICE to {}: {}'.format(user, message))

    def noticed(self, user, channel, message):
        """ Called when a NOTICE is sent to the bot or channel. """
        # If data is already monitored, printing again will only cause clutter.
        # So skip this part if monitordata is set.
        if not self.admin.monitordata:
            if channel == self.admin.nickname:
                # Private notice.
                noticefmt = 'NOTICE from {}: {}'
                print(noticefmt.format(user, message))
            else:
                # Channel/server notice.
                noticefmt = 'NOTICE from {} in {}: {}'
                print(noticefmt.format(user, channel, message))

    def pong(self, user, secs):
        """ Called when pong results are received. """
        # Only print a pong reply if secs is given, or monitordata is False.
        if secs:
            # seconds is known, print it whether monitordata is set or not.
            print('\nPONG from: {} ({}s)'.format(user, secs))
        elif not self.admin.monitordata:
            # no data monitoring, but seconds is unknown.
            print('\nPONG from: {} (time unknown)'.format(user))

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
            print('NickServ: {}'.format(message))

        # Disallow banned nicks.
        if nick in self.admin.banned:
            return None

        # rate-limit responses, handle auto-bans.
        ban_msg = None
        if self.admin.last_handle and self.admin.last_nick:
            # save seconds since last response.
            respondtime = (datetime.now() - self.admin.last_handle)
            respondsecs = respondtime.total_seconds()
            # If this user has been ban warned, check their last response time.
            if nick in self.admin.banned_warned.keys():
                lasttime = self.admin.banned_warned[nick]['last']
                usersecs = (datetime.now() - lasttime).total_seconds()
                if usersecs < 4:
                    if self.admin.ban_add(nick):
                        ban_msg = 'no more.'
                    else:
                        ban_msg = 'slow down.'

            elif (nick == self.admin.last_nick) and (respondsecs < 3):
                # first time offender
                self.admin.ban_add(nick)

        if ban_msg:
            # Send ban msg instead of usual command response.
            d = defer.maybeDeferred(lambda: ban_msg)
        else:
            # Process command.
            # Ignore cmd if we just processed the same command.
            if (message == self.admin.last_command) and (not is_admin):
                # print('Ignoring cmd: {}, '.format(message) +
                #      'last: {}'.format(self.admin.last_command))
                return None

            # Handle message parsing and commands.
            # If the message triggers a command, then a function is returned to
            # handle it. If there is no function returned, then just return.
            func = self.commandhandler.parse_data(user, channel, message)
            
            # Nothing returned from commandhandler, no response is needed.
            if not func:
                # normal private msg sent directly to pyval.
                if channel == self.admin.nickname:
                    print('Message from {}: {}'.format(nick, message))
                return None

            # Get '!cmd rest' to send to func args...
            command, sep, rest = message.lstrip('!').partition(' ')
            # Save this message, and build deferred with these args.
            self.admin.last_command = message
            # If the function returns a deferred, it will be handled
            # the same as non-deferred-returning functions.
            d = defer.maybeDeferred(func, rest.strip(), nick=nick)

        if self.admin.limit_rate:
            # Disallow backup of requests. If handlingcount is too much
            # just ignore this one.
            if (not is_admin) and (self.admin.handlingcount > 3):
                print('Too busy, ignoring command: {}'.format(message))
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

    def sendLine(self, line):
        """ Send line, catch what is being sent for logs. """
        # call the original sendline (handles default actions).
        irc.IRCClient.sendLine(self, line)
        # log everything sent if monitordata is set.
        if self.admin.monitordata:
            print('\nSent: {}'.format(line))
    
    def set_serverinfo(self):
        """ set self.servername, self.portstr from the original descripton. """
        if hasattr(self, 'serverstr'):
            self.servername, self.portstr = self.serverstr.split(':')[1:]
        else:
            self.servername, self.portstr = 'Unknown', 'Unknown'
            print('No serverstr set on PyValIRCProtocol! '
                  'Messages will say \'Unknown\'.')

    def setArg(self, argname, argval):
        """ Function to call from other places, to set argd args. """
        
        if self.argd:
            self.argd[argname] = argval
            print('Set arg: {} = {}'.format(argname, argval))

    def signedOn(self):
        # This is called once the server has acknowledged that we sent
        # both NICK and USER.
        for channel in self.factory.channels:
            print('Joining :{}'.format(channel))
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
                print('Delaying msg response for later: {}'.format(timeout))

        # Call the handle message function later-ish.
        reactor.callLater(timeout,
                          self._handleMessage,
                          msg,
                          target,
                          nick)

    def _showError(self, failure):
        return failure.getErrorMessage()
    
    
class PyValIRCFactory(protocol.ReconnectingClientFactory):

    def __init__(self, argd=None, serverstr=None):
        self.protocol = PyValIRCProtocol
        # Send a few pieces of info to the irc protocol by settings attributes.
        self.protocol.argd = argd
        self.protocol.serverstr = serverstr

        self.argd = argd
        
        if self.get_argd('--channels'):
            # Comma-separated list of channels to join from cmd-line args.
            if ',' in self.get_argd('--channels'):
                self.channels = self.get_argd('--channels').split(',')
            else:
                self.channels = [self.get_argd('--channels')]
        else:
            # Default channel to join when none are supplied

            self.channels = ['#pyval']
    
    def get_argd(self, argname):
        """ Safely retrieve arg from self.argd """
        
        if self.argd:
            if argname in self.argd.keys():
                return self.argd[argname]
            else:
                print('Key not found in self.argd!: {}'.format(argname))
        return None


def write_pidfile():
    """ Writes the current pid to file, for pyval_restart. """

    try:
        pyvalpid = getpid()
        with open('pyval_pid', 'w') as fwrite:
            fwrite.write(str(pyvalpid))
        print('Wrote pid to pyval_pid: {}'.format(pyvalpid))
        return True
    except (IOError, OSError) as ex:
        print('Unable to write pid file, pyval_restart will be useless.\n'
              '{}'.format(ex))
        return False


def main(reactor, serverstr, argd):
    """ main-entry point for ircbot. """
    try:
        endpoint = endpoints.clientFromString(reactor, serverstr)
        factory = PyValIRCFactory(argd=argd, serverstr=serverstr)
        d = endpoint.connect(factory)
        d.addCallback(lambda protocol: protocol.deferred)
        return d
    except Exception as ex:
        print('\nError in main():\n{}'.format(str(ex)))
        return None
 
if __name__ == '__main__':
    # Get docopt args
    main_argd = docopt(USAGESTR, version=VERSIONSTR)
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

    # Write pid file.
    write_pidfile()
    
    # Parse server/port settings from cmdline.
    if main_argd['--server']:
        servername = main_argd['--server']
    else:
        servername = 'irc.freenode.net'
    if main_argd['--port']:
        portnum = main_argd['--port']
    else:
        portnum = '6667'
    try:
        int(portnum)
    except ValueError:
        print('\nInvalid port number given!: {}'.format(main_argd['--port']))
        sys.exit(1)

    serverstr = 'tcp:{}:{}'.format(servername, portnum)

    # Start irc client.
    task.react(main, [serverstr, main_argd])
