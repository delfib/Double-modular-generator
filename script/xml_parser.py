import xml.etree.ElementTree as ET

class Fault:
    def __init__(self, type, variable, value=None):
        self.type = type
        self.variable = variable
        self.value = value

    def __repr__(self):
        return f"Fault(type={self.type}, variable={self.variable}, value={self.value})"

class Property:
    def __init__(self, id, comment, spec):
        self.id = id
        self.comment = comment
        self.spec = spec

    def __repr__(self):
        return f"Property(id={self.id})"
    
class FaultModel:
    def __init__(self, model_file, protocol_type, target_module, redundancy, faults, properties=None):
        self.model_file    = model_file
        self.protocol_type = protocol_type  
        self.target_module = target_module
        self.redundancy    = redundancy
        self.faults        = faults
        self.properties    = properties or []

    def __repr__(self):
        return (
            f"FaultInjectionSpec(model_file={self.model_file}, "
            f"protocol_type={self.protocol_type}, "
            f"target_module={self.target_module}, "
            f"redundancy={self.redundancy}, "
            f"faults={self.faults}, "
            f"properties={self.properties})"
        )


def parse_fault_model(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # <model>
    model_file = root.findtext("model")
    if model_file is None:
        raise ValueError("Missing <model> in XML")
    model_file = model_file.strip()

    # <protocol-type>  R or RR  
    protocol_type = root.findtext("protocol-type")
    if protocol_type not in ("R", "RR") or protocol_type is None:
        raise ValueError(f"<protocol-type> must be 'R' or 'RR', got '{protocol_type}'")
    else:
        protocol_type = protocol_type.strip().upper()

    # <target-module>
    target_module = root.findtext("target-module")
    if target_module is None:
        raise ValueError("Missing <target-module> in XML")
    target_module = target_module.strip()

    # <redundancy count="N" />
    redundancy = 1
    redundancy_elem = root.find("redundancy")
    if redundancy_elem is not None:
        redundancy = int(redundancy_elem.attrib.get("count", "1"))

    # <faults>
    faults = []
    faults_elem = root.find("faults")
    if faults_elem is not None:
        for f in faults_elem.findall("fault"):
            fault_id   = f.attrib.get("id", "")
            fault_type = f.findtext("type")
            variable   = f.findtext("variable")
            value      = f.findtext("value")

            if fault_type is None or variable is None:
                raise ValueError(f"Fault '{fault_id}' needs at least <type> and <variable>")

            fault_type = fault_type.strip()
            variable   = variable.strip()

            if fault_type == "stuck-at":
                if value is None:
                    raise ValueError(f"Stuck-at fault '{fault_id}' requires <value>")
                faults.append(Fault(fault_type, variable, value.strip()))

            elif fault_type == "byzantine":
                faults.append(Fault(fault_type, variable, value.strip() if value else None))

            else:
                raise ValueError(f"Unknown fault type '{fault_type}' in fault '{fault_id}'")

    # <properties>
    properties = []
    properties_elem = root.find("properties")
    if properties_elem is not None:
        for p in properties_elem.findall("property"):
            prop_id = p.attrib.get("id", "")
            comment = p.findtext("comment", default="").strip()
            spec    = p.findtext("spec")
            if spec is None:
                raise ValueError(f"Property '{prop_id}' is missing <spec>")
            properties.append(Property(prop_id, comment, spec.strip()))

    return FaultModel(
        model_file=model_file,
        protocol_type=protocol_type,
        target_module=target_module,
        redundancy=redundancy,
        faults=faults,
        properties=properties,
    )