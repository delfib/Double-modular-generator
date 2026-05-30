import sys

from xml_parser import parse_fault_model
from smv_utils import load_smv, save_smv

from model_generator import ModelGenerator

def main():

    if len(sys.argv) != 4:
        print("Usage: python3 main.py <input.smv> <faults.xml> <output.smv>")
        sys.exit(1)

    input_smv = sys.argv[1]
    faults_xml = sys.argv[2]
    output_smv = sys.argv[3]

    fault_model = parse_fault_model(faults_xml)

    smv_content = load_smv(input_smv)

    generator = ModelGenerator(fault_model)

    result = generator.generate(smv_content)

    save_smv(output_smv, result)

if __name__ == "__main__":
    main()