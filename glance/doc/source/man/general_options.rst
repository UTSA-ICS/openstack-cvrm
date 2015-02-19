  **-h, --help**
        Show the help message and exit

  **--version**
        Print the version number and exit

  **-v, --verbose**
        Print more verbose output

  **--noverbose**
        Disable verbose output

  **-d, --debug**
        Print debugging output (set logging level to DEBUG instead of
        default WARNING level)

  **--nodebug**
        Disable debugging output

  **--use-syslog**
        Use syslog for logging

  **--nouse-syslog**
        Disable the use of syslog for logging

  **--syslog-log-facility SYSLOG_LOG_FACILITY**
        syslog facility to receive log lines

  **--config-dir DIR**
        Path to a config directory to pull \*.conf files from. This
        file set is sorted, so as to provide a predictable parse order
        if individual options are over-ridden. The set is parsed after
        the file(s) specified via previous --config-file, arguments hence
        over-ridden options in the directory take precedence. This means
        that configuration from files in a specified config-dir will
        always take precedence over configuration from files specified
        by --config-file, regardless to argument order.

  **--config-file PATH**
        Path to a config file to use. Multiple config files can be
        specified by using this flag multiple times, for example,
        --config-file <file1> --config-file <file2>. Values in latter
        files take precedence.

  **--log-config-append PATH**
  **--log-config PATH**
        The name of logging configuration file. It does not
        disable existing loggers, but just appends specified
        logging configuration to any other existing logging
        options. Please see the Python logging module documentation
        for details on logging configuration files. The log-config
        name for this option is depcrecated.

  **--log-format FORMAT**
        A logging.Formatter log message format string which may use any
        of the available logging.LogRecord attributes. Default: None

  **--log-date-format DATE_FORMAT**
        Format string for %(asctime)s in log records. Default: None

  **--log-file PATH, --logfile PATH**
        (Optional) Name of log file to output to. If not set, logging
        will go to stdout.

  **--log-dir LOG_DIR, --logdir LOG_DIR**
        (Optional) The directory to keep log files in (will be prepended
        to --log-file)
