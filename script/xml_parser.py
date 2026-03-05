import xml.etree.ElementTree as ET

class Fault:
    def __init__(self, type, variable, value):
        self.type = type
        self.variable = variable
        self.value = value

    def __repr__(self):
        return f"Fault(type={self.type}, variable={self.variable}, value={self.value})"

class FaultModel:
    def __init__(self, model_file, target_module, redundancy, faults):
        self.model_file = model_file
        self.target_module = target_module
        self.redundancy = redundancy
        self.faults = faults

    def __repr__(self):
        return (
            f"FaultInjectionSpec(model_file={self.model_file}, "
            f"target_module={self.target_module}, "
            f"redundancy={self.redundancy}, "
            f"faults={self.faults})"
        )


def parse_fault_model(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # <model>
    model_file = root.findtext("model")
    if model_file is None:
        raise ValueError("Missing <model> in XML")
    model_file = model_file.strip()

    # <target-module>
    target_module = root.findtext("target-module")
    if target_module is None:
        raise ValueError("Missing <target-module> in XML")
    target_module = target_module.strip()

    # <redundancy count="N" />
    redundancy = 1
    redundancy_elem = root.find("redundancy")
    if redundancy_elem is not None:
        redundancy = int(redundancy_elem.attrib.get("count", "1"))  # give me the value of count or 1 if it doesn't exist 

    # <faults>
    faults = []
    faults_elem = root.find("faults")
    if faults_elem is not None:
        for f in faults_elem.findall("fault"):
            type = f.findtext("type")
            variable = f.findtext("variable")
            value = f.findtext("value")

            if variable is None or value is None or type is None:
                raise ValueError("Each <fault> needs <type>, <variable> and <value>")

            faults.append(Fault(type.strip(), variable.strip(), value.strip()))

    return FaultModel(
        model_file=model_file,
        target_module=target_module,
        redundancy=redundancy,
        faults=faults
    )