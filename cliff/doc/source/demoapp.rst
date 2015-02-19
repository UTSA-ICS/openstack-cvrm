========================
 Exploring the Demo App
========================

The cliff source package includes a ``demoapp`` directory containing
an example main program with several command plugins.

Setup
=====

To install and experiment with the demo app you should create a
virtual environment and activate it. This will make it easy to remove
the app later, since it doesn't do anything useful and you aren't
likely to want to hang onto it after you understand how it works.

::

  $ pip install virtualenv
  $ virtualenv .venv
  $ . .venv/bin/activate
  (.venv)$ 

Next, install cliff in the same environment.

::

  (.venv)$ python setup.py install

Finally, install the demo application into the virtual environment.

::

  (.venv)$ cd demoapp
  (.venv)$ python setup.py install

Usage
=====

Both cliff and the demo installed, you can now run the command
``cliffdemo``.

For basic command usage instructions and a list of the commands
available from the plugins, run::

  (.venv)$ cliffdemo -h

or::

  (.venv)$ cliffdemo --help

Run the ``simple`` command by passing its name as argument to ``cliffdemo``.

::

  (.venv)$ cliffdemo simple

The ``simple`` command prints this output to the console:

::

  sending greeting
  hi!


To see help for an individual command, use the ``help`` command::

  (.venv)$ cliffdemo help files

The Source
==========

The ``cliffdemo`` application is defined in a ``cliffdemo`` package
containing several modules. 

main.py
-------

The main application is defined in ``main.py``:

.. literalinclude:: ../../demoapp/cliffdemo/main.py
   :linenos:

The :class:`DemoApp` class inherits from :class:`App` and overrides
:func:`__init__` to set the program description and version number. It
also passes a :class:`CommandManager` instance configured to look for
plugins in the ``cliff.demo`` namespace.

The :func:`initialize_app` method of :class:`DemoApp` will be invoked
after the main program arguments are parsed, but before any command
processing is performed and before the application enters interactive
mode. This hook is intended for opening connections to remote web
services, databases, etc. using arguments passed to the main
application.

The :func:`prepare_to_run_command` method of :class:`DemoApp` will be
invoked after a command is identified, but before the command is given
its arguments and run. This hook is intended for pre-command
validation or setup that must be repeated and cannot be handled by
:func:`initialize_app`.

The :func:`clean_up` method of :class:`DemoApp` is invoked after a
command runs. If the command raised an exception, the exception object
is passed to :func:`clean_up`. Otherwise the ``err`` argument is
``None``.

The :func:`main` function defined in ``main.py`` is registered as a
console script entry point so that :class:`DemoApp` can be run from
the command line (see the discussion of ``setup.py`` below).

simple.py
---------

Two commands are defined in ``simple.py``:

.. literalinclude:: ../../demoapp/cliffdemo/simple.py
   :linenos:

:class:`Simple` demonstrates using logging to emit messages on the
console at different verbose levels.

::
    
    (.venv)$ cliffdemo simple
    sending greeting
    hi!

    (.venv)$ cliffdemo -v simple
    prepare_to_run_command Simple
    sending greeting
    debugging
    hi!
    clean_up Simple

    (.venv)$ cliffdemo -q simple
    hi!

:class:`Error` always raises a :class:`RuntimeError` exception when it
is invoked, and can be used to experiment with the error handling
features of cliff.

::
    
    (.venv)$ cliffdemo error
    causing error
    ERROR: this is the expected exception
    
    (.venv)$ cliffdemo -v error
    prepare_to_run_command Error
    causing error
    ERROR: this is the expected exception
    clean_up Error
    got an error: this is the expected exception
    
    (.venv)$ cliffdemo --debug error
    causing error
    this is the expected exception
    Traceback (most recent call last):
      File ".../cliff/app.py", line 218, in run_subcommand
        result = cmd.run(parsed_args)
      File ".../cliff/command.py", line 43, in run
        self.take_action(parsed_args)
      File ".../demoapp/cliffdemo/simple.py", line 24, in take_action
        raise RuntimeError('this is the expected exception')
    RuntimeError: this is the expected exception
    Traceback (most recent call last):
      File "/Users/dhellmann/Envs/cliff/bin/cliffdemo", line 9, in <module>
        load_entry_point('cliffdemo==0.1', 'console_scripts', 'cliffdemo')()
      File ".../demoapp/cliffdemo/main.py", line 33, in main
        return myapp.run(argv)
      File ".../cliff/app.py", line 160, in run
        result = self.run_subcommand(remainder)
      File ".../cliff/app.py", line 218, in run_subcommand
        result = cmd.run(parsed_args)
      File ".../cliff/command.py", line 43, in run
        self.take_action(parsed_args)
      File ".../demoapp/cliffdemo/simple.py", line 24, in take_action
        raise RuntimeError('this is the expected exception')
    RuntimeError: this is the expected exception

.. _demoapp-list:

list.py
-------

``list.py`` includes a single command derived from
:class:`cliff.lister.Lister` which prints a list of the files in the
current directory.

.. literalinclude:: ../../demoapp/cliffdemo/list.py
   :linenos:

:class:`Files` prepares the data, and :class:`Lister` manages the
output formatter and printing the data to the console.

::
    
    (.venv)$ cliffdemo files
    +---------------+------+
    |      Name     | Size |
    +---------------+------+
    | build         |  136 |
    | cliffdemo.log | 2546 |
    | Makefile      | 5569 |
    | source        |  408 |
    +---------------+------+
    
    (.venv)$ cliffdemo files -f csv
    "Name","Size"
    "build",136
    "cliffdemo.log",2690
    "Makefile",5569
    "source",408

.. _demoapp-show:

show.py
-------

``show.py`` includes a single command derived from
:class:`cliff.show.ShowOne` which prints the properties of the named
file.

.. literalinclude:: ../../demoapp/cliffdemo/show.py
   :linenos:

:class:`File` prepares the data, and :class:`ShowOne` manages the
output formatter and printing the data to the console.

::

    (.venv)$ cliffdemo file setup.py
    +---------------+--------------+
    |     Field     |    Value     |
    +---------------+--------------+
    | Name          | setup.py     |
    | Size          | 5825         |
    | UID           | 502          |
    | GID           | 20           |
    | Modified Time | 1335569964.0 |
    +---------------+--------------+


setup.py
--------

The demo application is packaged using distribute_, the modern
implementation of setuptools.

.. literalinclude:: ../../demoapp/setup.py
   :linenos:

The important parts of the packaging instructions are the
``entry_points`` settings. All of the commands are registered in the
``cliff.demo`` namespace. Each main program should define its own
command namespace so that it only loads the command plugins that it
should be managing.

.. _distribute: http://packages.python.org/distribute/
