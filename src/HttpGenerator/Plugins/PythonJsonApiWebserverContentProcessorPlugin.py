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

import importlib
import os
import pickle
import shutil
import sys
import textwrap

from collections import namedtuple, OrderedDict

import six

import CommonEnvironment
from CommonEnvironment.CallOnExit import CallOnExit
from CommonEnvironment import FileSystem
from CommonEnvironment import Interface
from CommonEnvironment import Process
from CommonEnvironment.Shell.All import CurrentShell
from CommonEnvironment import StringHelpers
from CommonEnvironment import TaskPool

from CommonEnvironmentEx.Package import InitRelativeImports

# ----------------------------------------------------------------------
_script_fullpath                            = CommonEnvironment.ThisFullpath()
_script_dir, _script_name                   = os.path.split(_script_fullpath)
# ----------------------------------------------------------------------

with InitRelativeImports():
    from .Impl.RestVisitor import RestVisitor
    from ..Plugin import Plugin as PluginBase


# ----------------------------------------------------------------------
# |  Load the output parsers
OutputParserInfo                            = namedtuple(
    "InputParserInfo",
    [
        "Mod",
        "SerializeFunc",
    ],
)

OUTPUT_PARSERS                              = OrderedDict()

for parser, file_extensions in [
    ("Json", [".json"]),
    ("Xml", [".xml"]),
    ("Yaml", [".yaml", ".yml"]),
]:
    generated_filename = os.path.join(
        _script_dir,
        "..",
        "SimpleSchema",
        "GeneratedCode",
        "Python{}".format(parser),
        "Python{parser}_Python{parser}Serialization.py".format(
            parser=parser,
        ),
    )
    assert os.path.isfile(generated_filename), generated_filename

    dirname, basename = os.path.split(generated_filename)
    basename = os.path.splitext(basename)[0]

    sys.path.insert(0, dirname)
    with CallOnExit(lambda: sys.path.pop(0)):
        mod = importlib.import_module(basename)
        assert mod

    serialize_func = getattr(mod, "Serialize")
    assert serialize_func

    OUTPUT_PARSERS[tuple(file_extensions)] = OutputParserInfo(mod, serialize_func)


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
        filenames = []

        input_filenames = context["inputs"]

        for input in input_filenames:
            basename, ext = os.path.splitext(os.path.basename(input))

            filenames.append("{}.JsonApi.{}".format(basename, ext))

        cls._input_filenames = input_filenames

        filenames += [
            "__init__.py",
            "JsonApiWebserverContentProcessor.py",
            os.path.join("Impl", "__init__.py"),
            os.path.join("Impl", "http_schema_PythonJsonSerialization.py"),
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

        # Generate the modified http output
        for input_filename in cls._input_filenames:
            assert input_filename in roots, input_filename

            updated_endpoints = cls._UpdateEndpointInfo(roots[input_filename])
            cls._WriteEndpoint(updated_endpoints, filenames.pop(0))

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
                    cls._ExtractSimpleSchemaContent(roots, temp_dir)

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
    def _UpdateEndpointInfo(endpoint_info):
        pass # BugBug: remove added functionality, update content

        return endpoint_info

    # ----------------------------------------------------------------------
    @staticmethod
    def _WriteEndpoint(endpoint_info, output_filename):
        ext = os.path.splitext(output_filename)[1]

        for output_extensions, output_parser in six.iteritems(OUTPUT_PARSERS):
            if ext not in output_extensions:
                continue

            with open(output_filename, "w") as f:
                f.write(
                    output_parser.SerializeFunc(
                        endpoint_info,
                        to_string=True,
                    ),
                )

            break

    # ----------------------------------------------------------------------
    @staticmethod
    def _CompileSimpleSchemaContent(temp_dir, simple_schema_filename, output_stream, verbose):
        command_line_template = '"{script}" Generate {{plugin}} http_schema "{output_dir}" "/input={input_filename}" "/output_data_filename_prefix={{plugin}}"{verbose}'.format(
            script=CurrentShell.CreateScriptName("SimpleSchemaGenerator"),
            output_dir=temp_dir,
            input_filename=simple_schema_filename,
            verbose=" /verbose" if verbose else "",
        )

        # ----------------------------------------------------------------------
        def Invoke(plugin, output_stream):
            command_line = command_line_template.format(
                plugin=plugin,
            )

            result, output = Process.Execute(command_line)

            if verbose or result != 0:
                output_stream.write(output)

            return result

        # ----------------------------------------------------------------------

        return TaskPool.Execute(
            [
                TaskPool.Task("PythonJson", lambda output_stream: Invoke("PythonJson", output_stream)),
                TaskPool.Task("Pickle", lambda output_stream: Invoke("Pickle", output_stream)),
            ],
            output_stream,
            progress_bar=True,
            verbose=verbose,
        )

    # ----------------------------------------------------------------------
    @staticmethod
    def _ExtractSimpleSchemaContent(roots, temp_dir):
        # BugBug: Pickling may not be necessary

        # Process the pickled content
        pickle_path_filename = os.path.join(temp_dir, "http_schema.path")
        assert os.path.isfile(pickle_path_filename)

        pickle_filename = os.path.join(temp_dir, "http_schema.pickle")
        assert os.path.isfile(pickle_filename)

        with open(pickle_path_filename) as f:
            pickle_path = f.read().strip()
            assert os.path.isdir(pickle_path), pickle_path

        sys.path.insert(0, pickle_path)
        with CallOnExit(lambda: sys.path.pop(0)):
            with open(pickle_filename, "rb") as f:
                content = pickle.load(f)

        # ----------------------------------------------------------------------
        def FindContent(content, content_name):
            for item in content:
                if item.Name == content_name:
                    return item

            return None

        # ----------------------------------------------------------------------
        def ProcessEndpoint(content, endpoint, endpoint_index, name_prefix):
            endpoint_name = "endpoint_{}".format(endpoint_index)

            content = FindContent(content, endpoint_name)
            if content is None:
                return

            for variable_index, variable in enumerate(endpoint.variables):
                variable_name = "variable_{}".format(variable_index)

                variable_element = FindContent(content.Children, variable_name)

                variable.simple_schema = {
                    "string" : variable.simple_schema,
                    "type_info" : variable_element.TypeInfo.Items[variable.name],
                    "serialization_method" : "Deserializer.{}{}_{}_{}".format(
                        name_prefix,
                        endpoint_name,
                        variable_name,
                        variable.name,
                    ),
                }

            for method_index, method in enumerate(endpoint.methods):
                method_name = "method_{}".format(method_index)

                method_element = FindContent(content.Children, method_name)
                if method_element is None:
                    continue

                for request_index, request in enumerate(method.requests):
                    request_name = "request_{}".format(request_index)

                    request_element = FindContent(method_element.Children, request_name)
                    if request_element is None:
                        continue

                    for prefix, items in [
                        ("header_", request.headers),
                        ("query_", request.query_items),
                        ("form_", request.form_items),
                    ]:
                        for item_index, item in enumerate(items):
                            item_name = "{}{}".format(prefix, item_index)

                            item_element = FindContent(request_element.Children, item_name)

                            item.simple_schema = {
                                "string" : item.simple_schema,
                                "type_info" : item_element.TypeInfo.Items[item.name],
                                "serialization_method" : "Deserializer.{}{}_{}_{}_{}_{}".format(
                                    name_prefix,
                                    endpoint_name,
                                    method_name,
                                    request_name,
                                    item_name,
                                    item.name,
                                ),
                            }

                    if request.body:
                        body_element = FindContent(request_element.Children, "body")

                        request.body.simple_schema = {
                            "string" : request.body.simple_schema,
                            "type_info" : body_element.TypeInfo,
                            "serialization_method" : "Deserializer.{}_{}_{}_{}_body".format(
                                name_prefix,
                                endpoint_name,
                                method_name,
                                request_name,
                            ),
                        }

                for response_index, response in enumerate(method.responses):
                    response_name = "response_{}".format(response_index)

                    response_element = FindContent(method_element.Children, response_name)
                    if response_element is None:
                        continue

                    for content_type_index, content_type in enumerate(response.contents):
                        content_name = "content_{}".format(content_type_index)

                        content_type_element = FindContent(response_element.Children, content_name)
                        if content_type_element is None:
                            continue

                        for prefix, items in [
                            ("header_", content_type.headers),
                        ]:
                            for item_index, item in enumerate(items):
                                item_name = "{}{}".format(prefix, item_index)

                                item_element = FindContent(content_type_element.Children, item_name)

                                item.simple_schema = {
                                    "string" : item.simple_schema,
                                    "type_info" : item_element.TypeInfo.Items[item.name],
                                    "serialization_method" : "Serializer.{}{}_{}_{}_{}_{}_{}".format(
                                        name_prefix,
                                        endpoint_name,
                                        method_name,
                                        response_name,
                                        content_name,
                                        item_name,
                                        item.name,
                                    ),
                                }

                        if content_type.body:
                            body_element = FindContent(content_type_element.Children, "body")

                            content_type.body.simple_schema = {
                                "string" : content_type.body.simple_schema,
                                "type_info" : body_element.TypeInfo,
                                "serialization_method" : "Serializer.{}{}_{}_{}_{}_body".format(
                                    name_prefix,
                                    endpoint_name,
                                    method_name,
                                    response_name,
                                    content_name,
                                ),
                            }

            for child_index, child in enumerate(endpoint.children):
                ProcessEndpoint(content.Children, child, child_index, "{}{}_".format(name_prefix, endpoint_name))

        # ----------------------------------------------------------------------

        endpoint_index = 0

        for root in six.itervalues(roots):
            for endpoint in root.endpoints:
                ProcessEndpoint(content, endpoint, endpoint_index, "")
                endpoint_index += 1


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

# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
@Interface.staticderived
class _RestVisitor(RestVisitor):

    # ----------------------------------------------------------------------
    def __init__(
        self,
        index=None,
    ):
        self.Index                          = index

        self._uri_stack                     = []
        self._all_uri_variables             = []

        self._helpers                       = OrderedDict()
        self._content                       = []

    # ----------------------------------------------------------------------
    @property
    def Helpers(self):
        return self._helpers.values()

    @property
    def Content(self):
        return self._content

    # ----------------------------------------------------------------------
    @Interface.override
    def OnEndpointBegin(self, endpoint, endpoint_type, name_stack):
        self._uri_stack.append(endpoint.uri)
        self._all_uri_variables.append(endpoint.variables)

        method_name = "_{}_ParseIds".format(endpoint.unique_name)

        # BugBug

    # ----------------------------------------------------------------------
    @Interface.override
    def OnEndpointEnd(self, endpoint, endpoint_type):
        pass # BugBug

    # ----------------------------------------------------------------------
    @Interface.override
    def OnPost(self, endpoint, pascal_name, method):
        # Create
        pass # BugBug

    # ----------------------------------------------------------------------
    @Interface.override
    def OnGetItem(self, endpoint, pascal_name, method):
        # Read
        pass # BugBug

    # ----------------------------------------------------------------------
    @Interface.override
    def OnPatchItem(self, endpoint, pascal_name, method):
        # Update
        pass # BugBug

    # ----------------------------------------------------------------------
    @Interface.override
    def OnDeleteItem(self, endpoint, pascal_name, method):
        # Delete (single)
        pass # BugBug

    # ----------------------------------------------------------------------
    @Interface.override
    def OnGetItems(self, endpoint, pascal_name, method):
        # Enumerate
        pass # BugBug
