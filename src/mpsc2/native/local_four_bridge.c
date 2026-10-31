/* Experimental offline bridge for macOS SC2 Base96883, UUID checked below.
 * Completes rejected 3..8-slot host initialization, distributes UDP discovery
 * to every guest, and waits for every native readiness event before launch.
 * Only this process's DATA is changed; installed files and TEXT are untouched.
 */
#include <arpa/inet.h>
#include <crt_externs.h>
#include <errno.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <mach-o/dyld.h>
#include <mach-o/loader.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static uint8_t *base;
static const char *directory;
static unsigned ports[7];
static unsigned player_count;
static atomic_int fanout_active;
static atomic_uint forwarded;

static int read_mem(uintptr_t address, void *out, size_t size) {
    mach_vm_size_t got=0;
    return mach_vm_read_overwrite(mach_task_self(),address,size,(mach_vm_address_t)out,&got)==KERN_SUCCESS && got==size;
}
static int exists(const char *name) {
    char path[4096];snprintf(path,sizeof(path),"%s/%s",directory,name);
    return access(path,F_OK)==0;
}
static void result(const char *name,const char *json) {
    char path[4096],temp[4096];
    snprintf(path,sizeof(path),"%s/%s",directory,name);
    snprintf(temp,sizeof(temp),"%s/%s.tmp",directory,name);
    FILE *f=fopen(temp,"w");if(!f)return;
    fputs(json,f);fputc('\n',f);fclose(f);rename(temp,path);
}
static ssize_t local_sendto(int fd,const void *buf,size_t len,int flags,const struct sockaddr *to,socklen_t tolen) {
    ssize_t original=sendto(fd,buf,len,flags,to,tolen);int saved=errno;
    if(atomic_load(&fanout_active) && to && tolen>=sizeof(struct sockaddr_in) && to->sa_family==AF_INET) {
        struct sockaddr_in peer=*(const struct sockaddr_in *)to;
        if(peer.sin_addr.s_addr==htonl(INADDR_LOOPBACK) && ntohs(peer.sin_port)==ports[0]) {
            for(unsigned i=1;i<player_count-1;i++) {
                peer.sin_port=htons(ports[i]);
                if(sendto(fd,buf,len,flags,(const struct sockaddr *)&peer,sizeof(peer))==(ssize_t)len)
                    atomic_fetch_add(&forwarded,1);
            }
        }
    }
    errno=saved;return original;
}
__attribute__((used,section("__DATA,__interpose"))) static const struct {
    const void *replacement,*original;
} interpose_sendto={local_sendto,sendto};

static void *bridge(void *unused) {
    (void)unused;
    /* Python signals only after receiving the exact multiple-agent rejection. */
    for(int tick=0;!exists("promote.signal");tick++) {
        if(tick>=12000)return NULL;
        usleep(10000);
    }
    volatile uint32_t *state=(void *)(base+0x50a7cb8);
    volatile uint8_t *host=base+0x8a4e220;
    uint32_t agents=*(uint32_t *)(base+0x8a4e224),computers=*(uint32_t *)(base+0x8a4e228);
    uint8_t *roster=*(uint8_t **)(base+0x8a4e978);
    uint64_t count=*(uint64_t *)(base+0x8a4e980);
    const uint8_t instructions[]={0x83,0xf8,0x02,0x77,0x0a,0xb0,0x01,0x75,0x62,0x48,0x83,0xf9,0x02,0x74,0x5c};
    int valid=*state==1 && *host==0 && agents==player_count && computers==0 && count==player_count && roster &&
              memcmp(base+0x1eb76f3,instructions,sizeof(instructions))==0;
    if(valid)for(unsigned i=0;i<player_count;i++)if(*(uint32_t *)(roster+64*i)!=1)valid=0;
    if(!valid){result("promote.json","{\"promoted\":false}");return NULL;}
    *host=1;*state=2;
    char promoted[256];
    snprintf(promoted,sizeof(promoted),"{\"promoted\":true,\"state_before\":1,\"state_after\":2,\"agents\":%u,\"computers\":0,\"roster_count\":%u}",player_count,player_count);
    result("promote.json",promoted);
    int held=0,stable=0,last_ready=-1;
    uintptr_t held_begin=0;
    for(int tick=0;tick<12000;tick++) {
        uintptr_t ready=0,begin=0,end=0;
        read_mem((uintptr_t)base+0x50a7e08,&ready,8);
        uint8_t flags[32];
        if(ready && read_mem(ready+16,&begin,8) && read_mem(ready+24,&end,8) && end-begin==32 &&
           read_mem(begin,flags,sizeof(flags))) {
            if(!held && flags[0]==1 && flags[1]==1 && flags[30]==0 && flags[31]==0) {
                /* Slot 15 is unused by all supported sessions. The API
                 * start predicate sums ready values and compares exactly to 2.
                 * Adding 2 prevents a premature start before every peer joins.
                 */
                ((volatile uint8_t *)begin)[31]=2;
                ((volatile uint8_t *)begin)[30]=1;
                held_begin=begin;held=1;
                atomic_store(&fanout_active,1);
                result("held.json","{\"held\":true,\"unused_slot\":15}");
            }
            if(held && begin!=held_begin){result("bridge-error.json","{\"error\":\"ready vector changed\"}");return NULL;}
            int ready_count=0;
            for(int i=0;i<15;i++)if(flags[2*i]==1 && flags[2*i+1]==1)ready_count++;
            if(held && (ready_count!=last_ready || tick%100==0)) {
                char progress[512];
                int offset=snprintf(progress,sizeof(progress),"{\"expected_players\":%u,\"native_ready_players\":%d,\"forwarded_datagrams\":%u,\"flags\":[",player_count,ready_count,atomic_load(&forwarded));
                for(int i=0;i<32;i++)offset+=snprintf(progress+offset,sizeof(progress)-(size_t)offset,"%s%u",i?",":"",flags[i]);
                snprintf(progress+offset,sizeof(progress)-(size_t)offset,"]}");
                result("readiness-progress.json",progress);
                last_ready=ready_count;
            }
            if(held && ready_count==(int)player_count)stable++;else stable=0;
            if(stable>=3) {
                char json[256];
                snprintf(json,sizeof(json),"{\"native_ready_players\":%u,\"forwarded_datagrams\":%u,\"released\":true}",player_count,atomic_load(&forwarded));
                /* All peers have completed native readiness. Only the API
                 * autostart counters are reduced; the native multiplayer roster
                 * and its network/simulation readiness remain intact.
                 */
                int keep=0;
                for(int i=0;i<15;i++)if(flags[2*i]==1 && flags[2*i+1]==1)
                    if(keep++>=2)((volatile uint8_t *)begin)[2*i+1]=0;
                /* Keep local forwarding enabled for this host's lifetime;
                 * no further runtime-data changes are needed after launch. */
                ((volatile uint8_t *)begin)[30]=0;
                ((volatile uint8_t *)begin)[31]=0;
                result("players-ready.json",json);
                if(player_count==4)result("four-ready.json",json); /* legacy evidence name */
                return NULL;
            }
        }
        usleep(10000);
    }
    atomic_store(&fanout_active,0);
    result("bridge-error.json","{\"error\":\"multiplayer readiness timed out\"}");
    return NULL;
}
__attribute__((constructor)) static void initialize(void) {
    directory=getenv("MPSC2_BRIDGE_DIR");
    const char *value=getenv("MPSC2_DISCOVERY_PORTS");
    const char *count_value=getenv("MPSC2_PLAYER_COUNT");
    if(!directory || !value)return;
    /* Default to four for older launchers using this source filename. */
    unsigned n=4;char tail;
    if(count_value && sscanf(count_value,"%u%c",&n,&tail)!=1)return;
    if(n<3 || n>8)return;
    unsigned p[7]={0};
    const char *cursor=value;
    for(unsigned i=0;i<n-1;i++) {
        char *end=NULL;
        unsigned long port=strtoul(cursor,&end,10);
        if(end==cursor || port<1024 || port>65535)return;
        p[i]=(unsigned)port;
        for(unsigned j=0;j<i;j++)if(p[i]==p[j])return;
        if(i<n-2){if(*end!=',')return;cursor=end+1;}
        else if(*end!='\0')return;
    }
    int argc=*_NSGetArgc(),loopback=0;char **argv=*_NSGetArgv();
    for(int i=1;i<argc;i++) {
        if(strcmp(argv[i],"-run")==0)return;
        if(strcmp(argv[i],"-listen")==0 && i+1<argc){if(strcmp(argv[i+1],"127.0.0.1")!=0)return;loopback=1;}
    }
    if(!loopback)return;
    const struct mach_header_64 *h=(const void *)_dyld_get_image_header(0);
    if(!h || h->magic!=MH_MAGIC_64 || h->cputype!=CPU_TYPE_X86_64)return;
    const uint8_t uuid[16]={0xda,0x36,0xf2,0x5f,0xc2,0x34,0x30,0xeb,0xbe,0x05,0xe4,0xbc,0x16,0x01,0x7b,0x08};
    const struct load_command *c=(const void *)(h+1);int ok=0;
    for(uint32_t i=0;i<h->ncmds;i++){if(c->cmd==LC_UUID)ok=memcmp(((const struct uuid_command *)c)->uuid,uuid,16)==0;c=(const void *)((const char *)c+c->cmdsize);}
    if(!ok)return;
    base=(uint8_t *)h;player_count=n;memcpy(ports,p,sizeof(ports));
    pthread_t thread;if(pthread_create(&thread,NULL,bridge,NULL)==0)pthread_detach(thread);
}
