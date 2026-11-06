package com.rajads.erp.redemption;

import com.rajads.erp.shared.ApiException;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.net.URLDecoder;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.time.Instant;

/** RFC 6238 TOTP helper for the remote-admin login contract. */
final class RemoteTotp {
    private RemoteTotp() { }

    static String generate(String configuredSecret) { return generate(configuredSecret, Instant.now()); }

    static String generate(String configuredSecret, Instant now) {
        String secret = extractSecret(configuredSecret);
        try {
            byte[] key = decodeBase32(secret);
            byte[] counter = ByteBuffer.allocate(Long.BYTES).putLong(now.getEpochSecond() / 30).array();
            Mac mac = Mac.getInstance("HmacSHA1");
            mac.init(new SecretKeySpec(key, "HmacSHA1"));
            byte[] digest = mac.doFinal(counter);
            int offset = digest[digest.length - 1] & 0x0f;
            int binary = ((digest[offset] & 0x7f) << 24) | ((digest[offset + 1] & 0xff) << 16)
                    | ((digest[offset + 2] & 0xff) << 8) | (digest[offset + 3] & 0xff);
            return String.format("%06d", binary % 1_000_000);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw ApiException.badRequest("INVALID_REMOTE_TOTP_SECRET", "TOTP 秘钥无效，请填写 Base32 秘钥或 otpauth:// 链接");
        }
    }

    private static String extractSecret(String configuredSecret) {
        if (configuredSecret == null || configuredSecret.isBlank()) {
            throw ApiException.badRequest("REMOTE_TOTP_SECRET_REQUIRED", "远端账号尚未配置 TOTP 秘钥，请编辑账号后重试");
        }
        String raw = configuredSecret.trim();
        if (!raw.regionMatches(true, 0, "otpauth://", 0, "otpauth://".length())) return raw;
        int queryStart = raw.indexOf('?');
        if (queryStart < 0 || queryStart == raw.length() - 1) {
            throw ApiException.badRequest("INVALID_REMOTE_TOTP_SECRET", "TOTP 秘钥无效，请填写 Base32 秘钥或 otpauth:// 链接");
        }
        for (String part : raw.substring(queryStart + 1).split("&")) {
            int separator = part.indexOf('=');
            if (separator > 0 && "secret".equalsIgnoreCase(part.substring(0, separator))) {
                return URLDecoder.decode(part.substring(separator + 1), StandardCharsets.UTF_8);
            }
        }
        throw ApiException.badRequest("INVALID_REMOTE_TOTP_SECRET", "TOTP 秘钥无效，请填写 Base32 秘钥或 otpauth:// 链接");
    }

    private static byte[] decodeBase32(String value) {
        String normalized = value.replaceAll("[\\s-]", "").replace("=", "").toUpperCase(java.util.Locale.ROOT);
        if (normalized.isBlank()) throw ApiException.badRequest("INVALID_REMOTE_TOTP_SECRET", "TOTP 秘钥无效，请填写 Base32 秘钥或 otpauth:// 链接");
        byte[] output = new byte[(normalized.length() * 5) / 8];
        int buffer = 0;
        int bits = 0;
        int outputIndex = 0;
        for (int index = 0; index < normalized.length(); index++) {
            char character = normalized.charAt(index);
            int digit = character >= 'A' && character <= 'Z' ? character - 'A' : character >= '2' && character <= '7' ? character - '2' + 26 : -1;
            if (digit < 0) throw ApiException.badRequest("INVALID_REMOTE_TOTP_SECRET", "TOTP 秘钥无效，请填写 Base32 秘钥或 otpauth:// 链接");
            buffer = (buffer << 5) | digit;
            bits += 5;
            if (bits >= 8) {
                output[outputIndex++] = (byte) ((buffer >> (bits - 8)) & 0xff);
                bits -= 8;
            }
        }
        return output;
    }
}
