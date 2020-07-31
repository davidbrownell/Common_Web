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
import textwrap
import uuid

import six

import CommonEnvironment
from CommonEnvironment import FileSystem
from CommonEnvironment import Interface
from CommonEnvironment import StringHelpers

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

        FileSystem.MakeDirs(temp_dir)

        simple_schema_filename = os.path.join(temp_dir, "http_schema.SimpleSchema")

        with open(simple_schema_filename, "w") as f:
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
                return textwrap.dedent(
                    """\
                    # {}-specific content
                    {}
                    <simple_schema_delimiter_{} string>

                    """,
                ).format(
                    element_type,
                    simple_schema_content,
                    str(uuid.uuid4()).replace("-", ""),
                )

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

        return simple_schema_filename
