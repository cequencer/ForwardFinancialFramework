//Reference http://www.jimbrooks.org/web/c++/system_specific.php

#include "memory_used.h"
#define OS_UNIX 1
#define __GLIBC__ 1
//#define OS_APPLE 1

#if OS_APPLE
#   include <mach/mach_init.h>
#   include <mach/task.h>
#elif OS_UNIX
#   include <sstream>
#   include <sys/time.h>
#   include <time.h>
#   if __GLIBC__  // GNU Linux
#       include <malloc.h>
#   elif OS_FREEBSD
#       include <sys/file.h>
#       include <sys/sysctl.h>
#       include <sys/user.h>
#       include <kvm.h>
#   endif
#endif
/*****************************************************************************
 * Return total amount of bytes allocated.
 *****************************************************************************/
unsigned long
MemoryUsed( void )
{
#if __GLIBC__  // GNU Linux

    // Per delorie.com:
    // Example:
    // struct mallinfo info = mallinfo();
    // printf("Memory in use: %d bytes\n", info.usmblks + info.uordblks);
    // printf("Total heap size: %d bytes\n", info.arena);
    struct mallinfo meminfo;
    meminfo = mallinfo();
  //return meminfo.arena;
    return meminfo.usmblks + meminfo.uordblks;

#elif OS_APPLE
    // Use Mach functions.
    task_basic_info machInfo  = { 0 };
    mach_port_t machTask  = mach_task_self();
    mach_msg_type_number_t machCount = TASK_BASIC_INFO_COUNT;
    if ( task_info( machTask, TASK_BASIC_INFO, reinterpret_cast<task_info_t>(&machInfo), &machCount ) == KERN_SUCCESS )
        return machInfo.resident_size;
    else
        
        return 0;  // error

#elif OS_FREEBSD

    // getrusage() doesn't work right on FreeBSD and anyway it has
    // a horrible convoluted interface for measuring memory.
    // kvm is reliable but does require linking with the kvm library.
    PERSISTENT kvm_t* kd = kvm_open( NULL, "/dev/null", NULL, O_RDONLY, "kvm_open" );  // open once
    if ( kd != NULL )
    {
        // Use FreeBSD kvm function to get the size of resident pages (RSS).
        int procCount = 0;
        struct kinfo_proc* kp = kvm_getprocs( kd, KERN_PROC_PID, getpid(), &procCount );  // do not free returned struct
        if ( (kp != NULL) and (procCount >= 1) )    // in case multiple threads have the same PID
            return kp->ki_rssize * getpagesize();   // success
    }
    return 0;  // failed

#else
    return 0;  // unsupported

#endif
}
