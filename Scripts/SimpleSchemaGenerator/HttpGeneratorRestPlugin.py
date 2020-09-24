# ----------------------------------------------------------------------
# |
# |  HttpGeneratorRestPlugin.py
# |
# |  David Brownell <db@DavidBrownell.com>
# |      2020-09-14 17:17:00
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

import copy
import os
import textwrap

from collections import OrderedDict

import rtyaml
import six

import CommonEnvironment
from CommonEnvironment import Interface
from CommonEnvironment import StringHelpers
from CommonEnvironment.TypeInfo import Arity
from CommonEnvironment.TypeInfo.FundamentalTypes.BoolTypeInfo import BoolTypeInfo
from CommonEnvironment.TypeInfo.FundamentalTypes.StringTypeInfo import StringTypeInfo

from CommonSimpleSchemaGenerator.RelationalPluginImpl import (
    RelationalPluginImpl,
    ChildVisitor as ChildVisitorBase,
    Relationship,
)
from CommonSimpleSchemaGenerator.TypeInfo.FundamentalTypes.Serialization.SimpleSchemaVisitor import (
    SimpleSchemaVisitor,
    SimpleSchemaType,
)

# ----------------------------------------------------------------------
_script_fullpath                            = CommonEnvironment.ThisFullpath()
_script_dir, _script_name                   = os.path.split(_script_fullpath)
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
@Interface.staticderived
class Plugin(RelationalPluginImpl):
    # ----------------------------------------------------------------------
    # |
    # |  Public Properties
    # |
    # ----------------------------------------------------------------------
    Name                                    = Interface.DerivedProperty("HttpGeneratorRest")
    Description                             = Interface.DerivedProperty("Generates HttpGenerator content for REST objects")

    # ----------------------------------------------------------------------
    # |
    # |  Public Methods
    # |
    # ----------------------------------------------------------------------
    @classmethod
    @Interface.override
    def GetAdditionalGeneratorItems(cls, context):
        return super(Plugin, cls).GetAdditionalGeneratorItems(context) + [RelationalPluginImpl]

    # ----------------------------------------------------------------------
    @classmethod
    @Interface.override
    def GenerateOutputFilenames(cls, context):
        return [os.path.join(context["output_dir"], "{}.yaml".format(context["output_name"]))]

    # ----------------------------------------------------------------------
    @classmethod
    @Interface.override
    def Generate(
        cls,
        simple_schema_generator,
        invoke_reason,
        input_filenames,
        output_filenames,
        name,
        elements,
        include_indexes,
        status_stream,
        verbose_stream,
        verbose,
    ):
        status_stream.write("Writing '{}'...".format(output_filenames[0]))
        with status_stream.DoneManager():
            with open(output_filenames[0], "w") as f:
                f.write(
                    cls._GenerateFileHeader(
                        prefix="# ",
                    ),
                )

                # ----------------------------------------------------------------------
                @Interface.staticderived
                class ChildVisitor(ChildVisitorBase):
                    # ----------------------------------------------------------------------
                    def __init__(self):
                        self.identities     = OrderedDict()
                        self.items          = OrderedDict()
                        self.update_items   = OrderedDict()
                        self.references     = OrderedDict()
                        self.backrefs       = OrderedDict()

                    # ----------------------------------------------------------------------
                    @Interface.override
                    def OnIdentity(self, item):
                        self.identities[item.Name] = item

                    # ----------------------------------------------------------------------
                    @Interface.override
                    def OnFundamental(self, item):
                        self.items[item.Name] = item

                        if item.IsMutable:
                            # Optional values and strings (because empty strings aren't valid)
                            # need additional information in order to support scenarios where
                            # the value should be reset.
                            if item.TypeInfo.Arity.IsOptional or isinstance(item.TypeInfo, StringTypeInfo):
                                self.update_items["_{}_reset_value".format(item.Name)] = BoolTypeInfo(
                                    arity=Arity.FromString("?"),
                                )

                            type_info = copy.deepcopy(item.TypeInfo)

                            type_info.Arity = Arity.FromString("?")

                            self.update_items[item.Name] = type_info

                    # ----------------------------------------------------------------------
                    @Interface.override
                    def OnReference(self, item):
                        self.references[item.ReferenceName]= item

                    # ----------------------------------------------------------------------
                    @Interface.override
                    def OnBackref(self, item):
                        self.backrefs[item.BackrefName] = item

                # ----------------------------------------------------------------------
                def GetReferenceIdTypeInfo(item):
                    """Returns the type info for a reference id"""

                    assert item.ReferencedObject.children
                    assert item.ReferencedObject.children[0].Name == "id", item.ReferencedObject.children[0].Name

                    return item.ReferencedObject.children[0].Item.TypeInfo

                # ----------------------------------------------------------------------
                def GetBackrefIdTypeInfo(item):
                    """Returns the type info for a backref id"""

                    assert item.ReferencingObject.children
                    assert item.ReferencingObject.children[0].Name == "id", item.ReferencingObject.children[0].Name

                    return item.ReferencingObject.children[0].Item.TypeInfo

                # ----------------------------------------------------------------------

                # Write the SimpleSchema content for all types
                simple_schema_visitor = SimpleSchemaVisitor()

                simple_schemas = []
                endpoints = []
                endpoint_lookup = {}

                for obj in cls.AllObjects:
                    child_visitor = ChildVisitor()
                    child_visitor.Accept(obj)

                    metadata_content = []

                    # Generate the identity metadata
                    metadata_content.append(
                        textwrap.dedent(
                            """\
                            (__identities__):
                              {}

                            """,
                        ).format(
                            StringHelpers.LeftJustify(
                                "\n".join(
                                    [
                                        simple_schema_visitor.Accept(
                                            item.TypeInfo,
                                            identity_name,
                                            simple_schema_type=SimpleSchemaType.Definition,
                                        )
                                        for identity_name, item in six.iteritems(child_visitor.identities)
                                    ]
                                ),
                                2,
                            ),
                        ),
                    )

                    # Items
                    metadata_content.append(
                        textwrap.dedent(
                            """\
                            (__items__):
                              {}

                            """,
                        ).format(
                            "pass" if not child_visitor.items else StringHelpers.LeftJustify(
                                "\n".join(
                                    [
                                        simple_schema_visitor.Accept(
                                            item.TypeInfo,
                                            item_name,
                                            simple_schema_type=SimpleSchemaType.Definition,
                                        )
                                        for item_name, item in six.iteritems(child_visitor.items)
                                    ]
                                ),
                                2,
                            ),
                        ),
                    )

                    # Update Items
                    metadata_content.append(
                        textwrap.dedent(
                            """\
                            (__update_items__):
                              {}

                            """,
                        ).format(
                            "pass" if not child_visitor.update_items else StringHelpers.LeftJustify(
                                "\n".join(
                                    [
                                        simple_schema_visitor.Accept(
                                            item_type_info,
                                            item_name,
                                            simple_schema_type=SimpleSchemaType.Definition,
                                        )
                                        for item_name, item_type_info in six.iteritems(child_visitor.update_items)
                                    ]
                                ),
                                2,
                            ),
                        ),
                    )

                    # Generate the relationship structures
                    reference_items = [(item_name, item) for item_name, item in six.iteritems(child_visitor.references) if not item.IsParentChild]

                    metadata_content.append(
                        textwrap.dedent(
                            """\
                            (__references__):
                              {}

                            """,
                        ).format(
                            "pass" if not reference_items else StringHelpers.LeftJustify(
                                "\n".join(["({} __metadata_{})".format(item_name, item.ReferencedObject.UniqueName) for item_name, item in reference_items]),
                                2,
                            ),
                        ),
                    )

                    backref_items = [(item_name, item) for item_name, item in six.iteritems(child_visitor.backrefs) if not item.IsParentChild]

                    metadata_content.append(
                        textwrap.dedent(
                            """\
                            (__backrefs__):
                              {}

                            """,
                        ).format(
                            "pass" if not backref_items else StringHelpers.LeftJustify(
                                "\n".join(["({} __metadata_{})".format(item_name, item.ReferencingObject.UniqueName) for item_name, item in backref_items]),
                                2,
                            ),
                        ),
                    )

                    # Finalize the types
                    simple_schemas.append(
                        textwrap.dedent(
                            """\
                            (__metadata_{}):
                              {}

                            """,
                        ).format(
                            obj.UniqueName,
                            StringHelpers.LeftJustify("".join(metadata_content).rstrip(), 2),
                        ),
                    )

                    # Generate the collection endpoint
                    collection_endpoint = OrderedDict()

                    collection_endpoint["context"] = "HttpGeneratorRestPlugin::collection"

                    if obj.Element.Parent is None:
                        endpoints.append(collection_endpoint)
                        path_prefix = "/"
                    else:
                        assert obj.Element.Parent.DottedName in endpoint_lookup, obj.Element.Parent.DottedName
                        endpoint_lookup[obj.Element.Parent.DottedName].append(collection_endpoint)
                        path_prefix = ""

                    collection_endpoint["uri"] = "{}{}/".format(path_prefix, obj.PluralPascalName)
                    collection_endpoint["group"] = obj.UniqueName
                    collection_endpoint["summary"] = "Operations on a collection of '{}' items".format(obj.SingularPascalName)

                    collection_endpoint["methods"] = [
                        {
                            "verb": "POST",
                            "summary": "CREATE",
                            "description": "Creates a '{}' item".format(obj.SingularPascalName),
                        },
                        {
                            "verb": "GET",
                            "summary": "ENUMERATE",
                            "description": "Returns all '{}' items".format(obj.SingularPascalName),
                        },
                    ]

                    collection_endpoint["children"] = []

                    # Generate the item endpoint
                    item_endpoint = OrderedDict()

                    item_endpoint["context"] = "HttpGeneratorRestPlugin::collection_item"

                    id_name = "{}_id".format(obj.SingularSnakeName)

                    item_endpoint["uri"] = "{{{}}}/".format(id_name)
                    item_endpoint["group"] = obj.UniqueName
                    item_endpoint["summary"] = "Operations on a '{}' item".format(obj.SingularPascalName)

                    if obj.Element.description:
                        item_endpoint["description"] = obj.Element.description

                    item_endpoint["variables"] = [
                        {
                            "name" : id_name,
                            "simple_schema" : simple_schema_visitor.Accept(child_visitor.identities["id"].TypeInfo, id_name),
                        },
                    ]

                    item_endpoint["methods"] = [
                        {
                            "verb": "GET",
                            "summary": "READ",
                            "description": "Returns a '{}' item".format(obj.SingularPascalName),
                        },
                        {
                            "verb": "DELETE",
                            "summary": "DELETE",
                            "description":
                            "Deletes a '{}' item".format(obj.SingularPascalName),
                        },
                    ]

                    if child_visitor.update_items:
                        item_endpoint["methods"].append(
                            {
                                "verb": "PATCH",
                                "summary": "UPDATE",
                                "description": "Updates a '{}' item".format(obj.SingularPascalName),
                            },
                        )

                    item_endpoint["children"] = []
                    collection_endpoint["children"].append(item_endpoint)

                    # References
                    for item_name, item in six.iteritems(child_visitor.references):
                        # We don't need to include the parent/child relationships,
                        # as those relationships are implied by the uri structure.
                        if item.IsParentChild:
                            continue

                        reference_endpoint = OrderedDict()

                        reference_endpoint["uri"] = "{}/".format(item_name)
                        reference_endpoint["group"] = obj.UniqueName

                        reference_endpoint["methods"] = []

                        item_endpoint["children"].append(reference_endpoint)

                        if item.RelationshipType == Relationship.RelationshipType.ManyToMany:
                            reference_endpoint["context"] = "HttpGeneratorRestPlugin::reference_collection"

                            reference_endpoint["methods"].append(
                                {
                                    "verb": "GET",
                                    "summary": "ENUMERATE",
                                    "description": "Returns all '{}' references".format(item.ReferencedObject.SingularPascalName),
                                },
                            )

                            if item.IsMutable:
                                reference_endpoint["methods"].append(
                                    {
                                        "verb": "POST",
                                        "summary": "CREATE",
                                        "description": "Creates a '{}' reference".format(item.ReferencedObject.SingularPascalName),
                                    },
                                )

                            # Individual items
                            reference_item_endpoint = OrderedDict()

                            reference_item_endpoint["context"] = "HttpGeneratorRestPlugin::reference_collection_item"

                            id_name = "{}_id".format(item.ReferencedObject.SingularSnakeName)

                            reference_item_endpoint["uri"] = "{{{}}}/".format(id_name)
                            reference_item_endpoint["group"] = obj.UniqueName

                            reference_item_endpoint["variables"] = [
                                {
                                    "name": id_name,
                                    "simple_schema": simple_schema_visitor.Accept(GetReferenceIdTypeInfo(item), id_name),
                                },
                            ]

                            reference_item_endpoint["methods"] = [
                                {
                                    "verb": "GET",
                                    "summary": "READ",
                                    "description": "Returns the '{}' reference item".format(item.ReferencedObject.SingularPascalName),
                                },
                            ]

                            if item.IsMutable:
                                reference_item_endpoint["methods"].append(
                                    {
                                        "verb": "DELETE",
                                        "summary": "DELETE",
                                        "description": "Deletes the '{}' reference item".format(item.ReferencedObject.SingularPascalName),
                                    },
                                )

                            reference_endpoint["children"] = [reference_item_endpoint]

                        else:
                            reference_endpoint["context"] = "HttpGeneratorRestPlugin::reference_item"

                            reference_endpoint["methods"].append(
                                {
                                    "verb": "GET",
                                    "summary": "READ",
                                    "description": "Returns the '{}' reference".format(item.ReferencedObject.SingularPascalName),
                                },
                            )

                            if item.IsMutable:
                                reference_endpoint["methods"].append(
                                    {
                                        "verb": "PATCH",
                                        "summary": "UPDATE",
                                        "description": "Updates the '{}' reference".format(item.ReferencedObject.SingularPascalName),
                                    },
                                )

                            if item.IsOptional:
                                reference_endpoint["methods"].append(
                                    {
                                        "verb": "DELETE",
                                        "summary": "DELETE",
                                        "description": "Deletes the '{}' reference".format(item.ReferencedObject.SingularPascalName),
                                    },
                                )

                    # Backrefs
                    for item_name, item in six.iteritems(child_visitor.backrefs):
                        # We don't need to include the parent/child relationships,
                        # as those relationships are implied by the uri structure.
                        if item.IsParentChild:
                            continue

                        backref_endpoint = OrderedDict()

                        backref_endpoint["uri"] = "{}/".format(item.BackrefName)
                        backref_endpoint["group"] = obj.UniqueName

                        backref_endpoint["methods"] = []

                        item_endpoint["children"].append(backref_endpoint)

                        if item.RelationshipType == Relationship.RelationshipType.OneToOne:
                            backref_endpoint["context"] = "HttpGeneratorRestPlugin::backref_item"

                            backref_endpoint["methods"].append(
                                {
                                    "verb": "GET",
                                    "summary": "READ",
                                    "description": "Returns the '{}' backref".format(item.ReferencingObject.SingularPascalName),
                                },
                            )

                        else:
                            backref_endpoint["context"] = "HttpGeneratorRestPlugin::backref_collection"

                            backref_endpoint["methods"].append(
                                {
                                    "verb": "GET",
                                    "summary": "ENUMERATE",
                                    "description": "Returns all '{}' backrefs".format(item.ReferencingObject.SingularPascalName),
                                },
                            )

                            # Individual items
                            backref_item_endpoint = OrderedDict()

                            backref_item_endpoint["context"] = "HttpGeneratorRestPlugin::backref_collection_item"

                            id_name = "{}_id".format(item.ReferencingObject.SingularSnakeName)

                            backref_item_endpoint["uri"] = "{{{}}}/".format(id_name)
                            backref_item_endpoint["group"] = obj.UniqueName

                            backref_item_endpoint["variables"] = [
                                {
                                    "name": id_name,
                                    "simple_schema": simple_schema_visitor.Accept(GetBackrefIdTypeInfo(item), id_name),
                                },
                            ]

                            backref_item_endpoint["methods"] = [
                                {
                                    "verb": "GET",
                                    "summary": "READ",
                                    "description": "Returns the '{}' backref item".format(item.ReferencingObject.SingularPascalName),
                                },
                            ]

                            backref_endpoint["children"] = [backref_item_endpoint]

                    endpoint_lookup[obj.Element.DottedName] = item_endpoint["children"]

                # Remove all empty children objects
                # ----------------------------------------------------------------------
                def RemoveEmptyChildren(endpoint):
                    if "children" in endpoint:
                        if not endpoint["children"]:
                            del endpoint["children"]
                        else:
                            for child in endpoint["children"]:
                                RemoveEmptyChildren(child)

                # ----------------------------------------------------------------------

                for endpoint in endpoints:
                    RemoveEmptyChildren(endpoint)

                # Commit the content
                f.write(
                    rtyaml.dump(
                        OrderedDict(
                            [
                                ("simple_schema_content", "".join(simple_schemas)),
                                ("endpoints", endpoints),
                            ],
                        ),
                    ),
                )
