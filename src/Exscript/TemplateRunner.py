# Copyright (C) 2007 Samuel Abels, http://debain.org
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2, as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
import sys, time, os, re, signal, gc, copy
from Interpreter     import Parser
from FooLib          import UrlParser
from SpiffWorkQueue  import WorkQueue
from SpiffWorkQueue  import Sequence
from TerminalActions import *

True  = 1
False = 0

class TemplateRunner(object):
    """
    API for accessing all of Exscript's functions programmatically.
    This may still need some cleaning up, so don't count on API stability 
    just yet.
    """
    bracket_expression_re = re.compile(r'^\{([^\]]*)\}$')

    def __init__(self, **kwargs):
        """
        Constructor.

        @type  kwargs: dict
        @param kwargs: The following options are supported:
            - verbose: The verbosity level of the interpreter.
            - parser_verbose: The verbosity level of the parser.
            - domain: The default domain of the contacted hosts.
            - logdir: The directory into which the logs are written.
            - overwrite_logs: Whether existing logfiles are overwritten.
            - no_prompt: Whether the compiled program should wait for a 
            prompt each time after the Exscript sent a command to the 
            remote host.
        """
        self.exscript       = None
        self.exscript_code  = None
        self.exscript_file  = None
        self.hostnames      = []
        self.host_defines   = {}
        self.global_defines = {}
        self.verbose        = kwargs.get('verbose')
        self.logdir         = kwargs.get('logdir')
        self.overwrite_logs = kwargs.get('overwrite_logs', False)
        self.domain         = kwargs.get('domain',         '')
        self.parser         = Parser(debug     = kwargs.get('parser_verbose', 0),
                                     no_prompt = kwargs.get('no_prompt',      0))


    def _dbg(self, level, msg):
        if level > self.verbose:
            return
        print msg


    def add_host(self, host):
        """
        Adds a single given host for executing the script later.

        @type  host: string
        @param host: A hostname or an IP address.
        """
        self.hostnames.append(host)
        url = UrlParser.parse_url(host)
        for key, val in url.vars.iteritems():
            match = Exscript.bracket_expression_re.match(val[0])
            if match is None:
                continue
            string = match.group(1) or 'a value for "%s"' % key
            val    = raw_input('Please enter %s: ' % string)
            url.vars[key] = [val]
        self.host_defines[host] = url.vars


    def add_hosts(self, hosts):
        """
        Adds the given list of hosts for executing the script later.

        @type  hosts: list[string]
        @param hosts: A list of hostnames or IP addresses.
        """
        for host in hosts:
            self.add_host(host)


    def add_hosts_from_file(self, filename):
        """
        Reads a list of hostnames from the file with the given name.

        @type  filename: string
        @param filename: A full filename.
        """
        # Open the file.
        if not os.path.exists(filename):
            raise IOError('No such file: %s' % filename)
        file_handle = open(filename, 'r')

        # Read the hostnames.
        for line in file_handle:
            hostname = line.strip()
            if hostname == '':
                continue
            self.add_host(hostname)

        file_handle.close()


    def add_hosts_from_csv(self, filename):
        """
        Reads a list of hostnames and variables from the .csv file with the 
        given name.

        @type  filename: string
        @param filename: A full filename.
        """
        # Open the file.
        if not os.path.exists(filename):
            raise IOError('No such file: %s' % filename)
        file_handle = open(filename, 'r')

        # Read the header.
        header = file_handle.readline().rstrip()
        if re.search(r'^hostname\b', header) is None:
            msg  = 'Syntax error in CSV file header:'
            msg += ' File does not start with "hostname".'
            raise Exception(msg)
        if re.search(r'^hostname(?:\t[^\t]+)*$', header) is None:
            msg  = 'Syntax error in CSV file header:'
            msg += ' Make sure to separate columns by tabs.'
            raise Exception(msg)
        varnames = header.split('\t')
        varnames.pop(0)
        
        # Walk through all lines and create a map that maps hostname to definitions.
        last_hostname = ''
        for line in file_handle:
            line         = re.sub(r'[\r\n]*$', '', line)
            values       = line.split('\t')
            hostname_url = values.pop(0).strip()
            hostname     = UrlParser.parse_url(hostname_url).hostname

            # Add the hostname to our list.
            if hostname != last_hostname:
                #print "Reading hostname", hostname, "from csv."
                self.add_host(hostname_url)
                last_hostname = hostname

            # Define variables according to the definition.
            for i in range(0, len(varnames)):
                varname = varnames[i]
                try:
                    value = values[i]
                except:
                    value = ''
                if self.host_defines[hostname].has_key(varname):
                    self.host_defines[hostname][varname].append(value)
                else:
                    self.host_defines[hostname][varname] = [value]

        file_handle.close()


    def define(self, **kwargs):
        """
        Defines the given variables such that they may be accessed from 
        within the Exscript.

        @type  kwargs: dict
        @param kwargs: Variables to make available to the Exscript.
        """
        self.global_defines.update(kwargs)


    def define_host(self, hostname, **kwargs):
        """
        Defines the given variables such that they may be accessed from 
        within the Exscript only while logged into the specified 
        hostname.

        @type  hostname: string
        @param hostname: A hostname or an IP address.
        @type  kwargs: dict
        @param kwargs: Variables to make available to the Exscript.
        """
        if not self.host_defines.has_key(hostname):
            self.host_defines[hostname] = {}
        self.host_defines[hostname].update(kwargs)


    def load(self, exscript_content):
        """
        Loads the given Exscript code, using the given options.
        MUST be called before run() is called, either directly or through 
        load_from_file().

        @type  exscript_content: string
        @param exscript_content: An exscript.
        """
        # Parse the exscript.
        self.parser.define(**self.global_defines)
        self.parser.define(**self.host_defines[self.hostnames[0]])
        self.parser.define(__filename__ = self.exscript_file)
        self.parser.define(hostname     = self.hostnames[0])
        try:
            self.exscript = self.parser.parse(exscript_content)
            self.exscript_code = exscript_content
        except Exception, e:
            if self.verbose > 0:
                raise
            print e
            sys.exit(1)


    def load_from_file(self, filename):
        """
        Loads the Exscript file with the given name, and calls load() to 
        process the code using the given options.

        @type  filename: string
        @param filename: A full filename.
        """
        file_handle        = open(filename, 'r')
        self.exscript_file = filename
        exscript_content   = file_handle.read()
        file_handle.close()
        self.load(exscript_content)


    def _get_sequence(self, parent, hostname, **kwargs):
        """
        Compiles the current exscript, and returns a new workqueue sequence 
        for it that is initialized and has all the variables defined.
        """
        if self.exscript is None:
            msg = 'An Exscript was not yet loaded using load().'
            raise Exception(msg)

        # Prepare variables that are passed to the Exscript interpreter.
        user             = kwargs.get('user')
        password         = kwargs.get('password')
        default_protocol = kwargs.get('protocol', 'telnet')
        url              = UrlParser.parse_url(hostname, default_protocol)
        this_proto       = url.protocol
        this_user        = url.username
        this_password    = url.password
        this_host        = url.hostname
        if not '.' in this_host and len(self.domain) > 0:
            this_host += '.' + self.domain
        variables = dict()
        variables.update(self.global_defines)
        variables.update(self.host_defines[hostname])
        variables['hostname'] = this_host
        variables.update(url.vars)
        if this_user is None:
            this_user = user
        if this_password is None:
            this_password = password

        #FIXME: In Python > 2.2 we can (hopefully) deep copy the object instead of
        # recompiling numerous times.
        self.parser.define(**variables)
        if kwargs.has_key('filename'):
            exscript = self.parser.parse_file(kwargs.get('filename'))
        else:
            exscript_code = kwargs.get('code', self.exscript_code)
            exscript      = self.parser.parse(exscript_code)
        #exscript = copy.deepcopy(self.exscript)
        exscript.init(**variables)
        exscript.define(__filename__ = self.exscript_file)
        exscript.define(__runner__   = self)
        exscript.define(__exscript__ = parent)

        # One logfile per host.
        logfile       = None
        error_logfile = None
        if self.logdir is None:
            sequence = Sequence(name = this_host)
        else:
            logfile       = os.path.join(self.logdir, this_host + '.log')
            error_logfile = logfile + '.error'
            overwrite     = self.overwrite_logs
            sequence      = LoggedSequence(name          = this_host,
                                           logfile       = logfile,
                                           error_logfile = error_logfile,
                                           overwrite_log = overwrite)

        # Choose the protocol.
        if this_proto == 'telnet':
            protocol = __import__('termconnect.Telnet',
                                  globals(),
                                  locals(),
                                  'Telnet')
        elif this_proto in ('ssh', 'ssh1', 'ssh2'):
            protocol = __import__('termconnect.SSH',
                                  globals(),
                                  locals(),
                                  'SSH')
        else:
            print 'Unsupported protocol %s' % this_proto
            return None

        # Build the sequence.
        noecho       = kwargs.get('no-echo',           False)
        key          = kwargs.get('ssh-key',           None)
        av           = kwargs.get('ssh-auto-verify',   None)
        nip          = kwargs.get('no-initial-prompt', False)
        nop          = kwargs.get('no-prompt',         False)
        authenticate = not kwargs.get('no-authentication', False)
        echo         = parent.get_max_threads() == 1 and not noecho
        wait         = not nip and not nop
        if this_proto == 'ssh1':
            ssh_version = 1
        elif this_proto == 'ssh2':
            ssh_version = 2
        else:
            ssh_version = None # auto-select
        protocol_args = {'echo':        echo,
                         'auto_verify': av,
                         'ssh_version': ssh_version}
        if url.port is not None:
            protocol_args['port'] = url.port
        sequence.add(Connect(protocol, this_host, **protocol_args))
        if key is None and authenticate:
            sequence.add(Authenticate(this_user,
                                      password = this_password,
                                      wait     = wait))
        elif authenticate:
            sequence.add(Authenticate(this_user,
                                      key_file = key,
                                      wait     = wait))
        sequence.add(CommandScript(exscript))
        sequence.add(Close())
        return sequence


    def run(self, parent, **kwargs):
        n_connections = parent.get_max_threads()

        for hostname in self.hostnames[:]:
            # To save memory, limit the number of parsed (=in-memory) items.
            while parent.workqueue.get_length() > n_connections * 2:
                time.sleep(1)
                gc.collect()

            self._dbg(1, 'Building sequence for %s.' % hostname)
            sequence = self._get_sequence(parent, hostname, **kwargs)
            parent.workqueue.enqueue(sequence)