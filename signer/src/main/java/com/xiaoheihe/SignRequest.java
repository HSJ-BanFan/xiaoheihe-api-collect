package com.xiaoheihe;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Strict request parser for the public signer loader.
 *
 * The format is one `key=value` line per field, ASCII only. There is no
 * escaping, no environment fallback and no default identity. Unknown,
 * duplicated, malformed or oversized input is rejected before any emulator
 * work starts.
 */
public final class SignRequest {
    public static final int PROTOCOL = 1;
    public static final int MAX_BYTES = 65536;
    public static final int MAX_VALUE = 4096;

    private static final Set<String> FIELDS = Set.of(
        "protocol", "resource_dir", "path", "timestamp", "identity", "imei",
        "device_info", "os_version", "app_version");
    private static final Pattern SAFE_VALUE = Pattern.compile("[\\x20-\\x7E]+");
    private static final Pattern IDENTITY = Pattern.compile("[0-9]{1,32}");
    private static final Pattern PATH_SEGMENT = Pattern.compile("(?!\\.\\.)[^?#\\\\]*");

    public final Path directory;
    public final String path;
    public final long timestamp;
    public final String identity;
    public final String imei;
    public final String deviceInfo;
    public final String osVersion;
    public final String appVersion;

    private SignRequest(Map<String, String> values) {
        this.directory = Path.of(values.get("resource_dir"));
        this.path = normalizePath(values.get("path"));
        this.timestamp = positiveLong("timestamp", values.get("timestamp"));
        this.identity = match("identity", values.get("identity"), IDENTITY);
        this.imei = safe("imei", values.get("imei"));
        this.deviceInfo = safe("device_info", values.get("device_info"));
        this.osVersion = safe("os_version", values.get("os_version"));
        this.appVersion = safe("app_version", values.get("app_version"));
        if (!this.directory.isAbsolute()) {
            throw new IllegalArgumentException("resource_dir must be an absolute path");
        }
    }

    public static SignRequest read(InputStream source) throws IOException {
        Map<String, String> values = parse(readBounded(source));
        String protocol = values.get("protocol");
        if (!String.valueOf(PROTOCOL).equals(protocol)) {
            throw new IllegalArgumentException("unsupported protocol");
        }
        return new SignRequest(values);
    }

    static Map<String, String> parse(byte[] raw) {
        String text = new String(raw, StandardCharsets.US_ASCII);
        Map<String, String> values = new LinkedHashMap<>();
        String[] lines = text.split("\n", -1);
        for (int index = 0; index < lines.length; index++) {
            String line = lines[index].endsWith("\r")
                ? lines[index].substring(0, lines[index].length() - 1) : lines[index];
            if (line.isEmpty()) {
                if (index != lines.length - 1) {
                    throw new IllegalArgumentException("blank line in request");
                }
                continue;
            }
            int split = line.indexOf('=');
            if (split <= 0) {
                throw new IllegalArgumentException("request line is not key=value");
            }
            String key = line.substring(0, split);
            String value = line.substring(split + 1);
            if (!FIELDS.contains(key)) {
                throw new IllegalArgumentException("unknown request field");
            }
            if (values.putIfAbsent(key, value) != null) {
                throw new IllegalArgumentException("duplicate request field");
            }
        }
        if (!values.keySet().equals(FIELDS)) {
            throw new IllegalArgumentException("request fields do not match the contract");
        }
        return values;
    }

    private static byte[] readBounded(InputStream source) throws IOException {
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        byte[] block = new byte[8192];
        int total = 0;
        int read;
        while ((read = source.read(block)) != -1) {
            total += read;
            if (total > MAX_BYTES) {
                throw new IllegalArgumentException("request exceeds the size limit");
            }
            buffer.write(block, 0, read);
        }
        if (total == 0) {
            throw new IllegalArgumentException("empty request");
        }
        for (byte value : buffer.toByteArray()) {
            if (value < 0x20 && value != '\n' && value != '\r') {
                throw new IllegalArgumentException("request contains a control byte");
            }
            if (value > 0x7e) {
                throw new IllegalArgumentException("request must be printable ASCII");
            }
        }
        return buffer.toByteArray();
    }

    private static String safe(String name, String value) {
        if (value == null || value.isEmpty() || value.length() > MAX_VALUE
                || value.indexOf('\\') >= 0 || value.indexOf(';') >= 0
                || !SAFE_VALUE.matcher(value).matches()) {
            throw new IllegalArgumentException(name + " is not a safe single-line ASCII value");
        }
        return value;
    }

    private static String match(String name, String value, Pattern pattern) {
        String checked = safe(name, value);
        if (!pattern.matcher(checked).matches()) {
            throw new IllegalArgumentException(name + " has an invalid format");
        }
        return checked;
    }

    private static long positiveLong(String name, String value) {
        String checked = safe(name, value);
        long parsed;
        try {
            parsed = Long.parseLong(checked);
        } catch (NumberFormatException error) {
            throw new IllegalArgumentException(name + " is not an integer");
        }
        if (parsed <= 0) {
            throw new IllegalArgumentException(name + " must be positive");
        }
        return parsed;
    }

    private static String normalizePath(String value) {
        String checked = safe("path", value);
        if (!checked.startsWith("/") || checked.length() > 512) {
            throw new IllegalArgumentException("path must start with a slash");
        }
        for (String segment : checked.split("/", -1)) {
            if (!PATH_SEGMENT.matcher(segment).matches()) {
                throw new IllegalArgumentException("path contains a forbidden segment");
            }
        }
        return checked.endsWith("/") ? checked : checked + "/";
    }
}
