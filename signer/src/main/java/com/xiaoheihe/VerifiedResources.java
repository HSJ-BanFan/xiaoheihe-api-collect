package com.xiaoheihe;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.LinkedHashSet;
import java.util.Set;

/**
 * Verifies prepared signer resources against the compiled-in compatibility
 * profile before any emulator or native library is created. The local
 * manifest is informative: the pinned constants below are authoritative.
 */
public final class VerifiedResources {
    public static final String PROFILE_ID = "heybox-arm64-001c9a49-v1";
    public static final String SOURCE_APK_SHA256 =
        "001c9a498a41780f6bd42bdaeed2ec3e644ef17afbb6dae0347cafe68c791e3e";
    public static final String APK_NAME = "minimal-app.apk";
    public static final String LIBRARY_NAME = "libglesv3_1.so";
    public static final String MANIFEST_NAME = "manifest.json";

    private static final long APK_BYTES = 690656L;
    private static final String APK_SHA256 =
        "9ce068dfda81de7e40897b97feddc24114d869ad3c6b69e72bb39b0b4201b890";
    private static final long LIBRARY_BYTES = 2064456L;
    private static final String LIBRARY_SHA256 =
        "d95d7c52daa012a84c644c9e1f62ca31444c989c65773d75400c0cf26bc06d9e";
    private static final byte[] ELF_PREFIX = {0x7f, 'E', 'L', 'F', 2, 1};
    private static final int ARM64_MACHINE = 0xb7;

    public final Path directory;
    public final Path apk;
    public final Path library;
    public final Path manifest;

    private VerifiedResources(Path directory) {
        this.directory = directory;
        this.apk = directory.resolve(APK_NAME);
        this.library = directory.resolve(LIBRARY_NAME);
        this.manifest = directory.resolve(MANIFEST_NAME);
    }

    public static VerifiedResources open(Path directory) throws IOException {
        Path normalized = directory.toAbsolutePath().normalize();
        if (!Files.isDirectory(normalized, LinkOption.NOFOLLOW_LINKS)) {
            throw new IllegalArgumentException("resource directory is missing");
        }
        VerifiedResources resources = new VerifiedResources(normalized);
        resources.checkListing();
        resources.checkFile(resources.apk, APK_BYTES, APK_SHA256);
        resources.checkFile(resources.library, LIBRARY_BYTES, LIBRARY_SHA256);
        resources.checkElf();
        resources.checkManifest();
        return resources;
    }

    private void checkListing() throws IOException {
        Set<String> names = new LinkedHashSet<>();
        try (DirectoryStream<Path> entries = Files.newDirectoryStream(directory)) {
            for (Path entry : entries) {
                names.add(entry.getFileName().toString());
            }
        }
        Set<String> expected = new LinkedHashSet<>(Set.of(APK_NAME, LIBRARY_NAME, MANIFEST_NAME));
        if (!names.equals(expected)) {
            throw new IllegalArgumentException("unexpected or missing resource files");
        }
    }

    private void checkFile(Path file, long bytes, String sha256) throws IOException {
        if (!Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS) || Files.isSymbolicLink(file)) {
            throw new IllegalArgumentException("resource is not a regular file");
        }
        if (Files.size(file) != bytes || !sha256(file).equals(sha256)) {
            throw new IllegalArgumentException("resource integrity mismatch");
        }
    }

    private void checkElf() throws IOException {
        byte[] header = new byte[20];
        try (InputStream stream = Files.newInputStream(library)) {
            if (stream.readNBytes(header, 0, header.length) != header.length) {
                throw new IllegalArgumentException("resource library is truncated");
            }
        }
        for (int index = 0; index < ELF_PREFIX.length; index++) {
            if (header[index] != ELF_PREFIX[index]) {
                throw new IllegalArgumentException("resource library is not little-endian ELF64");
            }
        }
        int machine = (header[18] & 0xff) | ((header[19] & 0xff) << 8);
        if (machine != ARM64_MACHINE) {
            throw new IllegalArgumentException("resource library is not ARM64");
        }
    }

    private void checkManifest() throws IOException {
        if (Files.size(manifest) > 8192) {
            throw new IllegalArgumentException("local manifest is unexpectedly large");
        }
        String text = Files.readString(manifest, StandardCharsets.UTF_8);
        require(text.contains("\"profile_id\": \"" + PROFILE_ID + "\""), "profile id");
        require(text.contains("\"schema_version\": 1"), "schema version");
        require(text.contains("\"source_apk_sha256\": \"" + SOURCE_APK_SHA256 + "\""), "source hash");
        require(text.contains("\"" + APK_SHA256 + "\""), "minimal apk record");
        require(text.contains("\"" + LIBRARY_SHA256 + "\""), "library record");
        require(text.contains("\"bytes\": " + APK_BYTES), "minimal apk size record");
        require(text.contains("\"bytes\": " + LIBRARY_BYTES), "library size record");
    }

    private static void require(boolean condition, String what) {
        if (!condition) {
            throw new IllegalArgumentException("local manifest does not record the " + what);
        }
    }

    private static String sha256(Path file) throws IOException {
        MessageDigest digest;
        try {
            digest = MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException("SHA-256 is unavailable", error);
        }
        try (InputStream stream = Files.newInputStream(file)) {
            byte[] block = new byte[1 << 20];
            int read;
            while ((read = stream.read(block)) != -1) {
                digest.update(block, 0, read);
            }
        }
        return HexFormat.of().formatHex(digest.digest());
    }
}
