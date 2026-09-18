package com.rajads.erp.redemption;

import com.rajads.erp.config.ErpProperties;
import com.rajads.erp.shared.ApiException;
import org.springframework.stereotype.Component;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.Base64;

/** Encrypts browser-supplied bearer tokens before they are written to PostgreSQL. */
@Component
public class RemoteConnectionCredentialCipher {
    private static final int GCM_TAG_BITS = 128;
    private static final int IV_BYTES = 12;
    private final ErpProperties properties;
    private final SecureRandom random = new SecureRandom();

    public RemoteConnectionCredentialCipher(ErpProperties properties) {
        this.properties = properties;
    }

    public String encrypt(String plaintext) {
        try {
            byte[] iv = new byte[IV_BYTES];
            random.nextBytes(iv);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key(), new GCMParameterSpec(GCM_TAG_BITS, iv));
            byte[] ciphertext = cipher.doFinal(plaintext.getBytes(StandardCharsets.UTF_8));
            byte[] packed = new byte[iv.length + ciphertext.length];
            System.arraycopy(iv, 0, packed, 0, iv.length);
            System.arraycopy(ciphertext, 0, packed, iv.length, ciphertext.length);
            return "v1:" + Base64.getEncoder().encodeToString(packed);
        } catch (GeneralSecurityException exception) {
            throw new IllegalStateException("无法加密远端连接凭据", exception);
        }
    }

    public String decrypt(String ciphertext) {
        try {
            if (ciphertext == null || !ciphertext.startsWith("v1:")) {
                throw ApiException.badRequest("REMOTE_CONNECTION_CREDENTIAL_INVALID", "远端连接凭据格式无效，请重新保存连接");
            }
            byte[] packed = Base64.getDecoder().decode(ciphertext.substring(3));
            if (packed.length <= IV_BYTES) throw ApiException.badRequest("REMOTE_CONNECTION_CREDENTIAL_INVALID", "远端连接凭据格式无效，请重新保存连接");
            byte[] iv = Arrays.copyOfRange(packed, 0, IV_BYTES);
            byte[] encrypted = Arrays.copyOfRange(packed, IV_BYTES, packed.length);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(GCM_TAG_BITS, iv));
            return new String(cipher.doFinal(encrypted), StandardCharsets.UTF_8);
        } catch (ApiException exception) {
            throw exception;
        } catch (IllegalArgumentException | GeneralSecurityException exception) {
            throw ApiException.badRequest("REMOTE_CONNECTION_CREDENTIAL_INVALID", "远端连接凭据无法解密；请检查密钥后重新保存连接");
        }
    }

    private javax.crypto.SecretKey key() {
        String encoded = properties.remoteConnections() == null ? null : properties.remoteConnections().encryptionKey();
        if (encoded == null || encoded.isBlank()) {
            throw ApiException.badRequest("REMOTE_CONNECTION_ENCRYPTION_KEY_REQUIRED", "未配置 ERP_REMOTE_CONNECTIONS_ENCRYPTION_KEY，不能保存远端后台凭据");
        }
        try {
            byte[] raw = Base64.getDecoder().decode(encoded.trim());
            if (raw.length != 32) throw new IllegalArgumentException("length");
            return new javax.crypto.spec.SecretKeySpec(raw, "AES");
        } catch (IllegalArgumentException exception) {
            throw ApiException.badRequest("REMOTE_CONNECTION_ENCRYPTION_KEY_INVALID", "ERP_REMOTE_CONNECTIONS_ENCRYPTION_KEY 必须是 32 字节 AES 密钥的 Base64 编码");
        }
    }
}
