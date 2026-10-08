package com.xiaoheihe;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;

/**
 * Pure boundary tests for the loader core. This is not a JUnit test: it runs
 * with a plain JDK through scripts/verify_contract.py, needs no Maven
 * dependency, and never loads Unidbg, the target library or the network.
 */
public final class ContractTest {
    private static void require(boolean value, String message) {
        if (!value) {
            throw new AssertionError(message);
        }
    }

    private static SignRequest parse(String text) throws Exception {
        return SignRequest.read(new ByteArrayInputStream(text.getBytes(StandardCharsets.US_ASCII)));
    }

    private static void rejected(String text) throws Exception {
        try {
            parse(text);
            throw new AssertionError("invalid request was accepted");
        } catch (IllegalArgumentException expected) {
            require(!String.valueOf(expected.getMessage()).contains("synthetic-private"),
                "value leaked in error message");
        }
    }

    private static String request(String root, String path) {
        return "protocol=1\n"
            + "resource_dir=" + root + "\n"
            + "path=" + path + "\n"
            + "timestamp=1700000000\n"
            + "identity=123\n"
            + "imei=synthetic-device\n"
            + "device_info=synthetic-model\n"
            + "os_version=14\n"
            + "app_version=1.3.385\n";
    }

    private static void copy(Path source, Path target) throws Exception {
        Files.copy(source, target, StandardCopyOption.REPLACE_EXISTING);
    }

    public static void main(String[] args) throws Exception {
        Path scratch = Path.of(args[0]).toAbsolutePath().normalize();
        Files.createDirectories(scratch);
        String root = scratch.toString();

        SignRequest request = parse(request(root, "/account/info"));
        require(request.path.equals("/account/info/"), "path was not normalized");
        require(request.identity.equals("123"), "identity differs");
        require(request.deviceInfo.equals("synthetic-model"), "device info lost");
        require(request.osVersion.equals("14") && request.appVersion.equals("1.3.385"),
            "version fields lost");
        require(request.directory.isAbsolute(), "resource directory is relative");

        rejected(request(root, "/account/info").replace("identity=123\n", ""));
        rejected(request(root, "/account/info").replace("identity=123", "identity=synthetic-private"));
        rejected(request(root, "/account/info").replace("resource_dir=" + root, "resource_dir=relative"));
        rejected(request(root, "/account/info").replace("protocol=1", "protocol=2"));
        rejected(request(root, "/account/info").replace("timestamp=1700000000", "timestamp=-1"));
        rejected(request(root, "/account/info").replace("timestamp=1700000000", "timestamp=abc"));
        rejected(request(root, "/account/info").replace("path=/account/info", "path=/account/../info"));
        rejected(request(root, "/account/info").replace("path=/account/info", "path=/account/info?secret=1"));
        rejected(request(root, "/account/info").replace("path=/account/info", "path=account/info"));
        rejected(request(root, "/account/info") + "identity=456\n");
        rejected(request(root, "/account/info") + "unknown=value\n");
        rejected(request(root, "/account/info").replace("imei=synthetic-device", "imei=synthetic-private\\nvalue"));
        rejected(request(root, "/account/info").replace("imei=synthetic-device", "imei="));
        try {
            parse("x".repeat(SignRequest.MAX_BYTES + 1));
            throw new AssertionError("oversized request accepted");
        } catch (IllegalArgumentException expected) {
            require(String.valueOf(expected.getMessage()).length() < 120,
                "oversized input was echoed in the error message");
        }

        try {
            VerifiedResources.open(scratch.resolve("missing-resources"));
            throw new AssertionError("missing resources accepted");
        } catch (IllegalArgumentException expected) {
            // Missing assets must fail before any emulator is constructed.
        }

        if (args.length > 1) {
            Path real = Path.of(args[1]).toAbsolutePath().normalize();
            VerifiedResources resources = VerifiedResources.open(real);
            require(resources.apk.getFileName().toString().equals(VerifiedResources.APK_NAME),
                "apk path differs");
            require(resources.library.getFileName().toString().equals(VerifiedResources.LIBRARY_NAME),
                "library path differs");

            Path tampered = scratch.resolve("tampered");
            Files.createDirectories(tampered);
            copy(resources.apk, tampered.resolve(VerifiedResources.APK_NAME));
            copy(resources.library, tampered.resolve(VerifiedResources.LIBRARY_NAME));
            copy(resources.manifest, tampered.resolve(VerifiedResources.MANIFEST_NAME));
            byte[] libraryBytes = Files.readAllBytes(tampered.resolve(VerifiedResources.LIBRARY_NAME));
            libraryBytes[libraryBytes.length / 2] ^= 0x01;
            Files.write(tampered.resolve(VerifiedResources.LIBRARY_NAME), libraryBytes);
            try {
                VerifiedResources.open(tampered);
                throw new AssertionError("tampered library accepted");
            } catch (IllegalArgumentException expected) {
                // Tampered bytes must be rejected even when the manifest still matches itself.
            }

            Path extra = scratch.resolve("extra");
            Files.createDirectories(extra);
            copy(resources.apk, extra.resolve(VerifiedResources.APK_NAME));
            copy(resources.library, extra.resolve(VerifiedResources.LIBRARY_NAME));
            copy(resources.manifest, extra.resolve(VerifiedResources.MANIFEST_NAME));
            Files.writeString(extra.resolve("unreviewed.dll"), "x");
            try {
                VerifiedResources.open(extra);
                throw new AssertionError("extra resource accepted");
            } catch (IllegalArgumentException expected) {
                // The directory listing is exact; unreviewed files are refused.
            }

            Path relabelled = scratch.resolve("relabelled");
            Files.createDirectories(relabelled);
            copy(resources.apk, relabelled.resolve(VerifiedResources.APK_NAME));
            copy(resources.library, relabelled.resolve(VerifiedResources.LIBRARY_NAME));
            copy(resources.manifest, relabelled.resolve(VerifiedResources.MANIFEST_NAME));
            String manifestText = Files.readString(relabelled.resolve(VerifiedResources.MANIFEST_NAME));
            Files.writeString(relabelled.resolve(VerifiedResources.MANIFEST_NAME),
                manifestText.replace(VerifiedResources.PROFILE_ID, "other-profile"));
            try {
                VerifiedResources.open(relabelled);
                throw new AssertionError("relabelled manifest accepted");
            } catch (IllegalArgumentException expected) {
                // A local manifest cannot substitute for the compiled-in profile.
            }
        }
        System.out.println("PASS: signer loader boundary checks; native_executed=false");
    }
}
