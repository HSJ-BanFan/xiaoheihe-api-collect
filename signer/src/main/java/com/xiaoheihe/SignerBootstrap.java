package com.xiaoheihe;

import java.io.InputStream;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.BasicFileAttributes;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/** JDK-only entry point. No third-party class is resolved before verification. */
public final class SignerBootstrap {
    private record Pin(String sha256, long bytes) {}

    public static void main(String[] args) {
        try {
            if (args.length != 0) {
                throw new IllegalArgumentException("arguments are not supported");
            }
            Path self = Path.of(SignerBootstrap.class.getProtectionDomain()
                .getCodeSource().getLocation().toURI()).toAbsolutePath().normalize();
            rejectLinks(self);
            Path directory = self.getParent().resolve("deps");
            rejectLinks(directory);
            Map<String, Pin> pins = readPins("/META-INF/xhh-deps.tsv", false);
            Set<String> actual;
            try (var entries = Files.list(directory)) {
                actual = entries.map(path -> path.getFileName().toString()).collect(Collectors.toSet());
            }
            if (!actual.equals(pins.keySet())) {
                throw new IllegalArgumentException("dependency inventory differs");
            }
            ArrayList<URL> urls = new ArrayList<>();
            urls.add(self.toUri().toURL());
            for (var entry : pins.entrySet()) {
                Path path = directory.resolve(entry.getKey());
                rejectLinks(path);
                if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) {
                    throw new IllegalArgumentException("dependency is not a file");
                }
                try (InputStream stream = Files.newInputStream(path)) {
                    verify(stream, entry.getValue());
                }
                urls.add(path.toUri().toURL());
            }
            // The SDK pins this JAR; its embedded lock transitively pins every sidecar.
            try (URLClassLoader loader = new URLClassLoader(urls.toArray(URL[]::new),
                    ClassLoader.getPlatformClassLoader())) {
                Map<String, Pin> resources = readPins("/META-INF/xhh-resources.tsv", true);
                for (var entry : resources.entrySet()) {
                    URL resolved = loader.getResource(entry.getKey());
                    if (resolved == null || !resolved.toString().startsWith(
                            "jar:" + urls.get(1).toExternalForm() + "!/")) {
                        throw new IllegalArgumentException("resource selected from wrong dependency");
                    }
                    try (InputStream stream = resolved.openStream()) {
                        verify(stream, entry.getValue());
                    }
                }
                System.err.println("verified_runtime_resources=" + resources.size());
                Thread thread = Thread.currentThread();
                ClassLoader previous = thread.getContextClassLoader();
                try {
                    thread.setContextClassLoader(loader);
                    loader.loadClass("com.xiaoheihe.XhhSignerMain")
                        .getMethod("main", String[].class).invoke(null, (Object) args);
                } finally {
                    thread.setContextClassLoader(previous);
                }
            }
        } catch (Throwable error) {
            System.err.println("dependency_verification_failed");
            System.exit(2);
        }
    }

    private static Map<String, Pin> readPins(String resource, boolean paths) throws Exception {
        byte[] raw;
        try (InputStream stream = SignerBootstrap.class.getResourceAsStream(resource)) {
            if (stream == null) throw new IllegalArgumentException("missing lock");
            raw = stream.readNBytes(1024 * 1024 + 1);
        }
        if (raw.length > 1024 * 1024) throw new IllegalArgumentException("oversized lock");
        Map<String, Pin> result = new LinkedHashMap<>();
        for (String line : new String(raw, StandardCharsets.US_ASCII).split("\n")) {
            String[] fields = line.split("\t", -1);
            if (fields.length != 3 || !fields[0].matches(paths
                    ? "[A-Za-z0-9_./-]+" : "[A-Za-z0-9_-][A-Za-z0-9_.-]*\\.jar")
                    || fields[0].contains("..") || fields[0].startsWith("/")
                    || !fields[1].matches("[a-f0-9]{64}")
                    || !fields[2].matches("[1-9][0-9]*")) {
                throw new IllegalArgumentException("invalid lock");
            }
            Pin pin = new Pin(fields[1], Long.parseLong(fields[2]));
            if (result.putIfAbsent(fields[0], pin) != null) {
                throw new IllegalArgumentException("duplicate lock entry");
            }
        }
        if (result.isEmpty()) throw new IllegalArgumentException("empty lock");
        return result;
    }

    private static void verify(InputStream stream, Pin expected) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] block = new byte[65536];
        long size = 0;
        int count;
        while ((count = stream.read(block)) != -1) {
            size += count;
            if (size > expected.bytes()) throw new IllegalArgumentException("oversized dependency");
            digest.update(block, 0, count);
        }
        if (size != expected.bytes() || !HexFormat.of().formatHex(digest.digest()).equals(expected.sha256())) {
            throw new IllegalArgumentException("dependency digest differs");
        }
    }

    private static void rejectLinks(Path path) throws Exception {
        for (Path entry = path; entry != null; entry = entry.getParent()) {
            BasicFileAttributes attributes = Files.readAttributes(entry,
                BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            if (attributes.isSymbolicLink() || attributes.isOther()) {
                throw new IllegalArgumentException("linked dependency path");
            }
            if (System.getProperty("os.name").startsWith("Windows")
                    && (((Number) Files.getAttribute(entry, "dos:attributes",
                        LinkOption.NOFOLLOW_LINKS)).intValue() & 0x400) != 0) {
                throw new IllegalArgumentException("reparse dependency path");
            }
        }
    }
}
