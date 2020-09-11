# ----------------------------------------------------------------------
# |
# |  WebserverPluginMixin.py
# |
# |  David Brownell <Brownelldb@DavidBrownell.com>
# |      2020-08-28 17:47:14
# |
# ----------------------------------------------------------------------
# |
# |  Copyright David Brownell 2020
# |  Distributed under the Boost Software License, Version 1.0. See
# |  accompanying file LICENSE_1_0.txt or copy at
# |  http://www.boost.org/LICENSE_1_0.txt.
# |
# ----------------------------------------------------------------------
"""Contains the WebserverPluginMixin object"""

import os
import textwrap

import CommonEnvironment
from CommonEnvironment import StringHelpers

# ----------------------------------------------------------------------
_script_fullpath                            = CommonEnvironment.ThisFullpath()
_script_dir, _script_name                   = os.path.split(_script_fullpath)
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
class WebserverPluginMixin(object):

    # ----------------------------------------------------------------------
    @staticmethod
    def GenerateWebserverFilenames():
        return ["Exceptions.py", "Interfaces.py"]

    # ----------------------------------------------------------------------
    @staticmethod
    def GenerateWebserver(
        output_filenames,
        status_stream,
        file_header,
        endpoints,
    ):
        assert len(output_filenames) == 2, output_filenames

        # Exceptions
        status_stream.write("Writing '{}'...".format(output_filenames[0]))
        with status_stream.DoneManager():
            with open(output_filenames[0], "w") as f:
                f.write(
                    textwrap.dedent(
                        """\
                        {}
                        # ----------------------------------------------------------------------
                        class WebserverException(Exception):
                            Code                                    = None
                            Desc                                    = None


                        # ----------------------------------------------------------------------
                        class BadRequestWebserverException(WebserverException):
                            Code                                    = 400


                        # ----------------------------------------------------------------------
                        class ForbiddenWebserverException(WebserverException):
                            Code                                    = 403


                        # ----------------------------------------------------------------------
                        class NotFoundWebserverException(WebserverException):
                            Code                                    = 404


                        # ----------------------------------------------------------------------
                        class UnsupportedContentWebserverException(WebserverException):
                            Code                                    = 415


                        # ----------------------------------------------------------------------
                        class CustomWebserverException(WebserverException):
                            def __init__(
                                self,
                                code,
                                desc=None,
                            ):
                                self.Code                           = code
                                self.Desc                           = desc
                        """,
                    ).format(file_header),
                )

        # Interfaces
        status_stream.write("Writing '{}'...".format(output_filenames[1]))
        with status_stream.DoneManager():
            implementation_content = []
            authenticator_content = []
            content_processor_content = []

            # ----------------------------------------------------------------------
            def Impl(endpoint):
                for method in endpoint.methods:
                    implementation_content.append(
                        textwrap.dedent(
                            """\
                            # ----------------------------------------------------------------------
                            @staticmethod
                            @Interface.abstractmethod
                            def {}_{}(authenticate_func, debug, session, context):
                                raise Exception("Abstract method")

                            """,
                        ).format(endpoint.unique_name, method.verb),
                    )

                    authenticator_content.append(
                        textwrap.dedent(
                            """\
                            # ----------------------------------------------------------------------
                            @staticmethod
                            @Interface.abstractmethod
                            def {}_{}(debug, user, context):
                                raise Exception("Abstract method")

                            """,
                        ).format(endpoint.unique_name, method.verb),
                    )

                    content_processor_content.append(
                        textwrap.dedent(
                            '''\
                            # ----------------------------------------------------------------------
                            @staticmethod
                            @Interface.abstractmethod
                            def {unique_name}_{verb}_Request(debug, uri_args, headers, form_data, query_data, body):
                                """Returns context"""
                                raise Exception("Abstract method")

                            # ----------------------------------------------------------------------
                            @staticmethod
                            @Interface.abstractmethod
                            def {unique_name}_{verb}_Response(get_ids_func, debug, uri, result):
                                """Returns (status_code, headers, body)"""
                                raise Exception("Abstract method")

                            ''',
                        ).format(
                            unique_name=endpoint.unique_name,
                            verb=method.verb,
                        ),
                    )

                for child in endpoint.children:
                    Impl(child)

            # ----------------------------------------------------------------------

            for endpoint in endpoints:
                Impl(endpoint)

            with open(output_filenames[1], "w") as f:
                f.write(
                    textwrap.dedent(
                        '''\
                        {file_header}
                        import enum
                        from collection import namedtuple

                        from CommonEnvironment import Interface

                        # ----------------------------------------------------------------------
                        class ImplementationInterface(Interface.Interface):

                            # ----------------------------------------------------------------------
                            # |
                            # |  Public Types
                            # |
                            # ----------------------------------------------------------------------
                            class SortType(enum.Enum):
                                """Used to specify order when returning multiple items"""

                                Ascending = 1
                                Descending = 2

                            # ----------------------------------------------------------------------
                            class QueryType(enum.Enum):
                                """TODO"""

                                Id = 1 # TODO: Desc
                                Attributes = 2 # TODO: Desc

                            # ----------------------------------------------------------------------
                            GetQueryType                            = namedtuple(
                                "GetQueryType",
                                [
                                    "Local",
                                    "Reference",
                                    "Backref",
                                ],
                            )

                            # ----------------------------------------------------------------------
                            # |
                            # |  Public Methods
                            # |
                            # ----------------------------------------------------------------------
                            @staticmethod
                            @Interface.abstractmethod
                            def GetIds(object):
                                """Returns a list of ids of the object and its ancestors"""
                                raise Exception("Abstract method")

                            # ----------------------------------------------------------------------
                            @staticmethod
                            @Interface.abstractmethod
                            def CreateScopedSession():
                                raise Exception("Abstract method")

                            {implementation_content}


                        # ----------------------------------------------------------------------
                        class AuthenticatorInterface(Interface.Interface):

                            # ----------------------------------------------------------------------
                            @staticmethod
                            @Interface.abstractmethod
                            def Authenticate(obj):
                                raise Exception("Abstract method")

                            {authenticator_content}


                        # ----------------------------------------------------------------------
                        class ContentProcessorInterface(Interface.Interface):
                            {content_processor_content}
                        ''',
                    ).format(
                        file_header=file_header,
                        implementation_content=StringHelpers.LeftJustify("".join(implementation_content).rstrip(), 4),
                        authenticator_content=StringHelpers.LeftJustify("".join(authenticator_content).rstrip(), 4),
                        content_processor_content=StringHelpers.LeftJustify("".join(content_processor_content).rstrip(), 4),
                    ),
                )
