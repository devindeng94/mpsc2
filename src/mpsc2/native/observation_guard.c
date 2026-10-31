/* Base96883 observation fix for independent multiplayer clients.
 * The engine's private opponent-upgrade field indexes upgrades[3-player_id].
 * For player IDs >=4 this underflows. Skip that 1v1-only field, preserving the
 * public PlayerRaw.upgrade_ids path and every simulation/action routine.
 * Seven bytes change on one process-private code page; installed files do not.
 */
#include <crt_externs.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <mach-o/dyld.h>
#include <mach-o/loader.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static const char *report_path;

static void report(const char *body) {
    char temporary[4096];
    if(snprintf(temporary,sizeof(temporary),"%s.tmp",report_path)>=(int)sizeof(temporary))return;
    FILE *file=fopen(temporary,"w");
    if(!file)return;
    fputs(body,file);fputc('\n',file);fclose(file);
    rename(temporary,report_path);
}

static void fail(const char *reason) {
    char body[256];
    snprintf(body,sizeof(body),"{\"applied\":false,\"error\":\"%s\"}",reason);
    report(body);
    _exit(96); /* Only the process explicitly launched with this guard. */
}

static void *install_guard(void *unused) {
    (void)unused;
    int argc=*_NSGetArgc(),loopback=0;char **argv=*_NSGetArgv();
    for(int i=1;i<argc;i++) {
        if(strcmp(argv[i],"-run")==0)fail("online launch refused");
        if(strcmp(argv[i],"-listen")==0 && i+1<argc) {
            if(strcmp(argv[i+1],"127.0.0.1")!=0)fail("non-loopback launch refused");
            loopback=1;
        }
    }
    if(!loopback)fail("missing loopback listener");
    const struct mach_header_64 *header=(const void *)_dyld_get_image_header(0);
    if(!header || header->magic!=MH_MAGIC_64 || header->cputype!=CPU_TYPE_X86_64)
        fail("unexpected executable architecture");
    const uint8_t uuid[16]={0xda,0x36,0xf2,0x5f,0xc2,0x34,0x30,0xeb,0xbe,0x05,0xe4,0xbc,0x16,0x01,0x7b,0x08};
    const struct load_command *command=(const void *)(header+1);int matched_uuid=0;
    for(uint32_t i=0;i<header->ncmds;i++) {
        if(command->cmd==LC_UUID)
            matched_uuid=memcmp(((const struct uuid_command *)command)->uuid,uuid,sizeof(uuid))==0;
        command=(const void *)((const char *)command+command->cmdsize);
    }
    if(!matched_uuid)fail("unexpected executable UUID");
    uint8_t *base=(uint8_t *)header,*site=base+0x1e9bf0c;
    const uint8_t expected[]={0x48,0x81,0xc3,0xcc,0,0,0,0x48,0x8b,0x85,0x50,0xdb,0xfd,0xff,0x0f,0xb7,0x04,0x43};
    const uint8_t calculation[]={0xb8,3,0,0,0,0x2b,0x85,0xa8,0xdb,0xfd,0xff};
    const uint8_t destination[]={0x48,0x8d,0xbd,0x20,0xdd,0xfd,0xff,0xe8,0xc4,0x69,0,0};
    /* SC2 unpacks its code after dylib constructors run. Python waits for the
     * terminal report before connecting, so no observation can race this write. */
    int unpacked=0;
    for(int tick=0;tick<6000;tick++) {
        if(!memcmp(site,expected,sizeof(expected))) {unpacked=1;break;}
        usleep(10000);
    }
    if(!unpacked || memcmp(base+0x1e9bd31,calculation,sizeof(calculation)) ||
       memcmp(base+0x1e9bfe0,destination,sizeof(destination)))
        fail("unexpected observation instructions");

    vm_size_t page_size=getpagesize();
    mach_vm_address_t page=(uintptr_t)site&~((uintptr_t)page_size-1),region=page;
    mach_vm_size_t region_size=0;mach_port_t object=MACH_PORT_NULL;
    vm_region_basic_info_data_64_t info;
    mach_msg_type_number_t count=VM_REGION_BASIC_INFO_COUNT_64;
    kern_return_t queried=mach_vm_region(mach_task_self(),&region,&region_size,
        VM_REGION_BASIC_INFO_64,(vm_region_info_t)&info,&count,&object);
    if(object!=MACH_PORT_NULL)mach_port_deallocate(mach_task_self(),object);
    if(queried!=KERN_SUCCESS || region>page || region+region_size<page+page_size ||
       info.protection!=(VM_PROT_READ|VM_PROT_EXECUTE))
        fail("unexpected code page protection");
    if(mach_vm_protect(mach_task_self(),page,page_size,0,
                      VM_PROT_READ|VM_PROT_WRITE|VM_PROT_COPY)!=KERN_SUCCESS)
        fail("private code page copy failed");
    /* JMP 0x1e9bfe0; NOP; NOP. The ordinary own-upgrade path precedes this. */
    const uint8_t branch[]={0xe9,0xcf,0,0,0,0x90,0x90};
    memcpy(site,branch,sizeof(branch));
    __builtin___clear_cache((char *)site,(char *)site+sizeof(branch));
    if(mach_vm_protect(mach_task_self(),page,page_size,0,info.protection)!=KERN_SUCCESS)
        fail("code page protection restoration failed");
    if(memcmp(site,branch,sizeof(branch)))fail("observation guard verification failed");
    char body[512];
    snprintf(body,sizeof(body),"{\"applied\":true,\"pid\":%d,\"site\":\"0x1e9bf0c\","
        "\"destination\":\"0x1e9bfe0\",\"bytes_changed\":7,\"own_upgrade_path_preserved\":true,"
        "\"installed_binary_modified\":false}",getpid());
    report(body);
    return NULL;
}

__attribute__((constructor)) static void initialize_guard(void) {
    report_path=getenv("MPSC2_OBSERVATION_GUARD_LOG");
    if(!report_path)return;
    pthread_t thread;
    if(pthread_create(&thread,NULL,install_guard,NULL)!=0)fail("guard thread creation failed");
    pthread_detach(thread);
}
