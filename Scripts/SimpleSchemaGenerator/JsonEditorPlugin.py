# ----------------------------------------------------------------------
# |
# |  JsonEditorPlugin.py
# |
# |  David Brownell <db@DavidBrownell.db@DavidBrownell.com>
# |      2022-05-31 11:35:31
# |
# ----------------------------------------------------------------------
# |
# |  Copyright David Brownell 2022
# |  Distributed under the Boost Software License, Version 1.0. See
# |  accompanying file LICENSE_1_0.txt or copy at
# |  http://www.boost.org/LICENSE_1_0.txt.
# |
# ----------------------------------------------------------------------
"""Contains the Plugin object"""

import json
import os

import six

import CommonEnvironment
from CommonEnvironment import Interface
from CommonEnvironment.Shell.All import CurrentShell

from CommonEnvironment.TypeInfo.FundamentalTypes.BoolTypeInfo import BoolTypeInfo
from CommonEnvironment.TypeInfo.FundamentalTypes.DateTimeTypeInfo import DateTimeTypeInfo
from CommonEnvironment.TypeInfo.FundamentalTypes.DateTypeInfo import DateTypeInfo
from CommonEnvironment.TypeInfo.FundamentalTypes.FloatTypeInfo import FloatTypeInfo
from CommonEnvironment.TypeInfo.FundamentalTypes.IntTypeInfo import IntTypeInfo
from CommonEnvironment.TypeInfo.FundamentalTypes.TimeTypeInfo import TimeTypeInfo
from CommonEnvironment.TypeInfo.FundamentalTypes.UriTypeInfo import UriTypeInfo

# Note that these imports have already been import by SimpleSchemaGenerator and
# should always be available without explicit path information.
from SimpleSchemaGenerator.Plugins.JsonSchemaPlugin import Plugin as JsonSchemaPlugin
from SimpleSchemaGenerator.Schema import Elements

# ----------------------------------------------------------------------
_script_fullpath                            = CommonEnvironment.ThisFullpath()
_script_dir, _script_name                   = os.path.split(_script_fullpath)
# ----------------------------------------------------------------------


# ----------------------------------------------------------------------
@Interface.staticderived
class Plugin(JsonSchemaPlugin):
    # ----------------------------------------------------------------------
    # |
    # |  Public Properties
    # |
    # ----------------------------------------------------------------------
    Name                                    = Interface.DerivedProperty("JsonEditor")
    Description                             = Interface.DerivedProperty("Generates JSON schemas that can be used with json-editor (https://github.com/json-editor/json-editor)")

    # ----------------------------------------------------------------------
    # |
    # |  Public Methods
    # |
    # ----------------------------------------------------------------------
    @classmethod
    @Interface.override
    def GenerateCustomSettingsAndDefaults(cls):
        yield from super(Plugin, cls).GenerateCustomSettingsAndDefaults()
        yield "arrays_as_tables", True

    # ----------------------------------------------------------------------
    @classmethod
    @Interface.override
    def GenerateOutputFilenames(cls, context):
        return [
            "{}.json-editor.json".format(context["output_name"]),
        ] \
            + super(Plugin, cls).GenerateOutputFilenames(context)

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
        arrays_as_tables,
        **kwargs,
    ):
        output_filenames = list(output_filenames)
        json_editor_output_filename = output_filenames.pop(0)

        result = super(Plugin, cls).Generate(
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
            **kwargs,
        )

        if result is None:
            result = 0

        if result != 0:
            return result

        status_stream.write("Creating '{}'...".format(json_editor_output_filename))
        with status_stream.DoneManager() as this_dm:
            include_map = cls._GenerateIncludeMap(elements, include_indexes)
            include_dotted_names = set(six.iterkeys(include_map))

            # Read the json schema output
            with open(output_filenames[0]) as f:
                json_schema = json.load(f)

            plugin_cls = cls

            # ----------------------------------------------------------------------
            class Visitor(Elements.ElementVisitor):
                # ----------------------------------------------------------------------
                @classmethod
                @Interface.override
                def OnExitingElement(cls, element):
                    if isinstance(element, Elements.ReferenceElement):
                        return

                    definition = cls._GetSchemaDefinition(element)
                    if "type" not in definition:
                        definition = cls._GetSchemaDefinition(
                            element,
                            item_definition=True,
                        )

                    if arrays_as_tables:
                        if definition.get("type", None) == "array":
                            definition["format"] = "table"

                    if element.description:
                        definition["options"] = {
                            "infoText": element.description,
                        }

                # ----------------------------------------------------------------------
                @classmethod
                @Interface.override
                def OnFundamental(cls, element):
                    format = {
                        BoolTypeInfo: "checkbox",
                        DateTimeTypeInfo: "datetime-local",
                        DateTypeInfo: "date",
                        FloatTypeInfo: "number",
                        IntTypeInfo: "number",
                        TimeTypeInfo: "time",
                        UriTypeInfo: "url",
                    }.get(type(element.TypeInfo), None)

                    if format is not None:
                        definition = cls._GetSchemaDefinition(
                            element,
                            item_definition=True,
                        )

                        definition["format"] = format

                # ----------------------------------------------------------------------
                @classmethod
                @Interface.override
                def OnCompound(cls, element):
                    compound_definition = cls._GetSchemaDefinition(
                        element,
                        item_definition=True,
                    )

                    for child_index, child in enumerate(plugin_cls._EnumerateChildren(
                        element,
                        include_definitions=False,
                    )):
                        child_definition = compound_definition["properties"].get(child.Name, None)
                        assert child_definition is not None
                        assert "$ref" in child_definition

                        child_definition["propertyOrder"] = child_index

                # ----------------------------------------------------------------------
                @staticmethod
                @Interface.override
                def OnSimple(element):
                    raise Exception("SimpleElements are not supported")

                # ----------------------------------------------------------------------
                @staticmethod
                @Interface.override
                def OnVariant(element):
                    # Nothing to do for variants
                    pass

                # ----------------------------------------------------------------------
                @staticmethod
                @Interface.override
                def OnReference(element):
                    # Nothing to do for references
                    pass

                # ----------------------------------------------------------------------
                @staticmethod
                @Interface.override
                def OnList(element):
                    # Nothing to do for lists
                    pass

                # ----------------------------------------------------------------------
                @staticmethod
                @Interface.override
                def OnAny(element):
                    # Nothing to do for any
                    pass

                # ----------------------------------------------------------------------
                @staticmethod
                @Interface.override
                def OnCustom(element):
                    raise Exception("CustomElements are not supported")

                # ----------------------------------------------------------------------
                @staticmethod
                @Interface.override
                def OnExtension(element):
                    raise Exception("ExtensionElements are not supported")

                # ----------------------------------------------------------------------
                # ----------------------------------------------------------------------
                # ----------------------------------------------------------------------
                @staticmethod
                def _GetSchemaDefinition(
                    element,
                    item_definition=False,
                ):
                    attribute_name = "_{}".format(element.DottedName)

                    if item_definition:
                        attribute_name += "_Item"

                    attribute_value = json_schema["definitions"].get(attribute_name, None)
                    assert attribute_value is not None, attribute_name

                    return attribute_value

            # ----------------------------------------------------------------------

            Visitor().Accept(
                elements,
                include_dotted_names=include_dotted_names,
            )

            with open(json_editor_output_filename, "w") as f:
                json.dump(
                    json_schema,
                    f,
                    indent=2,
                    separators=[", ", " : "],
                    sort_keys=True,
                )
