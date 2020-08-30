# ----------------------------------------------------------------------
# |
# |  PythonNullWebserverContentProcessorPlugin.py
# |
# |  David Brownell <db@DavidBrownell.com>
# |      2020-08-28 22:15:38
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
import textwrap

import six

import CommonEnvironment
from CommonEnvironment import Interface
from CommonEnvironment import StringHelpers

from CommonEnvironmentEx.Package import InitRelativeImports

# ----------------------------------------------------------------------
_script_fullpath                            = CommonEnvironment.ThisFullpath()
_script_dir, _script_name                   = os.path.split(_script_fullpath)
# ----------------------------------------------------------------------

with InitRelativeImports():
    from ..Plugin import Plugin as PluginBase

# ----------------------------------------------------------------------
@Interface.staticderived
class Plugin(PluginBase):

    # ----------------------------------------------------------------------
    # |  Public Properties
    Name                                    = Interface.DerivedProperty("PythonNullWebserverContentProcessor")
    Description                             = Interface.DerivedProperty("Noop ContentProcessor used by generated Webservers")

    # ----------------------------------------------------------------------
    # |  Public Methods
    @staticmethod
    @Interface.override
    def IsValidEnvironment():
        return True

    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.override
    def GenerateCustomSettingsAndDefaults():
        yield "no_helpers", False

    # ----------------------------------------------------------------------
    @classmethod
    @Interface.override
    def GenerateOutputFilenames(cls, context):
        filenames = ["__init__.py", "NullContentProcessor.py"]

        if not context["plugin_settings"]["no_helpers"]:
            filenames += [
                os.path.join("Helpers", "__init__.py"),
                os.path.join("Helpers", "ContentProcessors.py"),
            ]

        cls._filenames = filenames

        return filenames

    # ----------------------------------------------------------------------
    @classmethod
    @Interface.override
    def Generate(
        cls,
        http_code_generator,
        invoke_reason,
        output_dir,
        roots,
        status_stream,
        verbose_stream,
        verbose,

        no_helpers,
    ):
        file_header = cls._GenerateFileHeader(
            prefix="# ",
        )

        filenames = [os.path.join(output_dir, filename) for filename in cls._filenames]

        # Update the endpoints for processing
        endpoints = []

        for endpoint_info in six.itervalues(roots):
            endpoints += endpoint_info.endpoints

        # ----------------------------------------------------------------------
        def Impl(endpoint):
            endpoint.unique_name = endpoint.unique_name.replace(".", "")

            for child in endpoint.children:
                Impl(child)

        # ----------------------------------------------------------------------

        for endpoint in endpoints:
            Impl(endpoint)

        # __init__.py
        assert filenames

        status_stream.write("Writing '{}'...".format(filenames[0]))
        with status_stream.DoneManager():
            with open(filenames[0], "w") as f:
                f.write(file_header)

            filenames.pop(0)

        # NullContentProcessor.py
        assert filenames

        status_stream.write("Writing '{}'...".format(filenames[0]))
        with status_stream.DoneManager():
            with open(filenames[0], "w") as f:
                f.write(file_header)
                WriteNullContentProcessor(f, endpoints)

            filenames.pop(0)

        if not no_helpers:
            # __init__.py
            assert filenames

            status_stream.write("Writing '{}'...".format(filenames[0]))
            with status_stream.DoneManager():
                with open(filenames[0], "w") as f:
                    f.write(file_header)

                filenames.pop(0)

            # Authenticator
            assert filenames

            status_stream.write("Writing '{}'...".format(filenames[0]))
            with status_stream.DoneManager():
                with open(filenames[0], "w") as f:
                    f.write(file_header)
                    WriteContentProcessor(f)


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
def WriteNullContentProcessor(f, endpoints):
    content = []

    # ----------------------------------------------------------------------
    def Impl(endpoint):
        for method in endpoint.methods:
            content.append(
                textwrap.dedent(
                    """\
                    # ----------------------------------------------------------------------
                    @staticmethod
                    @Interface.override
                    def {unique_name}_{method_name}_Request(debug, uri_args, headers, form_data, query_data_body):
                        return None

                    # ----------------------------------------------------------------------
                    @staticmethod
                    @Interface.override
                    def {unique_name}_{method_name}_Response(get_ids_func, debug, uri, result):
                        return 200, [], "{unique_name}_{method_name}: {{}}".format(result)

                    """,
                ).format(
                    unique_name=endpoint.unique_name,
                    method_name=method.verb,
                ),
            )

        for child in endpoint.children:
            Impl(child)

    # ----------------------------------------------------------------------

    for endpoint in endpoints:
        Impl(endpoint)

    f.write(
        textwrap.dedent(
            """\
            import sys

            import six

            from CommonEnvironment import Interface

            # Get the ContentProcessorInterface
            for name, module in six.iteritems(sys.modules):
                if name.split(".")[-1] == "Interfaces" and hasattr(module, "ContentProcessorInterface"):
                    ContentProcessorInterface = module.ContentProcessorInterface
                    break

            # ----------------------------------------------------------------------
            @Interface.staticderived
            class NullContentProcessor(ContentProcessorInterface):
                {}
            """,
        ).format(StringHelpers.LeftJustify("".join(content).rstrip(), 4)),
    )


# ----------------------------------------------------------------------
def WriteContentProcessor(f):
    f.write(
        textwrap.dedent(
            """\
            from CommonEnvironmentEx.Package import InitRelativeImports

            with InitRelativeImports():
                from ..NullContentProcessor import NullContentProcessor

            content_processors = {
                None : NullContentProcessor,
            }
            """,
        ),
    )
