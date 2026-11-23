"""Statement Analyser: reads bank statements, categorizes, identifies merchants and reconciles accounts.

Use as a module:  from statement_analyser import analyse, analyse_full, mount, create_app   (see MODULE.md)
"""
from statement_analyser.module import DEFAULT_PREFIX, analyse, analyse_full, create_app, mount

__all__ = ["analyse", "analyse_full", "mount", "create_app", "DEFAULT_PREFIX"]
__version__ = "1.1.0"
