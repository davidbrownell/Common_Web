# ----------------------------------------------------------------------
# |
# |  RestPluginImpl.py
# |
# |  David Brownell <db@DavidBrownell.com>
# |      2020-09-27 09:06:19
# |
# ----------------------------------------------------------------------
# |
# |  Copyright David Brownell 2020
# |  Distributed under the Boost Software License, Version 1.0. See
# |  accompanying file LICENSE_1_0.txt or copy at
# |  http://www.boost.org/LICENSE_1_0.txt.
# |
# ----------------------------------------------------------------------
"""Contains the RestPluginImpl object"""

import copy
import enum
import os
import sys

from collections import OrderedDict

import six

import CommonEnvironment
from CommonEnvironment.CallOnExit import CallOnExit
from CommonEnvironment import FileSystem
from CommonEnvironment import Interface
from CommonEnvironment.Shell.All import CurrentShell

from CommonEnvironmentEx.Package import InitRelativeImports

# ----------------------------------------------------------------------
_script_fullpath                            = CommonEnvironment.ThisFullpath()
_script_dir, _script_name                   = os.path.split(_script_fullpath)
# ----------------------------------------------------------------------

with InitRelativeImports():
    from ...Plugin import Plugin as PluginBase

sys.path.insert(0, os.path.join(_script_dir, "..", "SimpleSchema", "GeneratedCode", "PythonYaml"))
with CallOnExit(lambda: sys.path.pop(0)):
    import PythonYaml_PythonYamlSerialization as PythonYamlSerialization

# ----------------------------------------------------------------------
class RestPluginImpl(PluginBase):
    """\
    Base class for Plugins that process REST output generated by the
    HttpGeneratorRestPlugin SimpleSchema plugin.
    """

    # ----------------------------------------------------------------------
    # |  Public Types
    class EndpointType(enum.Enum):
        Collection                          = enum.auto()
        CollectionItem                      = enum.auto()

        ReferenceCollection                 = enum.auto()
        ReferenceCollectionItem             = enum.auto()
        ReferenceItem                       = enum.auto()

        BackrefCollection                   = enum.auto()
        BackrefCollectionItem               = enum.auto()
        BackrefItem                         = enum.auto()

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
        yield "temp_dir", ""
        yield "no_scrub", False

    # ----------------------------------------------------------------------
    @classmethod
    @Interface.override
    def GenerateOutputFilenames(cls, context):
        output_filenames = [
            os.path.join(context["output_dir"], os.path.basename(input_filename))
            for input_filename in context["inputs"]
        ]

        cls._output_filenames = output_filenames

        return cls._output_filenames

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
        temp_dir,
        no_scrub,
        **custom_args,
    ):
        status_stream.write("Extracting endpoint types...")
        with status_stream.DoneManager():
            token_map = OrderedDict(
                [
                    ("collection", cls.EndpointType.Collection),
                    ("collection_item", cls.EndpointType.CollectionItem),
                    ("reference_collection", cls.EndpointType.ReferenceCollection),
                    ("reference_collection_item", cls.EndpointType.ReferenceCollectionItem),
                    ("reference_item", cls.EndpointType.ReferenceItem),
                    ("backref_collection", cls.EndpointType.BackrefCollection),
                    ("backref_collection_item", cls.EndpointType.BackrefCollectionItem),
                    ("backref_item", cls.EndpointType.BackrefItem),
                ],
            )

            # ----------------------------------------------------------------------
            def Extract(endpoint):
                tokens = [item.strip() for item in getattr(endpoint, "context", "").split(";") if item.strip()]

                endpoint_type = None

                # ----------------------------------------------------------------------
                def Set(endpoint_type_value):
                    nonlocal endpoint_type

                    if endpoint_type is not None:
                        raise Exception(
                            "The 'context' attribute associated with the endpoint '{}' has multiple values ({})".format(
                                endpoint.full_uri,
                                endpoint.context,
                            ),
                        )

                    endpoint_type = endpoint_type_value

                # ----------------------------------------------------------------------

                for token in tokens:
                    if token.startswith("HttpGeneratorRestPlugin::"):
                        token = token[len("HttpGeneratorRestPlugin::"):]

                    token_value = token_map.get(token, None)
                    if token_value is not None:
                        Set(token_value)

                if endpoint_type is None:
                    raise Exception(
                        textwrap.dedent(
                            """\
                            The endpoint type for '{}' was not set in the 'context' attribute. One of
                            the following values was expected:

                            {}

                            """,
                        ).format(
                            endpoint.full_uri,
                            "\n".join(["    - {}".format(token) for token in six.iterkeys(token_map)]),
                        ),
                    )

                endpoint.context = endpoint_type

                for child in endpoint.children:
                    Extract(child)

            # ----------------------------------------------------------------------

            for root_filename, root in six.iteritems(roots):
                try:
                    for endpoint in root.endpoints:
                        Extract(endpoint)
                except Exception as ex:
                    raise Exception("{} <{}>".format(str(ex), root_filename)) from None

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
                    compile_dm.result = cls._CompilePickledSimpleSchemaContent(
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
                    cls._ExtractPickledSimpleSchemaContent(roots, temp_dir)

        status_stream.write("Extracting endpoint metadata...")
        with status_stream.DoneManager():
            # ----------------------------------------------------------------------
            def ValidateAndAugment(elements_lookup, endpoint):
                element_name = "__metadata_{}".format(getattr(endpoint, "group", endpoint.unique_name))

                element = elements_lookup.get(element_name, None)
                if element is None:
                    raise Exception("The attribute 'simple_schema_content' did not have a definition for '{}'".format(element_name))

                for expected_child in [
                    "__identities__",
                    "__items__",
                    "__mutable_items__",
                    "__references__",
                    "__backrefs__",
                ]:
                    if expected_child not in element.TypeInfo.Items:
                        raise Exception(
                            "The child '{}' was not defined in the SimpleSchema element '{}' associate with the endpoint '{}'".format(
                                expected_child,
                                element_name,
                                endpoint.full_uri,
                            ),
                        )

                # Capture the relationship elements, as that information will be needed
                # by derived plugins.
                reference_endpoints = {}
                backref_endpoints = {}

                # ----------------------------------------------------------------------
                def ApplyRelationship(element, endpoints):
                    for child in element.Children:
                        endpoints[child.Name] = child

                # ----------------------------------------------------------------------

                relationship_map = {
                    "__references__" : lambda element: ApplyRelationship(element, reference_endpoints),
                    "__backrefs__" : lambda element: ApplyRelationship(element, backref_endpoints),
                }

                for child in element.Children:
                    apply_func = relationship_map.get(child.Name, None)
                    if apply_func is None:
                        continue

                    apply_func(child)

                # Calculate the information necessary to create an instance of this element
                construct_args = OrderedDict()

                # ----------------------------------------------------------------------
                def GetChildElement(element, child_name):
                    for child in element.Children:
                        if child.Name == child_name:
                            return child

                    return None

                # ----------------------------------------------------------------------

                identities_element = GetChildElement(element, "__identities__")
                for child in identities_element.Children:
                    if child.TypeInfo.Arity.IsOptional:
                        continue

                    child = copy.deepcopy(child)
                    assert child.TypeInfo.Arity.Min == 1, child.Arity
                    assert child.TypeInfo.Arity.Max == 1, child.Arity

                    child.TypeInfo.Arity.Min = 0

                    construct_args[child.Name] = child

                for child_name in [
                    "__items__",
                    "__references__",
                ]:
                    items_element = GetChildElement(element, child_name)
                    for child in items_element.Children:
                        construct_args[child.Name] = child

                # Commit the augmented data
                endpoint._element = element
                endpoint._reference_endpoints = reference_endpoints
                endpoint._backref_endpoints = backref_endpoints
                endpoint._construct_args = construct_args

                # Process all children
                for child in endpoint.children:
                    ValidateAndAugment(elements_lookup, child)

            # ----------------------------------------------------------------------

            for root_filename, root in six.iteritems(roots):
                try:
                    elements_lookup = {}

                    for element in root.simple_schema_content["elements"]:
                        assert element.Name not in elements_lookup, element.Name
                        elements_lookup[element.Name] = element

                    for endpoint in root.endpoints:
                        ValidateAndAugment(elements_lookup, endpoint)
                except Exception as ex:
                    raise Exception("{} <{}>".format(str(ex), root_filename)) from None

        status_stream.write("Generating content...")
        with status_stream.DoneManager() as generate_dm:
            for index, ((root_filename, root), output_filename) in enumerate(zip(six.iteritems(roots), cls._output_filenames)):
                generate_dm.stream.write("Generating '{}' ({} of {})...".format(output_filename, index + 1, len(roots)))
                with generate_dm.stream.DoneManager(
                    suffix="\n",
                ) as this_dm:
                    this_dm.stream.write("Loading original content...")
                    with this_dm.stream.DoneManager():
                        yaml_content = PythonYamlSerialization.Deserialize(root_filename)

                    if not no_scrub:
                        this_dm.stream.write("Scrubbing original content...")
                        with this_dm.stream.DoneManager():
                            del yaml_content.simple_schema_content

                            # ----------------------------------------------------------------------
                            def Scrub(endpoint):
                                del endpoint.context

                                for child in getattr(endpoint, "children", []):
                                    Scrub(child)

                            # ----------------------------------------------------------------------

                            for endpoint in yaml_content.endpoints:
                                Scrub(endpoint)

                    this_dm.stream.write("Updating content...")
                    with this_dm.stream.DoneManager():
                        cls._DecorateEndpoints(root.endpoints, yaml_content, **custom_args)

                    this_dm.stream.write("Writing content...")
                    with this_dm.stream.DoneManager():
                        with open(output_filename, "w") as f:
                            f.write(
                                PythonYamlSerialization.Serialize(
                                    yaml_content,
                                    to_string=True,
                                ),
                            )

    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.abstractmethod
    def _DecorateEndpoints(parsed_endpoints, output_endpoint_info, **kwargs):
        raise Exception("Abstract method")
