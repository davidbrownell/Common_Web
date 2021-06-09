# ----------------------------------------------------------------------
# |
# |  __main__.py
# |
# |  David Brownell <db@DavidBrownell.com>
# |      2020-07-16 17:02:19
# |
# ----------------------------------------------------------------------
# |
# |  Copyright David Brownell 2020-21
# |  Distributed under the Boost Software License, Version 1.0. See
# |  accompanying file LICENSE_1_0.txt or copy at
# |  http://www.boost.org/LICENSE_1_0.txt.
# |
# ----------------------------------------------------------------------
"""Generates HTTP-based code from provided information"""

import importlib
import itertools
import os
import re
import sys
import textwrap
import yaml

from collections import namedtuple, OrderedDict

import six

import CommonEnvironment
from CommonEnvironment.CallOnExit import CallOnExit
from CommonEnvironment import CommandLine

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
    "HttpGenerator",
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
    verb_exclude=CommandLine.EntryPoint.Parameter("Http verb to exclude from generation"),
    output_data_filename_prefix=CommandLine.EntryPoint.Parameter(
        "Prefix used by the code generation implementation; provide this value to generated content from multiple plugins in the same output directory",
    ),
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
    verb_exclude=CommandLine.StringTypeInfo(
        arity="*",
    ),
    output_data_filename_prefix=CommandLine.StringTypeInfo(
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
    verb_exclude=None,
    output_data_filename_prefix=None,
    plugin_arg=None,
    force=False,
    output_stream=sys.stdout,
    verbose=False,
):
    """Generates HTTP content using the given plugin"""

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
        verb_excludes=verb_exclude,
        plugin_settings=plugin_arg,
        output_data_filename_prefix=output_data_filename_prefix,
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
                break

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
                    " > ".join(getattr(ex, "stack", [])),
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

                # Ensure that the uri variables don't overlap with parent variables
                all_variables = set()

                for e in endpoint_stack:
                    for variable in e.variables:
                        if variable.name in all_variables:
                            raise Exception("The variable '{}' has already been defined".format(variable.name))

                        all_variables.add(variable.name)

                # Handle content that is mutually exclusive
                for method in endpoint.methods:
                    if method.default_request and method.requests:
                        raise Exception("'default_request' and 'requests' are mutually exclusive and cannot both be provided ({})".format(method.verb))

                    for response in method.responses:
                        if response.default_content and response.contents:
                            raise Exception("'default_content' and 'contents' are mutually exclusive and cannot both be provided ({}, {})".format(method.verb, response.code))

                    # Validate the children
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

                # Process the requests
                request_index = 0
                while request_index < len(method.requests):
                    if (
                        content_type_exclude_func(method.requests[request_index].content_type)
                        or not content_type_include_func(method.request[request_index].content_type)
                    ):
                        del method.requests[request_index]
                    else:
                        request_index += 1

                # Process the responses
                response_index = 0
                while response_index < len(method.responses):
                    response = method.responses[response_index]

                    content_index = 0
                    while content_index < len(response.contents):
                        if (
                            content_type_exclude_func(response.contents[content_index].content_type)
                            or not content_type_include_func(response.contents[content_index].content_type)
                        ):
                            del response.responses[content_index]
                        else:
                            content_index += 1

                    if not response.default_content and not response.contents:
                        del method.responses[response_index]
                    else:
                        response_index += 1

                if (
                    not method.default_request
                    and not method.requests
                    and not method.responses
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

    context["persisted_roots"] = yaml.dump(roots)

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
    roots = yaml.load(
        context["persisted_roots"],
        Loader=yaml.FullLoader,
    )

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

    return plugin.Generate(
        code_generator,
        invoke_reason,
        context["output_dir"],
        roots,
        status_stream,
        verbose_stream,
        verbose,
        **context["plugin_settings"],
    )


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
