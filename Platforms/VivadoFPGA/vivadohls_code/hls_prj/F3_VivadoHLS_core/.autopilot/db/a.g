#!/bin/sh
lli=${LLVMINTERP-lli}
exec $lli \
    /home/sf306/phd_codebase/FPL2014/FFF/ForwardFinancialFramework/Platforms/VivadoFPGA/vivadohls_code/hls_prj/F3_VivadoHLS_core/.autopilot/db/a.g.bc ${1+"$@"}