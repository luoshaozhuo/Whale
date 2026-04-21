"""Sample-data loading helpers for ingest persistence."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import yaml
from sqlalchemy.orm import Session

from whale.ingest.framework.persistence.orm.opcua_connection_orm import (
    OpcUaClientConnectionORM,
)
from whale.ingest.framework.persistence.orm.opcua_nodeset_orm import (
    AliasORM,
    NamespaceUriORM,
    UaObjectORM,
    UaObjectTypeORM,
    UaReferenceORM,
    UaVariableORM,
)
from whale.ingest.framework.persistence.orm.source_runtime_config_orm import (
    SourceRuntimeConfigORM,
)

UA_NODESET_NS = {"ua": "http://opcfoundation.org/UA/2011/03/UANodeSet.xsd"}


def load_sample_data(
    session: Session,
    connection_config_path: Path,
    nodeset_path: Path,
) -> None:
    """Load sample OPC UA configuration and NodeSet data into the database."""
    _load_connection_samples(session, connection_config_path)
    _load_nodeset_samples(session, nodeset_path)
    session.commit()


def _load_connection_samples(session: Session, connection_config_path: Path) -> None:
    """Load sample OPC UA client connections and runtime config rows."""
    raw_config = yaml.safe_load(connection_config_path.read_text(encoding="utf-8")) or {}
    connections = raw_config.get("connections", [])

    for item in connections:
        source_id = str(item["name"])
        update_interval_ms = int(item["update_interval_ms"])

        session.add(
            OpcUaClientConnectionORM(
                name=source_id,
                endpoint=str(item["endpoint"]),
                security_policy=str(item["security_policy"]),
                security_mode=str(item["security_mode"]),
                update_interval_ms=update_interval_ms,
                enabled=True,
            )
        )
        session.add(
            SourceRuntimeConfigORM(
                source_id=source_id,
                protocol="opcua",
                acquisition_mode="POLLING",
                interval_ms=update_interval_ms,
                enabled=True,
            )
        )


def _load_nodeset_samples(session: Session, nodeset_path: Path) -> None:
    """Load sample NodeSet metadata rows from the XML fixture."""
    root = ElementTree.parse(nodeset_path).getroot()

    _load_namespace_uris(session, root)
    _load_aliases(session, root)
    _load_object_types(session, root)
    _load_objects(session, root)
    _load_variables(session, root)
    _load_references(session, root)


def _load_namespace_uris(session: Session, root: ElementTree.Element) -> None:
    """Load namespace URI rows from a NodeSet document."""
    for index, element in enumerate(root.findall("./ua:NamespaceUris/ua:Uri", UA_NODESET_NS)):
        if element.text is None:
            continue
        session.add(
            NamespaceUriORM(
                uri=element.text.strip(),
                sort_order=index,
            )
        )


def _load_aliases(session: Session, root: ElementTree.Element) -> None:
    """Load alias rows from a NodeSet document."""
    for element in root.findall("./ua:Aliases/ua:Alias", UA_NODESET_NS):
        alias = element.get("Alias")
        target_node_id = _element_text(element)
        if alias is None or target_node_id == "":
            continue
        session.add(
            AliasORM(
                alias=alias,
                target_node_id=target_node_id,
            )
        )


def _load_object_types(session: Session, root: ElementTree.Element) -> None:
    """Load UAObjectType rows from a NodeSet document."""
    for element in root.findall("./ua:UAObjectType", UA_NODESET_NS):
        node_id = element.get("NodeId")
        browse_name = element.get("BrowseName")
        display_name = _child_text(element, "ua:DisplayName")
        if node_id is None or browse_name is None or display_name == "":
            continue
        session.add(
            UaObjectTypeORM(
                node_id=node_id,
                browse_name=browse_name,
                display_name=display_name,
                is_abstract=_parse_bool(element.get("IsAbstract")),
            )
        )


def _load_objects(session: Session, root: ElementTree.Element) -> None:
    """Load UAObject rows from a NodeSet document."""
    for element in root.findall("./ua:UAObject", UA_NODESET_NS):
        node_id = element.get("NodeId")
        browse_name = element.get("BrowseName")
        display_name = _child_text(element, "ua:DisplayName")
        if node_id is None or browse_name is None or display_name == "":
            continue
        session.add(
            UaObjectORM(
                node_id=node_id,
                browse_name=browse_name,
                display_name=display_name,
                parent_node_id=element.get("ParentNodeId"),
                type_definition=_find_type_definition(element),
            )
        )


def _load_variables(session: Session, root: ElementTree.Element) -> None:
    """Load UAVariable rows from a NodeSet document."""
    for element in root.findall("./ua:UAVariable", UA_NODESET_NS):
        node_id = element.get("NodeId")
        browse_name = element.get("BrowseName")
        parent_node_id = element.get("ParentNodeId")
        display_name = _child_text(element, "ua:DisplayName")
        if node_id is None or browse_name is None or parent_node_id is None or display_name == "":
            continue
        session.add(
            UaVariableORM(
                node_id=node_id,
                browse_name=browse_name,
                display_name=display_name,
                parent_node_id=parent_node_id,
                data_type=element.get("DataType"),
                value_rank=element.get("ValueRank"),
                initial_value_text=_find_initial_value_text(element),
            )
        )


def _load_references(session: Session, root: ElementTree.Element) -> None:
    """Load reference rows from a NodeSet document."""
    for source_node_class in ("UAObjectType", "UAObject", "UAVariable"):
        for element in root.findall(f"./ua:{source_node_class}", UA_NODESET_NS):
            source_node_id = element.get("NodeId")
            if source_node_id is None:
                continue
            references = element.findall("./ua:References/ua:Reference", UA_NODESET_NS)
            for reference in references:
                reference_type = reference.get("ReferenceType")
                target_node_id = _element_text(reference)
                if reference_type is None or target_node_id == "":
                    continue
                session.add(
                    UaReferenceORM(
                        source_node_id=source_node_id,
                        source_node_class=source_node_class,
                        reference_type=reference_type,
                        is_forward=_parse_is_forward(reference.get("IsForward")),
                        target_node_id=target_node_id,
                    )
                )


def _find_type_definition(element: ElementTree.Element) -> str | None:
    """Return the target node id of the HasTypeDefinition reference if present."""
    for reference in element.findall("./ua:References/ua:Reference", UA_NODESET_NS):
        if reference.get("ReferenceType") == "HasTypeDefinition":
            target_node_id = _element_text(reference)
            return target_node_id or None
    return None


def _find_initial_value_text(element: ElementTree.Element) -> str | None:
    """Return the serialized initial value text of one UAVariable if present."""
    value = element.find("./ua:Value", UA_NODESET_NS)
    if value is None or len(value) == 0:
        return None
    child = value[0]
    text = _element_text(child)
    return text or None


def _child_text(element: ElementTree.Element, pattern: str) -> str:
    """Return stripped child text or an empty string."""
    child = element.find(pattern, UA_NODESET_NS)
    if child is None:
        return ""
    return _element_text(child)


def _element_text(element: ElementTree.Element) -> str:
    """Return stripped element text or an empty string."""
    return (element.text or "").strip()


def _parse_bool(raw_value: str | None) -> bool:
    """Parse a truthy XML attribute value."""
    return str(raw_value).lower() == "true"


def _parse_is_forward(raw_value: str | None) -> bool:
    """Parse OPC UA IsForward semantics where missing means true."""
    if raw_value is None:
        return True
    return _parse_bool(raw_value)
