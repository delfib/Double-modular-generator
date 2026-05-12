# Command to run the fault injector script
```py
python3 faults_injector.py R_Protocol.smv faults.xml R_Protocol_Extended.smv
```
```py
 clear && python3 faults_injector.py RRA_Protocol.smv faults.xml RESULT.smv 
```

# Commnad to compile an smv file and check properties
```NuSMV  UNRC/tesis/double-modular-generator/script/R_Protocol_Extended.smv ```
```NuSMV  UNRC/tesis/double-modular-generator/RPC_protocol/RRA_Protocol/RRA_ProtocolExtendedClient.smv > UNRC/tesis/double-modular-generator/BORRAR.txt
```
# Commands to compile in college servers
```investigador@thursday:~/delfina$ ./NuSMV-2.7.0-linux64/bin/NuSMV RR_Protocol.smv > RESULT.txt ```
```./NuSMV-2.7.0-linux64/bin/NuSMV -int -bmc RR_Protocol.smv```

# Command to compile smv file and check properties using BMC:
```NuSMV -bmc -bmc_length 30 UNRC/tesis/double-modular-generator/script/RESULT.smv > UNRC/tesis/double-modular-generator/BORRAR.txt```


# BMC
NuSMV -int -bmc UNRC/tesis/double-modular-generator/script/RESULT.smv
*** This is NuSMV 2.7.0 (compiled on Fri Oct 25 17:21:01 2024)
*** Enabled addons are: compass
*** For more information on NuSMV see <http://nusmv.fbk.eu>
*** or email to <nusmv-users@list.fbk.eu>.
*** Please report bugs to <Please report bugs to <nusmv-users@fbk.eu>>

*** Copyright (c) 2010-2024, Fondazione Bruno Kessler

*** This version of NuSMV is linked to the CUDD library version 2.4.1
*** Copyright (c) 1995-2004, Regents of the University of Colorado

*** This version of NuSMV is linked to the MiniSat SAT solver. 
*** See http://minisat.se/MiniSat.html
*** Copyright (c) 2003-2006, Niklas Een, Niklas Sorensson
*** Copyright (c) 2007-2010, Niklas Sorensson

NuSMV > go_bmc 
WARNING *** Processes are still supported, but deprecated.      ***
WARNING *** In the future processes may be no longer supported. ***

WARNING *** The model contains PROCESSes or ISAs. ***
WARNING *** The HRC hierarchy will not be usable. ***
NuSMV > check_ltlspec_bmc_onepb -k 32
^CInterrupt
NuSMV > check_ltlspec_bmc_onepb -k 32 -l X
-- no counterexample found with bound 32 and no loop
NuSMV > check_ltlspec_bmc_onepb -n 1 -k 32 -l X
Error: 1 is not a valid property index, must be in the range [0,0].
NuSMV > check_ltlspec_bmc_onepb -k 32 -l X
-- no counterexample found with bound 32 and no loop
NuSMV > check_ltlspec_bmc_onepb -k 32 -l 0
-- no counterexample found with bound 32 and loop at 0
NuSMV > check_ltlspec_bmc_onepb -k 32 -l N
Error: string "N" is not valid. An integer was expected.
NuSMV > check_ltlspec_bmc_onepb -k 32 -l *
-- no counterexample found with bound 32
NuSMV > check_ltlspec_bmc_onepb -k 33 -l *






## problemas
- redundancia 1 en los servidores (en el R y el RR)
- cuando genero fallas en el cliente, la redunancia me lo pone en el cliente. que deberia pasar aca? si agrego redundancia que me la haga en el servidor por mas que las fallas se inyectan en el cliente?  (script2)
- te olbiga a poner si o si una propiedad en el xml, lo cual no se si esta bien.
