# ----------------------------------------------------------------------
# |
# |  Plugin.py
# |
# |  David Brownell <db@DavidBrownell.com>
# |      2020-07-16 17:21:59
# |
# ----------------------------------------------------------------------
# |
# |  Copyright David Brownell 2020
# |  Distributed under the Boost Software License, Version 1.0. See
# |  accompanying file LICENSE_1_0.txt or copy at
# |  http://www.boost.org/LICENSE_1_0.txt.
# |
# ----------------------------------------------------------------------
"""Contains the Plugin object"""

import os
import re

import CommonEnvironment
from CommonEnvironment import Interface

from CommonEnvironmentEx.CompilerImpl.GeneratorPluginFrameworkImpl.PluginBase import PluginBase

# ----------------------------------------------------------------------
_script_fullpath                            = CommonEnvironment.ThisFullpath()
_script_dir, _script_name                   = os.path.split(_script_fullpath)
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
class Plugin(PluginBase):
    """Abstract base class for HttpCodeGenerator plugins"""

    # ----------------------------------------------------------------------
    # |
    # |  Public Data
    # |
    # ----------------------------------------------------------------------
    URI_PARAMETER_REGEX                     = re.compile(r"\{(?P<name>.+?)\}")

    # SimpleSchema statements are represented as strings in the incoming file,
    # however some Plugins may want to interact with those elements as compiled
    # SimpleSchema objects rather than strings. In those scenarios, set this value
    # to True in derived classes. This operation is potentially expensive, which
    # is why it is disabled by default.
    COMPILE_SIMPLE_SCHEMA_STATEMENTS        = False

    # ----------------------------------------------------------------------
    # |
    # |  Public Methods
    # |
    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.abstractmethod
    def Generate(
        http_code_generator,
        invoke_reason,
        output_dir,
        endpoints,
        status_stream,
        verbose_stream,
        verbose,
        **custom_settings
    ):
        raise Exception("Abstract method")
