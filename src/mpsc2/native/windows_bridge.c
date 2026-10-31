/* Offline local-lobby bridge for a verified Windows x64 profile.
 * The launcher verifies the complete executable hash before loading this DLL
 * into its own child. Installed executable/data files are never changed.
 * Includes a guarded observation fix for the private 3-player_id upgrade
 * lookup. The public own-upgrade path is preserved, as on macOS.
 * DATA-state/readiness strategy matches local_four_bridge.c; Windows uses a
 * process-local sendto hook instead of Mach-O interposition.
 */
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include <shellapi.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include "minhook/include/MinHook.h"
#include "mpsc2_windows_profile.h"

static unsigned char *base;
static wchar_t directory[32768];
static wchar_t observation_report[32768];
static volatile LONG observation_faults;
static unsigned ports[7], players;
static volatile LONG active, forwarded;
static volatile LONG sends;
typedef int (WSAAPI *sendto_fn)(SOCKET,const char *,int,int,const struct sockaddr *,int);
static sendto_fn original_sendto;
static int loopback_launch(void) {
    int argc,loopback=0,online=0;wchar_t **argv=CommandLineToArgvW(GetCommandLineW(),&argc);
    if(!argv)return 0;
    for(int i=1;i<argc;i++) {
        if(!wcscmp(argv[i],L"-run"))online=1;
        if(!wcscmp(argv[i],L"-listen") && i+1<argc) {
            if(wcscmp(argv[++i],L"127.0.0.1")){LocalFree(argv);return 0;}
            loopback=1;
        }
    }
    LocalFree(argv);return loopback && !online;
}

static void guard_report(const wchar_t *path,const char *error) {
    wchar_t temp[32768];
    if(swprintf(temp,32768,L"%ls.tmp",path)<0)ExitProcess(96);
    FILE *f=_wfopen(temp,L"wb");if(!f)ExitProcess(96);
    if(error)fprintf(f,"{\"applied\":false,\"error\":\"%s\"}\n",error);
    else fprintf(f,"{\"applied\":true,\"pid\":%lu,\"profile_id\":\"%s\",\"strategy\":\"vectored-exception\",\"site\":\"0x%llx\",\"destination\":\"0x%llx\",\"bytes_changed\":0,\"own_upgrade_path_preserved\":true,\"installed_binary_modified\":false,\"observed_invalid_lookup\":%s}\n",GetCurrentProcessId(),MPSC2_PROFILE_ID,MPSC2_UPGRADE_FAULT_RVA,MPSC2_UPGRADE_CLEANUP_RVA,observation_faults?"true":"false");
    fclose(f);
    if(!MoveFileExW(temp,path,MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH))ExitProcess(96);
    if(error)ExitProcess(96);
}
static LONG CALLBACK guard_invalid_opponent_upgrade(EXCEPTION_POINTERS *info) {
    CONTEXT *ctx=info->ContextRecord;
    EXCEPTION_RECORD *record=info->ExceptionRecord;
    unsigned player=(unsigned)(ctx->R14&0xff);
    /* Only recover the verified unsigned 3-player_id READ at this one
     * instruction. Every other access violation keeps normal engine handling.
     * This build maps its code SEC_NO_CHANGE, so no code page is rewritten. */
    if(record->ExceptionCode!=EXCEPTION_ACCESS_VIOLATION || record->NumberParameters<2 ||
       record->ExceptionInformation[0]!=0 || ctx->Rip!=(uintptr_t)base+MPSC2_UPGRADE_FAULT_RVA ||
       player<4 || player>8 || ctx->Rcx!=(uint32_t)(3u-player) ||
       record->ExceptionInformation[1]!=ctx->Rbx+2*ctx->Rcx+0xcc)return EXCEPTION_CONTINUE_SEARCH;
    ctx->Rip=(uintptr_t)base+MPSC2_UPGRADE_CLEANUP_RVA;
    if(InterlockedIncrement(&observation_faults)==1)guard_report(observation_report,NULL);
    return EXCEPTION_CONTINUE_EXECUTION;
}
static void observation_guard(const wchar_t *path) {
    if(!loopback_launch())guard_report(path,"loopback offline launch required");
    const unsigned char expected[]=MPSC2_OPPONENT_UPGRADE_BYTES;
    const unsigned char own[]=MPSC2_OWN_UPGRADE_BYTES;
    const unsigned char destination[]=MPSC2_UPGRADE_CLEANUP_BYTES;
    if(memcmp(base+MPSC2_OPPONENT_UPGRADE_RVA,expected,sizeof(expected)) ||
       memcmp(base+MPSC2_OWN_UPGRADE_RVA,own,sizeof(own)) ||
       memcmp(base+MPSC2_UPGRADE_CLEANUP_RVA,destination,sizeof(destination)))guard_report(path,"unexpected observation instructions");
    wcscpy(observation_report,path);
    if(!AddVectoredExceptionHandler(1,guard_invalid_opponent_upgrade))guard_report(path,"observation exception handler failed");
    guard_report(path,NULL);
}

static int read_mem(uintptr_t address, void *out, size_t size) {
    SIZE_T got=0;
    return ReadProcessMemory(GetCurrentProcess(),(void *)address,out,size,&got) && got==size;
}
static void report(const wchar_t *name,const char *body) {
    wchar_t path[32768],temp[32768];
    if(swprintf(path,32768,L"%ls/%ls",directory,name)<0 ||
       swprintf(temp,32768,L"%ls/%ls.tmp",directory,name)<0)return;
    FILE *f=_wfopen(temp,L"wb");if(!f)return;
    fputs(body,f);fputc('\n',f);fclose(f);
    MoveFileExW(temp,path,MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH);
}
static int exists(const wchar_t *name) {
    wchar_t path[32768];
    if(swprintf(path,32768,L"%ls/%ls",directory,name)<0)return 0;
    return GetFileAttributesW(path)!=INVALID_FILE_ATTRIBUTES;
}
static void fail(const char *reason) {
    char body[256];snprintf(body,sizeof(body),"{\"error\":\"%s\"}",reason);
    report(L"bridge-error.json",body);
}
static int WSAAPI local_sendto(SOCKET fd,const char *buf,int len,int flags,const struct sockaddr *to,int tolen) {
    InterlockedIncrement(&sends);
    int result=original_sendto(fd,buf,len,flags,to,tolen),saved=WSAGetLastError();
    if(InterlockedCompareExchange(&active,0,0) && to && tolen>=(int)sizeof(struct sockaddr_in) && to->sa_family==AF_INET) {
        struct sockaddr_in peer=*(const struct sockaddr_in *)to;
        if(peer.sin_addr.s_addr==htonl(INADDR_LOOPBACK) && ntohs(peer.sin_port)==ports[0]) {
            for(unsigned i=1;i<players-1;i++) {
                peer.sin_port=htons((u_short)ports[i]);
                if(original_sendto(fd,buf,len,flags,(const struct sockaddr *)&peer,sizeof(peer))==len)
                    InterlockedIncrement(&forwarded);
            }
        }
    }
    WSASetLastError(saved);return result;
}
static int hook_sendto(void) {
    void *target=(void *)GetProcAddress(GetModuleHandleW(L"ws2_32.dll"),"sendto");
    return target && MH_Initialize()==MH_OK &&
        MH_CreateHook(target,(void *)local_sendto,(void **)&original_sendto)==MH_OK &&
        MH_EnableHook(MH_ALL_HOOKS)==MH_OK;
}
static DWORD WINAPI bridge(void *unused) {
    (void)unused;
    base=(void *)GetModuleHandleW(NULL);
    wchar_t guard_path[32768];
    if(GetEnvironmentVariableW(L"MPSC2_WINDOWS_GUARD_LOG",guard_path,32768))observation_guard(guard_path);
    if(!GetEnvironmentVariableW(L"MPSC2_BRIDGE_DIR",directory,32768))return 0;
    wchar_t count[16],values[128];
    if(!GetEnvironmentVariableW(L"MPSC2_PLAYER_COUNT",count,16) ||
       !GetEnvironmentVariableW(L"MPSC2_DISCOVERY_PORTS",values,128))return 0;
    wchar_t *end;
    players=(unsigned)wcstoul(count,&end,10);
    if(*end || players<3 || players>8){fail("invalid player count");return 0;}
    const wchar_t *cursor=values;
    for(unsigned i=0;i<players-1;i++) {
        unsigned long port=wcstoul(cursor,&end,10);
        if(end==cursor || port<1024 || port>65535){fail("invalid port");return 0;}
        ports[i]=(unsigned)port;
        for(unsigned j=0;j<i;j++)if(ports[j]==ports[i]){fail("duplicate port");return 0;}
        if(i<players-2){if(*end!=L','){fail("missing port");return 0;}cursor=end+1;}
        else if(*end){fail("extra ports");return 0;}
    }
    if(!loopback_launch()){fail("loopback offline launch required");return 0;}
    const unsigned char expected[]=MPSC2_LOBBY_CHECK_BYTES;
    if(memcmp(base+MPSC2_LOBBY_CHECK_RVA,expected,sizeof(expected))){fail("unexpected lobby instructions");return 0;}
    const unsigned char ready_code[]=MPSC2_READINESS_CHECK_BYTES;
    if(memcmp(base+MPSC2_READINESS_CHECK_RVA,ready_code,sizeof(ready_code))){fail("unexpected readiness instructions");return 0;}
    if(!hook_sendto()){fail("sendto import not found");return 0;}
    char loaded[160];snprintf(loaded,sizeof(loaded),"{\"loaded\":true,\"pid\":%lu,\"profile_id\":\"%s\"}",GetCurrentProcessId(),MPSC2_PROFILE_ID);
    report(L"bridge-loaded.json",loaded);
    for(int tick=0;!exists(L"promote.signal");tick++) {
        if(tick>=12000){fail("promotion timed out");return 0;}Sleep(10);
    }
    volatile uint32_t *state=(void *)(base+MPSC2_LOBBY_STATE_RVA);
    volatile unsigned char *host=base+MPSC2_HOST_FLAG_RVA;
    unsigned agents=*(uint32_t *)(base+MPSC2_API_COUNT_RVA),computers=*(uint32_t *)(base+MPSC2_COMPUTER_COUNT_RVA);
    unsigned char *roster=*(unsigned char **)(base+MPSC2_ROSTER_POINTER_RVA);
    uint64_t count_roster=*(uint64_t *)(base+MPSC2_ROSTER_COUNT_RVA);
    int valid=*state==1 && *host==0 && agents==players && computers==0 && count_roster==players && roster;
    if(valid)for(unsigned i=0;i<players;i++)if(*(uint32_t *)(roster+64*i)!=1)valid=0;
    if(!valid){fail("host preconditions rejected");return 0;}
    *host=1;*state=2;
    report(L"promote.json","{\"promoted\":true,\"state_before\":1,\"state_after\":2}");
    int held=0,stable=0,last_ready=-1;uintptr_t held_begin=0;
    for(int tick=0;tick<12000;tick++) {
        uintptr_t ready=0,begin=0,end_ready=0;unsigned char flags[32];
        read_mem((uintptr_t)base+MPSC2_READINESS_POINTER_RVA,&ready,8);
        if(ready && read_mem(ready+16,&begin,8) && read_mem(ready+24,&end_ready,8) && end_ready-begin==32 && read_mem(begin,flags,32)) {
            if(!held && flags[0]==1 && flags[1]==1 && flags[28]==0 && flags[29]==0 && flags[30]==0 && flags[31]==0) {
                /* Windows counts truthy pairs; macOS sums their byte values.
                 * TWO unused slots keep the Windows count above two even
                 * before the first guest arrives. Setting one byte to 2 does
                 * not work here: it immediately starts a one-player game. */
                InterlockedExchange((volatile LONG *)(begin+28),0x01010101);
                held_begin=begin;held=1;InterlockedExchange(&active,1);
                report(L"held.json","{\"held\":true,\"unused_slots\":[14,15]}");
            }
            if(held && begin!=held_begin){fail("ready vector changed");return 0;}
            int ready_count=0;
            for(int i=0;i<14;i++)if(flags[2*i]==1 && flags[2*i+1]==1)ready_count++;
            if(held && (ready_count!=last_ready || tick%100==0)) {
                char progress[512];int offset=snprintf(progress,sizeof(progress),"{\"native_ready_players\":%d,\"forwarded_datagrams\":%ld,\"sendto_calls\":%ld,\"flags\":[",ready_count,forwarded,sends);
                for(int i=0;i<32;i++)offset+=snprintf(progress+offset,sizeof(progress)-offset,"%s%u",i?",":"",flags[i]);
                snprintf(progress+offset,sizeof(progress)-offset,"]}");report(L"readiness-progress.json",progress);last_ready=ready_count;
            }
            if(held && ready_count==(int)players)stable++;else stable=0;
            if(stable>=3) {
                int keep=0;
                for(int i=0;i<14;i++)if(flags[2*i]==1 && flags[2*i+1]==1)
                    if(keep++>=2)((volatile unsigned char *)begin)[2*i+1]=0;
                ((volatile unsigned char *)begin)[28]=0;((volatile unsigned char *)begin)[29]=0;
                ((volatile unsigned char *)begin)[30]=0;((volatile unsigned char *)begin)[31]=0;
                char json[256];snprintf(json,sizeof(json),"{\"native_ready_players\":%u,\"forwarded_datagrams\":%ld,\"released\":true}",players,forwarded);
                report(L"players-ready.json",json);return 0;
            }
        }
        Sleep(10);
    }
    InterlockedExchange(&active,0);fail("multiplayer readiness timed out");return 0;
}
BOOL WINAPI DllMain(HINSTANCE module,DWORD reason,LPVOID reserved) {
    (void)reserved;
    if(reason==DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(module);
        HANDLE thread=CreateThread(NULL,0,bridge,NULL,0,NULL);
        if(thread)CloseHandle(thread);else return FALSE;
    }
    return TRUE;
}
