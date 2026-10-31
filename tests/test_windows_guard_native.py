"""Exercise the actual native fault predicate without launching SC2."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from mpsc2.windows_session import compiler
from mpsc2.versions import write_windows_header
import mpsc2


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows native ABI test')
def test_guard_resumes_only_the_verified_invalid_read(tmp_path):
    cc = compiler()
    if not cc:
        pytest.skip('set MPSC2_WINDOWS_CC to run the native handler test')
    native = Path(mpsc2.__file__).parent / 'native'
    write_windows_header(tmp_path)
    harness = tmp_path / 'guard_test.c'
    harness.write_text(r'''
#include "windows_bridge.c"
#include <assert.h>

int main(void) {
    base=(unsigned char *)(uintptr_t)0x140000000ULL;
    observation_faults=1; /* no file I/O during synthetic exception delivery */
    for(unsigned player=4;player<=8;player++) {
        CONTEXT good={0};
        good.Rip=(uintptr_t)base+0xb3dbef;
        good.R14=player;good.Rcx=(uint32_t)(3u-player);
        good.Rbx=0x20000000000ULL;good.Rax=player;
        EXCEPTION_RECORD record={0};
        record.ExceptionCode=EXCEPTION_ACCESS_VIOLATION;
        record.NumberParameters=2;
        record.ExceptionInformation[1]=good.Rbx+2*good.Rcx+0xcc;
        for(int variant=0;variant<9;variant++) {
            CONTEXT ctx=good;
            EXCEPTION_RECORD event=record;
            switch(variant) {
                case 1:event.ExceptionCode=EXCEPTION_ILLEGAL_INSTRUCTION;break;
                case 2:event.NumberParameters=1;break;
                case 3:event.ExceptionInformation[0]=1;break; /* write fault */
                case 4:ctx.Rip++;break;
                case 5:ctx.R14=3;break;
                case 6:ctx.R14=9;break;
                case 7:ctx.Rcx--;break;
                case 8:event.ExceptionInformation[1]++;break;
            }
            EXCEPTION_POINTERS info={&event,&ctx};
            DWORD64 original_ip=ctx.Rip;
            LONG result=guard_invalid_opponent_upgrade(&info);
            assert(result==(variant?EXCEPTION_CONTINUE_SEARCH:EXCEPTION_CONTINUE_EXECUTION));
            assert(ctx.Rip==(variant?original_ip:(uintptr_t)base+0xb3dc2c));
            assert(ctx.Rax==good.Rax && ctx.Rbx==good.Rbx);
        }
    }
    return 0;
}
''', encoding='utf-8')
    minhook = native / 'minhook/src'
    executable = tmp_path / 'guard_test.exe'
    env = {**os.environ, 'PATH': str(Path(cc).parent)+os.pathsep+os.environ.get('PATH', '')}
    command = [cc, '-O2', '-I', str(native), '-I', str(tmp_path), str(harness),
               *[str(minhook / name) for name in ('buffer.c', 'hook.c', 'trampoline.c', 'hde/hde64.c')],
               '-lws2_32', '-lshell32', '-o', str(executable)]
    result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    subprocess.run([str(executable)], check=True, timeout=10)
