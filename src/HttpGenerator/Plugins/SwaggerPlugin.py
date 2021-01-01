# ----------------------------------------------------------------------
# |
# |  SwaggerPlugin.py
# |
# |  David Brownell <db@DavidBrownell.com>
# |      2020-07-16 17:25:49
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

import itertools
import json
import os
import textwrap

from collections import OrderedDict

import six

import CommonEnvironment
from CommonEnvironment.CallOnExit import CallOnExit
from CommonEnvironment import FileSystem
from CommonEnvironment import Interface
from CommonEnvironment import Process
from CommonEnvironment.Shell.All import CurrentShell
from CommonEnvironment.StreamDecorator import StreamDecorator

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

    # Notes for Swagger v3.0.3:
    #   - Multiple servers are not supported
    #   - Server Variables are not supported
    #   - externalDocs are not supported
    #   - security is not supported

    # ----------------------------------------------------------------------
    # |  Public Properties
    Name                                    = Interface.DerivedProperty("Swagger")
    Description                             = Interface.DerivedProperty("Generates Swagger API definitions (https://swagger.io/)")

    # ----------------------------------------------------------------------
    # |  Public Methods
    @staticmethod
    @Interface.override
    def IsValidEnvironment():
        return True

    # ----------------------------------------------------------------------
    REQUIRED_SETTINGS                       = set(
        [
            "open_api_version",
            "title",
            "api_version",
            "license_name",
            "server_uri",
        ],
    )

    @staticmethod
    @Interface.override
    def GenerateCustomSettingsAndDefaults():
        yield "temp_dir", ""

        yield "no_json", False
        yield "no_yaml", False

        yield "pretty_print", False

        yield "open_api_version", "3.0.3"

        yield "title", ""                   # Required
        yield "api_version", ""             # Required
        yield "description", ""
        yield "terms_of_service", ""

        yield "contact_name", ""
        yield "contact_uri", ""
        yield "contact_email", ""

        yield "license_name", ""            # Required
        yield "license_uri", ""

        yield "server_uri", ""              # Required
        yield "server_description", ""

    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.override
    def GenerateOutputFilenames(context):
        filenames = []

        if not context["plugin_settings"]["no_json"]:
            filenames.append("Swagger.json")

        if not context["plugin_settings"]["no_yaml"]:
            filenames.append("Swagger.yaml")

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
        **plugin_settings,
    ):
        for name in cls.REQUIRED_SETTINGS:
            assert name in plugin_settings, name
            if not plugin_settings[name]:
                raise Exception("'{}' is a required swagger arg".format(name)) from None

        temp_dir = plugin_settings.pop("temp_dir")
        no_json = plugin_settings.pop("no_json")
        no_yaml = plugin_settings.pop("no_yaml")
        pretty_print = plugin_settings.pop("pretty_print")

        if no_json and no_yaml:
            return 0

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
                        delete_temp_dir = False
                        return compile_dm.result

                # Extract the generated content
                dm.stream.write("Extracting...")
                with dm.stream.DoneManager():
                    try:
                        cls._ExtractSimpleSchemaContent(roots, temp_dir)

                        all_endpoints = OrderedDict([(k, v.endpoints) for k, v in six.iteritems(roots)])

                    except:
                        delete_temp_dir = False
                        raise

            endpoint_data = cls._GenerateEndpointData(all_endpoints, status_stream, **plugin_settings)

            if not no_json:
                cls._GenerateJsonContent(
                    status_stream,
                    endpoint_data,
                    os.path.join(output_dir, "Swagger.json"),
                    pretty_print=pretty_print,
                )

            if not no_yaml:
                cls._GenerateYamlContent(
                    status_stream,
                    endpoint_data,
                    os.path.join(output_dir, "Swagger.yaml"),
                )

        return 0

    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    @staticmethod
    def _CompileSimpleSchemaContent(temp_dir, simple_schema_filename, output_stream, verbose):
        command_line = '"{script}" Generate JsonSchema http_schema "{output_dir}" "/input={input_filename}"{verbose}'.format(
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
    @staticmethod
    def _ExtractSimpleSchemaContent(roots, temp_dir):
        schema_filename = os.path.join(temp_dir, "http_schema.schema.json")
        assert os.path.isfile(schema_filename), schema_filename

        with open(schema_filename) as f:
            json_schema = json.load(f)

        # Denormalize the definitions and properties

        resolved = set()

        # ----------------------------------------------------------------------
        def GetDefinitionElement(ref):
            assert ref.startswith("#/"), ref
            ref = ref[2:]

            d = json_schema

            for ref_item in ref.split("/"):
                assert ref_item in d, (ref, ref_item)
                d = d[ref_item]

            return d

        # ----------------------------------------------------------------------
        def Resolve(value):
            if isinstance(value, list):
                return [Resolve(item) for item in value]
            elif not isinstance(value, dict):
                return value

            if "$ref" in value:
                new_value = Resolve(GetDefinitionElement(value["$ref"]))

                for k, v in six.iteritems(value):
                    if k == "$ref":
                        continue

                    assert not isinstance(v, dict), v
                    assert not isinstance(v, list), v

                    new_value[k] = v

                return new_value

            if id(value) in resolved:
                return value

            resolved.add(id(value))

            for k, v in six.iteritems(value):
                value[k] = Resolve(v)

            return value

        # ----------------------------------------------------------------------

        Resolve(json_schema["definitions"])
        Resolve(json_schema["properties"])

        json_schema.pop("definitions")

        # Extract the simple schema content. Note that we can skip any simple_schema_content
        # values, as they were only necessary to create the simple_schema values associated
        # with headers, query_items, form_items, body, etc.

        # ----------------------------------------------------------------------
        def GetSchemaValue(
            dictionary,
            value,
            extract_single_child=False,
        ):
            if value not in dictionary:
                return None

            value = dictionary[value]

            if extract_single_child:
                assert "properties" in value, value
                properties = value["properties"]

                if len(properties) != 1:
                    raise Exception("Multiple values were found '{}'".format(list(six.iterkeys(properties))))

                property_name = next(six.iterkeys(properties))

                return (
                    property_name in value.get("required", []),
                    properties[property_name],
                )

            if "properties" in value:
                value = value["properties"]

            return value

        # ----------------------------------------------------------------------
        def ProcessEndpoint(endpoint_index, endpoint, json_schema):
            json_schema = GetSchemaValue(json_schema, "endpoint_{}".format(endpoint_index))
            if json_schema is None:
                return

            for variable_index, variable in enumerate(endpoint.variables):
                is_variable_required, variable_schema = GetSchemaValue(
                    json_schema,
                    "variable_{}".format(variable_index),
                    extract_single_child=True,
                )

                variable.simple_schema = {
                    "string" : variable.simple_schema,
                    "content" : variable_schema,
                    "is_required" : is_variable_required,
                }

            for method_index, method in enumerate(endpoint.methods):
                method_schema = GetSchemaValue(json_schema, "method_{}".format(method_index))
                if method_schema is None:
                    continue

                for request_index, request in enumerate(method.requests):
                    request_schema = GetSchemaValue(method_schema, "request_{}".format(request_index))
                    if request_schema is None:
                        continue

                    for prefix, items in [
                        ("header_", request.headers),
                        ("query_", request.query_items),
                        ("form_", request.form_items),
                    ]:
                        for item_index, item in enumerate(items):
                            is_item_required, item_schema = GetSchemaValue(
                                request_schema,
                                "{}{}".format(prefix, item_index),
                                extract_single_child=True,
                            )

                            item.simple_schema = {
                                "string" : item.simple_schema,
                                "content" : item_schema,
                                "is_required" : is_item_required,
                            }

                    if request.body:
                        is_required, body_schema = GetSchemaValue(
                            request_schema,
                            "body",
                            extract_single_child=True,
                        )

                        request.body.simple_schema = {
                            "string" : request.body.simple_schema,
                            "content" : body_schema,
                            "is_required" : is_required,
                        }

                for response_index, response in enumerate(method.responses):
                    response_schema = GetSchemaValue(method_schema, "response_{}".format(response_index))
                    if response_schema is None:
                        continue

                    for content_index, content in enumerate(response.contents):
                        content_schema = GetSchemaValue(response_schema, "content_{}".format(content_index))
                        if content_schema is None:
                            continue

                        for prefix, items in [
                            ("header_", content.headers),
                        ]:
                            for item_index, item in enumerate(items):
                                is_item_required, item_schema = GetSchemaValue(
                                    content_schema,
                                    "{}{}".format(prefix, item_index),
                                    extract_single_child=True,
                                )

                                item.simple_schema = {
                                    "string" : item.simple_schema,
                                    "content" : item_schema,
                                    "is_required" : is_item_required,
                                }

                        if content.body:
                            is_required, body_schema = GetSchemaValue(
                                content_schema,
                                "body",
                                extract_single_child=True,
                            )

                            content.body.simple_schema = {
                                "string" : content.body.simple_schema,
                                "content" : body_schema,
                                "is_required" : is_required,
                            }

            for child_index, child in enumerate(endpoint.children):
                ProcessEndpoint(child_index, child, json_schema)

        # ----------------------------------------------------------------------

        endpoint_index = 0

        for root in six.itervalues(roots):
            for endpoint in root.endpoints:
                ProcessEndpoint(endpoint_index, endpoint, json_schema["properties"])
                endpoint_index += 1

    # ----------------------------------------------------------------------
    @staticmethod
    def _GenerateEndpointData(
        all_endpoints,
        status_stream,
        open_api_version,
        title,
        api_version,
        description,
        terms_of_service,
        contact_name,
        contact_uri,
        contact_email,
        license_name,
        license_uri,
        server_uri,
        server_description,
    ):
        status_stream.write("\nProcessing endpoint data...")
        with status_stream.DoneManager() as dm:
            warning_stream = StreamDecorator(
                dm.stream,
                line_prefix="WARNING: ",
            )

            result = OrderedDict()

            result["openapi"] = open_api_version

            result["info"] = OrderedDict(
                [
                    ("title", title),
                    ("description", description),
                    ("termsOfService", terms_of_service),
                    ("version", api_version),
                ],
            )

            if contact_name:
                result["info"].setdefault("contact", OrderedDict())["name"] = contact_name
            if contact_uri:
                result["info"].setdefault("contact", OrderedDict())["url"] = contact_uri
            if contact_email:
                result["info"].setdefault("contact", OrderedDict())["email"] = contact_email

            result["info"]["license"] = OrderedDict([("name", license_name)])
            if license_uri:
                result["info"]["license"]["url"] = license_uri

            result["servers"] = [
                {
                    "url" : server_uri,
                    "description" : server_description,
                    # No support for variables
                },
            ]

            # Process the endpoints
            uri_parameters = OrderedDict()

            paths = OrderedDict()
            components = OrderedDict()
            tags = []

            # ----------------------------------------------------------------------
            def RemoveUriParameters(these_uri_parameters):
                for uri_parameter_name in these_uri_parameters:
                    assert uri_parameter_name in uri_parameters, uri_parameter_name
                    del uri_parameters[uri_parameter_name]

            # ----------------------------------------------------------------------
            def ParseEndpoint(endpoint):
                # Create the uri parameters for this endpoint
                these_uri_parameters = set()

                for variable in endpoint.variables:
                    parameter = OrderedDict(
                        [
                            ("name", variable.name),
                            ("in", "path"),
                            ("required", True),
                            ("allowEmptyValue", False),
                            ("style", "simple"),
                            ("schema", variable.simple_schema["content"]),
                        ],
                    )

                    if variable.description:
                        parameter["description"] = variable.description

                    uri_parameters[variable.name] = parameter
                    these_uri_parameters.add(variable.name)

                with CallOnExit(lambda: RemoveUriParameters(these_uri_parameters)):
                    this_tag_name = endpoint.group.replace(".", " > ") if endpoint.group else None
                    if this_tag_name:
                        tags.append(this_tag_name)

                    this_path = OrderedDict()

                    if endpoint.summary:
                        this_path["summary"] = endpoint.summary

                    if endpoint.description:
                        this_path["description"] = endpoint.description

                    if uri_parameters:
                        this_path["parameters"] = list(six.itervalues(uri_parameters))

                    for method in endpoint.methods:
                        this_method = OrderedDict()

                        if this_tag_name:
                            this_method["tags"] = [this_tag_name]

                        for potential_attr in [
                            "summary",
                            "description",
                        ]:
                            potential_value = getattr(method, potential_attr, None)
                            if potential_value:
                                this_method[potential_attr] = potential_value

                        # Write the request info
                        request_parameters = None
                        request_body_is_required = None
                        request_body_description = None
                        request_bodies = OrderedDict()

                        for request in method.requests:
                            # Process the request parameters
                            if request.headers or request.query_items:
                                if request_parameters is None:
                                    parameters = []

                                    for in_type, items in [
                                        ("header", request.headers),
                                        ("query", request.query_items),
                                    ]:
                                        for item in items:
                                            parameters.append(
                                                {
                                                    "name" : item.name,
                                                    "in" : in_type,
                                                    "required" : item.simple_schema["is_required"],
                                                    "schema" : item.simple_schema["content"],
                                                },
                                            )

                                            if item.description:
                                                parameters[-1]["description"] = item.description

                                    assert parameters
                                    request_parameters = (parameters, request.content_type)

                                else:
                                    warning_stream.write(
                                        textwrap.dedent(
                                            """\
                                            Swagger doesn't support content-type-specific header and
                                            query item information for requests; the first encountered
                                            set of information will be used for all content-types.

                                                Original:               {uri} - {verb} [{original_content_type}]
                                                Ignored (this item):    {uri} - {verb} [{this_content_type}]

                                            """,
                                        ).format(
                                            uri=endpoint.full_uri,
                                            verb=method.verb,
                                            original_content_type=request_parameters[1],
                                            this_content_type=request.content_type,
                                        ),
                                    )

                            # Process to body
                            if request.form_items and request.body:
                                warning_stream.write(
                                    textwrap.dedent(
                                        """\
                                        Swagger doesn't support requests with both form items and a request body;
                                        only the form items will be used.

                                            {uri} - {verb} [{content_type}]

                                        """,
                                    ).format(
                                        uri=endpoint.full_uri,
                                        verb=method.verb,
                                        content_type=request.content_type,
                                    ),
                                )

                            if request.form_items:
                                # Swagger wants to see these items as an object
                                properties = {}
                                required = []

                                for item in request.form_items:
                                    properties[item.name] = item.simple_schema["content"]

                                    if item.simple_schema["is_required"]:
                                        required.append(item.name)

                                schema = {
                                    "type" : "object",
                                    "properties" : properties,
                                }

                                if required:
                                    required.sort()
                                    schema["required"] = required

                                request_bodies[request.content_type] = {
                                    "schema" : schema,
                                }

                            elif request.body:
                                request_bodies[request.content_type] = {
                                    "schema" : request.body.simple_schema["content"],
                                }

                                if request_body_is_required is None:
                                    request_body_is_required = (request.body.simple_schema["is_required"], request.content_type)
                                elif request.body.simple_schema["is_required"] != request_body_is_required[0]:
                                    warning_stream.write(
                                        textwrap.dedent(
                                            """\
                                            Swagger doesn't support content-type-specific requirement information
                                            for body of requests; the first encountered requirement information will be
                                            used for all content-types.

                                                Original:               {uri} - {verb} [{original_content_type}]
                                                Ignored (this item):    {uri} - {verb} [{this_content_type}]

                                            """,
                                        ).format(
                                            uri=endpoint.full_uri,
                                            verb=method.verb,
                                            original_content_type=request_body_is_required[1],
                                            this_content_type=request.content_type,
                                        ),
                                    )

                                if request.body.description:
                                    if request_body_description is None:
                                        request_body_description = (request.body.description, request.content_type)
                                    else:
                                        warning_stream.write(
                                            textwrap.dedent(
                                                """\
                                                Swagger doesn't support content-type-specific descriptions for
                                                requests; the first encountered description will be used for all
                                                content-types.

                                                    Original:               {uri} - {verb} [{original_content_type}]
                                                    Ignored (this item):    {uri} - {verb} [{this_content_type}]

                                                """,
                                            ).format(
                                                uri=endpoint.full_uri,
                                                verb=method.verb,
                                                original_content_type=request_body_description[1],
                                                this_content_type=request.content_type,
                                            ),
                                        )

                        if request_parameters:
                            this_method["parameters"] = request_parameters[0]

                        if request_bodies:
                            assert request_body_is_required is not None

                            this_method["requestBody"] = {
                                "content" : request_bodies,
                                "required" : request_body_is_required[0],
                            }

                            if request_body_description is not None:
                                this_method["requestBody"]["description"] = request_body_description[0]

                        # Write the response info
                        all_responses = OrderedDict()

                        for response in method.responses:
                            this_response = OrderedDict()

                            if response.description:
                                this_response["description"] = response.description
                            else:
                                this_response["description"] = "Http status code '{}'".format(response.code)

                            response_headers = None
                            response_bodies = OrderedDict()

                            for content in response.contents:
                                if content.headers:
                                    if response_headers is None:
                                        these_response_headers = OrderedDict()

                                        for header in content.headers:
                                            these_response_headers[header.name] = {
                                                "schema" : header.simple_schema["content"],
                                                "required" : header.simple_schema["is_required"],
                                            }

                                            if header.description:
                                                these_response_headers[header.name]["description"] = header.description

                                        response_headers = (these_response_headers, content.content_type)

                                    else:
                                        warning_stream.write(
                                            textwrap.dedent(
                                                """\
                                                Swagger doesn't support content-type-specific header information
                                                for responses; the first encountered set of information will
                                                be used for all content-types.

                                                    Original:               {uri} - {verb} ({code}) [{original_content_type}]
                                                    Ignored (this item):    {uri} - {verb} ({code}) [{this_content_type}]

                                                """,
                                            ).format(
                                                uri=endpoint.full_uri,
                                                verb=method.verb,
                                                code=response.code,
                                                original_content_type=response_headers[1],
                                                this_content_type=content.content_type,
                                            ),
                                        )

                                if content.body:
                                    response_bodies[content.content_type] = {
                                        "schema" : content.body.simple_schema["content"],
                                    }

                                    if content.body.description:
                                        warning_stream.write(
                                            textwrap.dedent(
                                                """\
                                                Swagger does not support content-type-specific descriptions
                                                for bodies.

                                                    {uri} - {verb} ({code}) [{content_type}]

                                                """,
                                            ).format(
                                                uri=endpoint.full_uri,
                                                verb=method.verb,
                                                code=response.code,
                                                content_type=content.content_type,
                                            ),
                                        )

                            if response_headers:
                                this_response["headers"] = response_headers[0]
                            if response_bodies:
                                this_response["content"] = response_bodies

                            all_responses[response.code] = this_response

                        # Apply the responses
                        if all_responses:
                            this_method["responses"] = all_responses

                        # Always provide method information
                        this_path[method.verb.lower()] = this_method

                    if this_path:
                        paths[endpoint.full_uri] = this_path

                    for child in endpoint.children:
                        ParseEndpoint(child)

            # ----------------------------------------------------------------------

            for endpoint in itertools.chain(*six.itervalues(all_endpoints)):
                ParseEndpoint(endpoint)

            assert paths
            result["paths"] = paths

            if components:
                result["components"] = components
            if tags:
                result["tags"] = [{"name": tag} for tag in set(tags)]

            return result

    # ----------------------------------------------------------------------
    @staticmethod
    def _GenerateJsonContent(
        status_stream,
        endpoint_data,
        output_filename,
        pretty_print=False,
    ):
        status_stream.write("Writing '{}'...".format(output_filename))
        with status_stream.DoneManager():
            with open(output_filename, "w") as f:
                if pretty_print:
                    json.dump(
                        endpoint_data,
                        f,
                        indent=2,
                        separators=[", ", " : "],
                    )
                else:
                    json.dump(endpoint_data, f)

    # ----------------------------------------------------------------------
    @staticmethod
    def _GenerateYamlContent(
        status_stream,
        endpoint_data,
        output_filename,
    ):
        import rtyaml

        status_stream.write("Writing '{}'...".format(output_filename))
        with status_stream.DoneManager():
            with open(output_filename, "w") as f:
                f.write(rtyaml.dump(endpoint_data))
