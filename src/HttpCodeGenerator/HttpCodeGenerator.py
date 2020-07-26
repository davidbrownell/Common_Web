# ----------------------------------------------------------------------
# |
# |  HttpCodeGenerator.py
# |
# |  David Brownell <db@DavidBrownell.com>
# |      2020-07-16 17:02:19
# |
# ----------------------------------------------------------------------
# |
# |  Copyright David Brownell 2020
# |  Distributed under the Boost Software License, Version 1.0. See
# |  accompanying file LICENSE_1_0.txt or copy at
# |  http://www.boost.org/LICENSE_1_0.txt.
# |
# ----------------------------------------------------------------------
"""Generates HTTP-based code from provided information"""

import importlib
import itertools
import os
import pickle
import re
import sys
import textwrap
import uuid

from collections import namedtuple, OrderedDict

import six

import CommonEnvironment
from CommonEnvironment.CallOnExit import CallOnExit
from CommonEnvironment import CommandLine
from CommonEnvironment import FileSystem
from CommonEnvironment import Process
from CommonEnvironment.Shell.All import CurrentShell
from CommonEnvironment.StreamDecorator import StreamDecorator
from CommonEnvironment import StringHelpers

from CommonEnvironmentEx.CompilerImpl.GeneratorPluginFrameworkImpl import GeneratorFactory
from CommonEnvironmentEx.Package import InitRelativeImports

# ----------------------------------------------------------------------
_script_fullpath                            = CommonEnvironment.ThisFullpath()
_script_dir, _script_name                   = os.path.split(_script_fullpath)
# ----------------------------------------------------------------------

with InitRelativeImports():
    from .Plugin import Plugin


# ----------------------------------------------------------------------
# |  Load the input parsers
InputParserInfo                             = namedtuple(
    "InputParserInfo",
    [
        "Mod",
        "DeserializeFunc",
    ],
)

INPUT_PARSERS                               = OrderedDict()

for parser, file_extensions in [
    ("Json", [".json"]),
    ("Xml", [".xml"]),
    ("Yaml", [".yaml", ".yml"]),
]:
    generated_filename = os.path.join(
        _script_dir,
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

    deserialize_func = getattr(mod, "Deserialize")
    assert deserialize_func

    INPUT_PARSERS[tuple(file_extensions)] = InputParserInfo(mod, deserialize_func)


# ----------------------------------------------------------------------
PLUGINS                                     = GeneratorFactory.CreatePluginMap("DEVELOPMENT_ENVIRONMENT_HTTP_GENERATOR_PLUGINS", os.path.join(_script_dir, "Plugins"), sys.stdout)

_PluginTypeInfo                             = CommandLine.EnumTypeInfo(list(six.iterkeys(PLUGINS)))

# ----------------------------------------------------------------------
def _GetOptionalMetadata(*args, **kwargs):
    return __GetOptionalMetadata(*args, **kwargs)


def _CreateContext(*args, **kwargs):
    return __CreateContext(*args, **kwargs)


def _Invoke(*args, **kwargs):
    return __Invoke(*args, **kwargs)


CodeGenerator                               = GeneratorFactory.CodeGeneratorFactory(
    PLUGINS,
    "HttpCodeGenerator",
    __doc__.replace("\n", ""),
    r".+({})".format(
        "|".join(itertools.chain(*INPUT_PARSERS.keys()))
    ),
    _GetOptionalMetadata,
    _CreateContext,
    _Invoke,
    requires_output_name=False,
)


# ----------------------------------------------------------------------
@CommandLine.EntryPoint(
    plugin=CommandLine.EntryPoint.Parameter("Name of plugin used for generation"),
    output_dir=CommandLine.EntryPoint.Parameter("Output directory used during generation; the way in which this value impacts generated output varies from plugin to plugin"),
    input=CommandLine.EntryPoint.Parameter("Input filename or a directory containing input files"),
    content_type_include=CommandLine.EntryPoint.Parameter("Http content type to include in generation"),
    content_type_exclude=CommandLine.EntryPoint.Parameter("Http content type to exclude from generation"),
    verb_include=CommandLine.EntryPoint.Parameter("Http verb to include in generation"),
    method_exclude=CommandLine.EntryPoint.Parameter("Http verb to exclude from generation"),
    output_data_filename_prefix=CommandLine.EntryPoint.Parameter(
        "Prefix used by the code generation implementation; provide this value to generated content from multiple plugins in the same output directory",
    ),
    temp_dir=CommandLine.EntryPoint.Parameter("Temporary directory used to write generated content"),
    plugin_arg=CommandLine.EntryPoint.Parameter("Argument passed directly to the plugin"),
    force=CommandLine.EntryPoint.Parameter("Force generation"),
    verbose=CommandLine.EntryPoint.Parameter("Produce verbose output during generation"),
)
@CommandLine.Constraints(
    plugin=_PluginTypeInfo,
    output_dir=CommandLine.DirectoryTypeInfo(
        ensure_exists=False,
    ),
    input=CommandLine.FilenameTypeInfo(
        match_any=True,
        arity="*",
    ),
    content_type_include=CommandLine.StringTypeInfo(
        arity="*",
    ),
    content_type_exclude=CommandLine.StringTypeInfo(
        arity="*",
    ),
    verb_include=CommandLine.StringTypeInfo(
        arity="*",
    ),
    method_exclude=CommandLine.StringTypeInfo(
        arity="*",
    ),
    output_data_filename_prefix=CommandLine.StringTypeInfo(
        arity="?",
    ),
    temp_dir=CommandLine.DirectoryTypeInfo(
        ensure_exists=False,
        arity="?",
    ),
    plugin_arg=CommandLine.DictTypeInfo(
        require_exact_match=False,
        arity="*",
    ),
    output_stream=None,
)
def Generate(
    plugin,
    output_dir,
    input,
    content_type_include=None,
    content_type_exclude=None,
    verb_include=None,
    method_exclude=None,
    output_data_filename_prefix=None,
    temp_dir=None,
    plugin_arg=None,
    force=False,
    output_stream=sys.stdout,
    verbose=False,
):
    """Generates HTTP content using the given plugin"""

    if temp_dir:
        FileSystem.MakeDirs(temp_dir)

    return GeneratorFactory.CommandLineGenerate(
        CodeGenerator,
        input,
        output_stream,
        verbose,
        force=force,
        plugin_name=plugin,
        output_dir=output_dir,
        content_type_includes=content_type_include,
        content_type_excludes=content_type_exclude,
        verb_includes=verb_include,
        verb_excludes=method_exclude,
        plugin_settings=plugin_arg,
        output_data_filename_prefix=output_data_filename_prefix,
        temp_dir=temp_dir,
    )


# ----------------------------------------------------------------------
@CommandLine.EntryPoint(
    output_dir=CommandLine.EntryPoint.Parameter("Output directory previously generated"),
)
@CommandLine.Constraints(
    output_dir=CommandLine.DirectoryTypeInfo(),
    output_stream=None,
)
def Clean(
    output_dir,
    output_stream=sys.stdout,
):
    """Cleans content previously generated"""

    return GeneratorFactory.CommandLineClean(output_dir, output_stream)


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
def CommandLineSuffix():
    return textwrap.dedent(
        """\
        Where <plugin> can be one of the following:

        {}

        """,
    ).format(
        "\n".join(["    - {0:<30}  {1}".format("{}:".format(pi.Plugin.Name), pi.Plugin.Description) for pi in six.itervalues(PLUGINS)])
    )


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
def __GetOptionalMetadata():
    return [
        ("content_type_includes", []),
        ("content_type_excludes", []),
        ("verb_includes", []),
        ("verb_excludes", []),
        ("output_data_filename_prefix", None),
        ("temp_dir", ""),
    ]


# ----------------------------------------------------------------------
def __CreateContext(context, plugin):

    # Read all the endpoint info
    roots = OrderedDict()

    for input_filename in context["inputs"]:
        ext = os.path.splitext(input_filename)[1]

        for extensions, input_parser_info in six.iteritems(INPUT_PARSERS):
            if ext not in extensions:
                continue

            try:
                root = input_parser_info.DeserializeFunc(
                    input_filename,
                    always_include_optional=True,
                )

                roots[input_filename] = root

            except Exception as ex:
                # Augment the exception with stack information
                args = list(ex.args)

                args[0] = textwrap.dedent(
                    """\
                    {}

                    {}
                    [{}]
                    """,
                ).format(
                    args[0],
                    input_filename,
                    " > ".join(ex.stack),
                )

                ex.args = tuple(args)
                raise ex from None

    # Validate the endpoint info
    endpoint_stack = []

    # ----------------------------------------------------------------------
    def Validate(input_filename, endpoint):
        nonlocal endpoint_stack

        endpoint_stack.append(endpoint)
        with CallOnExit(endpoint_stack.pop):
            try:
                # Ensure that all parameters in the uri are defined in variables and vice versa
                uri_variables = set()

                for match in Plugin.URI_PARAMETER_REGEX.finditer(endpoint.uri):
                    name = match.group("name")

                    if name in uri_variables:
                        raise Exception("The uri variable '{}' has already been defined".format(name))

                    uri_variables.add(name)

                for variable in endpoint.variables:
                    if variable.name not in uri_variables:
                        raise Exception("The uri variable '{}' was not found in the uri '{}'".format(variable.name, endpoint.uri))

                    uri_variables.remove(variable.name)

                if uri_variables:
                    raise Exception("The uri variables {} were not defined".format(", ".join(["'{}'".format(variable) for variable in uri_variables])))

                for child in endpoint.children:
                    Validate(input_filename, child)

            except Exception as ex:
                # Augment the exception with stack information
                args = list(ex.args)

                args[0] = textwrap.dedent(
                    """\
                    {}

                    {}
                    [{}]
                    """,
                ).format(
                    args[0],
                    input_filename,
                    "".join([e.uri for e in endpoint_stack]),
                )

                ex.args = tuple(args)
                raise ex from None

    # ----------------------------------------------------------------------

    for input_filename, root in six.iteritems(roots):
        for endpoint in root.endpoints:
            Validate(input_filename, endpoint)

    # Filter the content
    if (
        context["content_type_includes"]
        or context["content_type_excludes"]
        or context["verb_includes"]
        or context["verb_excludes"]
    ):
        if context["content_type_excludes"]:
            content_type_excludes_regexes = [re.compile(value) for value in context["content_type_excludes"]]
            content_type_exclude_func = lambda rar: any(regex for regex in content_type_excludes_regexes if regex.match(rar.content_type))
        else:
            content_type_exclude_func = lambda rar: False

        if context["content_type_includes"]:
            content_type_include_regexes = [re.compile(value) for value in context["content_type_includes"]]
            content_type_include_func = lambda rar: any(regex for regex in content_type_include_regexes if regex.match(rar.content_type))
        else:
            content_type_include_func = lambda rar: True

        verb_includes = set([value.upper() for value in context["verb_includes"]])
        verb_excludes = set([value.upper() for value in context["verb_excludes"]])

        # ----------------------------------------------------------------------
        def Filter(endpoint):
            method_index = 0
            while method_index < len(endpoint.methods):
                method = endpoint.methods[method_index]

                rar_index = 0
                while rar_index < len(method.request_and_responses):
                    rar = method.request_and_responses[rar_index]

                    if (
                        content_type_exclude_func(rar)
                        or not content_type_include_func(rar)
                    ):
                        del method.request_and_responses[rar_index]
                    else:
                        rar_index += 1

                if (
                    not method.request_and_responses
                    or (verb_excludes and method.name in verb_excludes)
                    or (verb_includes and method.name not in verb_includes)
                ):
                    del endpoint.methods[method_index]
                else:
                    method_index += 1

            child_index = 0
            while child_index < len(endpoint.children):
                child = endpoint.children[child_index]

                Filter(child)

                if not child.methods and not child.children:
                    del endpoint.children[child_index]
                else:
                    child_index += 1

        # ----------------------------------------------------------------------

        for input_filename, root in list(six.iteritems(roots)):
            endpoint_index = 0
            while endpoint_index < len(root.endpoints):
                endpoint = root.endpoints[endpoint_index]

                Filter(endpoint)

                if not root.endpoint.methods and not endpoint.children:
                    del root.endpoints[endpoint_index]
                else:
                    endpoint_index += 1

            if not root.endpoints:
                del roots[input_filename]

    # Here we have all the endpoints and need to assign them to the context.
    # However, the context will be compared with previous context to see if
    # a new generation is required. To make this work as expected, we need to
    # compare the data within the endpoints and not the endpoints themselves.
    # Pickle the data, and then unpickle it if it turns out that a new
    # generation is necessary.
    context["pickled_roots"] = pickle.dumps(roots)

    return context


# ----------------------------------------------------------------------
def __Invoke(
    code_generator,
    invoke_reason,
    context,
    status_stream,
    verbose_stream,
    verbose,
    plugin,
):
    roots = pickle.loads(context["pickled_roots"])

    # ----------------------------------------------------------------------
    def Postprocess(endpoint, uris):
        uris.append(endpoint.uri)
        with CallOnExit(uris.pop):
            endpoint.full_uri = ''.join(uris).replace("//", "/")
            endpoint.unique_name = endpoint.full_uri.replace("/", ".").replace("{", "__").replace("}", "__")

            for child in endpoint.children:
                Postprocess(child, uris)

    # ----------------------------------------------------------------------

    for root in six.itervalues(roots):
        for endpoint in root.endpoints:
            Postprocess(endpoint, [])

    if plugin.COMPILE_SIMPLE_SCHEMA_STATEMENTS:
        status_stream.write("Creating SimpleSchema content...")
        with status_stream.DoneManager() as dm:
            # Create the temporary directory
            temp_dir = context["temp_dir"] or CurrentShell.CreateTempDirectory()
            dm.stream.write("Temporary content: {}\n\n".format(temp_dir))

            delete_temp_dir = not context["temp_dir"]

            # ----------------------------------------------------------------------
            def DeleteTempDir():
                nonlocal delete_temp_dir

                if delete_temp_dir:
                    FileSystem.RemoveTree(temp_dir)

            # ----------------------------------------------------------------------

            with CallOnExit(DeleteTempDir):
                simple_schema_filename = _WriteSimpleSchemaContent(roots, temp_dir, dm.stream)

                dm.result = _CompileSimpleSchemaContent(verbose, temp_dir, simple_schema_filename, dm.stream)
                if dm.result != 0:
                    delete_temp_dir = False
                    return dm.result

                _ProcessSimpleSchemaContent(roots, temp_dir, dm.stream)

    endpoints = OrderedDict(
        [
            (k, v.endpoints) for k, v in six.iteritems(roots)
        ],
    )

    return plugin.Generate(
        code_generator,
        invoke_reason,
        context["output_dir"],
        endpoints,
        status_stream,
        verbose_stream,
        verbose,
        **context["plugin_settings"],
    )

# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
def _WriteSimpleSchemaContent(roots, temp_dir, output_stream):
    simple_schema_filename = os.path.join(temp_dir, "http_schema.SimpleSchema")

    output_stream.write("Writing...")
    with output_stream.DoneManager():
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

                    for rar_index, rar in enumerate(method.request_and_responses):
                        rar_sink = six.moves.StringIO()

                        if rar.simple_schema_content:
                            rar_sink.write(SimpleSchemaContentToString("RequestAndResounse", rar.simple_schema_content))

                        if rar.request:
                            request_sink = six.moves.StringIO()

                            for header_index, header in enumerate(rar.request.headers):
                                request_sink.write(ElementToString("header_{}".format(header_index), header.simple_schema))

                            for query_item_index, query_item in enumerate(rar.request.query_items):
                                request_sink.write(ElementToString("query_{}".format(query_item_index), query_item.simple_schema))

                            for form_item_index, form_item in enumerate(rar.request.form_items):
                                request_sink.write(ElementToString("form_{}".format(form_item_index), form_item.simple_schema))

                            if rar.request.body:
                                request_sink.write(ElementToString("body", rar.request.body.simple_schema))

                            request_sink = request_sink.getvalue()
                            if request_sink:
                                rar_sink.write(ElementToString("request", request_sink))

                        for response_index, response in enumerate(rar.responses):
                            response_sink = six.moves.StringIO()

                            for header_index, header in enumerate(response.headers):
                                response_sink.write(ElementToString("header_{}".format(header_index), header.simple_schema))

                            if response.body:
                                response_sink.write(ElementToString("body", response.body.simple_schema))

                            response_sink = response_sink.getvalue()
                            if response_sink:
                                rar_sink.write(ElementToString("response_{}".format(response_index), response_sink))

                        rar_sink = rar_sink.getvalue()
                        if rar_sink:
                            method_sink.write(ElementToString("rar_{}".format(rar_index), rar_sink))

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
                    f.write(SimpleSchemaContentToString("Global", root.simple_schema_content))

            endpoint_index = 0
            for root in six.itervalues(roots):
                for endpoint in root.endpoints:
                    result = GenerateEndpointContent(endpoint, endpoint_index)
                    if result:
                        f.write(result)

                    endpoint_index += 1

    return simple_schema_filename


# ----------------------------------------------------------------------
def _CompileSimpleSchemaContent(verbose, temp_dir, simple_schema_filename, output_stream):
    output_stream.write("Compiling...")
    with output_stream.DoneManager() as compile_dm:
        command_line = '"{script}" Generate Pickle http_schema "{output_dir}" "/input={input_filename}"{verbose}'.format(
            script=CurrentShell.CreateScriptName("SimpleSchemaGenerator"),
            output_dir=temp_dir,
            input_filename=simple_schema_filename,
            verbose=" /verbose" if verbose else "",
        )

        compile_dm.result, output = Process.Execute(command_line)

        if verbose or compile_dm.result != 0:
            compile_dm.stream.write(output)

        return compile_dm.result


# ----------------------------------------------------------------------
def _ProcessSimpleSchemaContent(roots, temp_dir, output_stream):
    output_stream.write("Processing...")
    with output_stream.DoneManager():
        # Load the generated content
        path_filename = os.path.join(temp_dir, "http_schema.path")
        assert os.path.isfile(path_filename), path_filename

        with open(path_filename) as f:
            path = f.read().strip()
            assert os.path.isdir(path), path

        sys.path.insert(0, path)
        with CallOnExit(lambda: sys.path.pop(0)):
            pickle_filename = os.path.join(temp_dir, "http_schema.pickle")
            assert os.path.isfile(pickle_filename), pickle_filename

            with open(pickle_filename, "rb") as f:
                elements = pickle.load(f)

        # ----------------------------------------------------------------------
        def GetSimpleSchemaContent(elements, element_index):
            starting_index = element_index

            while (
                element_index < len(elements)
                and not elements[element_index].Name.startswith("simple_schema_delimiter_")
            ):
                element_index += 1

            children = elements[starting_index : element_index]

            if element_index != len(elements):
                element_index += 1

            return children, element_index

        # ----------------------------------------------------------------------
        def GetSimpleSchemaElement(element_name_prefix, element):
            assert element.Name.startswith(element_name_prefix), (element.Name, element_name_prefix)
            assert len(element.Children) == 1, element.children
            return element.Children[0]

        # ----------------------------------------------------------------------
        def ExtractRequestContent(request, element):
            """Returns True if request content was processed, False if there was no content to process"""

            children = element.Children
            child_index = 0

            for header in request.headers:
                header.simple_schema = {
                    "string" : header.simple_schema,
                    "content" : GetSimpleSchemaElement("header_", children[child_index]),
                }
                child_index += 1

            for query_item in request.query_items:
                query_item.simple_schema = {
                    "string" : query_item.simple_schema,
                    "content" : GetSimpleSchemaElement("query_", children[child_index]),
                }
                child_index += 1

            for form_item in request.form_items:
                form_item.simple_schema = {
                    "string" : form_item.simple_schema,
                    "content" : GetSimpleSchemaElement("form_", children[child_index]),
                }
                child_index += 1

            if request.body:
                child = children[child_index]
                assert child.Name == "body", child.Name
                assert child.Children

                request.body.simple_schema = {
                    "string" : request.body.simple_schema,
                    "content" : child.Children,
                }
                child_index += 1

            if child_index == 0:
                return False

            assert child_index == len(children), (child_index, len(children))
            return True

        # ----------------------------------------------------------------------
        def ExtractResponseContent(response, element):
            """Returns True if response content was processed, False if there was no content to process"""

            children = element.Children
            child_index = 0

            for header in response.headers:
                header.simple_schema = {
                    "string" : header.simple_schema,
                    "content" : GetSimpleSchemaElement("header_", children[child_index]),
                }
                child_index += 1

            if response.body:
                child = children[child_index]
                assert child.Name == "body", child.Name
                assert child.Children

                response.body.simple_schema = {
                    "string" : response.body.simple_schema,
                    "content" : child.Children,
                }
                child_index += 1

            if child_index == 0:
                return False

            assert child_index == len(children), (child_index, len(children))
            return True

        # ----------------------------------------------------------------------
        def ExtractRequestAndResponseContent(rar, element):
            """Returns True if rar content was processed, False if there was no content to process"""

            children = element.Children
            num_children = len(children)

            child_index = 0

            if rar.simple_schema_content:
                content_elements, child_index = GetSimpleSchemaContent(children, child_index)
                rar.simple_schema_content = {
                    "string" : rar.simple_schema_content,
                    "content" : content_elements,
                }

            if rar.request and ExtractRequestContent(rar.request, children[child_index]):
                child_index += 1

            for response in rar.responses:
                if (
                    child_index != num_children
                    and ExtractResponseContent(response, children[child_index])
                ):
                    child_index += 1

            if child_index == 0:
                return False

            assert child_index == len(children), (child_index, len(children))
            return True

        # ----------------------------------------------------------------------
        def ExtractMethodContent(method, element):
            """Returns True if method content was processed, False if there was no content to process"""

            children = element.Children
            num_children = len(children)

            child_index = 0

            if method.simple_schema_content:
                content_elements, child_index = GetSimpleSchemaContent(children, child_index)
                method.simple_schema_content = {
                    "string" : method.simple_schema_content,
                    "content" : content_elements,
                }

            for rar in method.request_and_responses:
                if (
                    child_index != num_children
                    and ExtractRequestAndResponseContent(rar, children[child_index])
                ):
                    child_index += 1

            if child_index == 0:
                return False

            assert child_index == len(children), (child_index, len(children))
            return True

        # ----------------------------------------------------------------------
        def ExtractEndpointContent(endpoint, element):
            """Returns True if endpoint content was processed, False if there was no content to process"""

            children = element.Children
            num_children = len(children)

            child_index = 0

            if endpoint.simple_schema_content:
                content_elements, child_index = GetSimpleSchemaContent(children, child_index)
                endpoint.simple_schema_content = {
                    "string" : endpoint.simple_schema_content,
                    "content" : content_elements,
                }

            for variable in endpoint.variables:
                variable.simple_schema = {
                    "string" : variable.simple_schema,
                    "content" : GetSimpleSchemaElement("variable_", children[child_index]),
                }
                child_index += 1

            for method in endpoint.methods:
                if (
                    child_index != num_children
                    and ExtractMethodContent(method, children[child_index])
                ):
                    child_index += 1

            for child in endpoint.children:
                if (
                    child_index != num_children
                    and ExtractEndpointContent(child, children[child_index])
                ):
                    child_index += 1

            if child_index == 0:
                return False

            assert child_index == len(children), (child_index, len(children))
            return True

        # ----------------------------------------------------------------------

        # Get the root content
        num_elements = len(elements)
        element_index = 0

        for root in six.itervalues(roots):
            if root.simple_schema_content:
                content_elements, element_index = GetSimpleSchemaContent(elements, element_index)
                root.simple_schema_content = {
                    "string" : root.simple_schema_content,
                    "content" : content_elements,
                }

        for root in six.itervalues(roots):
            for endpoint in root.endpoints:
                if (
                    element_index != num_elements
                    and ExtractEndpointContent(endpoint, elements[element_index])
                ):
                    element_index += 1

        assert element_index == len(elements), (element_index, len(elements))


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
if __name__ == "__main__":
    try:
        sys.exit(
            CommandLine.Main()
        )
    except KeyboardInterrupt:
        pass
