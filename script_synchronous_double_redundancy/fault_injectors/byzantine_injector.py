import re
from fault_injectors.base_injector import BaseInjector

class ByzantineInjector(BaseInjector):
     def inject(self, module_text, module_name, redundancy):
        if not self.faults:
            return module_text

        # Collect all fault configurations 
        fault_ids = [f.fault_id for f in self.faults]
        fault_enum_str = ", ".join(["none"] + fault_ids)

        module_text = self._add_to_var_block(module_text, f"    fault_mode : {{{fault_enum_str}}};")

        fault_init = "    init(fault_mode) := none;"
        fault_mode_next = (
            f"    next(fault_mode) :=\n"
            f"        case\n"
            f"            fault_mode = none : {{{fault_enum_str}}};\n"
            f"            TRUE              : fault_mode;\n"
            f"        esac;"
        )
        
        module_text = self._add_to_assign_block(module_text, fault_init, fault_mode_next)

        for fault in self.faults:
            target_var = fault.variable
            
            # Extract the original domain of the state variable to determine its full range of options
            domain_match = re.search(rf"{target_var}\s*:\s*(\{{[^}}]+\}})", module_text)
            if domain_match:
                full_range = domain_match.group(1)
            else:
                full_range = "{TRUE, FALSE}" 

            byzantine_case = f"        fault_mode = {fault.fault_id} : {full_range};"
            pattern = rf"(next\({target_var}\)\s*:=\s*case\n)"
            module_text = re.sub(pattern, rf"\1{byzantine_case}\n", module_text)

        # in RRA Server guard the TRUE branch inside next(request_received)
        if module_name == "Server" and "reply_ack_received" in module_text:
            pattern = r"(next\(request_received\)\s*:=\s*case\s*\n.*?)(server_request_state\s*=\s*receiving.*?:\s*TRUE;)"
            module_text = re.sub(
                pattern, 
                r"\1fault_mode = none &\n        \2", 
                module_text, 
                flags=re.DOTALL
            )

        # Avoid side effects on counters and interface toggles
        potential_side_effects = ["request_toggle", "reply_ack_toggle", "num_requests_sent", "num_requests_received", "request_sent"]
        active_side_effects = [v for v in potential_side_effects if f"next({v})" in module_text]
        
        module_text = self._suppress_side_effects(module_text, active_side_effects)

        return module_text