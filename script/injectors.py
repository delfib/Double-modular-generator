import re

def _extract_enum_values(module_text, variable):
    """
    Parse the VAR block to find the enum values declared for `variable`.
    E.g.  server_state : {receiving, received};  ->  ['receiving', 'received']
    """
    pattern = rf'{re.escape(variable)}\s*:\s*\{{([^}}]+)\}}'
    match = re.search(pattern, module_text)
    if not match:
        raise ValueError(
            f"Could not find enum declaration for variable '{variable}' "
            f"in module text."
        )
    return [v.strip() for v in match.group(1).split(',')]

class BaseInjector:
    """
    Shared build pipeline used by all concrete injectors.
    Subclasses must implement:
      - get_fault_mode_enum()        
      - _build_fault_cases_for_var() 
    """
    def __init__(self, faults):
        self.faults = faults

    def get_fault_mode_enum(self):
        """Return the full fault_mode enum as a comma-separated string."""
        raise NotImplementedError

    def _build_fault_cases_for_var(self, variable, var_faults, module_text):
        """
        Return the SMV case lines (as a string) to prepend inside
        next(<variable>) := case … for every fault that targets <variable>.
        """
        raise NotImplementedError

    def build_extended_module(self, module_text, original_name, new_name, redundancy):
        """
        Clone the target module, rename it, and inject all fault logic.
        For redundancy > 1 a server_id param is added to index the queue slot.
        """
        text = module_text

        # Rename module declaration
        text = re.sub(
            rf'MODULE\s+{re.escape(original_name)}\s*\(',
            f'MODULE {new_name}(',
            text
        )

        # Add server_id parameter to module signature if redundancy > 1
        if redundancy > 1:
            text = re.sub(
                rf'MODULE\s+{re.escape(new_name)}\(([^)]*)\)',
                lambda m: f'MODULE {new_name}({m.group(1)}, server_id)',
                text
            )

        # Inject fault_mode VAR declaration
        text = self._inject_fault_mode_var(text)
        # Inject fault_mode ASSIGN (init + next)
        text = self._inject_fault_mode_assign(text)
        # Inject fault conditions into next(<variable>) case blocks
        text = self._inject_fault_conditions(text, module_text)
        # Guard the toggle logic so faults don't fire spurious toggles
        text = self._protect_toggle_logic(text)

        # Update queue slot references for redundant servers
        if redundancy > 1:
            text = self._update_queue_references(text)

        return text

    def _inject_fault_mode_var(self, text):
        """Insert  fault_mode : {none, ...};  as the first VAR declaration."""
        enum_vals  = self.get_fault_mode_enum()
        fault_decl = f"    fault_mode : {{{enum_vals}}};\n"
        # Insert after VAR line
        return re.sub(r'(VAR\s*\n)', r'\1' + fault_decl, text)

    def _inject_fault_mode_assign(self, text):
        """
        Insert init(fault_mode) and next(fault_mode) into the ASSIGN block.
        """
        enum_vals  = self.get_fault_mode_enum()
        init_line  = "    init(fault_mode) := none;\n\n"
        next_block = (
            f"    next(fault_mode) :=\n"
            f"        case\n"
            f"            fault_mode = none : {{{enum_vals}}};\n"
            f"            TRUE              : fault_mode;\n"
            f"        esac;\n\n"
        )
        # Insert init(fault_mode) right after ASSIGN
        text = re.sub(r'(ASSIGN\s*\n)', r'\1' + init_line, text)
        # Insert next(fault_mode) before the first existing next() assignment
        text = re.sub(r'(    next\()', next_block + r'    next(', text, count=1)
        return text

    def _inject_fault_conditions(self, text, module_text):
        # Group faults by the variable they target
        faults_by_var = {}
        for fault in self.faults:
            faults_by_var.setdefault(fault.variable, []).append(fault)

        for variable, var_faults in faults_by_var.items():
            pattern = rf'(next\({re.escape(variable)}\)\s*:=\s*case)'
            match   = re.search(pattern, text)
            if not match:
                raise ValueError(f"Could not find next({variable}) assignment")

            fault_lines = self._build_fault_cases_for_var(variable, var_faults, module_text)
            insert_pos  = match.end()
            text = text[:insert_pos] + fault_lines + text[insert_pos:]

        return text

    def _protect_toggle_logic(self, text):
        """Add a fault_mode = none  guard to the toggle condition."""
        pattern = r'(next\(request_toggle\)\s*:=\s*case)(.*?)(esac;)'
        match   = re.search(pattern, text, re.DOTALL)
        if not match:
            return text

        cases     = match.group(2)
        new_cases = []
        for line in cases.split('\n'):
            if '!request_toggle' in line and ':' in line:
                parts     = line.split(':', 1)
                condition = parts[0].strip()
                action    = parts[1].strip()
                new_cases.append(
                    f"        fault_mode = none &\n"
                    f"        {condition} : {action}\n"
                )
            else:
                new_cases.append(line + '\n')

        new_block = match.group(1) + ''.join(new_cases) + '    ' + match.group(3)
        return text[:match.start()] + new_block + text[match.end():]

    def _update_queue_references(self, text):
        """Replace queue.last_server_toggle with queue.last_server_toggle[server_id]."""
        text = re.sub(
            r'queue\.last_server_toggle(?!\[)',
            'queue.last_server_toggle[server_id]',
            text
        )
        return text


class StuckAtInjector(BaseInjector):
    """
    Injects stuck-at faults: the target variable is permanently frozen at a
    fixed value once the fault mode is activated.
    """

    def get_fault_mode_enum(self):
        modes = ['none']
        for fault in self.faults:
            mode_name = f"stuck_{fault.value}"
            if mode_name not in modes:
                modes.append(mode_name)
        return ', '.join(modes)

    def _build_fault_cases_for_var(self, variable, var_faults, module_text):
        lines = "\n"
        for fault in var_faults:
            mode_name = f"stuck_{fault.value}"
            lines += f"        fault_mode = {mode_name} : {fault.value};\n"
        return lines


class ByzantineInjector(BaseInjector):
    """
    Injects byzantine faults: the target variable chooses its next value
    completely non-deterministically from its full declared enum, ignoring
    all protocol rules once the fault mode is activated.
    """
    def get_fault_mode_enum(self):
        modes = ['none']
        for fault in self.faults:
            mode_name = f"byzantine_{fault.variable}"
            if mode_name not in modes:
                modes.append(mode_name)
        return ', '.join(modes)

    def _build_fault_cases_for_var(self, variable, var_faults, module_text):
        # Derive the non-deterministic value set from the variable's enum declaration
        enum_vals = _extract_enum_values(module_text, variable)
        ndet_set  = '{' + ', '.join(enum_vals) + '}'
        mode_name = f"byzantine_{variable}"
        return f"\n        fault_mode = {mode_name} : {ndet_set};\n"


def create_injector(faults):
    """Return the appropriate injector for the given fault list."""
    fault_types = set(f.type for f in faults)

    if len(fault_types) > 1:
        raise ValueError(
            f"All faults must be of the same type. "
            f"Found mixed types: {fault_types}. "
            f"Use a separate faults.xml per fault type."
        )

    fault_type = fault_types.pop()

    if fault_type == 'stuck-at':
        return StuckAtInjector(faults)

    if fault_type == 'byzantine':
        return ByzantineInjector(faults)

    raise ValueError(f"Unsupported fault type: '{fault_type}'")