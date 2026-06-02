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
        # Determine which variables are currently declared in the module
        declared_guards = []
        if "fault_mode_stuck_at" in module_text:
            declared_guards.append("fault_mode_stuck_at = none")
        if "fault_mode_byzantine" in module_text:
            declared_guards.append("fault_mode_byzantine = none")

        for var in toggle_vars:
            pattern = rf"(next\({var}\)\s*:=\s*case\n)(\s*)([^\n]+)"
            
            match = re.search(pattern, module_text)
            if match:
                header, indent, first_line = match.groups()
                
                # Check which of the declared guards are not already present in this specific block's first line
                missing_guards = [g for g in declared_guards if g not in first_line]
                
                if missing_guards:
                    # Build a single line guard statement out of the missing variables
                    guard_string = " & ".join(missing_guards) + " &"
                    specific_pattern = rf"(next\({var}\)\s*:=\s*case\n\s*)(\w+)"
                    module_text = re.sub(specific_pattern, rf"\1{guard_string}\n        \2", module_text)
                    
        return module_text

    def _add_fault_mode_infrastructure(self, module_text, fault_ids, suffix):
        """Builds infrastructure for a type-specific fault variable"""
        var_name = f"fault_mode_{suffix}"
        fault_enum_str = ", ".join(["none"] + fault_ids)
        
        module_text = self._add_to_var_block(module_text, f"    {var_name} : {{{fault_enum_str}}};")
        
        fault_init = f"    init({var_name}) := none;"
        fault_mode_next = (
            f"    next({var_name}) :=\n"
            f"        case\n"
            f"            {var_name} = none : {{{fault_enum_str}}};\n"
            f"            TRUE              : {var_name};\n"
            f"        esac;"
        )
        module_text = self._add_to_assign_block(module_text, fault_init, fault_mode_next)
        return module_text