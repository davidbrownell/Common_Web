# ----------------------------------------------------------------------
# |
# |  Build.py-ignore
# |
# |  David Brownell <db@DavidBrownell.com>
# |      2020-07-16 18:52:18
# |
# ----------------------------------------------------------------------
# |
# |  Copyright David Brownell 2020
# |  Distributed under the Boost Software License, Version 1.0. See
# |  accompanying file LICENSE_1_0.txt or copy at
# |  http://www.boost.org/LICENSE_1_0.txt.
# |
# ----------------------------------------------------------------------
"""Builds the HttpCodeGenerator input parsers"""

import os
import sys
import textwrap

import CommonEnvironment
from CommonEnvironment import BuildImpl
from CommonEnvironment import CommandLine
from CommonEnvironment import FileSystem
from CommonEnvironment import Process
from CommonEnvironment.Shell.All import CurrentShell
from CommonEnvironment.StreamDecorator import StreamDecorator

# ----------------------------------------------------------------------
_script_fullpath                            = CommonEnvironment.ThisFullpath()
_script_dir, _script_name                   = os.path.split(_script_fullpath)
# ----------------------------------------------------------------------

CONFIGURATIONS                              = [
    "PythonJson",
    "PythonXml",
    "PythonYaml",
]

# ----------------------------------------------------------------------
@CommandLine.EntryPoint
@CommandLine.Constraints(
    configuration=CommandLine.EnumTypeInfo(
        CONFIGURATIONS,
        arity="*",
    ),
    output_stream=None,
)
def Build(
    configuration=None,
    force=False,
    output_stream=sys.stdout,
    verbose=False,
):
    configurations = configuration or CONFIGURATIONS
    del configuration

    with StreamDecorator(output_stream).DoneManager(
        line_prefix="",
        prefix="\nResults: ",
        suffix="\n",
    ) as dm:
        input_file = os.path.join(_script_dir, "HttpCodeGenerator.SimpleSchema")
        assert os.path.isfile(input_file), input_file

        command_line_template = '{script} Generate {{plugin}} "{{plugin}}" "{{output_dir}}" "/input={input_file}"{force}{verbose}'.format(
            script=CurrentShell.CreateScriptName("SimpleSchemaGenerator"),
            input_file=input_file,
            force="" if not force else " /force",
            verbose="" if not verbose else " /verbose",
        )

        for index, configuration in enumerate(configurations):
            dm.stream.write("Executing '{}' ({} of {})...".format(configuration, index + 1, len(configurations)))
            with dm.stream.DoneManager(
                suffix="\n",
            ) as this_dm:
                command_line = command_line_template.format(
                    plugin=configuration,
                    output_dir=os.path.join(_script_dir, "GeneratedCode", configuration),
                )

                this_dm.result = Process.Execute(command_line, this_dm.stream)

        return dm.result


# ----------------------------------------------------------------------
@CommandLine.EntryPoint
@CommandLine.Constraints(
    configuration=CommandLine.EnumTypeInfo(
        CONFIGURATIONS,
        arity="*",
    ),
    output_stream=None,
)
def Clean(
    configuration=None,
    output_stream=sys.stdout,
):
    configurations = configuration or CONFIGURATIONS
    del configuration

    with StreamDecorator(output_stream).DoneManager(
        line_prefix="",
        prefix="\nResults: ",
        suffix="\n",
    ) as dm:
        for index, configuration in enumerate(configurations):
            dm.stream.write("Removing '{}' ({} of {})...".format(configuration, index + 1, len(configurations)))
            with dm.stream.DoneManager(
                suffix="\n",
            ) as this_dm:
                output_dir = os.path.join(_script_dir, "GeneratedCode", configuration)

                if not os.path.isdir(output_dir):
                    this_dm.stream.write("'{}' is not a valid directory.\n".format(output_dir))
                    continue

                FileSystem.RemoveTree(output_dir)

        return dm.result


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
def CommandLineSuffix():
    return textwrap.dedent(
        """\
        Where <configuration> can be:

        {}

        or omitted for all configurations.

        """,
    ).format(
        "\n".join(["    - {}".format(configuration) for configuration in CONFIGURATIONS]),
    )


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
if __name__ == "__main__":
    try:
        sys.exit(
            BuildImpl.Main(
                BuildImpl.Configuration(
                    name="HttpCodeGenerator_SimpleSchema",
                    requires_output_dir=False,
                ),
            ),
        )
    except KeyboardInterrupt:
        pass
