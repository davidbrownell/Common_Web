# ----------------------------------------------------------------------
# |
# |  PythonJsonApiWebserverContentProcessorPlugin.py
# |
# |  David Brownell <db@DavidBrownell.com>
# |      2020-08-29 20:07:18
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
import pickle
import textwrap

from collections import OrderedDict

import six

import CommonEnvironment
from CommonEnvironment.CallOnExit import CallOnExit
from CommonEnvironment import FileSystem
from CommonEnvironment import Interface
from CommonEnvironment import Process
from CommonEnvironment.Shell.All import CurrentShell
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
    Name                                    = Interface.DerivedProperty("PythonJsonApiWebserverContentProcessor")
    Description                             = Interface.DerivedProperty("Creates code that can process JsonApi content (https://jsonapi.org)")

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
        yield "temp_dir", ""
        yield "include_json_content_type", True
        yield "include_jsonp_content_type", True

    # ----------------------------------------------------------------------
    @classmethod
    @Interface.override
    def GenerateOutputFilenames(cls, context):
        filenames = [
            "__init__.py",
            "JsonApiWebserverContentProcessor.py",
            os.path.join("Impl", "__init__.py"),
        ]

        roots = pickle.loads(context["pickled_roots"])

        index = 0
        for endpoint_info in six.itervalues(roots):
            for _ in endpoint_info.endpoints:
                filenames += [os.path.join("Impl", "{}{}.py".format(prefix, index)) for prefix in ["Requests", "Responses"]]
                index += 1

        cls._num_impl_indexes = index

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
        temp_dir,
        include_json_content_type,
        include_jsonp_content_type,
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

        status_stream.write("Creating SimpleSchema content...")
        with status_stream.DoneManager(
            suffix="\n",
        ) as dm:
            # Create the temp directory and (optionally) remove it on exit
            if not temp_dir:
                delete_temp_dir = True
                temp_dir = CurrentShell.CreateTempDirectory()
            else:
                delete_temp_dir = False

            FileSystem.MakeDirs(temp_dir)

            # ----------------------------------------------------------------------
            def CleanupTempDir():
                if delete_temp_dir:
                    FileSystem.RemoveTree(temp_dir)

            # ----------------------------------------------------------------------

            with CallOnExit(CleanupTempDir):
                dm.stream.write("Working directory: {}\n\n".format(temp_dir))

                # Create the content
                dm.stream.write("Writing...")
                with dm.stream.DoneManager():
                    simple_schema_filename = cls._WriteSimpleSchemaContent(roots, temp_dir)

                # Compile the content
                dm.stream.write("Compiling...")
                with dm.stream.DoneManager() as compile_dm:
                    compile_dm.result = cls._CompileSimpleSchemaContent(
                        temp_dir,
                        simple_schema_filename,
                        compile_dm.stream,
                        verbose,
                    )

                    if compile_dm.result != 0:
                        return compile_dm.result

                # Extract the generated content
                dm.stream.write("Extracting...")
                with dm.stream.DoneManager():
                    # BugBug cls._ExtractSimpleSchemaContent(roots, temp_dir)
                    pass

                # __init__.py
                assert filenames

                status_stream.write("Writing '{}'...".format(filenames[0]))
                with status_stream.DoneManager():
                    with open(filenames[0], "w") as f:
                        f.write(file_header)

                    filenames.pop(0)

                # JsonApiContentProcessor.py
                assert filenames

                status_stream.write("Writing '{}'...".format(filenames[0]))
                with status_stream.DoneManager():
                    with open(filenames[0], "w") as f:
                        f.write(file_header)
                        WriteJsonApiContentProcessor(f, endpoints, cls._num_impl_indexes)

                    filenames.pop(0)


    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    @staticmethod
    def _CompileSimpleSchemaContent(temp_dir, simple_schema_filename, output_stream, verbose):
        command_line = '"{script}" Generate PythonJson http_schema "{output_dir}" "/input={input_filename}"{verbose}'.format(
            script=CurrentShell.CreateScriptName("SimpleSchemaGenerator"),
            output_dir=temp_dir,
            input_filename=simple_schema_filename,
            verbose=" /verbose" if verbose else "",
        )

        result, output = Process.Execute(command_line)

        if verbose or result != 0:
            output_stream.write(output)

        return result

# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
def WriteJsonApiContentProcessor(f, endpoints, num_helpers_indexes):
    f.write(
        textwrap.dedent(
            """\
            import re
            import sys
            import traceback

            import six

            from collections import OrderedDict

            from CommonEnvironment import Interface

            from CommonEnvironmentEx.Package import InitRelativeImports

            # ----------------------------------------------------------------------
            # Get ContentProcessorInterface
            for name, module in six.iteritems(sys.modules):
                if name.split('.')[-1] == "Interfaces" and hasattr(module, "ContentProcessorInterface"):
                    ContentProcessorInterface = module.ContentProcessorInterface
                    ImplementationInterface = module.ImplementationInterface

                    break

            # Get Exceptions
            for name, module in six.iteritems(sys.modules):
                if name.split('.')[-1] == "Exceptions" and hasattr(module, "WebserverException"):
                    Exceptions = module
                    break

            # ----------------------------------------------------------------------
            with InitRelativeImports():
                {packages}

            # ----------------------------------------------------------------------
            @Interface.staticderived
            class JsonApiWebserverContentProcessor(ContentProcessorInterface):
                # BugBug: content
                # BugBug: Helpers

                # ----------------------------------------------------------------------
                @staticmethod
                def _ExecuteRequest(func, debug):
                    try:
                        return func()

                    except Exceptions.WebserverException:
                        raise

                    except Exception as ex:
                        content = str(ex)

                        if hasattr(ex, "stack"):
                            content += " [{{}}]".format(" / ".join(ex.stack))

                        if debug:
                            content += "\\n\\n{{}}".format(traceback.format_exc())

                        raise Exceptions.BadRequestWebserverException(content)
            """,
        ).format(
            packages=StringHelpers.LeftJustify(
                "".join(
                    [
                        textwrap.dedent(
                            """\
                            from .Impl import Requests{index}
                            from .Impl import Responses{index}
                            """,
                        ).format(
                            index=index,
                        )
                        for index in range(num_helpers_indexes)
                    ]
                ).rstrip(),
                4,
            ),
        ),
    )
