# ----------------------------------------------------------------------
# |
# |  JsonApiRestPlugin.py
# |
# |  David Brownell <db@DavidBrownell.com>
# |      2020-09-24 15:01:41
# |
# ----------------------------------------------------------------------
# |
# |  Copyright David Brownell 2020-22
# |  Distributed under the Boost Software License, Version 1.0. See
# |  accompanying file LICENSE_1_0.txt or copy at
# |  http://www.boost.org/LICENSE_1_0.txt.
# |
# ----------------------------------------------------------------------
"""Contains the Plugin object"""

import enum
import os
import textwrap

import six

import CommonEnvironment
from CommonEnvironment import Interface
from CommonEnvironment import StringHelpers

from CommonEnvironmentEx.Package import InitRelativeImports

from CommonSimpleSchemaGenerator.TypeInfo.FundamentalTypes.Serialization.SimpleSchemaVisitor import SimpleSchemaVisitor

# ----------------------------------------------------------------------
_script_fullpath                            = CommonEnvironment.ThisFullpath()
_script_dir, _script_name                   = os.path.split(_script_fullpath)
# ----------------------------------------------------------------------

with InitRelativeImports():
    from .Impl.RestPluginImpl import RestPluginImpl

# ----------------------------------------------------------------------
FIDELITY_QUERY_ITEM_NAME                    = "fidelity"
REF_FIDELITY_QUERY_ITEM_NAME                = "ref_fidelity"
BACKRE_FIDELITY_QUERY_ITEM_NAME             = "backref_fidelity"
SORT_QUERY_ITEM_NAME                        = "sort"
PAGE_QUERY_ITEM_NAME                        = "page"
PAGE_SIZE_QUERY_ITEM_NAME                   = "page_size"


# ----------------------------------------------------------------------
@Interface.staticderived
class Plugin(RestPluginImpl):
    # ----------------------------------------------------------------------
    # |  Public Properties
    Name                                    = Interface.DerivedProperty("JsonApiRest")
    Description                             = Interface.DerivedProperty("Creates a yaml file containing HttpGenerator definitions for REST methods according to the jsonapi specification (https://jsonapi.org/)")

    # ----------------------------------------------------------------------
    # |  Public Methods
    @classmethod
    @Interface.override
    def GenerateCustomSettingsAndDefaults(cls):
        yield from super(Plugin, cls).GenerateCustomSettingsAndDefaults()
        yield "no_pagination", False
        yield "no_sort", False
        yield "authentication_scheme", ""                                   # Name in IANA Authentication Scheme registry (https://www.iana.org/assignments/http-authschemes/http-authschemes.xhtml)
        yield "if_unmodified_since_header_verbs", ""                        # Comma-delimited list of http verbs that include the 'If-Unmodified-Since' header
        yield "if_unmodified_since_header_is_optional", False               # True if the 'If-Unmodified-Since' header should be considered optional

    # ----------------------------------------------------------------------
    # |  Private Methods
    @classmethod
    @Interface.override
    def _DecorateEndpoints(
        cls,
        parsed_endpoints,
        output_endpoint_info,
        no_pagination,
        no_sort,
        authentication_scheme,
        if_unmodified_since_header_verbs,
        if_unmodified_since_header_is_optional,
    ):
        if not hasattr(output_endpoint_info, "simple_schema_content"):
            output_endpoint_info.simple_schema_content = ""

        if_unmodified_since_header_verbs = set(_HttpProcessor.Verbs.FromString(item) for item in if_unmodified_since_header_verbs.split(",") if item.strip())

        if if_unmodified_since_header_is_optional and not if_unmodified_since_header_verbs:
            raise Exception("'if_unmodified_since_header_is_optional' should only be set to True when 'if_unmodified_since_header_verbs' has been provided")

        output_endpoint_info.simple_schema_content += textwrap.dedent(
            """\
                # GET fields (Read and Enumerate)
                #
                #   id:                     id, type
                #   identities:             <id>, identities (if any)
                #   items:                  <id>, items (if any)
                #   full:                   <id>, <identities>, <items>
                #   complete:               <full> for the entire reference hierarchy (complete is applied to all references)
                #
                (Fidelity enum values=[id, identities, items, full] default=full ?)
                (RefFidelity enum values=[none, id, identities, items, full, complete] default=identities ?)
                (BackrefFidelity enum values=[none, id, identities, items, full] default=id ?)

                (ReferenceRelationshipType enum values=[reference] ?)
                (BackrefRelationshipType enum values=[backref] ?)

                # GET fields (Enumerate)
                (Sort string validation_expression="(-?{var})(,(-?{var}))*" ?)

                """,
            ).format(
                var="[a-zA-Z0-9_]+",
            )

        # Create the map with classes
        endpoint_processor_map = {
            RestPluginImpl.EndpointType.Collection : _CollectionProcessor,
            RestPluginImpl.EndpointType.CollectionItem : _CollectionItemProcessor,
            RestPluginImpl.EndpointType.ReferenceCollection : _ReferenceCollectionProcessor,
            RestPluginImpl.EndpointType.ReferenceCollectionItem : _ReferenceCollectionItemProcessor,
            RestPluginImpl.EndpointType.ReferenceItem : _ReferenceItemProcessor,
            RestPluginImpl.EndpointType.BackrefCollection : _BackrefCollectionProcessor,
            RestPluginImpl.EndpointType.BackrefCollectionItem : _BackrefCollectionItemProcessor,
            RestPluginImpl.EndpointType.BackrefItem : _BackrefItemProcessor,
        }

        # Instantiate the classes in the map
        for k, v in six.iteritems(endpoint_processor_map):
            endpoint_processor_map[k] = v(
                authentication_scheme,
                if_unmodified_since_header_verbs,
                if_unmodified_since_header_is_optional,
            )

        # ----------------------------------------------------------------------
        def Impl(source_endpoint, dest_endpoint):
            processor = endpoint_processor_map[source_endpoint.context]

            simple_schemas = []

            for source_method, dest_method in zip(source_endpoint.methods, dest_endpoint.methods):
                assert source_method.verb == dest_method.verb, (source_method.verb, dest_method.verb)

                if not hasattr(dest_method, "requests"):
                    dest_method.requests = []
                if not hasattr(dest_method, "responses"):
                    dest_method.responses = []

                if source_method.verb == "POST":
                    func = processor.OnPost
                elif source_method.verb == "GET":
                    func = lambda *args: processor.OnGet(*args, no_pagination, no_sort)
                elif source_method.verb == "PATCH":
                    func = processor.OnPatch
                elif source_method.verb == "DELETE":
                    func = processor.OnDelete
                else:
                    assert False, source_method.verb

                potential_simple_schemas = func(
                    source_endpoint,
                    dest_endpoint,
                    dest_method,
                )

                if potential_simple_schemas:
                    simple_schemas.append(potential_simple_schemas)

            if simple_schemas:
                output_endpoint_info.simple_schema_content += "".join(simple_schemas)

            for source_child, dest_child in zip(
                getattr(source_endpoint, "children", []),
                getattr(dest_endpoint, "children", []),
            ):
                Impl(source_child, dest_child)

        # ----------------------------------------------------------------------

        for source, dest in zip(parsed_endpoints, output_endpoint_info.endpoints):
            Impl(source, dest)


# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
class _HttpProcessor(Interface.Interface):
    CONTENT_TYPE                            = "application/vnd.api+json"

    # ----------------------------------------------------------------------
    def __init__(
        self,
        authentication_scheme,
        if_unmodified_since_header_verbs,
        if_unmodified_since_header_is_optional,
    ):
        self.authentication_scheme                      = authentication_scheme
        self.if_unmodified_since_header_verbs           = if_unmodified_since_header_verbs
        self.if_unmodified_since_header_is_optional     = if_unmodified_since_header_is_optional

    # ----------------------------------------------------------------------
    @staticmethod
    def GetOrCreateResponseContents(dest_method, code):
        """Returns the contents array for a particular response code"""

        contents = next((d["contents"] for d in dest_method.responses if d["code"] == code), None)
        if contents is not None:
            return contents

        dest_method.responses.append(
            {
                "code" : code,
                "contents" : [],
            },
        )

        descriptions = {
            200 : ("OK", "The request was successful."),
            204 : ("No Content", "The request has been processed and there is nothing to return."),
            400 : ("Bad Request", "The request parameters are not valid."),
            401 : ("Unauthorized", "The request is not authorized."),
            404 : ("Not Found", "An object at this endpoint does not exist."),
            412 : ("Precondition Failed", "One or more conditions given in the request header fields evaluated to false when tested on the server."),
        }

        result = descriptions.get(code, None)
        if result is not None:
            dest_method.responses[-1]["summary"] = result[0]
            dest_method.responses[-1]["description"] = result[1]

        return dest_method.responses[-1]["contents"]

    # ----------------------------------------------------------------------
    def CreateResponses(self, verb, dest_method, *codes):
        if verb in self.if_unmodified_since_header_verbs and 412 not in codes:
            codes = list(codes)
            codes.append(412)

        for code in codes:
            self.GetOrCreateResponseContents(dest_method, code).append(
                {
                    "content_type" : self.CONTENT_TYPE,
                },
            )

    # ----------------------------------------------------------------------
    @staticmethod
    def ExtractNameFromMetadataName(value):
        assert value.startswith("__metadata_"), value
        return value[len("__metadata_"):]

    # ----------------------------------------------------------------------
    @staticmethod
    def GetReferenceElement(
        source_endpoint,
        is_reference,
        uri_component_offset=0,
    ):
        uri_components = source_endpoint.full_uri.strip("/").split("/")
        assert uri_component_offset < len(uri_components), (uri_component_offset, uri_components)

        name = uri_components[-1 - uri_component_offset]

        if is_reference:
            collection = source_endpoint._reference_endpoints
        else:
            collection = source_endpoint._backref_endpoints

        assert name in collection, name
        return collection[name]

    # ----------------------------------------------------------------------
    @classmethod
    def ExtractRelationshipNameFromMetadataName(
        cls,
        source_endpoint,
        is_reference,
        uri_component_offset=0,
    ):
        element = cls.GetReferenceElement(
            source_endpoint,
            is_reference,
            uri_component_offset=uri_component_offset,
        )

        return cls.ExtractNameFromMetadataName(element.Reference.DottedName)

    # ----------------------------------------------------------------------
    @staticmethod
    def GetGetQueryItems():
        query_items = [
            {
                "name" : FIDELITY_QUERY_ITEM_NAME,
                "description" : "Specifies the granularity of data associated with the returned object",
                "simple_schema" : "<fidelity Fidelity>",
            },
            {
                "name" : REF_FIDELITY_QUERY_ITEM_NAME,
                "description" : "Specifies the granularity of data associated with returned reference relationships",
                "simple_schema" : "<ref_fidelity RefFidelity>",
            },
            {
                "name" : BACKRE_FIDELITY_QUERY_ITEM_NAME,
                "description" : "Specifies the granularity of data associated with returned backref relationships",
                "simple_schema" : "<backref_fidelity BackrefFidelity>",
            },
        ]

        return query_items

    # ----------------------------------------------------------------------
    @classmethod
    def GetGetItemsQueryItems(cls, source_endpoint, no_pagination, no_sort):
        query_items = cls.GetGetQueryItems()

        if not no_sort:
            if getattr(source_endpoint._element.TypeInfo.Items["__items__"], "Items", []):
                query_items.append(
                    {
                        "name" : SORT_QUERY_ITEM_NAME,
                        "description" : 'Attribute values use to sort results (example: "attr1,-attr3")',
                        "simple_schema" : "<sort Sort>",
                    },
                )

        if not no_pagination:
            query_items += [
                {
                    "name" : PAGE_QUERY_ITEM_NAME,
                    "description" : "Page index (when results are paginated)",
                    "simple_schema" : "<page int min=0 ?>",
                },
                {
                    "name" : PAGE_SIZE_QUERY_ITEM_NAME,
                    "description" : "Page size (when results are paginated)",
                    "simple_schema" : "<page_size int min=1 ?>",
                },
            ]

        return query_items

    # ----------------------------------------------------------------------
    def GetStandardHeaderItems(self, verb):
        headers = []

        if self.authentication_scheme:
            headers.append(
                {
                    "name" : "Authorization",
                    "simple_schema" : '<authorization string description="{}">'.format(self.authentication_scheme),
                },
            )

        if verb in self.if_unmodified_since_header_verbs:
            headers.append(
                {
                    "name" : "If-Unmodified-Since",
                    "simple_schema" : "<if_unmodified_since datetime{}>".format(" ?" if self.if_unmodified_since_header_is_optional else ""),
                },
            )

        return headers

    # ----------------------------------------------------------------------
    @staticmethod
    def PruneBackrefQueryItems(query_items):
        return [
            qi for qi in query_items if qi["name"] not in [REF_FIDELITY_QUERY_ITEM_NAME, BACKRE_FIDELITY_QUERY_ITEM_NAME]
        ]

    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    class Verbs(enum.Enum):
        Post                                = enum.auto()
        Get                                 = enum.auto()
        Patch                               = enum.auto()
        Delete                              = enum.auto()

        # ----------------------------------------------------------------------
        @classmethod
        def FromString(cls, value):
            lvalue = value.strip().lower()

            if lvalue == "post":
                return cls.Post
            elif lvalue == "get":
                return cls.Get
            elif lvalue == "patch":
                return cls.Patch
            elif lvalue == "delete":
                return cls.Delete
            else:
                raise Exception("The value '{}' does not correspond to a supported verb".format(value))

    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.abstractmethod
    def OnPost(source_endpoint, dest_endpoint, dest_method):
        raise Exception("Abstract method")

    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.abstractmethod
    def OnGet(source_endpoint, dest_endpoint, dest_method, no_pagination, no_sort):
        raise Exception("Abstract method")

    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.abstractmethod
    def OnPatch(source_endpoint, dest_endpoint, dest_method):
        raise Exception("Abstract method")

    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.abstractmethod
    def OnDelete(source_endpoint, dest_endpoint, dest_method):
        raise Exception("Abstract method")


# ----------------------------------------------------------------------
class _CollectionProcessor(_HttpProcessor):
    # ----------------------------------------------------------------------
    @Interface.override
    def OnPost(self, source_endpoint, dest_endpoint, dest_method):
        # ----------------------------------------------------------------------
        def IsReferenceElement(element):
            return "ReferenceElement" in str(element.__class__)

        # ----------------------------------------------------------------------
        def GetReferenceArityString(element):
            result = element.TypeInfo.Arity.ToString()
            if result:
                result = " {}".format(result)

            return result

        # ----------------------------------------------------------------------

        attributes = []
        references = []

        for name, element in six.iteritems(source_endpoint._construct_args):
            if IsReferenceElement(element):
                references.append(
                    "<{name} {ref}_id{arity}>".format(
                        name=name,
                        ref=self.ExtractNameFromMetadataName(element.Reference.Name),
                        arity=GetReferenceArityString(element),
                    ),
                )
            else:
                attributes.append(SimpleSchemaVisitor.Accept(element.TypeInfo, name))

        if attributes:
            attributes = textwrap.dedent(
                """\
                <attributes>:
                    {}
                """,
            ).format(StringHelpers.LeftJustify("\n".join(attributes), 4))

        if references:
            references = textwrap.dedent(
                """\
                <relationships>:
                    {}
                """,
            ).format(StringHelpers.LeftJustify("\n".join(references), 4))

        dest_method.requests.append(
            {
                "content_type" : self.CONTENT_TYPE,
                "headers" : self.GetStandardHeaderItems(self.Verbs.Post),
                "body" : {
                    "simple_schema" : textwrap.dedent(
                        """\
                        <data>:
                            <type {reference}_id.type>{attributes}{references}
                        """,
                    ).format(
                        reference=source_endpoint.group,
                        attributes="" if not attributes else "\n    {}".format(StringHelpers.LeftJustify(attributes, 4).rstrip()),
                        references="" if not references else "\n    {}".format(StringHelpers.LeftJustify(references, 4).rstrip()),
                    ),
                },
            },
        )

        self.GetOrCreateResponseContents(dest_method, 200).append(
            {
                "content_type" : self.CONTENT_TYPE,
                "headers" : [
                    {
                        "name" : "Location",
                        "simple_schema" : "<location uri>",
                    },
                ],
                "body" : {
                    "simple_schema" : textwrap.dedent(
                        """\
                        <body>:
                            <data {}_id>
                            <links>:
                                <self uri>
                        """,
                    ).format(source_endpoint.group),
                },
            },
        )

        self.CreateResponses(self.Verbs.Post, dest_method, 400, 401)

    # ----------------------------------------------------------------------
    @Interface.override
    def OnGet(self, source_endpoint, dest_endpoint, dest_method, no_pagination, no_sort):
        # TODO: Handle variants

        unique_name = source_endpoint.group

        dest_method.requests.append(
            {
                "content_type" : self.CONTENT_TYPE,
                "headers" : self.GetStandardHeaderItems(self.Verbs.Get),
                "query_items" : self.GetGetItemsQueryItems(source_endpoint, no_pagination, no_sort),
            },
        )

        self.GetOrCreateResponseContents(dest_method, 200).append(
            {
                "content_type" : self.CONTENT_TYPE,
                "body" : {
                    "simple_schema" : textwrap.dedent(
                        """\
                        <body>:
                            <data {}_item *>
                            <links>:
                                <self uri>
                                <meta>:
                                    <item_template uri>
                                    <next uri ?>
                                    <prev uri ?>

                        """,
                    ).format(unique_name),
                },
            },
        )

        self.CreateResponses(self.Verbs.Get, dest_method, 400, 401)

        identities = source_endpoint._element.TypeInfo.Items["__identities__"].Items
        items = getattr(source_endpoint._element.TypeInfo.Items["__items__"], "Items", [])

        # Create the attributes data
        attribute_content = []

        # Create the identities definition
        if len(identities) > 1:
            attribute_content.append(
                textwrap.dedent(
                    """\
                    (identities):
                        {}

                    """,
                ).format(
                    StringHelpers.LeftJustify(
                        "\n".join([SimpleSchemaVisitor.Accept(type_info, name) for name, type_info in six.iteritems(identities) if name != "id"]),
                        4,
                    ),
                ),
            )

        # Create the items definition
        if items:
            attribute_content.append(
                textwrap.dedent(
                    """\
                    (items):
                        {}

                    """,
                ).format(
                    StringHelpers.LeftJustify(
                        "\n".join([SimpleSchemaVisitor.Accept(type_info, name) for name, type_info in six.iteritems(items)]),
                        4,
                    ),
                ),
            )

        if len(identities) > 1 and items:
            attribute_content.append(
                textwrap.dedent(
                    """\
                    (full (identities, items)): pass

                    <attributes (full | items | identities) ?>

                    """,
                ),
            )
        elif items:
            attribute_content.append(
                textwrap.dedent(
                    """\
                    <attributes items ?>

                    """,
                ),
            )
        else:
            attribute_content.append(
                textwrap.dedent(
                    """\
                    <attributes identities ?>

                    """,
                ),
            )

        # Get the reference and backref elements
        reference_elements = None
        backref_elements = None

        for element in source_endpoint._element.Children:
            if element.Name == "__references__":
                assert reference_elements is None
                reference_elements = element.Children

            if element.Name == "__backrefs__":
                assert backref_elements is None
                backref_elements = element.Children

        # Create the relationship data
        if reference_elements or backref_elements:
            relationship_content = []

            for elements, base_name_template, relationship_type_prefix in [
                (reference_elements, "{}_item", "Reference"),
                (backref_elements, "{}_attributes", "Backref"),
            ]:
                for element in (elements or []):
                    relationship_content.append(
                        textwrap.dedent(
                            """\
                            <{name} ?>:
                                <data {base}{arity}>
                                <links>:
                                    <self uri>
                                    <meta>:
                                        {links_meta_content}
                                <meta ?>:
                                    <relationship_type {relationship_type_prefix}RelationshipType>

                            """,
                        ).format(
                            name=element.Name,
                            base=base_name_template.format(self.ExtractNameFromMetadataName(element.Reference.Name)),
                            arity=" *" if element.TypeInfo.Arity.IsCollection else " ?" if element.TypeInfo.Arity.IsOptional else "",
                            relationship_type_prefix=relationship_type_prefix,
                            links_meta_content=StringHelpers.LeftJustify(
                                textwrap.dedent(
                                    """\
                                    <item_template uri>
                                    <related_template uri>
                                    """,
                                )
                                if element.TypeInfo.Arity.IsCollection else
                                textwrap.dedent(
                                    """\
                                    <related uri>
                                    """,
                                ),
                                12,
                            ).rstrip(),
                        ),
                    )

            relationship_content = textwrap.dedent(
                """\
                <relationships ?>:
                    {}
                """,
            ).format(
                StringHelpers.LeftJustify("".join(relationship_content), 4),
            )

        else:
            relationship_content = "pass"

        assert identities
        id_name, id_typeinfo = next(six.iteritems(identities))
        assert id_name == "id", id_name

        return textwrap.dedent(
            """\
            # ----------------------------------------------------------------------
            # |
            # |  {uri}
            # |
            # ----------------------------------------------------------------------
            ({unique_name}_id):
                {id_content}
                <type enum values=[{type_values}]>

            ({unique_name}_attributes {unique_name}_id):
                {attribute_content}

            ({unique_name}_item {unique_name}_attributes):
                {relationship_content}

            """,
        ).format(
            uri=source_endpoint.full_uri,
            unique_name=unique_name,
            type_values=unique_name,
            id_content=SimpleSchemaVisitor.Accept(id_typeinfo, "id"),
            attribute_content=StringHelpers.LeftJustify("".join(attribute_content).rstrip(), 4),
            relationship_content=StringHelpers.LeftJustify("".join(relationship_content).rstrip(), 4),
        )

    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.override
    def OnPatch(source_endpoint, dest_endpoint, dest_method):
        raise Exception("This should never be called")

    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.override
    def OnDelete(source_endpoint, dest_endpoint, dest_method):
        raise Exception("This should never be called")


# ----------------------------------------------------------------------
class _CollectionItemProcessor(_HttpProcessor):
    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.override
    def OnPost(source_endpoint, dest_endpoint, dest_method):
        raise Exception("This should never be called")

    # ----------------------------------------------------------------------
    @Interface.override
    def OnGet(self, source_endpoint, dest_endpoint, dest_method, no_pagination, no_sort):
        dest_method.requests.append(
            {
                "content_type" : self.CONTENT_TYPE,
                "headers" : self.GetStandardHeaderItems(self.Verbs.Get),
                "query_items" : self.GetGetQueryItems(),
            },
        )

        self.GetOrCreateResponseContents(dest_method, 200).append(
            {
                "content_type" : self.CONTENT_TYPE,
                "body" : {
                    "simple_schema" : textwrap.dedent(
                        """\
                        <body>:
                            <data {}_item>
                            <links>:
                                <self uri>

                        """,
                    ).format(source_endpoint.group),
                },
            },
        )

        self.CreateResponses(self.Verbs.Get, dest_method, 400, 401, 404)

    # ----------------------------------------------------------------------
    @Interface.override
    def OnPatch(self, source_endpoint, dest_endpoint, dest_method):
        mutable_items = source_endpoint._element.TypeInfo.Items["__mutable_items__"].Items
        assert mutable_items

        dest_method.requests.append(
            {
                "content_type" : self.CONTENT_TYPE,
                "headers" : self.GetStandardHeaderItems(self.Verbs.Patch),
                "body" : {
                    "simple_schema" : textwrap.dedent(
                        """\
                        <body>:
                            <data {unique_name}_id>:
                                <attributes>:
                                    {attributes}
                        """,
                    ).format(
                        unique_name=source_endpoint.group,
                        attributes=StringHelpers.LeftJustify(
                            "\n".join([SimpleSchemaVisitor.Accept(type_info, name) for name, type_info in six.iteritems(mutable_items)]),
                            12,
                        ),
                    ),
                },
            },
        )

        self.CreateResponses(self.Verbs.Patch, dest_method, 204, 400, 401, 404)

    # ----------------------------------------------------------------------
    @Interface.override
    def OnDelete(self, source_endpoint, dest_endpoint, dest_method):
        dest_method.requests.append(
            {
                "content_type" : self.CONTENT_TYPE,
                "headers" : self.GetStandardHeaderItems(self.Verbs.Delete),
            },
        )

        self.CreateResponses(self.Verbs.Delete, dest_method, 204, 401, 404)


# ----------------------------------------------------------------------
class _ReferenceCollectionProcessor(_HttpProcessor):
    # ----------------------------------------------------------------------
    @Interface.override
    def OnPost(self, source_endpoint, dest_endpoint, dest_method):
        reference_type = self.ExtractRelationshipNameFromMetadataName(
            source_endpoint,
            is_reference=True,
        )

        dest_method.requests.append(
            {
                "content_type" : self.CONTENT_TYPE,
                "headers" : self.GetStandardHeaderItems(self.Verbs.Post),
                "body" : {
                    "simple_schema" : textwrap.dedent(
                        """\
                        <body>:
                            <data {}_id>
                        """,
                    ).format(reference_type),
                },
            },
        )

        self.GetOrCreateResponseContents(dest_method, 200).append(
            {
                "content_type" : self.CONTENT_TYPE,
                "body" : {
                    "simple_schema" : textwrap.dedent(
                        """\
                        <body>:
                            <data {}_id>
                            <links>:
                                <self uri>
                                <meta>:
                                    <related uri>
                            <meta ?>:
                                <relationship_type ReferenceRelationshipType>
                        """,
                    ).format(reference_type),
                },
            },
        )

        self.CreateResponses(self.Verbs.Post, dest_method, 400, 401, 404)

    # ----------------------------------------------------------------------
    @Interface.override
    def OnGet(self, source_endpoint, dest_endpoint, dest_method, no_pagination, no_sort):
        reference_type = self.ExtractRelationshipNameFromMetadataName(
            source_endpoint,
            is_reference=True,
        )

        dest_method.requests.append(
            {
                "content_type" : self.CONTENT_TYPE,
                "headers" : self.GetStandardHeaderItems(self.Verbs.Get),
                "query_items" : self.GetGetItemsQueryItems(source_endpoint, no_pagination, no_sort),
            },
        )

        if self.GetReferenceElement(
            source_endpoint,
            is_reference=True,
        ).TypeInfo.Arity.Min == 0:
            arity = "*"
        else:
            arity = "+"

        self.GetOrCreateResponseContents(dest_method, 200).append(
            {
                "content_type" : self.CONTENT_TYPE,
                "body" : {
                    "simple_schema" : textwrap.dedent(
                        """\
                        <body>:
                            <data {reference}_item {arity}>
                            <links>:
                                <self uri>
                                <meta>:
                                    <item_template uri>
                                    <next uri ?>
                                    <prev uri ?>

                                    <related_template uri>
                            <meta ?>:
                                <relationship_type ReferenceRelationshipType>
                        """,
                    ).format(
                        reference=reference_type,
                        arity=arity,
                    ),
                },
            },
        )

        self.CreateResponses(self.Verbs.Get, dest_method, 400, 401)

    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.override
    def OnPatch(source_endpoint, dest_endpoint, dest_method):
        raise Exception("This should never be called")

    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.override
    def OnDelete(source_endpoint, dest_endpoint, dest_method):
        raise Exception("This should never be called")


# ----------------------------------------------------------------------
class _ReferenceCollectionItemProcessor(_HttpProcessor):
    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.override
    def OnPost(source_endpoint, dest_endpoint, dest_method):
        raise Exception("This should never be called")

    # ----------------------------------------------------------------------
    @Interface.override
    def OnGet(self, source_endpoint, dest_endpoint, dest_method, no_pagination, no_sort):
        reference_type = self.ExtractRelationshipNameFromMetadataName(
            source_endpoint,
            is_reference=True,
            uri_component_offset=1,
        )

        dest_method.requests.append(
            {
                "content_type" : self.CONTENT_TYPE,
                "headers" : self.GetStandardHeaderItems(self.Verbs.Get),
                "query_items" : self.GetGetQueryItems(),
            },
        )

        self.GetOrCreateResponseContents(dest_method, 200).append(
            {
                "content_type" : self.CONTENT_TYPE,
                "body" : {
                    "simple_schema" : textwrap.dedent(
                        """\
                        <body>:
                            <data {}_item>
                            <links>:
                                <self uri>
                                <meta>:
                                    <related uri>
                            <meta ?>:
                                <relationship_type ReferenceRelationshipType>
                        """,
                    ).format(
                        reference_type,
                    ),
                },
            },
        )

        self.CreateResponses(self.Verbs.Get, dest_method, 400, 401, 404)

    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.override
    def OnPatch(source_endpoint, dest_endpoint, dest_method):
        raise Exception("This should never be called")

    # ----------------------------------------------------------------------
    @Interface.override
    def OnDelete(self, source_endpoint, dest_endpoint, dest_method):
        dest_method.requests.append(
            {
                "content_type" : self.CONTENT_TYPE,
                "headers" : self.GetStandardHeaderItems(self.Verbs.Delete),
            },
        )

        self.CreateResponses(self.Verbs.Delete, dest_method, 204, 401, 404)


# ----------------------------------------------------------------------
class _ReferenceItemProcessor(_HttpProcessor):
    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.override
    def OnPost(source_endpoint, dest_endpoint, dest_method):
        raise Exception("This should never be called")

    # ----------------------------------------------------------------------
    @Interface.override
    def OnGet(self, source_endpoint, dest_endpoint, dest_method, no_pagination, no_sort):
        reference_type = self.ExtractRelationshipNameFromMetadataName(
            source_endpoint,
            is_reference=True,
        )

        dest_method.requests.append(
            {
                "content_type" : self.CONTENT_TYPE,
                "headers" : self.GetStandardHeaderItems(self.Verbs.Get),
                "query_items" : self.GetGetQueryItems(),
            },
        )

        if self.GetReferenceElement(
            source_endpoint,
            is_reference=True,
        ).TypeInfo.Arity.IsOptional:
            arity = " ?"
        else:
            arity = ""

        self.GetOrCreateResponseContents(dest_method, 200).append(
            {
                "content_type" : self.CONTENT_TYPE,
                "body" : {
                    "simple_schema" : textwrap.dedent(
                        """\
                        <body>:
                            <data {reference}_item{arity}>
                            <links>:
                                <self uri>
                                <meta{arity}>:
                                    <related uri>
                            <meta ?>:
                                <relationship_type ReferenceRelationshipType>
                        """,
                    ).format(
                        reference=reference_type,
                        arity=arity,
                    ),
                },
            },
        )

        self.CreateResponses(self.Verbs.Get, dest_method, 400, 401, 404)

    # ----------------------------------------------------------------------
    @Interface.override
    def OnPatch(self, source_endpoint, dest_endpoint, dest_method):
        reference_type = self.ExtractRelationshipNameFromMetadataName(
            source_endpoint,
            is_reference=True,
        )

        dest_method.requests.append(
            {
                "content_type" : self.CONTENT_TYPE,
                "headers" : self.GetStandardHeaderItems(self.Verbs.Patch),
                "body" : {
                    "simple_schema" : textwrap.dedent(
                        """\
                        <body>:
                            <data {}_id>
                        """,
                    ).format(reference_type),
                },
            },
        )

        self.GetOrCreateResponseContents(dest_method, 200).append(
            {
                "content_type" : self.CONTENT_TYPE,
                "body" : {
                    "simple_schema" : textwrap.dedent(
                        """\
                        <body>:
                            <data {}_id>
                            <links>:
                                <self uri>
                                <meta>:
                                    <related uri>
                            <meta ?>:
                                <relationship_type ReferenceRelationshipType>
                        """,
                    ).format(reference_type),
                },
            },
        )

        self.CreateResponses(self.Verbs.Patch, dest_method, 400, 401, 404)

    # ----------------------------------------------------------------------
    @Interface.override
    def OnDelete(self, source_endpoint, dest_endpoint, dest_method):
        dest_method.requests.append(
            {
                "content_type" : self.CONTENT_TYPE,
                "headers" : self.GetStandardHeaderItems(self.Verbs.Delete),
            },
        )

        self.CreateResponses(self.Verbs.Delete, dest_method, 204, 401, 404)


# ----------------------------------------------------------------------
class _BackrefCollectionProcessor(_HttpProcessor):
    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.override
    def OnPost(source_endpoint, dest_endpoint, dest_method):
        raise Exception("This should never be called")

    # ----------------------------------------------------------------------
    @Interface.override
    def OnGet(self, source_endpoint, dest_endpoint, dest_method, no_pagination, no_sort):
        reference_type = self.ExtractRelationshipNameFromMetadataName(
            source_endpoint,
            is_reference=False,
        )

        dest_method.requests.append(
            {
                "content_type" : self.CONTENT_TYPE,
                "headers" : self.GetStandardHeaderItems(self.Verbs.Get),
                "query_items" : self.PruneBackrefQueryItems(
                    self.GetGetItemsQueryItems(source_endpoint, no_pagination, no_sort)
                ),
            },
        )

        if self.GetReferenceElement(
            source_endpoint,
            is_reference=False,
        ).TypeInfo.Arity.Min == 0:
            arity = "*"
        else:
            arity = "+"

        self.GetOrCreateResponseContents(dest_method, 200).append(
            {
                "content_type" : self.CONTENT_TYPE,
                "body" : {
                    "simple_schema" : textwrap.dedent(
                        """\
                        <body>:
                            <data {reference}_attributes {arity}>
                            <links>:
                                <self uri>
                                <meta>:
                                    <item_template uri>
                                    <next uri ?>
                                    <prev uri ?>

                                    <related_template uri>
                            <meta ?>:
                                <relationship_type BackrefRelationshipType>
                        """,
                    ).format(
                        reference=reference_type,
                        arity=arity,
                    ),
                },
            },
        )

        self.CreateResponses(self.Verbs.Get, dest_method, 400, 401)

    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.override
    def OnPatch(source_endpoint, dest_endpoint, dest_method):
        raise Exception("This should never be called")

    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.override
    def OnDelete(source_endpoint, dest_endpoint, dest_method):
        raise Exception("This should never be called")


# ----------------------------------------------------------------------
class _BackrefCollectionItemProcessor(_HttpProcessor):
    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.override
    def OnPost(source_endpoint, dest_endpoint, dest_method):
        raise Exception("This should never be called")

    # ----------------------------------------------------------------------
    @Interface.override
    def OnGet(self, source_endpoint, dest_endpoint, dest_method, no_pagination, no_sort):
        reference_type = self.ExtractRelationshipNameFromMetadataName(
            source_endpoint,
            is_reference=False,
            uri_component_offset=1,
        )

        dest_method.requests.append(
            {
                "content_type" : self.CONTENT_TYPE,
                "headers" : self.GetStandardHeaderItems(self.Verbs.Get),
                "query_items" : self.PruneBackrefQueryItems(
                    self.GetGetQueryItems(),
                ),
            },
        )

        self.GetOrCreateResponseContents(dest_method, 200).append(
            {
                "content_type" : self.CONTENT_TYPE,
                "body" : {
                    "simple_schema" : textwrap.dedent(
                        """\
                        <body>:
                            <data {}_attributes>
                            <links>:
                                <self uri>
                                <meta>:
                                    <related uri>
                            <meta ?>:
                                <relationship_type BackrefRelationshipType>
                        """,
                    ).format(
                        reference_type,
                    ),
                },
            },
        )

        self.CreateResponses(self.Verbs.Get, dest_method, 400, 401, 404)

    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.override
    def OnPatch(source_endpoint, dest_endpoint, dest_method):
        raise Exception("This should never be called")

    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.override
    def OnDelete(source_endpoint, dest_endpoint, dest_method):
        raise Exception("This should never be called")


# ----------------------------------------------------------------------
class _BackrefItemProcessor(_HttpProcessor):
    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.override
    def OnPost(source_endpoint, dest_endpoint, dest_method):
        raise Exception("This should never be called")

    # ----------------------------------------------------------------------
    @Interface.override
    def OnGet(self, source_endpoint, dest_endpoint, dest_method, no_pagination, no_sort):
        reference_type = self.ExtractRelationshipNameFromMetadataName(
            source_endpoint,
            is_reference=False,
        )

        dest_method.requests.append(
            {
                "content_type" : self.CONTENT_TYPE,
                "headers" : self.GetStandardHeaderItems(self.Verbs.Get),
                "query_items" : self.PruneBackrefQueryItems(
                    self.GetGetQueryItems(),
                ),
            },
        )

        if self.GetReferenceElement(
            source_endpoint,
            is_reference=False,
        ).TypeInfo.Arity.IsOptional:
            arity = " ?"
        else:
            arity = ""

        self.GetOrCreateResponseContents(dest_method, 200).append(
            {
                "content_type" : self.CONTENT_TYPE,
                "body" : {
                    "simple_schema" : textwrap.dedent(
                        """\
                        <body>:
                            <data {reference}_attributes{arity}>
                            <links>:
                                <self uri>
                                <meta{arity}>:
                                    <related uri>
                            <meta ?>:
                                <relationship_type BackrefRelationshipType>
                        """,
                    ).format(
                        reference=reference_type,
                        arity=arity,
                    ),
                },
            },
        )

        self.CreateResponses(self.Verbs.Get, dest_method, 400, 401, 404)


    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.override
    def OnPatch(source_endpoint, dest_endpoint, dest_method):
        raise Exception("This should never be called")

    # ----------------------------------------------------------------------
    @staticmethod
    @Interface.override
    def OnDelete(source_endpoint, dest_endpoint, dest_method):
        raise Exception("This should never be called")
