# ----------------------------------------------------------------------
# |
# |  PythonFlaskWebserverPlugin.py
# |
# |  David Brownell <db@DavidBrownell.com>
# |      2020-08-28 19:19:07
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
from CommonEnvironment.CallOnExit import CallOnExit
from CommonEnvironment import Interface
from CommonEnvironment.StreamDecorator import StreamDecorator
from CommonEnvironment import StringHelpers

from CommonEnvironmentEx.Package import InitRelativeImports

# ----------------------------------------------------------------------
_script_fullpath                            = CommonEnvironment.ThisFullpath()
_script_dir, _script_name                   = os.path.split(_script_fullpath)
# ----------------------------------------------------------------------

with InitRelativeImports():
    from .Impl.WebserverPluginMixin import WebserverPluginMixin
    from ..Plugin import Plugin as PluginBase

# ----------------------------------------------------------------------
@Interface.staticderived
class Plugin(WebserverPluginMixin, PluginBase):

    # ----------------------------------------------------------------------
    # |  Public Properties
    Name                                    = Interface.DerivedProperty("PythonFlaskWebserver")
    Description                             = Interface.DerivedProperty("Creates a Flask app (https://github.com/pallets/flask)")

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
        yield "additional_python_paths", []
        yield "support_default_content_processor", True

    # ----------------------------------------------------------------------
    @classmethod
    @Interface.override
    def GetAdditionalGeneratorItems(cls, context):
        return [WebserverPluginMixin] + super().GetAdditionalGeneratorItems(context)

    # ----------------------------------------------------------------------
    @classmethod
    @Interface.override
    def GenerateOutputFilenames(cls, context):
        filenames = ["__init__.py", "FlaskMethods.py"]

        if not context["plugin_settings"]["no_helpers"]:
            filenames += [
                os.path.join("Helpers", "__init__.py"),
                os.path.join("Helpers", "FlaskApp.py"),
                os.path.join("Helpers", "App.py"),
                os.path.join("Helpers", "RunServer.py"),
            ]

        mixin_filenames = cls.GenerateWebserverFilenames()
        filenames += mixin_filenames

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
        additional_python_paths,
        support_default_content_processor,
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

        # FlaskMethods.py
        assert filenames

        status_stream.write("Writing '{}'...".format(filenames[0]))
        with status_stream.DoneManager():
            with open(filenames[0], "w") as f:
                f.write(file_header)
                WriteFlaskMethods(f, endpoints, support_default_content_processor)

            filenames.pop(0)

        if not no_helpers:
            # __init__.py
            assert filenames

            status_stream.write("Writing '{}'...".format(filenames[0]))
            with status_stream.DoneManager():
                with open(filenames[0], "w") as f:
                    f.write(file_header)

                filenames.pop(0)

            # FlaskApp.py
            assert filenames

            status_stream.write("Writing '{}'...".format(filenames[0]))
            with status_stream.DoneManager():
                with open(filenames[0], "w") as f:
                    f.write(file_header)
                    WriteFlaskApp(f)

                filenames.pop(0)

            # App.py
            assert filenames

            status_stream.write("Writing '{}'...".format(filenames[0]))
            with status_stream.DoneManager():
                with open(filenames[0], "w") as f:
                    f.write(file_header)
                    WriteApp(f, additional_python_paths)

                filenames.pop(0)

            # RunServer.py
            assert filenames

            status_stream.write("Writing '{}'...".format(filenames[0]))
            with status_stream.DoneManager():
                with open(filenames[0], "w") as f:
                    f.write(file_header)
                    WriteRunSever(f)

                filenames.pop(0)

        # Mixin
        cls.GenerateWebserver(
            filenames,
            status_stream,
            file_header,
            endpoints,
        )


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
def WriteFlaskMethods(f, endpoints, support_default_content_processor):
    content = []

    # ----------------------------------------------------------------------
    def Impl(endpoint, uri_parameters):
        uri_parameters += endpoint.variables

        # ----------------------------------------------------------------------
        def RemoveParameters():
            iterations = len(endpoint.variables)

            while iterations:
                assert uri_parameters
                uri_parameters.pop()

                iterations -= 1

        # ----------------------------------------------------------------------

        with CallOnExit(RemoveParameters):
            method_content = []

            # Process the variables
            if uri_parameters:
                args = ", {}".format(", ".join([variable.name for variable in uri_parameters]))
            else:
                args = ""

            # Process the methods
            for method in endpoint.methods:
                method_content.append(
                    textwrap.dedent(
                        """\
                        # ----------------------------------------------------------------------
                        def {lower_name}(self{args}):
                            return _Execute("{unique_name}_{name}"{args})


                        """,
                    ).format(
                        name=method.verb,
                        lower_name=method.verb.lower(),
                        unique_name=endpoint.unique_name,
                        args=args,
                    ),
                )

            if method_content:
                content.append(
                    textwrap.dedent(
                        """\
                        # ----------------------------------------------------------------------
                        class {name}(MethodView):
                            {methods}


                        app.add_url_rule(
                            "{uri}",
                            view_func={name}.as_view("{name}"),
                        )


                        """,
                    ).format(
                        name=endpoint.unique_name,
                        uri=endpoint.full_uri.replace("{", "<").replace("}", ">"),
                        methods=StringHelpers.LeftJustify("".join(method_content).rstrip(), 4),
                    ),
                )

            for child in endpoint.children:
                Impl(child, uri_parameters)

    # ----------------------------------------------------------------------

    for endpoint in endpoints:
        Impl(endpoint, [])

    f.write(
        textwrap.dedent(
            '''\
            import os
            import sys
            import textwrap
            import traceback

            import six

            from collections import OrderedDict
            from urllib.parse import urlparse as uriparse

            from flask import abort, request, Response
            from flask.views import MethodView

            import CommonEnvironment
            from CommonEnvironment import StringHelpers

            from CommonEnvironmentEx.Package import InitRelativeImports

            # ----------------------------------------------------------------------
            _script_fullpath                            = CommonEnvironment.ThisFullpath()
            _script_dir, _script_name                   = os.path.split(_script_fullpath)
            # ----------------------------------------------------------------------

            with InitRelativeImports():
                from .Exceptions import *
                from .Interfaces import *

            # ----------------------------------------------------------------------
            # ----------------------------------------------------------------------
            # ----------------------------------------------------------------------

            # app
            try:
                import FlaskApp

                if hasattr(FlaskApp, "GetFlaskApp"):
                    app = FlaskApp.GetFlaskApp()
                elif hasattr(FlaskApp, "app"):
                    app = FlaskApp.app
                else:
                    raise ImportError()

            except:
                raise Exception(
                    textwrap.dedent(
                        """\\
                        The value 'app' or the method 'GetFlaskApp' must be implemented
                        in a python module named 'FlaskApp'.

                            Example:
                                def FlaskApp():
                                    from flask import Flask
                                    return Flask(__name__)

                        Exception Info:
                            {{}}

                        """,
                    ).format(StringHelpers.LeftJustify(traceback.format_exc(), 4)),
                )

            # Content processors
            try:
                import ContentProcessors

                if hasattr(ContentProcessors, "GetContentProcessors"):
                    content_processors = ContentProcessors.GetContentProcessors()
                elif hasattr(ContentProcessors, "content_processors"):
                    content_processors = ContentProcessors.content_processors
                else:
                    raise ImportError()

            except:
                raise Exception(
                    textwrap.dedent(
                        """\\
                        The value 'content_processors' or the method 'GetContentProcessors' must be implemented
                        in a python module named 'ContentProcessors'.

                            Example:
                                from Interfaces import ContentProcessorInterface

                                class HtmlContentProcessor(ContentProcessorInterface):
                                    ...

                                class PlainTextContentProcessor(ContentProcessorInterface):
                                    ...

                                def GetContentProcessors():
                                    return OrderedDict(
                                        [
                                            ("text/html", HtmlContentProcessor),
                                            ("text/plain", PlainTextContentProcessor),
                                        ],
                                    )

                        Exception Info:
                            {{}}

                        """,
                    ).format(StringHelpers.LeftJustify(traceback.format_exc(), 4)),
                )

            # Authenticator
            try:
                import Authenticator

                if hasattr(Authenticator, "GetAuthenticator"):
                    authenticator = Authenticator.GetAuthenticator()
                elif hasattr(Authenticator, "authenticator"):
                    authenticator = Authenticator.authenticator
                else:
                    raise ImportError()

            except:
                raise Exception(
                    textwrap.dedent(
                        """\\
                        The value 'authenticator' or the method 'GetAuthenticator' must be implemented
                        in a python module named 'Authenticator'.

                        Example:
                            from Interfaces import AuthenticatorInterface

                            class CustomImplementation(AuthenticatorInterface):
                                ...

                            def GetAuthenticator():
                                return CustomImplementation()

                        Exception Info:
                            {{}}

                        """,
                    ).format(StringHelpers.LeftJustify(traceback.format_exc(), 4)),
                )

            # Implementation
            try:
                import Implementation

                if hasattr(Implementation, "GetImplementation"):
                    implementation = Implementation.GetImplementation()
                elif hasattr(Implementation, "implementation"):
                    implementation = Implementation.implementation
                else:
                    raise ImportError()

            except:
                raise Exception(
                    textwrap.dedent(
                        """\\
                        The value 'implementation' or the method 'GetImplementation' must be implemented
                        in a python module named 'Implementation'.

                        Example:
                            from Interfaces import ImplementationInterface

                            class CustomImplementation(ImplementationInterface):
                                ...

                            def GetImplementation():
                                return CustomImplementation()

                        Exception Info:
                            {{}}

                        """,
                    ).format(StringHelpers.LeftJustify(traceback.format_exc(), 4)),
                )

            assert app
            assert content_processors
            assert authenticator
            assert implementation

            # ----------------------------------------------------------------------
            # ----------------------------------------------------------------------
            {methods}


            # ----------------------------------------------------------------------
            # ----------------------------------------------------------------------
            # ----------------------------------------------------------------------

            # Note that a value of '*' supports any/all domains
            _Execute_cors_domain                                = app.config.get("_FLASK_CORS_DOMAIN", None)
            _default_content_processor_key                      = {default_content_processor_assignment_value}


            # ----------------------------------------------------------------------
            def _GetContentProcessorType():
                if request.headers:
                    if "Accept" in request.headers:
                        for value in request.headers["Accept"].split(";"):
                            value = value.split(",")[-1].strip()

                            if value in content_processors:
                                return value

                    if "Content-Type" in request.headers and and request.headers["Content-Type"] in content_processors:
                        return request.headers["Content-Type"]

                if _default_content_processor_key is not None:
                    return _default_content_processor_key

                raise UnsupportedContentWebserverException()


            # ----------------------------------------------------------------------
            def _Execute(method_name, *args):
                try:
                    content_processor_type = _GetContentProcessorType()

                    content_processor = content_processors[content_processor_type]

                    # Extract the content from the request values
                    context = getattr(content_processor, "{{}}_Request".format(method_name))(
                        app.debug,
                        args,
                        request.headers,
                        request.form,
                        request.args,
                        request.data,
                    )

                    with implementation.CreateScopedSession() as session:
                        # TODO # Authenticate
                        # TODO user = None # TODO
                        # TODO
                        # TODO getattr(authenticator, method_name)(app.debug, user, context)

                        # Calculate the result
                        result = getattr(implementation, method_name)(
                            authenticator.Authenticate,
                            app.debug,
                            session,
                            context,
                        )

                        # Strip any query parameters from the uri
                        uri_result = uriparse(request.url)

                        uri = "{{scheme}}://{{netloc}}{{path}}".format(
                            scheme=uri_result.scheme,
                            netloc=uri_result.netloc,
                            path=uri_result.path,
                        )

                        # Convert the result into http components
                        status_code, headers, body = getattr(content_processor, "{{}}_Response".format(method_name))(
                            implementation.GetIds,
                            app.debug,
                            uri,
                            result,
                        )

                    headers = headers or {{}}

                    if "Content-Type" not in headers:
                        headers["Content-Type"] = content_processor_type

                    # Create the response based on the http components
                    response = Response(
                        body,
                        mimetype=content_processor_type,
                        headers=headers,
                        status=status_code,
                    )

                    if _Execute_cors_domain is not None:
                        domain = request.headers.get("Origin", None) or _Execute_cors_domain
                        assert domain is not None

                        response.headers["Access-Control-Allow-Origin"] = domain

                    return response

                except WebserverException as ex:
                    assert ex.Code is not None

                    if ex.Desc:
                        abort(ex.Code, ex.Desc)

                    potential_content = str(ex)
                    if potential_content:
                        abort(ex.Code, potential_content)

                    abort(ex.Code)

                except Exception as ex:
                    if app.debug:
                        trace = traceback.format_exc()

                        sys.stdout.write(trace)
                        abort(500, trace)

                    abort(500, str(ex))
            ''',
        ).format(
            methods="".join(content).rstrip(),
            default_content_processor_assignment_value="six.iterkeys(content_processors).next()" if support_default_content_processor else "None",
        ),
    )


# ----------------------------------------------------------------------
def WriteFlaskApp(f):
    f.write(
        textwrap.dedent(
            """\
            def GetFlaskApp():
                from flask import Flask
                return Flask(__name__)
            """,
        ),
    )


# ----------------------------------------------------------------------
def WriteApp(f, additional_python_paths):
    f.write(
        textwrap.dedent(
            """\
            import os
            import sys

            import six

            import CommonEnvironment
            from CommonEnvironment.CallOnExit import CallOnExit
            from CommonEnvironment import Constraints

            # ----------------------------------------------------------------------
            _script_fullpath                            = CommonEnvironment.ThisFullpath()
            _script_dir, _script_name                   = os.path.split(_script_fullpath)
            # ----------------------------------------------------------------------

            # ----------------------------------------------------------------------
            @Constraints.FunctionConstraints(
                import_paths=Constraints.DirectoryTypeInfo(
                    arity="*",
                ),
                custom_imports=Constraints.DictTypeInfo(
                    require_exact_match=False,
                    arity="?",
                ),
            )
            def Create(
                import_paths=None,
                custom_imports=None,
            ):
                # Update the paths
                for path in [
                    _script_dir,
                    os.path.join(_script_dir, ".."),
                ]:
                    sys.path.insert(0, path)
                {additional_python_paths}

                for import_path in (import_paths or []):
                    sys.path.insert(0, import_path)

                # Add custom imports
                for k, v in six.iteritems(custom_imports or {{}}):
                    if not os.path.exists(v):
                        raise Exception("'{{}}' is not a valid filename or directory".format(v))

                    if os.path.isfile(v):
                        dirname, basename = os.path.split(v)
                        basename = os.path.splitext(basename)[0]
                    elif os.path.isdir(v):
                        dirname, basename = os.path.split(v)
                    else:
                        assert False

                    sys.path.insert(0, dirname)
                    with CallOnExit(lambda: sys.path.pop(0)):
                        module = __import__(basename)

                    sys.modules[k] = module

                # Get the app
                import FlaskMethods
                from FlaskMethods import app

                return app


            # ----------------------------------------------------------------------
            def Run(
                app,
                debug,
                host=None,
                port=None,
            ):
                app.run(
                    debug=app.config.get("_FLASK_DEBUG", debug),
                    use_debugger=app.config.get("_FLASK_USE_DEBUGGER", debug),
                    use_reloader=app.config.get("_FLASK_USE_RELOADER", debug),
                    host=host,
                    port=port,
                )
            """,
        ).format(
            additional_python_paths="# No additional paths" if not additional_python_paths else "for path in [{}]: sys.path.insert(0, path)".format(", ".join(additional_python_paths)),
        ),
    )


# ----------------------------------------------------------------------
def WriteRunSever(f):
    f.write(
        textwrap.dedent(
            '''\
            import os
            import sys
            import textwrap

            import six

            import CommonEnvironment
            from CommonEnvironment import CommandLine

            from CommonEnvironmentEx.Package import InitRelativeImports

            # ----------------------------------------------------------------------
            _script_fullpath                            = CommonEnvironment.ThisFullpath()
            _script_dir, _script_name                   = os.path.split(_script_fullpath)
            # ----------------------------------------------------------------------

            with InitRelativeImports():
                from .App import Create, Run

            # ----------------------------------------------------------------------
            @CommandLine.EntryPoint
            @CommandLine.FunctionConstraints(
                import_path=CommandLine.DirectoryTypeInfo(
                    arity="*",
                ),
                custom_import=CommandLine.DictTypeInfo(
                    require_exact_match=False,
                    arity="*",
                ),
            )
            def EntryPoint(
                import_path=None,
                custom_import=None,
                debug=False,
            ):
                import_paths = import_path
                del import_path

                custom_imports = custom_import
                del custom_import

                if import_paths:
                    sys.stdout.write(
                        textwrap.dedent(
                            """\

                            Custom python paths:
                            {}

                            """,
                        ).format(
                            "\\n".join(["    - {}".format(path) for path in import_paths]),
                        ),
                    )

                if custom_imports:
                    sys.stdout.write(
                        textwrap.dedent(
                            """\

                            Custom python modules:
                            {}

                            """,
                        ).format(
                            "\\n".join(["    - {0:60} {1}".format("{}:".format(k), v) for k, v in six.iteritems(custom_imports)]),
                        ),
                    )

                sys.stdout.write("Starting Flask...\\n\\n")

                Run(Create(import_paths, custom_imports))

            # ----------------------------------------------------------------------
            # ----------------------------------------------------------------------
            # ----------------------------------------------------------------------
            if __name__ == "__main__":
                try:
                    sys.exit(
                        CommandLine.Main(
                            allow_exceptions=True,
                        ),
                    )
                except KeyboardInterrupt:
                    pass
            ''',
        ),
    )
