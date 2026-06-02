import re
from abc import ABC, abstractmethod

class BaseInjector(ABC):
    def __init__(self, faults):
        self.faults = faults

    @abstractmethod
    def inject(self, module_text, module_name, redundancy):
        pass

    def _add_to_var_block(self, module_text, statements):
        """Helper to safely insert declarations into the VAR block."""
        return module_text.replace("VAR\n", f"VAR\n{statements}\n")

    def _add_to_assign_block(self, module_text, init_statement, next_statement):
        """
        Safely places the init statement right at the top of ASSIGN,
        and places the next statement right before the first existing next() block.
        """
        module_text = module_text.replace("ASSIGN\n", f"ASSIGN\n{init_statement}\n")
        
        if "next(" in module_text:
            module_text = re.sub(r"(\s+next\()", f"\n{next_statement}\n\\1", module_text, count=1)
        else:
            # if no next statements exist yet
            module_text += f"\n{next_statement}\n"
            
        return module_text

    def _suppress_side_effects(self, module_text, toggle_vars):
        """
        Prefixes functional next() blocks with 'fault_mode = none &' 
        to disable toggles or metrics counters while faulted.
        """
        for var in toggle_vars:
            pattern = rf"(next\({var}\)\s*:=\s*case\n\s*)(\w+)"
            module_text = re.sub(pattern, r"\1fault_mode = none &\n        \2", module_text)
        return module_text