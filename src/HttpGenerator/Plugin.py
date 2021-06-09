# ----------------------------------------------------------------------
# |
# |  Plugin.py
# |
# |  David Brownell <db@DavidBrownell.com>
# |      2020-07-16 17:21:59
# |
# ----------------------------------------------------------------------
# |
# |  Copyright David Brownell 2020-21
# |  Distributed under the Boost Software License, Version 1.0. See
# |  accompanying file LICENSE_1_0.txt or copy at
# |  http://www.boost.org/LICENSE_1_0.txt.
# |
# ----------------------------------------------------------------------
"""Contains the Plugin object"""

import hashlib
import os
import pickle
import re
import shutil
import sys
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

from CommonEnvironmentEx.CompilerImpl.GeneratorPluginFrameworkImpl.PluginBase import PluginBase

# ----------------------------------------------------------------------
_script_fullpath                            = CommonEnvironment.ThisFullpath()
_script_dir, _script_name                   = os.path.split(_script_fullpath)
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
class Plugin(PluginBase):
    """Abstract base class for HttpGenerator plugins"""

    # ----------------------------------------------------------------------
    # |
    # |  Public Data
    # |
    # ----------------------------------------------------------------------
    URI_PARAMETER_REGEX                     = re.compile(r"\{(?P<name>.+?)\}")

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
        roots,
        status_stream,
        verbose_stream,
        verbose,
        **custom_settings
    ):
        raise Exception("Abstract method")

    # ----------------------------------------------------------------------
    # |
    # |  Protected Methods
    # |
    # ----------------------------------------------------------------------
    @staticmethod
    def _WriteSimpleSchemaContent(roots, temp_dir):
        """Creates a .SimpleSchema file based on the simple_schema definitions provided"""

        temp_filename = CurrentShell.CreateTempFilename()

        # Write to a temp file, and only copy the content if it is different from the
        # existing file (if any).
        with open(temp_filename, "w") as f:
            delimiter_index = 0

            # ----------------------------------------------------------------------
            def ElementToString(element_name, simple_schema_content):
                return textwrap.dedent(
                    """\
                    <{}>:
                        {}

                    """,
                ).format(
                    element_name,
                    StringHelpers.LeftJustify(simple_schema_content, 4).rstrip(),
                )

            # ----------------------------------------------------------------------
            def SimpleSchemaContentToString(element_type, simple_schema_content):
                nonlocal delimiter_index

                result = textwrap.dedent(
                    """\
                    # {}-specific content
                    {}
                    <simple_schema_delimiter_{} string>

                    """,
                ).format(
                    element_type,
                    simple_schema_content,
                    delimiter_index,
                )

                delimiter_index += 1

                return result

            # ----------------------------------------------------------------------
            def GenerateEndpointContent(endpoint, endpoint_index):
                endpoint_sink = six.moves.StringIO()

                if endpoint.simple_schema_content:
                    endpoint_sink.write(SimpleSchemaContentToString("Endpoint", endpoint.simple_schema_content))

                for variable_index, variable in enumerate(endpoint.variables):
                    endpoint_sink.write(ElementToString("variable_{}".format(variable_index), variable.simple_schema))

                for method_index, method in enumerate(endpoint.methods):
                    method_sink = six.moves.StringIO()

                    if method.simple_schema_content:
                        method_sink.write(SimpleSchemaContentToString("Method", method.simple_schema_content))

                    for request_index, request in enumerate(method.requests):
                        request_sink = six.moves.StringIO()

                        for prefix, items in [
                            ("header_", request.headers),
                            ("query_", request.query_items),
                            ("form_", request.form_items),
                        ]:
                            for item_index, item in enumerate(items):
                                request_sink.write(ElementToString("{}{}".format(prefix, item_index), item.simple_schema))

                        if request.body:
                            request_sink.write(ElementToString("body", request.body.simple_schema))

                        request_sink = request_sink.getvalue()
                        if request_sink:
                            method_sink.write(ElementToString("request_{}".format(request_index), request_sink))

                    for response_index, response in enumerate(method.responses):
                        response_sink = six.moves.StringIO()

                        if response.simple_schema_content:
                            response_sink.write(SimpleSchemaContentToString("Response{}".format(response_index), response.simple_schema_content))

                        for content_index, content in enumerate(response.contents):
                            content_sink = six.moves.StringIO()

                            for prefix, items in [
                                ("header_", content.headers),
                            ]:
                                for item_index, item in enumerate(items):
                                    content_sink.write(ElementToString("{}{}".format(prefix, item_index), item.simple_schema))

                            if content.body:
                                content_sink.write(ElementToString("body", content.body.simple_schema))

                            content_sink = content_sink.getvalue()
                            if content_sink:
                                response_sink.write(ElementToString("content_{}".format(content_index), content_sink))

                        response_sink = response_sink.getvalue()
                        if response_sink:
                            method_sink.write(ElementToString("response_{}".format(response_index), response_sink))

                    method_sink = method_sink.getvalue()
                    if method_sink:
                        endpoint_sink.write(ElementToString("method_{}".format(method_index), method_sink))

                for child_index, child in enumerate(endpoint.children):
                    result = GenerateEndpointContent(child, child_index)
                    if result:
                        endpoint_sink.write(result)

                endpoint_sink = endpoint_sink.getvalue()
                if endpoint_sink:
                    return ElementToString("endpoint_{}".format(endpoint_index), endpoint_sink)

                return None

            # ----------------------------------------------------------------------

            for root in six.itervalues(roots):
                if root.simple_schema_content:
                    result = SimpleSchemaContentToString("Global", root.simple_schema_content)
                    assert result

                    f.write(result)

            endpoint_index = 0
            for root in six.itervalues(roots):
                for endpoint in root.endpoints:
                    result = GenerateEndpointContent(endpoint, endpoint_index)
                    if result:
                        f.write(result)

                    endpoint_index += 1

        # Determine if the file's contents have changed
        simple_schema_filename = os.path.join(temp_dir, "http_schema.SimpleSchema")

        should_copy = False

        if not os.path.isfile(simple_schema_filename):
            should_copy = True
            FileSystem.MakeDirs(temp_dir)
        else:
            # ----------------------------------------------------------------------
            def CalcHash(filename):
                hash = hashlib.sha256()

                with open(filename, "rb") as f:
                    while True:
                        content = f.read(4096)
                        if not content:
                            break

                        hash.update(content)

                return hash.hexdigest()

            # ----------------------------------------------------------------------

            should_copy = CalcHash(temp_filename) != CalcHash(simple_schema_filename)

        if should_copy:
            shutil.copyfile(temp_filename, simple_schema_filename)

        return simple_schema_filename

    # ----------------------------------------------------------------------
    @staticmethod
    def _CompilePickledSimpleSchemaContent(temp_dir, simple_schema_filename, output_stream, verbose):
        result, output = Process.Execute(
            '"{script}" Generate Pickle http_schema "{output_dir}" "/input={input_filename}" "/output_data_filename_prefix=Pickle"{verbose}'.format(
                script=CurrentShell.CreateScriptName("SimpleSchemaGenerator"),
                output_dir=temp_dir,
                input_filename=simple_schema_filename,
                verbose=" /verbose" if verbose else "",
            ),
        )

        if verbose:
            output_stream.write(output)

        return result

    # ----------------------------------------------------------------------
    @staticmethod
    def _ExtractPickledSimpleSchemaContent(roots, temp_dir):
        # Load the pickled content
        pickle_path_filename = os.path.join(temp_dir, "http_schema.path")
        assert os.path.isfile(pickle_path_filename), pickle_path_filename

        pickle_filename = os.path.join(temp_dir, "http_schema.pickle")
        assert os.path.isfile(pickle_filename), pickle_filename

        with open(pickle_path_filename) as f:
            pickle_path = f.read().strip()
            assert os.path.isdir(pickle_path), pickle_path

        sys.path.insert(0, pickle_path)
        with CallOnExit(lambda: sys.path.pop(0)):
            with open(pickle_filename, "rb") as f:
                content = pickle.load(f)

        # Extract the content

        # ----------------------------------------------------------------------
        def FindElement(content, content_name):
            for item in content:
                if item.Name == content_name:
                    return item

            return None

        # ----------------------------------------------------------------------
        def GetTypeInfo(element):
            if len(element.TypeInfo.Items) != 1:
                raise Exception("Multiple values were found '{}'".format(list(six.iterkeys(element.TypeInfo.Items))))

            return next(six.itervalues(element.TypeInfo.Items))

        # ----------------------------------------------------------------------
        def ProcessEndpoint(content, endpoint, endpoint_index, name_prefix):
            endpoint_name = "endpoint_{}".format(endpoint_index)

            content = FindElement(content, endpoint_name)
            if content is None:
                return

            for variable_index, variable in enumerate(endpoint.variables):
                element = FindElement(content.Children, "variable_{}".format(variable_index))
                assert element

                variable.simple_schema = {
                    "string" : variable.simple_schema,
                    "element" : element,
                    "type_info" : GetTypeInfo(element),
                }

            for method_index, method in enumerate(endpoint.methods):
                method_name = "method_{}".format(method_index)

                method_element = FindElement(content.Children, method_name)
                if method_element is None:
                    continue

                for request_index, request in enumerate(method.requests):
                    request_name = "request_{}".format(request_index)

                    request_element = FindElement(method_element.Children, request_name)
                    if request_element is None:
                        continue

                    for prefix, items in [
                        ("header_", request.headers),
                        ("query_", request.query_items),
                        ("form_", request.form_items),
                    ]:
                        for item_index, item in enumerate(items):
                            element = FindElement(request_element.Children, "{}{}".format(prefix, item_index))
                            assert element

                            item.simple_schema = {
                                "string" : item.simple_schema,
                                "element" : element,
                                "type_info" : GetTypeInfo(element),
                            }

                    if request.body:
                        element = FindElement(request_element.Children, "body")
                        assert element

                        request.body.simple_schema = {
                            "string" : request.body.simple_schema,
                            "element" : element,
                            "type_info" : GetTypeInfo(element),
                        }

                for response_index, response in enumerate(method.responses):
                    response_name = "response_{}".format(response_index)

                    response_element = FindElement(method_element.Children, response_name)
                    if response_element is None:
                        continue

                    for content_type_index, content_type in enumerate(response.contents):
                        content_name = "content_{}".format(content_type_index)

                        content_type_element = FindElement(response_element.Children, content_name)
                        if content_type_element is None:
                            continue

                        for prefix, items in [
                            ("header_", content_type.headers),
                        ]:
                            for item_index, item in enumerate(items):
                                item_name = "{}{}".format(prefix, item_index)

                                element = FindElement(content_type_element.Children, item_name)
                                assert element

                                item.simple_schema = {
                                    "string" : item.simple_schema,
                                    "element" : element,
                                    "type_info" : GetTypeInfo(element),
                                }

                        if content_type.body:
                            element = FindElement(content_type_element.Children, "body")
                            assert element

                            content_type.body.simple_schema = {
                                "string" : content_type.body.simple_schema,
                                "element" : element,
                                "type_info" : GetTypeInfo(element),
                            }

            for child_index, child in enumerate(endpoint.children):
                ProcessEndpoint(content.Children, child, child_index, "{}{}_".format(name_prefix, endpoint_name))

        # ----------------------------------------------------------------------

        # Extract the global schema
        global_simple_schema_index = 0

        for root in six.itervalues(roots):
            if not root.simple_schema_content:
                continue

            starting_global_simple_schema_index = global_simple_schema_index

            while global_simple_schema_index < len(content):
                if content[global_simple_schema_index].Name.startswith("simple_schema_delimiter_"):
                    break

                global_simple_schema_index += 1

            root.simple_schema_content = {
                "string" : root.simple_schema_content,
                "elements" : content[starting_global_simple_schema_index : global_simple_schema_index],
            }

            # Move beyond the delimiter
            global_simple_schema_index += 1

        # Extract the endpoints
        endpoint_index = 0

        for root in six.itervalues(roots):
            for endpoint in root.endpoints:
                ProcessEndpoint(content, endpoint, endpoint_index, "")
                endpoint_index += 1
