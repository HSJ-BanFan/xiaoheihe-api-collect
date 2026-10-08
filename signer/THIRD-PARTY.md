# Precompiled signer distribution

The bootstrap and com.xiaoheihe sources are MIT licensed. The release JAR
also contains Java classes compiled from unidbg API and Android source and
the Unicorn2Factory and DynarmicFactory sources at public commit
2ded0545d4ae053055f469ef4a4c49e3f15196a7, under Apache License 2.0.
The complete Apache license is included as META-INF/LICENSE-unidbg.txt.
Upstream source is https://github.com/zhkl0228/unidbg/tree/2ded0545d4ae053055f469ef4a4c49e3f15196a7.

The build adds an explicit com.github.unidbg.Module import to
AbstractARMDebugger.java and AndroidElfLoader.java for Java 17 compilation.
The source archive includes the selected sources and the rebuild script.
The iOS module is not compiled or distributed.

The net.fornwall.jelf Java sources in the Android overlay derive from
jelf, copyright (c) 2012 Fredrik Fornwall, under MIT. The included
META-INF/LICENSE-jelf.txt is from the upstream 2020 revision
ea3b25955dfbc7768522e9fab082a3e2ab5c8c04, at
https://github.com/fornwall/jelf/blob/ea3b25955dfbc7768522e9fab082a3e2ab5c8c04/LICENSE.txt.
This records the source project's license; the exact revision from which
unidbg copied its modified files has not been independently established.

The XxHash32 implementation credits Yann Collet's xxHash. Its BSD 2-Clause
license is included as META-INF/xxHash-LICENSE.txt. The upstream project is
https://github.com/Cyan4973/xxHash. The system property code ported from
usercorn retains Ryan Hileman's MIT license, included as
META-INF/usercorn-LICENSE.txt. Its source project is
https://github.com/lunixbochs/usercorn. The source archive retains the
existing source attributions as well as these full license texts.

No unidbg backend hook classes or third-party native files are copied into
the bootstrap JAR. No target APK, extracted target library, account data,
JRE or third-party dependency JAR is a project release asset.

The installer downloads pinned original dependencies from their publishers.
Those artifacts retain their own licenses. The upstream-artifacts.json file
records the precise sources and hashes. They include unidbg backend 0.9.9,
Unicorn 1.0.15, Capstone 3.1.8, Keystone 0.9.7, Demumble 1.0.4, JNA 5.10.0,
native-lib-loader 2.3.5, Apache Commons Codec 1.21.0, Collections 4.5.0,
IO 2.21.0, Fastjson 2.0.65, apk-parser 2.6.10 and SLF4J 2.0.16.
GPL-labelled metadata is not a substitute for source license review.
Unicorn includes GPLv2 code. Keystone has GPLv2 core and MIT Java bindings
with its documented FOSS exception. Demumble's source licensing differs
from its Maven GPL label. JNA offers Apache 2.0 or LGPL 2.1.

The local resource JAR is assembled from exact upstream archive members
on the user's computer. It is not uploaded as a release asset. Runtime
hash checking establishes integrity, not an operating-system sandbox or
a legal conclusion about combinations of third-party components.
