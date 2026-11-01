/* Offline Linux SC2 Base75689 only. Private startup code changes; no installed
 * files are modified. The host uses the normal CreateGame initialization and
 * waits for N genuine readiness events. All clients retain public upgrades. */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dlfcn.h>
#include <elf.h>
#include <errno.h>
#include <link.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <unistd.h>

static const char *report_path;
static unsigned ports[7], player_count;
static ssize_t (*real_sendto)(int,const void *,size_t,int,const struct sockaddr *,socklen_t);

static void report(int applied, const char *error) {
    char temporary[4096];
    if (!report_path || snprintf(temporary,sizeof(temporary),"%s.tmp",report_path)>=(int)sizeof(temporary)) return;
    FILE *f=fopen(temporary,"w");
    if (!f) return;
    fprintf(f,"{\"applied\":%s,\"pid\":%d,\"profile_id\":\"linux-x86_64-75689-v1\","
        "\"host_player_count\":%u,\"own_upgrade_path_preserved\":true,"
        "\"installed_binary_modified\":false,\"error\":\"%s\"}\n",
        applied?"true":"false",getpid(),player_count,error);
    if (fclose(f) || rename(temporary,report_path)) _exit(96);
}
static void fail(const char *reason) { report(0,reason); _exit(96); }

static int identity(struct dl_phdr_info *info,size_t size,void *result) {
    (void)size;
    if (info->dlpi_name && *info->dlpi_name) return 0;
    if (info->dlpi_addr!=0) return 1; /* This verified executable is ET_EXEC. */
    const unsigned char expected[]={0x11,0xfd,0x8f,0xb4,0x71,0xf9,0xae,0x89,0x51,0x1c,
        0xbc,0x3e,0xd2,0x21,0x0f,0xce,0x69,0x98,0xf0,0x26};
    for (unsigned i=0;i<info->dlpi_phnum;i++) {
        const ElfW(Phdr) *p=&info->dlpi_phdr[i];
        if (p->p_type!=PT_NOTE) continue;
        const unsigned char *cursor=(void *)p->p_vaddr,*end=cursor+p->p_memsz;
        while ((size_t)(end-cursor)>=sizeof(ElfW(Nhdr))) {
            const ElfW(Nhdr) *n=(void *)cursor;
            size_t names=((size_t)n->n_namesz+3)&~(size_t)3;
            size_t descs=((size_t)n->n_descsz+3)&~(size_t)3;
            cursor+=sizeof(*n);
            if (names>(size_t)(end-cursor) || descs>(size_t)(end-cursor)-names) break;
            if (n->n_type==NT_GNU_BUILD_ID && n->n_namesz==4 && !memcmp(cursor,"GNU",4) &&
                n->n_descsz==sizeof(expected) && !memcmp(cursor+names,expected,sizeof(expected)))
                *(int *)result=1;
            cursor+=names+descs;
        }
    }
    return 1;
}

static void check(uintptr_t address,const unsigned char *expected,size_t size) {
    /* Refuse changed instructions or unexpected writable/shared executable pages. */
    FILE *f=fopen("/proc/self/maps","r");
    char line[8192],mode[5]; unsigned long start,end; int found=0;
    if (!f) fail("cannot inspect code mapping");
    while (fgets(line,sizeof(line),f)) {
        if (sscanf(line,"%lx-%lx %4s",&start,&end,mode)==3 && address>=start && address+size<=end) {
            found=!strcmp(mode,"r-xp"); break;
        }
    }
    fclose(f);
    if (!found || memcmp((void *)address,expected,size)) fail("unexpected instruction signature or code mapping");
}
static void patch(uintptr_t address,const unsigned char *bytes,size_t size) {
    long page_size=sysconf(_SC_PAGESIZE);
    if (page_size<=0) fail("invalid page size");
    uintptr_t page=address&~((uintptr_t)page_size-1);
    size_t length=((address+size-page+(size_t)page_size-1)/(size_t)page_size)*(size_t)page_size;
    if (mprotect((void *)page,length,PROT_READ|PROT_WRITE)) fail("private code copy failed");
    memcpy((void *)address,bytes,size);
    __builtin___clear_cache((char *)address,(char *)(address+size));
    if (mprotect((void *)page,length,PROT_READ|PROT_EXEC)) fail("code protection restoration failed");
}

ssize_t sendto(int fd,const void *buf,size_t len,int flags,const struct sockaddr *to,socklen_t tolen) {
    if (!real_sendto) real_sendto=dlsym(RTLD_NEXT,"sendto");
    if (!real_sendto) { errno=ENOSYS; return -1; }
    ssize_t result=real_sendto(fd,buf,len,flags,to,tolen); int saved=errno;
    if (player_count && to && tolen>=sizeof(struct sockaddr_in) && to->sa_family==AF_INET) {
        struct sockaddr_in peer=*(const struct sockaddr_in *)to;
        if (peer.sin_addr.s_addr==htonl(INADDR_LOOPBACK) && ntohs(peer.sin_port)==ports[0]) {
            for (unsigned i=1;i<player_count-1;i++) {
                peer.sin_port=htons(ports[i]);
                real_sendto(fd,buf,len,flags,(const struct sockaddr *)&peer,sizeof(peer));
            }
        }
    }
    errno=saved; return result;
}

__attribute__((constructor)) static void initialize(void) {
    report_path=getenv("MPSC2_LINUX_GUARD_LOG");
    if (!report_path) return;
    char args[16384]; FILE *f=fopen("/proc/self/cmdline","rb");
    if (!f) fail("cannot inspect launch arguments");
    size_t size=fread(args,1,sizeof(args),f); fclose(f);
    if (!size || size==sizeof(args) || args[size-1]) fail("invalid launch arguments");
    int loopback=0;
    for (size_t i=0;i<size;) {
        const char *arg=args+i; i+=strlen(arg)+1;
        if (!strcmp(arg,"-run")) fail("online launch refused");
        if (!strcmp(arg,"-listen")) {
            if (i>=size || strcmp(args+i,"127.0.0.1")) fail("non-loopback launch refused");
            loopback=1;
        }
    }
    if (!loopback) fail("missing loopback listener");
    int matched=0; dl_iterate_phdr(identity,&matched);
    if (!matched) fail("unexpected executable build ID");
    const unsigned char own[]={0x41,0x0f,0xb7,0x84,0x44,0xcc,0,0,0};
    const unsigned char opponent[]={0x48,0x8b,0x44,0x24,0x28,0x41,0x0f,0xb7,0x04,0x44,0x3d,0x98,0xb5,0,0};
    const unsigned char calculation[]={0xb8,3,0,0,0,0x48,0x8b,0x4c,0x24,0x40,0x29,0xc8};
    const unsigned char cleanup[]={0x48,0x89,0xdf,0xe8,0xa8,0x21,0xd4,0xff};
    check(0x10430f7,own,sizeof(own)); check(0x10431bc,opponent,sizeof(opponent));
    check(0x1042ff7,calculation,sizeof(calculation)); check(0x1043270,cleanup,sizeof(cleanup));
    const char *count=getenv("MPSC2_PLAYER_COUNT"),*cursor=getenv("MPSC2_DISCOVERY_PORTS");
    if (count || cursor) {
        char tail; unsigned n;
        if (!count || !cursor || sscanf(count,"%u%c",&n,&tail)!=1 || n<3 || n>8)
            fail("invalid host player count");
        for (unsigned i=0;i<n-1;i++) {
            char *end; unsigned long port=strtoul(cursor,&end,10);
            if (end==cursor || port<1024 || port>65535) fail("invalid discovery port");
            ports[i]=(unsigned)port;
            for (unsigned j=0;j<i;j++) if (ports[j]==ports[i]) fail("duplicate discovery port");
            if (i<n-2) { if (*end!=',') fail("missing discovery port"); cursor=end+1; }
            else if (*end) fail("extra discovery port");
        }
        const unsigned char lobby[]={0x83,0xf8,2,0x77,0x12,0xb0,1,0x0f,0x85,0xcb,0,0,0,0x48,0x83,0xf9,2,0x0f,0x84,0xc1,0,0,0};
        const unsigned char ready[]={0x83,0xf8,2,0x75,0x55};
        check(0x105b605,lobby,sizeof(lobby)); check(0x13a2eb0,ready,sizeof(ready));
        unsigned char value=(unsigned char)n;
        patch(0x105b607,&value,1); patch(0x105b615,&value,1); patch(0x13a2eb2,&value,1);
        player_count=n;
    }
    /* Skip only the private opponent-upgrade field; the public own-upgrade
     * append above this branch still executes. JMP 0x1043270. */
    const unsigned char branch[]={0xe9,0xaf,0,0,0};
    patch(0x10431bc,branch,sizeof(branch));
    real_sendto=dlsym(RTLD_NEXT,"sendto");
    if (!real_sendto) fail("sendto unavailable");
    report(1,"");
}
