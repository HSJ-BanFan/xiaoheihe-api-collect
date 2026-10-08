package com.xiaoheihe;

import com.github.unidbg.AndroidEmulator;
import com.github.unidbg.Emulator;
import com.github.unidbg.Module;
import com.github.unidbg.arm.backend.Backend;
import com.github.unidbg.arm.backend.BackendFactory;
import com.github.unidbg.arm.backend.CodeHook;
import com.github.unidbg.arm.backend.DynarmicFactory;
import com.github.unidbg.arm.backend.UnHook;
import com.github.unidbg.arm.backend.Unicorn2Factory;
import com.github.unidbg.file.FileResult;
import com.github.unidbg.file.IOResolver;
import com.github.unidbg.linux.android.AndroidEmulatorBuilder;
import com.github.unidbg.linux.android.AndroidResolver;
import com.github.unidbg.linux.android.dvm.AbstractJni;
import com.github.unidbg.linux.android.dvm.BaseVM;
import com.github.unidbg.linux.android.dvm.DalvikModule;
import com.github.unidbg.linux.android.dvm.DvmClass;
import com.github.unidbg.linux.android.dvm.DvmObject;
import com.github.unidbg.linux.android.dvm.StringObject;
import com.github.unidbg.linux.android.dvm.VM;
import com.github.unidbg.linux.android.dvm.VaList;
import com.github.unidbg.linux.android.dvm.VarArg;
import com.github.unidbg.linux.file.ByteArrayFileIO;
import com.github.unidbg.memory.Memory;
import unicorn.Arm64Const;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

/**
 * Public signer loader for the xiaoheihe API documentation project.
 *
 * Reads one strict request from stdin, verifies the prepared resources against
 * the compiled-in compatibility profile, then runs the target native library
 * under Unidbg to produce the request signature quadruple. Stdout carries
 * exactly one JSON line; diagnostics go to stderr.
 *
 * There is no HTTP server, no MCP endpoint, no environment fallback and no
 * built-in identity. The request supplies every value the signing path uses.
 */
public final class XhhSignerMain extends AbstractJni implements IOResolver {
    private static final String PACKAGE_NAME = "com.max.xiaoheihe";
    private static final String CHUNK_SEED = "HPPDCEAENEHBFHPASRDCAMNHJLAAPF";
    private static final String SHADER_CLASS = "com/graphice/shaderar/ShaderManager";
    private static final boolean TRACE = Boolean.getBoolean("xhh.trace");

    private final SignRequest request;
    private final AndroidEmulator emulator;
    private final VM vm;
    private final DvmClass shaderManager;
    private final DvmObject<?> contextObj;

    public static void main(String[] args) {
        if (args.length != 0) {
            System.err.println("signer loader takes no arguments; send one request on stdin");
            System.exit(2);
        }
        XhhSignerMain signer = null;
        try {
            SignRequest request = SignRequest.read(System.in);
            VerifiedResources resources = VerifiedResources.open(request.directory);
            signer = new XhhSignerMain(resources, request);
            System.out.println(signer.sign());
        } catch (IllegalArgumentException error) {
            System.err.println("invalid signer request: " + error.getMessage());
            System.exit(2);
        } catch (Throwable error) {
            System.err.println("signer failed: " + error);
            System.exit(1);
        } finally {
            if (signer != null) {
                signer.close();
            }
        }
    }

    private XhhSignerMain(VerifiedResources resources, SignRequest request) throws Exception {
        this.request = request;
        this.emulator = AndroidEmulatorBuilder.for64Bit()
                .setProcessName(PACKAGE_NAME)
                .addBackendFactory(backendFactory())
                .build();
        System.err.println("backend=" + emulator.getBackend().getClass().getSimpleName());
        emulator.getSyscallHandler().addIOResolver(this);

        Memory memory = emulator.getMemory();
        memory.setLibraryResolver(new AndroidResolver(23));

        this.vm = emulator.createDalvikVM(resources.apk.toFile());
        vm.setVerbose(false);
        vm.setJni(this);

        DalvikModule dalvikModule = vm.loadLibrary(resources.library.toFile(), false);
        Module module = dalvikModule.getModule();
        dalvikModule.callJNI_OnLoad(emulator);

        this.shaderManager = vm.resolveClass(SHADER_CLASS);
        this.contextObj = vm.resolveClass("android/content/ContextWrapper",
                vm.resolveClass("android/content/Context")).newObject(null);

        // Fixed in-library jump table for the pinned compatibility profile.
        final long base = module.base;
        emulator.getBackend().hook_add_new(new CodeHook() {
            @Override
            public void hook(Backend backend, long address, int size, Object user) {
                long relative = address - base;
                trace("hook at 0x" + Long.toHexString(relative));
                if (relative == 0x1C5A28L || relative == 0x1C5AD4L) {
                    backend.reg_write(Arm64Const.UC_ARM64_REG_PC, base + 0x1C5AE4L);
                } else if (relative == 0x1C5C00L) {
                    backend.reg_write(Arm64Const.UC_ARM64_REG_PC, base + 0x1C5C18L);
                }
            }

            @Override
            public void onAttach(UnHook unHook) {
            }

            @Override
            public void detach() {
            }
        }, base + 0x1C5000L, base + 0x1C6000L, null);

        shaderManager.callStaticJniMethod(emulator, "setParseDepth(Ljava/lang/String;Z)V",
                new StringObject(vm, "init"), true);
    }

    private String sign() {
        String timestamp = String.valueOf(request.timestamp);
        String path = request.path;

        trace("getChunkFlag");
        String chunkFlag = stringOf(shaderManager.callStaticJniMethodObject(emulator,
                "getChunkFlag(Landroid/content/Context;Ljava/lang/String;)Ljava/lang/String;",
                contextObj, new StringObject(vm, CHUNK_SEED)));

        trace("getIdxOffset");
        String index = stringOf(shaderManager.callStaticJniMethodObject(emulator,
                "getIdxOffset(Landroid/content/Context;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;",
                contextObj, new StringObject(vm, chunkFlag), new StringObject(vm, timestamp),
                new StringObject(vm, request.imei)));

        trace("setViewport/setGramLen/setBuf/setDepRel/setDLen/setPtrOffset");
        call("setViewport(Ljava/lang/String;Ljava/lang/String;)V", timestamp, index);
        call("setGramLen(Ljava/lang/String;Ljava/lang/String;)V", path, index);
        call("setBuf(Ljava/lang/String;Ljava/lang/String;)V", timestamp, index);
        call("setDepRel(Ljava/lang/String;Ljava/lang/String;)V", request.deviceInfo, index);
        call("setDLen(Ljava/lang/String;Ljava/lang/String;)V", request.osVersion, index);
        call("setPtrOffset(Ljava/lang/String;Ljava/lang/String;)V", request.appVersion, index);

        trace("getObjType(hkey)");
        String hkey = stringOf(shaderManager.callStaticJniMethodObject(emulator,
                "getObjType(Landroid/content/Context;Ljava/lang/String;Z)Ljava/lang/String;",
                contextObj, new StringObject(vm, index), false));
        trace("getObjType(random)");
        String random = stringOf(shaderManager.callStaticJniMethodObject(emulator,
                "getObjType(Landroid/content/Context;Ljava/lang/String;Z)Ljava/lang/String;",
                contextObj, new StringObject(vm, index), true));

        return json(path, timestamp, index, hkey, request.osVersion + ":" + random);
    }

    private static void trace(String message) {
        if (TRACE) {
            System.err.println("[trace] " + message);
        }
    }

    private void call(String signature, String first, String second) {
        shaderManager.callStaticJniMethod(emulator, signature,
                new StringObject(vm, first), new StringObject(vm, second));
    }

    /**
     * The legacy unicorn backend that unidbg-android pulls in faults inside the
     * pinned target library. `unicorn2` is the default; `dynarmic` exists so a
     * failing run can be compared without rebuilding.
     */
    private static BackendFactory backendFactory() {
        String requested = System.getProperty("xhh.backend", "unicorn2");
        switch (requested) {
            case "unicorn2":
                return new Unicorn2Factory(true);
            case "dynarmic":
                return new DynarmicFactory(true);
            default:
                throw new IllegalArgumentException("unsupported backend selection: " + requested);
        }
    }

    private static String stringOf(DvmObject<?> value) {
        Object content = value == null ? null : value.getValue();
        if (!(content instanceof String) || ((String) content).isEmpty()) {
            throw new IllegalStateException("native signing call returned no value");
        }
        return (String) content;
    }

    private void close() {
        try {
            emulator.close();
        } catch (Throwable error) {
            System.err.println("signer cleanup failed: " + error);
        }
    }

    private static String json(String path, String time, String nonce, String hkey, String random) {
        return "{\"path\":\"" + escape(path) + "\",\"_time\":\"" + escape(time)
                + "\",\"nonce\":\"" + escape(nonce) + "\",\"hkey\":\"" + escape(hkey)
                + "\",\"_rnd\":\"" + escape(random) + "\"}";
    }

    private static String escape(String value) {
        StringBuilder escaped = new StringBuilder(value.length() + 8);
        for (int index = 0; index < value.length(); index++) {
            char current = value.charAt(index);
            switch (current) {
                case '"':
                    escaped.append("\\\"");
                    break;
                case '\\':
                    escaped.append("\\\\");
                    break;
                default:
                    if (current < 0x20) {
                        escaped.append(String.format("\\u%04x", (int) current));
                    } else {
                        escaped.append(current);
                    }
            }
        }
        return escaped.toString();
    }

    @Override
    public FileResult resolve(Emulator emulator, String pathname, int oflags) {
        if ("/proc/self/cmdline".equals(pathname)) {
            return FileResult.success(new ByteArrayFileIO(oflags, pathname,
                    (PACKAGE_NAME + "\0").getBytes(StandardCharsets.UTF_8)));
        }
        if ("/proc/self/status".equals(pathname)) {
            return FileResult.success(new ByteArrayFileIO(oflags, pathname,
                    "TracerPid:\t0\nState:\tS (sleeping)\n".getBytes(StandardCharsets.UTF_8)));
        }
        return null;
    }

    @Override
    public int getStaticIntField(BaseVM vm, DvmClass dvmClass, String signature) {
        if (signature != null && signature.contains("MODE_PRIVATE")) {
            return 0;
        }
        return super.getStaticIntField(vm, dvmClass, signature);
    }

    @Override
    public DvmObject<?> callObjectMethod(BaseVM vm, DvmObject<?> object, String signature, VarArg args) {
        DvmObject<?> handled = emulateAndroidCall(vm, signature);
        return handled != null ? handled : super.callObjectMethod(vm, object, signature, args);
    }

    @Override
    public DvmObject<?> callObjectMethodV(BaseVM vm, DvmObject<?> object, String signature, VaList vaList) {
        DvmObject<?> handled = emulateAndroidCall(vm, signature);
        return handled != null ? handled : super.callObjectMethodV(vm, object, signature, vaList);
    }

    private DvmObject<?> emulateAndroidCall(BaseVM vm, String signature) {
        if (signature == null) {
            return null;
        }
        if (signature.contains("getPackageName()")) {
            return new StringObject(vm, PACKAGE_NAME);
        }
        if (signature.contains("getFilesDir()")) {
            return vm.resolveClass("java/io/File").newObject(
                    new File("/data/user/0/" + PACKAGE_NAME + "/files"));
        }
        if (signature.contains("getPackageManager()")) {
            return vm.resolveClass("android/content/pm/PackageManager").newObject(null);
        }
        if (signature.contains("getSharedPreferences(")) {
            return vm.resolveClass("android/content/SharedPreferences").newObject(null);
        }
        if (signature.contains("getString(")) {
            return new StringObject(vm, request.imei + request.identity);
        }
        return null;
    }
}
